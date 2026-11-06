"""Guest paths are literal: `[`, `]`, `*` and `?` must never act as wildcards.

Task, marker, log and staging names come from the configuration, so a name such
as `board[1].pbix` is legal. `Test-Path`/`Remove-Item`/`Get-Content` without
`-LiteralPath` treat those characters as a pattern: cleanup could delete a
different file, or report the target absent while it is still there. Every path
in the task runner and the zip staging therefore takes `-LiteralPath`.

Directories are created with `[IO.Directory]::CreateDirectory`, which has no
wildcard semantics at all and does not depend on `New-Item -LiteralPath` being
available on Windows PowerShell 5.1 (a missing parameter binding would fail the
whole staging stage). The guest probes answer the runner's real scripts, not
loose substrings of them.
"""

from __future__ import annotations

import re

import pytest

from agentic_bi.guest_task import TaskRunnerMixin, remove_script
from agentic_bi.guest_types import GuestConfig, StageError

_BRACKET_PATH = r"C:\pbi\out\board[1].pbix"
_STAR_PATH = r"C:\pbi\out\board*.pbix"


class TestRemoveScriptIsLiteral:
    @pytest.mark.parametrize("path", [_BRACKET_PATH, _STAR_PATH])
    def test_both_commands_take_literal_path(self, path: str) -> None:
        script = remove_script(path)
        assert script.count("-LiteralPath") == 2
        assert f"Test-Path -LiteralPath '{path}'" in script
        assert f"Remove-Item -LiteralPath '{path}'" in script

    def test_a_wildcard_is_still_one_quoted_literal(self) -> None:
        script = remove_script(_STAR_PATH)
        assert script.count("'") == 4, "each path is one single-quoted literal"
        assert f"'{_STAR_PATH}'" in script


class _Deadline:
    expired = False

    def slice(self, value: float) -> float:
        return 0.0


class _Guest:
    """Answers the runner's probes for the configured marker/log paths."""

    def __init__(self) -> None:
        self.present: set[str] = set()

    def ps(self, script: str, **kw: object) -> str:
        if "Register-ScheduledTask -TaskName" in script:
            self.present.add("marker")
            self.present.add("log")
            return ""
        if "Get-Content -LiteralPath" in script:
            return "EXITCODE=0\r\n" if "marker" in self.present else ""
        if "Remove-Item -LiteralPath" in script:
            if ".done" in script:
                self.present.discard("marker")
            if ".log" in script:
                self.present.discard("log")
            return ""
        if "'yes'" in script and "'no'" in script:
            path = script.split("Test-Path -LiteralPath '", 1)[1].split("'", 1)[0]
            if path.endswith("payload.ps1"):
                return "yes"
            if path.endswith(".log"):
                return "yes" if "log" in self.present else "no"
            return "yes" if "marker" in self.present else "no"
        return ""


def _runner() -> tuple[TaskRunnerMixin, list[str], list[str]]:
    calls: list[str] = []
    written: list[str] = []
    guest = _Guest()
    runner = TaskRunnerMixin()
    runner.config = GuestConfig(
        winrm="http://guest:5985/wsman",
        user="u",
        password="p",
        out=r"C:\pbi\out",
    )

    def ps(script: str, **kw: object) -> str:
        calls.append(script)
        return guest.ps(script, **kw)

    runner.ps = ps  # type: ignore[method-assign]
    runner.write_text = lambda path, text: written.append(text)  # type: ignore[attr-defined]
    runner.read_text = lambda path: "EXITCODE=0"  # type: ignore[attr-defined]
    return runner, calls, written


def _run(runner: TaskRunnerMixin) -> None:
    runner.run_task(
        name="board",
        script="Write-Output hi",
        deadline=_Deadline(),  # type: ignore[arg-type]
        poll=0,
    )


class TestRunTaskPathsAreLiteral:
    def test_the_runner_writes_and_reads_with_literal_path(self) -> None:
        runner, calls, written = _runner()
        _run(runner)
        assert "Set-Content -LiteralPath" in written[-1]
        assert "Remove-Item -LiteralPath" in written[-1]
        assert "Set-Content -Path" not in written[-1]
        assert any("Get-Content -LiteralPath" in call for call in calls)
        assert not any("Get-Content 'C:\\pbi" in call for call in calls)

    def test_every_probe_is_literal(self) -> None:
        runner, calls, _ = _runner()
        _run(runner)
        probes = [
            call for call in calls if "Test-Path" in call and "Remove" not in call
        ]
        assert probes
        assert all("-LiteralPath" in call for call in probes)

    def test_the_task_action_names_the_payload_as_one_quoted_literal(self) -> None:
        runner, calls, _ = _runner()
        _run(runner)
        register = next(c for c in calls if "Register-ScheduledTask" in c)
        assert re.search(
            r"-Argument '-NoProfile -ExecutionPolicy Bypass "
            r'-File "C:\\pbi\\out\\board\.[0-9a-f]{8}\.ps1"\'',
            register,
        )


class TestExtractZipPathsAreLiteral:
    def _transport(self) -> tuple[TaskRunnerMixin, list[str]]:
        calls: list[str] = []

        transport = TaskRunnerMixin()

        def ps(script: str, **kw: object) -> str:
            calls.append(script)
            if "Get-ChildItem" in script:
                return "3\n"
            if "'yes'" in script:
                return "no"
            return ""

        transport.ps = ps  # type: ignore[method-assign]
        return transport, calls

    def test_staging_uses_literal_paths(self) -> None:
        transport, calls = self._transport()
        dest = r"C:\pbi\stage[1]*"
        count = transport.extract_zip(r"C:\pbi\in[1].zip", dest, expected=3)
        assert count == 3
        count_script = next(call for call in calls if "Get-ChildItem" in call)
        assert f"Get-ChildItem -LiteralPath '{dest}'" in count_script
        assert f"ExtractToDirectory('C:\\pbi\\in[1].zip', '{dest}')" in count_script
        assert any(
            f"[IO.Directory]::CreateDirectory('{dest}')" in call for call in calls
        )
        assert any("Test-Path -LiteralPath" in call for call in calls)
        assert not any("Test-Path 'C:\\pbi" in call for call in calls)

    def test_staging_never_uses_new_item(self) -> None:
        transport, calls = self._transport()
        transport.extract_zip(r"C:\pbi\in.zip", r"C:\pbi\stage", expected=3)
        assert not any("New-Item" in call for call in calls)

    def test_a_partial_extraction_still_fails_loudly(self) -> None:
        transport, _ = self._transport()
        with pytest.raises(StageError, match="extracted 3 of 4"):
            transport.extract_zip(r"C:\pbi\in.zip", r"C:\pbi\stage", expected=4)
