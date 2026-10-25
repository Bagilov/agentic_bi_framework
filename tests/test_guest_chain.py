"""Offline tests for the guest chain: budget, verdicts, staging and exit parsing.

These never touch a VM: the guest is exercised by the gated integration tests in
`test_pbix_desktop_oracle.py`. Here we pin the pure logic that a chain verdict
depends on — the shared `Deadline`, the marker/exit-code parser, the staged zip
layout, the build script, and the fail-fast behaviour when no guest is
configured.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from agentic_bi.guest_chain import (
    BUILT,
    NOT_BUILT,
    STAGE_FAILED,
    TIMEOUT,
    ChainConfig,
    ChainResult,
    build_dashboard,
)
from agentic_bi.guest_chain_build import (
    _register_on_path,
    build_script,
    stage_framework,
    tail,
)
from agentic_bi.guest_chain_cli import _emit, main
from agentic_bi.guest_task import parse_exitcode
from agentic_bi.guest_transport import (
    ChainTimeout,
    Deadline,
    GuestConfig,
    host_reachable_ip,
    ps_quote,
)
from agentic_bi.guest_vm import VMController

_GUEST_VARS = (
    "AGENTIC_BI_GUEST_WINRM",
    "AGENTIC_BI_GUEST_USER",
    "AGENTIC_BI_GUEST_PASSWORD",
)


@pytest.fixture
def no_guest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the guest is unconfigured, whatever the developer's shell has."""
    for name in _GUEST_VARS:
        monkeypatch.delenv(name, raising=False)


class TestDeadline:
    def test_rejects_a_non_positive_budget(self) -> None:
        with pytest.raises(ValueError):
            Deadline(0)

    def test_expires_after_its_budget(self) -> None:
        deadline = Deadline(0.01)
        while not deadline.expired:
            pass
        with pytest.raises(ChainTimeout):
            deadline.check("stage")

    def test_slice_never_overshoots_the_remaining_budget(self) -> None:
        deadline = Deadline(0.5)
        assert deadline.slice(60.0) <= deadline.seconds
        assert deadline.slice(0.1) == pytest.approx(0.1)

    def test_remaining_never_goes_negative(self) -> None:
        deadline = Deadline(0.01)
        while not deadline.expired:
            pass
        assert deadline.remaining == 0.0


class TestParseExitcode:
    @pytest.mark.parametrize(
        ("marker", "expected"),
        [
            ("EXITCODE=0", 0),
            ("EXITCODE=2", 2),
            ("EXITCODE=-1", -1),
            ("EXITCODE=7\r\n", 7),
            ("EXITCODE=", None),
            ("", None),
            ("noise", None),
            ("EXITCODE=abc", None),
        ],
    )
    def test_only_a_complete_token_yields_a_code(self, marker, expected) -> None:
        assert parse_exitcode(marker) == expected


class TestChainResult:
    def test_ok_requires_built_and_no_failed_oracle(self) -> None:
        assert ChainResult(verdict=BUILT).ok
        assert ChainResult(verdict=BUILT, oracle="MODEL_LOADED").ok
        assert not ChainResult(verdict=BUILT, oracle="CRASH").ok
        assert not ChainResult(verdict=NOT_BUILT).ok
        assert not ChainResult(verdict=STAGE_FAILED).ok
        assert not ChainResult(verdict=TIMEOUT).ok

    def test_as_dict_is_json_serialisable(self, tmp_path: Path) -> None:
        pbix = tmp_path / "x.pbix"
        result = ChainResult(verdict=BUILT, pbix=pbix, bytes_written=5)
        result.record("vm", "started")
        payload = json.loads(json.dumps(result.as_dict()))
        assert payload["verdict"] == BUILT
        # `as_dict` stringifies with `str(Path)`, whose separators differ by
        # platform; compare against the same conversion, not a POSIX literal.
        assert payload["pbix"] == str(pbix)
        assert payload["bytes"] == 5
        assert payload["log"] == ["vm: started"]


class TestStageFramework:
    def test_archives_the_runtime_at_the_archive_root(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / "src" / "pkg").mkdir(parents=True)
        (repo / "src" / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "src" / "pkg" / "__pycache__").mkdir()
        (repo / "src" / "pkg" / "__pycache__" / "mod.pyc").write_bytes(b"\x00")
        (repo / "examples").mkdir()
        (repo / "examples" / "b.py").write_text("y = 2\n", encoding="utf-8")
        (repo / "README.md").write_text("hi\n", encoding="utf-8")
        (repo / "ignored").mkdir()
        (repo / "ignored" / "secret.txt").write_text("no\n", encoding="utf-8")

        dest = tmp_path / "abf.zip"
        stage_framework(repo, dest)
        names = set(zipfile.ZipFile(dest).namelist())

        assert names == {"src/pkg/mod.py", "examples/b.py", "README.md"}
        assert not any("__pycache__" in name for name in names)

    def test_accepts_a_string_repo_path(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "m.py").write_text("z = 3\n", encoding="utf-8")
        dest = tmp_path / "abf.zip"
        stage_framework(str(repo), dest)  # type: ignore[arg-type]
        assert "src/m.py" in zipfile.ZipFile(dest).namelist()


