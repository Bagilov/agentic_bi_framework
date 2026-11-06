"""Two runs of the same name must not share a single artifact.

`run_task` used to name the runner and the payload from `name` alone while every
caller derived the log, the marker and the pre-run cleanup (`files_before`) from
that same `name`. Two concurrent runs with one name therefore overwrote each
other's payload, and the second run's cleanup deleted the first run's live marker,
log and freshly built `.pbix`.

Every artifact now carries one random per-run token. The final `.pbix` is
deliberately *not* part of that set: it is the caller's declared output and is
replaced by a finished build (`guest_chain_build.run_build`), never deleted
before a run starts.
"""

from __future__ import annotations

import re

from agentic_bi.guest_task import TaskRunnerMixin
from agentic_bi.guest_task_script import run_paths, run_token
from agentic_bi.guest_types import GuestConfig

_OUT = r"C:\pbi\out"
_MARKER = re.compile(r"\$d='([^']+)\.done'")
_LOG = re.compile(r"Out-File -LiteralPath '([^']+)'")
_RUNNER_TOKEN = re.compile(r"\.([0-9a-f]{8})\.ps1$")


class _Deadline:
    expired = False

    def slice(self, value: float) -> float:
        return 0.0


class _Guest:
    """Records every script and file the runner touches; always succeeds."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.written: list[tuple[str, str]] = []

    def ps(self, script: str, **kw: object) -> str:
        self.calls.append(script)
        if "Register-ScheduledTask -TaskName" in script:
            return ""
        if "Get-Content -LiteralPath" in script:
            return "EXITCODE=0\r\n"
        if "'yes'" in script and "'no'" in script:
            return "yes" if ".payload.ps1" in script else "no"
        return ""


def _runner(guest: _Guest) -> TaskRunnerMixin:
    runner = TaskRunnerMixin()
    runner.config = GuestConfig(
        winrm="http://guest:5985/wsman", user="u", password="p", out=_OUT
    )
    runner.ps = guest.ps  # type: ignore[method-assign]
    runner.write_text = lambda path, text: guest.written.append((path, text))  # type: ignore[attr-defined]
    runner.read_text = lambda path: ""  # type: ignore[attr-defined]
    return runner


def _run(runner: TaskRunnerMixin, name: str, cleanup: str) -> None:
    runner.run_task(
        name=name,
        script="Write-Output hi",
        files_before=cleanup,
        deadline=_Deadline(),  # type: ignore[arg-type]
        poll=0,
    )


def _runner_texts(guest: _Guest) -> list[str]:
    return [
        text
        for path, text in guest.written
        if path.endswith(".ps1") and not path.endswith(".payload.ps1")
    ]


class TestThePerRunPathsAreDisjoint:
    def test_two_runs_of_one_name_do_not_share_a_runner_or_payload(self) -> None:
        guest = _Guest()
        runner = _runner(guest)
        _run(runner, "agentic_bi_board", "")
        _run(runner, "agentic_bi_board", "")
        payloads = [path for path, _ in guest.written if path.endswith(".payload.ps1")]
        scripts = [
            path
            for path, _ in guest.written
            if path.endswith(".ps1") and not path.endswith(".payload.ps1")
        ]
        assert len(payloads) == 2 and len(set(payloads)) == 2
        assert len(scripts) == 2 and len(set(scripts)) == 2

    def test_two_runs_of_one_name_do_not_share_a_log_or_marker(self) -> None:
        guest = _Guest()
        runner = _runner(guest)
        _run(runner, "agentic_bi_board", "")
        _run(runner, "agentic_bi_board", "")
        scripts = _runner_texts(guest)
        logs = [m.group(1) for text in scripts for m in [_LOG.search(text)] if m]
        markers = [m.group(1) for text in scripts for m in [_MARKER.search(text)] if m]
        assert len(logs) == 2 and len(set(logs)) == 2, logs
        assert len(markers) == 2 and len(set(markers)) == 2, markers

    def test_the_cleanup_reaches_only_the_run_it_was_given_for(self) -> None:
        guest = _Guest()
        runner = _runner(guest)
        _run(runner, "board", "Remove-Own 'C:\\pbi\\out\\first.pbix'\r\n")
        _run(runner, "board", "Remove-Own 'C:\\pbi\\out\\second.pbix'\r\n")
        first, second = _runner_texts(guest)
        assert "first.pbix" in first and "second.pbix" not in first
        assert "second.pbix" in second and "first.pbix" not in second

    def test_run_paths_are_unique_per_call(self) -> None:
        first = run_paths(_OUT, "board")
        second = run_paths(_OUT, "board")
        for name in ("task", "runner", "payload", "log", "marker"):
            assert getattr(first, name) != getattr(second, name)

    def test_every_artifact_of_one_run_carries_the_same_token(self) -> None:
        paths = run_paths(_OUT, "board")
        match = _RUNNER_TOKEN.search(paths.runner)
        assert match, paths.runner
        token = match.group(1)
        assert paths.task == f"board_{token}"
        assert paths.payload == rf"{_OUT}\board.{token}.payload.ps1"
        assert paths.log == rf"{_OUT}\board.{token}.log"
        assert paths.marker == rf"{_OUT}\board.{token}.done"

    def test_the_token_is_not_a_pid_and_second_counter(self) -> None:
        tokens = {run_token() for _ in range(20)}
        assert len(tokens) == 20
