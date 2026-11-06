"""`run_task` must fail loudly instead of reporting a fake task result.

Two silent-failure paths are pinned here:

* an empty (or `None`) script used to produce a payload that only carried the
  exit footer, so the run reported success without doing any work;
* a payload that never reached the guest let the scheduled task fail with exit
  code 1, which the marker then reported as the task's *result*.

The marker must also be written exactly once per run, a stale marker **or log**
that survives the pre-run cleanup must abort the run instead of being read back
as this run's result, and the fake guest answers the runner's real scripts
(`Register-ScheduledTask -TaskName`, `Get-Content -LiteralPath`, an existence
probe) rather than matching loose substrings of them.
"""

from __future__ import annotations

import pytest

from agentic_bi.guest_task import TaskRunnerMixin
from agentic_bi.guest_task_script import _MARKER_TOKEN
from agentic_bi.guest_types import GuestConfig, StageError


class _Deadline:
    expired = False

    def slice(self, value: float) -> float:
        return 0.0


class _Guest:
    """A stateful guest: registering the task writes its marker once."""

    def __init__(
        self,
        code: int = 0,
        *,
        payload_written: bool = True,
        marker_removable: bool = True,
        log_removable: bool = True,
    ) -> None:
        self.calls: list[str] = []
        self.written: list[tuple[str, str]] = []
        self.code = code
        self.marker: str | None = None
        self.log: str | None = None
        self.marker_removable = marker_removable
        self.log_removable = log_removable
        self.payload_written = payload_written

    def ps(self, script: str, **kw: object) -> str:
        self.calls.append(script)
        if "Register-ScheduledTask -TaskName" in script:
            self.marker = f"{_MARKER_TOKEN}{self.code}\r\n"
            self.log = "previous log"
            return ""
        if "Get-Content -LiteralPath" in script:
            return self.marker or ""
        if "Remove-Item -LiteralPath" in script:
            if ".done" in script and self.marker_removable:
                self.marker = None
            if ".log" in script and self.log_removable:
                self.log = None
            return ""
        if "'yes'" in script and "'no'" in script:
            path = script.split("Test-Path -LiteralPath '", 1)[1].split("'", 1)[0]
            if path.endswith("payload.ps1"):
                return "yes" if self.payload_written else "no"
            if path.endswith(".done"):
                return "yes" if self.marker else "no"
            if path.endswith(".log"):
                return "yes" if self.log else "no"
        return ""

    def write_text(self, guest_path: str, text: str) -> None:
        self.written.append((guest_path, text))

    def read_text(self, guest_path: str) -> str:
        return self.log or ""


def _runner(**kwargs: object) -> tuple[_Guest, TaskRunnerMixin]:
    guest = _Guest(**kwargs)  # type: ignore[arg-type]
    runner = TaskRunnerMixin()
    runner.config = GuestConfig(
        winrm="http://guest:5985/wsman",
        user="u",
        password="p",
        out=r"C:\pbi\out",
    )
    runner.ps = guest.ps  # type: ignore[method-assign]
    runner.write_text = guest.write_text  # type: ignore[method-assign]
    runner.read_text = guest.read_text  # type: ignore[method-assign]
    return guest, runner


def _run(runner: TaskRunnerMixin, script: str = "Write-Output hi") -> int:
    _, code = runner.run_task(
        name="probe",
        script=script,
        deadline=_Deadline(),  # type: ignore[arg-type]
        poll=0,
    )
    return code


class TestEmptyScriptIsRefused:
    @pytest.mark.parametrize("script", ["", "\r\n", "   \t\r\n"])
    def test_empty_scripts_raise_before_touching_the_guest(self, script: str) -> None:
        guest, runner = _runner()
        with pytest.raises(ValueError, match="non-empty script"):
            _run(runner, script)
        assert guest.calls == []
        assert guest.written == []

    def test_none_raises_instead_of_an_attribute_error(self) -> None:
        guest, runner = _runner()
        with pytest.raises(ValueError, match="non-empty script"):
            _run(runner, None)  # type: ignore[arg-type]
        assert guest.calls == []


class TestMissingPayloadIsLoud:
    def test_the_run_stops_before_the_task_is_registered(self) -> None:
        guest, runner = _runner(payload_written=False)
        with pytest.raises(StageError, match="payload"):
            _run(runner)
        assert not any(
            "Register-ScheduledTask -TaskName" in call for call in guest.calls
        )

    def test_the_marker_stays_absent_so_no_code_is_reported(self) -> None:
        guest, runner = _runner(payload_written=False)
        with pytest.raises(StageError, match="payload"):
            _run(runner)
        assert guest.marker is None


class TestStaleMarkerOrLogBlocksTheRun:
    def test_an_unremovable_marker_is_a_failure_not_a_result(self) -> None:
        guest, runner = _runner(marker_removable=False)
        guest.marker = f"{_MARKER_TOKEN}1"
        with pytest.raises(StageError, match="stale marker"):
            _run(runner)
        assert not any(
            "Register-ScheduledTask -TaskName" in call for call in guest.calls
        )

    def test_an_unremovable_log_is_a_failure_not_this_runs_output(self) -> None:
        guest, runner = _runner(log_removable=False)
        guest.log = "output of the previous run"
        with pytest.raises(StageError, match="stale marker"):
            _run(runner)
        assert not any(
            "Register-ScheduledTask -TaskName" in call for call in guest.calls
        )


class TestTheMarkerIsWrittenExactlyOnce:
    def test_the_runner_has_one_marker_write(self) -> None:
        guest, runner = _runner()
        assert _run(runner) == 0
        runner_text = guest.written[-1][1]
        assert runner_text.count("Set-Content") == 1
        assert runner_text.count(_MARKER_TOKEN) == 1

    def test_the_payload_runs_before_the_marker_is_written(self) -> None:
        guest, runner = _runner()
        _run(runner)
        runner_text = guest.written[-1][1]
        assert runner_text.index(".payload.ps1") < runner_text.index("Set-Content")
        assert runner_text.index("Set-Content") < runner_text.index("[IO.File]::Move")


class TestRepeatedRunsStartClean:
    def test_each_run_cleans_the_previous_marker_and_log(self) -> None:
        guest, runner = _runner(code=0)
        assert _run(runner) == 0
        guest.code = 2
        assert _run(runner) == 2
        registers = [
            index
            for index, call in enumerate(guest.calls)
            if "Register-ScheduledTask -TaskName" in call
        ]
        assert len(registers) == 2
        second = registers[1]
        window = guest.calls[registers[0] : second]
        assert any("Remove-Item -LiteralPath" in call for call in window)
        assert any(".done" in call for call in window)
        assert any(".log" in call for call in window)

    def test_the_second_run_reports_its_own_code(self) -> None:
        guest, runner = _runner(code=0)
        assert _run(runner) == 0
        guest.code = 3
        assert _run(runner) == 3
