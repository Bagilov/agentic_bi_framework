"""Offline tests for the guest chain: budget, verdicts, staging and exit parsing.

These never touch a VM: the guest is exercised by the gated integration tests in
`test_pbix_desktop_oracle.py`. Here we pin the pure logic that a chain verdict
depends on — the shared `Deadline`, the marker/exit-code parser, the staged zip
layout, the build script, and the fail-fast behaviour when no guest is
configured.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.guest_chain import (
    BUILT,
    NOT_BUILT,
    STAGE_FAILED,
    TIMEOUT,
    ChainConfig,
    ChainResult,
)
from agentic_bi.guest_chain_build import (
    _register_on_path,
    build_script,
    run_build,
    tail,
)
from agentic_bi.guest_task import parse_exitcode
from agentic_bi.guest_transport import (
    ChainTimeout,
    Deadline,
    GuestConfig,
    StageError,
    host_reachable_ip,
    ps_quote,
)

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
            ("EXITCODE=0\r\n", 0),
            ("EXITCODE=2\r\n", 2),
            ("EXITCODE=-1\r\n", -1),
            ("EXITCODE=7\r\n", 7),
            ("noise\r\nEXITCODE=3\r\n", 3),
            ("EXITCODE=0", None),
            ("EXITCODE=1", None),
            ("EXITCODE=", None),
            ("EXITCODE=\r\n", None),
            ("", None),
            ("noise", None),
            ("EXITCODE=abc\r\n", None),
            ("EXITCODE=0\r\nmore", None),
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

    def test_the_entry_is_matched_literally_not_as_a_regex(self) -> None:
        guest = GuestConfig(
            winrm="http://guest:5985/wsman",
            user="u",
            password="p",
            python=r"C:\pbi\py\python.exe",
            root=r"C:\pbi\abf",
        )
        script = _register_on_path(guest)
        # `-Pattern` is a regex; `C:\pbi\abf\src` fails to compile without it.
        assert "-SimpleMatch" in script

    def test_the_entry_is_appended_in_ascii_through_a_literal_path(self) -> None:
        guest = GuestConfig(
            winrm="http://guest:5985/wsman",
            user="u",
            password="p",
            python=r"D:\py\python.exe",
            root=r"D:\stage",
        )
        script = _register_on_path(guest)
        # Windows PowerShell 5.1's `Add-Content` default is ANSI, which would
        # write a non-ASCII entry as bytes the interpreter cannot import.
        assert (
            "Add-Content -LiteralPath $pth -Value 'D:\\stage\\src' -Encoding ASCII"
            in script
        )

    def test_the_docstring_documents_the_pinned_behaviour(self) -> None:
        doc = _register_on_path.__doc__ or ""
        for expected in ("-LiteralPath", "missing", "ASCII", "._pth"):
            assert expected in doc


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


class _LockedTransport:
    """A transport whose guest holds (or does not hold) the chain lock."""

    def __init__(self, locked: bool = False) -> None:
        self.locked = locked
        self.scripts: list[str] = []

    def ps(self, script: str, **kwargs: object) -> str:
        self.scripts.append(script)
        if "CreateNew" in script and self.locked:
            raise StageError("another guest chain holds the lock; refusing")
        if "Get-Item -LiteralPath" in script and ").Length" in script:
            return "1234"
        return ""

    def push_file(self, local: Path, dest: str, deadline: Deadline) -> None:
        return None

    def extract_zip(self, zip_path: str, dest_dir: str, *, expected: int) -> int:
        return expected

    def run_task(self, **kwargs: object) -> tuple[str, int]:
        return "builder output", 1


def _chain_config(tmp_path: Path) -> ChainConfig:
    data = tmp_path / "sales.csv"
    data.write_text("a,b\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return ChainConfig(
        guest=GuestConfig(
            winrm="http://guest:5985/wsman",
            user="u",
            password="p",
            root=r"C:\pbi\abf",
            out=r"C:\pbi\out",
        ),
        data=data,
        table="Sales",
        out=Path("output_files/board.pbix"),
        repo=repo,
    )


class TestChainLock:
    """The staging tree is shared, so two chains must not stage at once."""

    def test_the_lock_is_taken_and_released(self, tmp_path: Path) -> None:
        transport = _LockedTransport()
        run_build(
            transport,  # type: ignore[arg-type]
            _chain_config(tmp_path),
            Deadline(30),
            ChainResult(verdict="NOT_BUILT"),
        )
        lock_scripts = [s for s in transport.scripts if "abf.chain.lock" in s]
        assert len(lock_scripts) == 2, "one acquire, one release"
        assert "CreateNew" in lock_scripts[0]
        assert "Remove-Item" in lock_scripts[1]

    def test_a_live_lock_fails_the_stage(self, tmp_path: Path) -> None:
        transport = _LockedTransport(locked=True)
        with pytest.raises(StageError, match="another guest chain"):
            run_build(
                transport,  # type: ignore[arg-type]
                _chain_config(tmp_path),
                Deadline(30),
                ChainResult(verdict="NOT_BUILT"),
            )
        assert not any("abf.zip" in s for s in transport.scripts)


class TestDesktopBin:
    def test_a_configured_desktop_path_reaches_the_build_script(
        self, tmp_path: Path
    ) -> None:
        """A relocated Desktop install must not get the default `PBI_RS_BIN`."""
        config = _chain_config(tmp_path)
        config.guest = GuestConfig(
            winrm="http://guest:5985/wsman",
            user="u",
            password="p",
            root=r"C:\pbi\abf",
            out=r"C:\pbi\out",
            desktop=r"D:\Apps\PBIDesktop\bin",
        )
        script = build_script(config, r"C:\pbi\out\board.pbix")
        assert "$env:PBI_RS_BIN='D:\\Apps\\PBIDesktop\\bin'" in script


class TestOracleBudget:
    def test_no_budget_left_is_a_timeout_not_a_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`int(remaining) == 0` used to reach `Deadline(0)` and raise ValueError."""
        import agentic_bi.guest_chain as mod

        called: list[object] = []
        monkeypatch.setattr(
            "agentic_bi.desktop_oracle_guest.run_oracle",
            lambda *a, **k: called.append((a, k)),
        )
        config = _chain_config(Path("/tmp/kilo"))
        deadline = Deadline(60)
        deadline._start -= 59.7
        result = ChainResult(verdict=BUILT)
        mod._run_oracle(config, Path("board.pbix"), deadline, result)
        assert called == []
        assert result.verdict == TIMEOUT
        assert "no budget left" in result.log[-1]
