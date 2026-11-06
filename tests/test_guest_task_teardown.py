"""`run_task` teardown must never replace the verdict it was cleaning up after.

The `Unregister-ScheduledTask` in the `finally` used to be a plain `self.ps(...)`.
When the transport died at the end of a run (the guest rebooted, the WinRM
session expired), that call raised `StageError` *inside* the `finally` and masked
the original `ChainTimeout`: the chain reported STAGE_FAILED instead of TIMEOUT
and could spend more budget in the teardown than the run had left.

The teardown is therefore best effort: it logs and lets the original exception
through. It must also actually stop the task: `Unregister-ScheduledTask` fails on
a **running** task, and `-EA SilentlyContinue` hid that, so the task stayed
registered and later wrote a marker into the next run's name. The teardown stops
it first, and only when it is registered.
"""

from __future__ import annotations

import pytest

from agentic_bi.guest_task import TaskRunnerMixin
from agentic_bi.guest_types import ChainTimeout, GuestConfig


class _ExpiringDeadline:
    """Expires after a couple of polls, so the run reaches `ChainTimeout`."""

    def __init__(self) -> None:
        self.checks = 0

    @property
    def expired(self) -> bool:
        self.checks += 1
        return self.checks > 3

    def slice(self, value: float) -> float:
        return 0.0


class _Guest:
    """A guest whose task never writes a marker and whose transport then dies."""

    def __init__(
        self, *, unregister_raises: bool = True, writes_marker: bool = False
    ) -> None:
        self.calls: list[str] = []
        self.unregister_raises = unregister_raises
        self.writes_marker = writes_marker
        self.marker = False

    def ps(self, script: str, **kw: object) -> str:
        self.calls.append(script)
        if "Register-ScheduledTask -TaskName" in script:
            self.marker = self.writes_marker
            return ""
        if "Get-Content -LiteralPath" in script:
            return "EXITCODE=0\r\n" if self.marker else ""
        if "Remove-Item -LiteralPath" in script:
            self.marker = False
            return ""
        if "'yes'" in script and "'no'" in script:
            path = script.split("Test-Path -LiteralPath '", 1)[1].split("'", 1)[0]
            if path.endswith("payload.ps1"):
                return "yes"
            return "yes" if self.marker else "no"
        if "Unregister-ScheduledTask" in script and self.unregister_raises:
            raise RuntimeError("the WinRM session is gone")
        return ""


def _runner(guest: _Guest) -> TaskRunnerMixin:
    runner = TaskRunnerMixin()
    runner.config = GuestConfig(
        winrm="http://guest:5985/wsman", user="u", password="p", out=r"C:\pbi\out"
    )
    runner.ps = guest.ps  # type: ignore[method-assign]
    runner.write_text = lambda path, text: None  # type: ignore[attr-defined]
    runner.read_text = lambda path: ""  # type: ignore[attr-defined]
    return runner


def _run(runner: TaskRunnerMixin) -> None:
    runner.run_task(
        name="probe",
        script="Write-Output hi",
        deadline=_ExpiringDeadline(),  # type: ignore[arg-type]
        poll=0,
    )


class TestTheTeardownIsBestEffort:
    def test_a_dead_transport_does_not_mask_the_timeout(self) -> None:
        guest = _Guest(unregister_raises=True)
        runner = _runner(guest)
        with pytest.raises(ChainTimeout, match="marker not seen"):
            _run(runner)

    def test_the_teardown_is_still_attempted(self) -> None:
        guest = _Guest(unregister_raises=True)
        runner = _runner(guest)
        with pytest.raises(ChainTimeout):
            _run(runner)
        assert any("Unregister-ScheduledTask" in call for call in guest.calls)

    def test_the_failure_is_logged_so_it_is_not_silent(self, caplog) -> None:
        guest = _Guest(unregister_raises=True)
        runner = _runner(guest)
        with caplog.at_level("WARNING", logger="agentic_bi.guest_task"):
            with pytest.raises(ChainTimeout):
                _run(runner)
        assert any("unregister" in record.message for record in caplog.records)

    def test_a_working_teardown_still_lets_the_result_through(self) -> None:
        guest = _Guest(unregister_raises=False, writes_marker=True)
        runner = _runner(guest)
        _, code = runner.run_task(
            name="probe",
            script="Write-Output hi",
            deadline=_ExpiringDeadline(),  # type: ignore[arg-type]
            poll=0,
        )
        assert code == 0
        assert any("Unregister-ScheduledTask" in call for call in guest.calls)


class TestTheTeardownStopsTheRunningTask:
    def test_a_registered_task_is_stopped_before_it_is_unregistered(self) -> None:
        guest = _Guest(unregister_raises=False, writes_marker=True)
        runner = _runner(guest)
        _, _ = runner.run_task(
            name="probe",
            script="Write-Output hi",
            deadline=_ExpiringDeadline(),  # type: ignore[arg-type]
            poll=0,
        )
        teardown = next(c for c in guest.calls if "Stop-ScheduledTask" in c)
        assert "Get-ScheduledTask -TaskName" in teardown
        assert "Stop-ScheduledTask -TaskName" in teardown
        assert teardown.index("Get-ScheduledTask") < teardown.index(
            "Stop-ScheduledTask"
        )
        assert teardown.index("Stop-ScheduledTask") < teardown.index(
            "Unregister-ScheduledTask"
        )

    def test_the_stop_is_guarded_so_a_missing_task_is_not_an_error(self) -> None:
        guest = _Guest(unregister_raises=False, writes_marker=True)
        runner = _runner(guest)
        _, _ = runner.run_task(
            name="probe",
            script="Write-Output hi",
            deadline=_ExpiringDeadline(),  # type: ignore[arg-type]
            poll=0,
        )
        teardown = next(c for c in guest.calls if "Stop-ScheduledTask" in c)
        assert "Get-ScheduledTask -TaskName 'probe_" in teardown
        assert "-EA SilentlyContinue) { Stop-ScheduledTask" in teardown
