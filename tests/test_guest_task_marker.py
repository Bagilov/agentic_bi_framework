"""The task marker must always carry a real exit code, and the log a real cause.

`run_task` used to dot-source the payload and then write `EXITCODE=$LASTEXITCODE`
into the marker. Two ordinary payloads broke that: `$LASTEXITCODE` is empty when
the payload ends on a cmdlet (so the marker never parsed and the chain polled to
its deadline), and a payload `exit N` left the process before the marker was
written at all. Both were reproduced on the Windows guest.

A refused child was the third silent path: nothing redirected its stdout/stderr,
so the log stayed empty and the marker carried only `EXITCODE=1` — the actual
cause (ACL, parse error, `powershell.exe` not on PATH) was lost. These tests pin
the structure that fixes all three: a child-process payload with an exit footer, a
runner that starts with `$ErrorActionPreference='Stop'`, appends the child's
output to the log, folds its exit code into a **complete** marker, and writes that
marker atomically so a poll cannot read `EXITCODE=1` of an unfinished `EXITCODE=10`.
"""

from __future__ import annotations

from agentic_bi.guest_task import _EXIT_FOOTER, TaskRunnerMixin


class _Deadline:
    expired = False

    def slice(self, value: float) -> float:
        return 0.0


def _runner() -> tuple[TaskRunnerMixin, list[str], list[str]]:
    calls: list[str] = []
    written: list[str] = []
    state = {"marker": False, "log": False}
    runner = TaskRunnerMixin()
    runner.config = type("C", (), {"out": r"C:\pbi\out"})()  # type: ignore[attr-defined]

    def ps(script: str, **kw: object) -> str:
        calls.append(script)
        if "Register-ScheduledTask -TaskName" in script:
            state["marker"], state["log"] = True, True
            return ""
        if "Get-Content -LiteralPath" in script:
            return "EXITCODE=0\r\n" if state["marker"] else ""
        if "Remove-Item -LiteralPath" in script:
            state["marker"], state["log"] = False, False
            return ""
        if "'yes'" in script and "'no'" in script:
            path = script.split("Test-Path -LiteralPath '", 1)[1].split("'", 1)[0]
            if path.endswith(".payload.ps1"):
                return "yes"
            if path.endswith(".log"):
                return "yes" if state["log"] else "no"
            return "yes" if state["marker"] else "no"
        return ""

    runner.ps = ps  # type: ignore[method-assign]
    runner.write_text = lambda path, text: written.append(text)  # type: ignore[attr-defined]
    runner.read_text = lambda path: "builder output"  # type: ignore[attr-defined]
    return runner, calls, written


def _run() -> tuple[list[str], list[str], int, str]:
    runner, calls, written = _runner()
    log, code = runner.run_task(
        name="probe",
        script="Write-Output hi",
        deadline=_Deadline(),
        poll=0,
    )
    return calls, written, code, log


class TestPayloadRunsAsItsOwnProcess:
    """The payload is a separate process, so its `exit N` reaches the runner."""

    def test_the_runner_invokes_the_payload_file(self) -> None:
        _, written, _, _ = _run()
        assert ".payload.ps1" in written[-1]
        assert "-File" in written[-1]

    def test_the_payload_ends_with_the_exit_footer(self) -> None:
        _, written, _, _ = _run()
        assert written[0].startswith("Write-Output hi")
        assert written[0].rstrip().endswith(_EXIT_FOOTER.rstrip())

    def test_the_runner_writes_the_child_exit_code_into_the_marker(self) -> None:
        _, written, _, _ = _run()
        runner_text = written[-1]
        assert "$LASTEXITCODE" in runner_text
        assert '"EXITCODE=" + $abfCode' in runner_text

    def test_a_missing_child_status_becomes_a_failure_not_an_empty_marker(
        self,
    ) -> None:
        _, written, _, _ = _run()
        assert "if (-not $abfOk) { $abfCode = 1 }" in written[-1]
        assert "EXITCODE=$LASTEXITCODE" not in written[-1]


class TestTheMarkerIsCompleteAndAtomic:
    def test_the_marker_is_written_to_a_temporary_and_moved(self) -> None:
        _, written, _, _ = _run()
        runner_text = written[-1]
        assert "Set-Content -LiteralPath" in runner_text
        assert "$s='" in runner_text and "$d='" in runner_text
        assert "[IO.File]::Move($s,$d)" in runner_text
        assert ", $true)" not in runner_text
        assert runner_text.index("Set-Content") < runner_text.index("[IO.File]::Move")

    def test_the_temporary_marker_is_cleaned_up_first(self) -> None:
        _, written, _, _ = _run()
        runner_text = written[-1]
        assert ".done.tmp'" in runner_text
        assert runner_text.index("Remove-Item -LiteralPath") < runner_text.index(
            "Set-Content"
        )


class TestTheChildOutputReachesTheLog:
    """A refused child must leave its reason in the log, not just `EXITCODE=1`."""

    def test_the_child_is_redirected_into_the_log(self) -> None:
        _, written, _, _ = _run()
        assert "2>&1 | Out-File -LiteralPath" in written[-1]
        assert "-Append -Encoding utf8" in written[-1]

    def test_the_exit_code_is_read_after_the_redirect(self) -> None:
        _, written, _, _ = _run()
        runner_text = written[-1]
        assert runner_text.index("Out-File") < runner_text.index(
            "$abfCode = $LASTEXITCODE"
        )

    def test_the_marker_is_written_after_the_exit_code_is_known(self) -> None:
        _, written, _, _ = _run()
        runner_text = written[-1]
        assert runner_text.index("$abfCode = $LASTEXITCODE") < runner_text.index(
            "Set-Content"
        )

    def test_the_stale_log_is_cleared_before_the_child_runs(self) -> None:
        _, written, _, _ = _run()
        runner_text = written[-1]
        assert runner_text.index("Remove-Item -LiteralPath") < runner_text.index(
            "Out-File"
        )


class TestTheRunnerFailsLoudly:
    def test_the_runner_starts_with_stop(self) -> None:
        _, written, _, _ = _run()
        assert written[-1].startswith("$ErrorActionPreference='Stop'")

    def test_the_redirect_failure_is_folded_into_the_code(self) -> None:
        # `Stop` is restored only after the exit rule, so a refused `Out-File`
        # is non-terminating and its `$?` reaches the marker as a failure.
        _, written, _, _ = _run()
        runner_text = written[-1]
        rule = runner_text.index("$abfOk = $?")
        assert runner_text.index("$ErrorActionPreference='Continue'") < rule
        assert rule < runner_text.rindex("$ErrorActionPreference='Stop'")

    def test_stop_is_restored_before_the_marker_write(self) -> None:
        _, written, _, _ = _run()
        runner_text = written[-1]
        last_stop = runner_text.rindex("$ErrorActionPreference='Stop'")
        assert last_stop < runner_text.index("Set-Content"), (
            "a refused Set-Content must terminate instead of leaving no marker"
        )


class TestTheRunReturnsTheLog:
    def test_the_log_and_code_come_from_the_guest(self) -> None:
        _, _, code, log = _run()
        assert code == 0
        assert log == "builder output"


class TestFooterFoldsTheNativeExitCode:
    """A payload ending on a failing native command is still reported."""

    def test_footer_uses_last_exit_code_when_present(self) -> None:
        assert "$LASTEXITCODE" in _EXIT_FOOTER
        assert "exit $abfCode" in _EXIT_FOOTER

    def test_footer_captures_success_before_anything_else(self) -> None:
        assert _EXIT_FOOTER.splitlines()[0] == "$abfOk = $?"