class TestBuildScript:
    def _config(self, **overrides) -> ChainConfig:
        guest = GuestConfig(winrm="http://guest:5985/wsman", user="u", password="p")
        defaults = dict(
            guest=guest,
            data=Path("examples/engine_sales.csv"),
            table="Sales",
            out=Path("output_files/board.pbix"),
        )
        defaults.update(overrides)
        return ChainConfig(**defaults)

    def test_pins_guest_root_and_runs_the_builder(self) -> None:
        script = build_script(
            self._config(), r"C:\pbi\out\board.pbix", r"C:\pbi\out\b.log"
        )
        assert r"$env:PYTHONPATH='C:\pbi\abf\src'" in script
        assert r"C:\pbi\abf\examples\engine_table_board.py" in script
        assert r"--table 'Sales'" in script
        assert "--title" not in script

    def test_groups_a_title_when_given(self) -> None:
        script = build_script(
            self._config(title="Q3 Sales"),
            r"C:\pbi\out\board.pbix",
            r"C:\pbi\out\b.log",
        )
        assert "--title 'Q3 Sales'" in script

    def test_quotes_a_hostile_table_so_it_cannot_inject(self) -> None:
        script = build_script(
            self._config(table="x'; Remove-Item C:\\ -Recurse; '"),
            r"C:\pbi\out\board.pbix",
            r"C:\pbi\out\b.log",
        )
        assert "--table 'x''; Remove-Item C:\\ -Recurse; '''" in script
        assert "--table 'x';" not in script


class TestPsQuote:
    def test_doubles_single_quotes(self) -> None:
        assert ps_quote("a'b") == "'a''b'"

    def test_wraps_numbers_and_paths(self) -> None:
        assert ps_quote(7) == "'7'"
        assert ps_quote(r"C:\pbi\out") == r"'C:\pbi\out'"


class TestRegisterOnPath:
    def test_derives_the_pth_and_src_from_config(self) -> None:
        guest = GuestConfig(
            winrm="http://guest:5985/wsman",
            user="u",
            password="p",
            python=r"D:\py\python.exe",
            root=r"D:\stage",
        )
        script = _register_on_path(guest)
        assert r"$pth='D:\py\python312._pth'" in script
        assert r"'D:\stage\src'" in script
        assert "C:\\pbi" not in script


class TestTail:
    def test_flattens_whitespace_and_keeps_the_end(self) -> None:
        assert tail("a\n  b\tc") == "a b c"
        assert tail("x" * 50, limit=4) == "x" * 4


class TestHostReachableIp:
    def test_derives_the_gateway_from_the_endpoint(self, monkeypatch) -> None:
        monkeypatch.delenv("AGENTIC_BI_HOST_IP", raising=False)
        config = GuestConfig(
            winrm="http://192.168.64.3:5985/wsman", user="u", password="p"
        )
        assert host_reachable_ip(config) == "192.168.64.1"

    def test_explicit_override_wins(self, monkeypatch) -> None:
        monkeypatch.setenv("AGENTIC_BI_HOST_IP", "10.0.0.9")
        config = GuestConfig(
            winrm="http://192.168.64.3:5985/wsman", user="u", password="p"
        )
        assert host_reachable_ip(config) == "10.0.0.9"

    def test_non_ip_endpoint_is_returned_as_is(self, monkeypatch) -> None:
        monkeypatch.delenv("AGENTIC_BI_HOST_IP", raising=False)
        config = GuestConfig(
            winrm="http://guest.local:5985/wsman", user="u", password="p"
        )
        assert host_reachable_ip(config) == "guest.local"


class TestVMController:
    def test_unconfigured_controller_is_inert(self, monkeypatch) -> None:
        monkeypatch.setattr("agentic_bi.guest_vm.shutil.which", lambda _: None)
        vm = VMController("SOME-UUID")
        assert not vm.configured
        assert vm.status() == "unknown"
        vm.start()  # must not shell out
        vm.stop()

    def test_no_uuid_means_not_configured(self) -> None:
        assert not VMController(None).configured


class TestUnconfiguredChain:
    def test_build_dashboard_fails_fast_without_a_guest(self, no_guest) -> None:
        with pytest.raises(RuntimeError, match="guest not configured"):
            build_dashboard()

    def test_main_returns_exit_two_and_reports_not_configured(
        self, no_guest, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([]) == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["verdict"] == "NOT_CONFIGURED"
        assert payload["ok"] is False


class TestEmitIsBoundarySafe:
    """An unwritable --json path warns and still prints the verdict; no traceback."""

    def test_unwritable_json_path_warns_without_raising(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory\n", encoding="utf-8")
        target = blocker / "verdict.json"
        _emit({"verdict": "NOT_CONFIGURED", "ok": False}, str(target))
        captured = capsys.readouterr()
        assert json.loads(captured.out)["verdict"] == "NOT_CONFIGURED"
        assert "could not write the verdict" in captured.err
