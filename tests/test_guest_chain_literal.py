"""Chain-build paths are literal: `[`, `]`, `*` must not act as wildcards.

The guest root/out paths come from the environment, so `C:\\pbi\\abf[1]` is a
legal value. Every path argument in the build stage therefore takes
`-LiteralPath`, a missing `._pth` is refused before any read/write, and the
appended entry is ASCII-checked on the host and written with an explicit
`-Encoding ASCII` (Windows PowerShell 5.1's `Add-Content` default is ANSI).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentic_bi.guest_chain import ChainConfig, ChainResult
from agentic_bi.guest_chain_build import (
    _ascii_entry,
    _register_on_path,
    run_build,
)
from agentic_bi.guest_task import remove_script
from agentic_bi.guest_types import Deadline, GuestConfig, StageError

_BRACKET_ROOT = r"C:\pbi\abf[1]"
_STAR_ROOT = r"C:\pbi\abf*"
_BRACKET_PY = r"C:\pbi\py[1]\python.exe"


def _guest(root: str = _BRACKET_ROOT, python: str = _BRACKET_PY) -> GuestConfig:
    return GuestConfig(
        winrm="http://guest:5985/wsman",
        user="u",
        password="p",
        python=python,
        root=root,
        out=r"C:\pbi\out[1]",
    )


class TestRegisterOnPathIsLiteral:
    @pytest.mark.parametrize("root", [_BRACKET_ROOT, _STAR_ROOT])
    def test_every_path_argument_is_literal(self, root: str) -> None:
        script = _register_on_path(_guest(root=root))
        assert "Test-Path -LiteralPath $pth" in script
        assert f"Select-String -LiteralPath $pth -Pattern '{root}\\src'" in script
        assert f"Add-Content -LiteralPath $pth -Value '{root}\\src'" in script
        assert "Select-String -Path" not in script
        assert "Add-Content $pth" not in script

    def test_the_entry_is_still_one_quoted_literal(self) -> None:
        script = _register_on_path(_guest(root=_STAR_ROOT))
        assert f"'{_STAR_ROOT}\\src'" in script
        assert "-SimpleMatch" in script


class TestMissingPth:
    def test_the_file_is_checked_before_the_read_and_the_write(self) -> None:
        script = _register_on_path(_guest())
        guard = script.index("Test-Path -LiteralPath $pth")
        read = script.index("Select-String -LiteralPath $pth")
        write = script.index("Add-Content -LiteralPath $pth")
        assert guard < read < write

    def test_a_missing_file_produces_a_clear_error_not_a_stray_write(self) -> None:
        script = _register_on_path(_guest())
        assert "throw (" in script
        assert "python312._pth" in script
        assert "$ErrorActionPreference='Stop'" in script
        assert "is missing" in script


class TestEncoding:
    def test_the_entry_is_written_with_explicit_ascii(self) -> None:
        script = _register_on_path(_guest())
        assert "-Encoding ASCII" in script

    def test_a_non_ascii_source_path_is_refused_before_any_write(self) -> None:
        guest = _guest(root=r"C:\Users\Ибрагим\abf")
        with pytest.raises(StageError) as raised:
            _register_on_path(guest)
        message = str(raised.value)
        assert "is not ASCII" in message
        assert "nothing was written" in message
        assert "Add-Content" not in message

    def test_a_non_ascii_interpreter_directory_is_allowed(self) -> None:
        # Only the *appended entry* must be ASCII; the `._pth` path itself is a
        # path argument, not file content, and PowerShell handles it as text.
        script = _register_on_path(_guest(python=r"C:\Users\Ибрагим\py\python.exe"))
        assert r"$pth='C:\Users\Ибрагим\py\python312._pth'" in script
        assert f"'{_BRACKET_ROOT}\\src'" in script

    def test_the_helper_returns_the_value_unchanged(self) -> None:
        assert _ascii_entry(r"C:\pbi\abf\src", what="guest source path") == (
            r"C:\pbi\abf\src"
        )


class _FakeTransport:
    """Records the PowerShell/transfer calls `run_build` makes."""

    def __init__(self, size: str = "1234") -> None:
        self.scripts: list[str] = []
        self.pushed: list[tuple[Path, str]] = []
        self.task: dict[str, object] = {}
        self._size = size

    def ps(self, script: str, **kwargs: object) -> str:
        self.scripts.append(script)
        if "Get-Item -LiteralPath" in script:
            return self._size
        return ""

    def push_file(self, local: Path, dest: str, deadline: Deadline) -> None:
        self.pushed.append((Path(local), dest))

    def extract_zip(self, zip_path: str, dest_dir: str, *, expected: int) -> int:
        assert expected == 0, "an empty repo stages an empty zip"
        return expected

    def run_task(self, **kwargs: object) -> tuple[str, int]:
        self.task = kwargs
        return "builder output", 0


class TestRunBuildIsLiteral:
    def _config(self, tmp_path: Path) -> ChainConfig:
        data = tmp_path / "engine sales[1].csv"
        data.write_text("a,b\n", encoding="utf-8")
        repo = tmp_path / "repo"
        repo.mkdir()
        return ChainConfig(
            guest=_guest(),
            data=data,
            table="Sales",
            out=Path("output_files/board[1].pbix"),
            repo=repo,
        )

    def test_only_literal_paths_reach_the_guest(self, tmp_path: Path) -> None:
        transport = _FakeTransport()
        config = self._config(tmp_path)
        result = ChainResult(verdict="NOT_BUILT")
        assert run_build(
            transport,  # type: ignore[arg-type]
            config,
            Deadline(30),
            result,
        )

        joined = "\n".join(transport.scripts)
        assert transport.pushed[0][1] == r"C:\pbi\out[1]\abf.zip"
        # `[IO.Directory]::CreateDirectory` has no wildcard semantics at all and
        # needs no `-LiteralPath` parameter binding (see guest_winrm.write_text).
        assert "[IO.Directory]::CreateDirectory('C:\\pbi\\out[1]')" in joined
        assert "New-Item" not in joined
        per_run = re.search(r"board\[1\]\.[0-9a-f]{8}\.pbix", joined)
        assert per_run, "the build keeps a per-run artifact"
        assert f"Test-Path -LiteralPath 'C:\\pbi\\out[1]\\{per_run.group(0)}'" in joined
        assert f"Get-Item -LiteralPath 'C:\\pbi\\out[1]\\{per_run.group(0)}'" in joined
        assert "Test-Path 'C:" not in joined
        assert "Get-Item 'C:" not in joined

    def test_the_pre_run_cleanup_targets_only_this_runs_own_artifact(
        self, tmp_path: Path
    ) -> None:
        transport = _FakeTransport()
        config = self._config(tmp_path)
        run_build(
            transport,  # type: ignore[arg-type]
            config,
            Deadline(30),
            ChainResult(verdict="NOT_BUILT"),
        )
        files_before = transport.task["files_before"]
        assert isinstance(files_before, str)
        assert files_before == remove_script(
            files_before.split("Test-Path -LiteralPath '", 1)[1].split("'", 1)[0]
        )
        assert re.search(
            r"Test-Path -LiteralPath 'C:\\pbi\\out\[1\]\\board\[1\]\."
            r"[0-9a-f]{8}\.pbix'",
            files_before,
        )
        assert r"C:\pbi\out[1]\board[1].pbix" not in files_before
        assert "Remove-Item '" not in files_before

    def test_a_finished_build_is_copied_onto_the_declared_output(
        self, tmp_path: Path
    ) -> None:
        transport = _FakeTransport()
        config = self._config(tmp_path)
        assert run_build(
            transport,  # type: ignore[arg-type]
            config,
            Deadline(30),
            ChainResult(verdict="NOT_BUILT"),
        )
        publish = next(c for c in transport.scripts if "[IO.File]::Copy(" in c)
        assert "$d='C:\\pbi\\out[1]\\board[1].pbix'" in publish
        assert "$src='C:\\pbi\\out[1]\\board[1]." in publish
        # The publish must not consume the file the chain pulls.
        assert re.search(
            r"\$stg='C:\\pbi\\out\[1\]\\board\[1\]\.pbix\.[0-9a-f]{8}"
            r"\.publish\.tmp'",
            publish,
        )
        assert "Move($s,$d,$true)" not in publish
        assert "Copy($src,$stg,$true)" in publish
