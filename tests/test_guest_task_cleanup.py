"""A finished `run_task` removes its own artifacts; a failed one keeps them.

Each run writes a payload, a runner, a marker and a marker `.tmp` under
`config.out`. Nothing removed them, so every run leaked four files (plus a whole
`.pbix` for an oracle run) in the guest's output directory. The log is different:
it is the run's output, so it is kept in both cases.
"""

from __future__ import annotations

import pytest

from agentic_bi.guest_task import TaskRunnerMixin
from agentic_bi.guest_types import ChainTimeout, GuestConfig, StageError


class _Deadline:
    def __init__(self, expire_after: int | None = None) -> None:
        self.expired = False
        self._left = expire_after

    def slice(self, value: float) -> float:
        if self._left is not None:
            self._left -= 1
            if self._left <= 0:
                self.expired = True
        return 0.0


class _Guest:
    """Records every PowerShell call; a registered task writes a marker."""

    def __init__(self, exits: bool = True) -> None:
        self.calls: list[str] = []
        self.attempts: list[tuple[str, object]] = []
        self.written: list[str] = []
        self._exits = exits
        self.marker_ready = False

    def ps(self, script: str, **kw: object) -> str:
        self.calls.append(script)
        self.attempts.append((script, kw.get("attempts")))
        if "Register-ScheduledTask -TaskName" in script:
            self.marker_ready = True
            return ""
        if "Get-Content -LiteralPath" in script:
            return "EXITCODE=0\r\n" if self._exits and self.marker_ready else ""
        return ""


def _runner(guest: _Guest) -> TaskRunnerMixin:
    runner = TaskRunnerMixin()
    runner.config = GuestConfig(
        winrm="http://guest:5985/wsman", user="u", password="p", out=r"C:\pbi\out"
    )
    runner.ps = guest.ps  # type: ignore[method-assign]
    runner.write_text = lambda path, text: guest.written.append(path)  # type: ignore[method-assign]
    runner.read_text = lambda path: "run log"  # type: ignore[attr-defined]
    # Before the task is registered only the payload exists (the stale marker
    # and log are gone), so the pre-run cleanup terminates on the first probe.
    runner._exists = (  # type: ignore[method-assign]
        lambda path: path.endswith(".payload.ps1") or guest.marker_ready
    )
    return runner


def _cleanup_scripts(calls: list[str]) -> list[str]:
    return [call for call in calls if "Remove-Item -LiteralPath" in call]


def _paths(guest: _Guest) -> tuple[str, str]:
    payload, runner = guest.written
    assert payload.endswith(".payload.ps1")
    assert runner.endswith(".ps1")
    return payload, runner


def test_a_finished_run_removes_its_payload_runner_and_marker():
    guest = _Guest()
    runner = _runner(guest)
    log, code = runner.run_task(
        name="agentic_bi_board",
        script="Write-Output hi",
        deadline=_Deadline(),  # type: ignore[arg-type]
        poll=0,
    )
    assert (log, code) == ("run log", 0)
    payload, script = _paths(guest)
    stem = script.rsplit(".", 1)[0]
    cleanup = _cleanup_scripts(guest.calls)[-1]
    for path in (payload, script, f"{stem}.done", f"{stem}.done.tmp"):
        assert f"'{path}'" in cleanup, path
    # the log is the run's output and stays
    assert ".log" not in cleanup


def test_a_timeout_keeps_every_artifact_for_diagnosis():
    guest = _Guest(exits=False)
    runner = _runner(guest)
    with pytest.raises(ChainTimeout):
        runner.run_task(
            name="agentic_bi_board",
            script="Write-Output hi",
            deadline=_Deadline(expire_after=1),  # type: ignore[arg-type]
            poll=0,
        )
    payload, _ = _paths(guest)
    for call in _cleanup_scripts(guest.calls):
        assert payload not in call


def test_a_failed_setup_keeps_every_artifact_for_diagnosis():
    guest = _Guest()
    runner = _runner(guest)
    # A stale marker that refuses to disappear: cleanup gives up before the
    # task is registered, so no payload cleanup may follow.
    runner._exists = (  # type: ignore[method-assign]
        lambda path: path.endswith(".payload.ps1") or path.endswith(".done")
    )
    with pytest.raises(StageError, match="could not be removed"):
        runner.run_task(
            name="agentic_bi_board",
            script="Write-Output hi",
            deadline=_Deadline(),  # type: ignore[arg-type]
            poll=0,
        )
    payload, _ = _paths(guest)
    for call in _cleanup_scripts(guest.calls):
        assert payload not in call


def test_teardown_and_cleanup_do_not_retry_past_the_deadline():
    """A dead guest must not add minutes of retries after the timeout.

    `ps` retries four times with a 60 s operation timeout and a 2/4/6 s backoff,
    so an unbounded teardown call could take ~6 minutes *per call* after the
    chain's own budget had already expired. Both `finally` calls therefore run
    with `attempts=1`.
    """
    guest = _Guest()
    runner = _runner(guest)
    runner.run_task(
        name="agentic_bi_board",
        script="Write-Output hi",
        deadline=_Deadline(),  # type: ignore[arg-type]
        poll=0,
    )
    teardown = [a for script, a in guest.attempts if "Stop-ScheduledTask" in script]
    cleanup = [
        a
        for script, a in guest.attempts
        if "Remove-Item -LiteralPath" in script and ".payload.ps1" in script
    ]
    assert teardown == [1]
    assert cleanup == [1]
