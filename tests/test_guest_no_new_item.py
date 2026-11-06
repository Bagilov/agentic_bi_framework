"""No generated guest script may use `New-Item` for a directory.

`New-Item -ItemType Directory -Force -LiteralPath <path>` was used in the write
path, the zip staging, the build stage and the oracle. `-LiteralPath` on
`New-Item` is inherited from `ItemCommandBase`, but Windows PowerShell 5.1 does
not document it and a failed parameter binding is **terminal**: it would break
staging entirely. `[IO.Directory]::CreateDirectory` has no wildcard semantics
at all, is idempotent, and needs no parameter binding, so every directory is
created with it.

The oracle also created its output directory with a raw `-Path`, which expanded
`[`, `]` and `*` from the configured out dir as a wildcard pattern.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi.guest_transport import GuestConfig, WinRMTransport

_OUT = r"C:\pbi\out[1]"


def _transport() -> tuple[WinRMTransport, list[str]]:
    transport = WinRMTransport.__new__(WinRMTransport)
    transport.config = GuestConfig(
        winrm="http://127.0.0.1:5985/wsman", user="u", password="p", out=_OUT
    )
    calls: list[str] = []

    def ps(script: str, **kw: object) -> str:
        calls.append(script)
        if "Get-ChildItem" in script:
            return "3\n"
        if "'yes'" in script:
            return "no"
        return ""

    transport.ps = ps  # type: ignore[method-assign]
    return transport, calls


class TestWriteTextCreatesTheDirectoryWithoutNewItem:
    def test_the_parent_is_created_with_create_directory(self) -> None:
        transport, calls = _transport()
        transport.write_text(rf"{_OUT}\sub\task.ps1", "body")
        created = [call for call in calls if "CreateDirectory" in call]
        assert created
        assert rf"[IO.Directory]::CreateDirectory('{_OUT}\sub')" in created[0]
        assert not any("New-Item" in call for call in calls)


class TestZipStagingCreatesTheDirectoryWithoutNewItem:
    def test_extract_zip_stages_with_create_directory(self) -> None:
        transport, calls = _transport()
        transport.extract_zip(rf"{_OUT}\abf.zip", _OUT, expected=3)
        created = [call for call in calls if "CreateDirectory" in call]
        assert created
        assert f"[IO.Directory]::CreateDirectory('{_OUT}')" in created[0]
        assert not any("New-Item" in call for call in calls)


class _FakeBuildTransport:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def ps(self, script: str, **kwargs: object) -> str:
        self.scripts.append(script)
        return "1234" if "Get-Item -LiteralPath" in script else ""

    def push_file(self, local: Path, dest: str, deadline) -> None:
        return None

    def extract_zip(self, zip_path: str, dest_dir: str, *, expected: int) -> int:
        return expected

    def run_task(self, **kwargs: object) -> tuple[str, int]:
        return "builder output", 0


class TestTheBuildStageCreatesTheDirectoryWithoutNewItem:
    def test_run_build_uses_create_directory(self, tmp_path: Path) -> None:
        from agentic_bi.guest_chain import ChainConfig, ChainResult
        from agentic_bi.guest_chain_build import run_build
        from agentic_bi.guest_types import Deadline

        data = tmp_path / "sales[1].csv"
        data.write_text("a,b\n", encoding="utf-8")
        repo = tmp_path / "repo"
        repo.mkdir()
        config = ChainConfig(
            guest=GuestConfig(
                winrm="http://guest:5985/wsman",
                user="u",
                password="p",
                root=r"C:\pbi\abf",
                out=_OUT,
            ),
            data=data,
            table="Sales",
            out=Path("output_files/board[1].pbix"),
            repo=repo,
        )
        transport = _FakeBuildTransport()
        assert run_build(
            transport,  # type: ignore[arg-type]
            config,
            Deadline(30),
            ChainResult(verdict="NOT_BUILT"),
        )
        joined = "\n".join(transport.scripts)
        assert f"[IO.Directory]::CreateDirectory('{_OUT}')" in joined
        assert "New-Item" not in joined


class TestTheOracleCreatesItsDirectoryWithoutNewItem:
    def test_run_oracle_uses_create_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from agentic_bi import desktop_oracle_guest as oracle

        class _FakeTransport:
            def __init__(self, config: GuestConfig) -> None:
                self.config = config
                self.scripts: list[str] = []
                self.closed = False

            def ps(self, script: str, **kw: object) -> str:
                self.scripts.append(script)
                return ""

            def push_file(self, local: Path, dest: str, deadline) -> None:
                return None

            def run_task(self, **kwargs: object) -> tuple[str, int]:
                return "RESULT [MODEL_LOADED]", 0

            def close(self) -> None:
                self.closed = True

        created: list[_FakeTransport] = []

        def factory(config: GuestConfig) -> _FakeTransport:
            transport = _FakeTransport(config)
            created.append(transport)
            return transport

        monkeypatch.setattr(oracle, "WinRMTransport", factory)
        pbix = tmp_path / "board[1].pbix"
        pbix.write_bytes(b"pbix")
        result = oracle.run_oracle(
            pbix,
            config=GuestConfig(
                winrm="http://guest:5985/wsman", user="u", password="p", out=_OUT
            ),
        )
        assert result.verdict == "MODEL_LOADED"
        transport = created[0]
        assert transport.closed
        joined = "\n".join(transport.scripts)
        assert f"[IO.Directory]::CreateDirectory('{_OUT}')" in joined
        assert "New-Item" not in joined
        assert "$ErrorActionPreference='Stop'" in transport.scripts[0]

    @pytest.mark.parametrize("name", ["_oracle_script"])
    def test_the_oracle_script_log_has_one_encoding(self, name: str) -> None:
        from agentic_bi.desktop_oracle_guest import _oracle_script

        script = _oracle_script(
            GuestConfig(winrm="http://guest:5985/wsman", user="u", password="p"),
            r"C:\pbi\out\board[1].pbix",
            90,
            240,
        )
        assert "*>" not in script, "`*>` writes UTF-16 into a UTF-8 log"
        assert "Out-File" not in script, "the runner is the log's only writer"
