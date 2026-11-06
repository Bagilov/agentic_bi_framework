"""`_exists` must not turn a noisy answer into a false "absent".

The guest probe prints `yes`/`no`, but PowerShell can prepend a warning or a
progress line to that answer. Comparing the **whole** stdout against `yes` made a
payload that was written look absent (a false `StageError` before the task even
started) and made every cleanup retry look like it had not cleaned anything.

The contract is "the answer is a line, and it is the last non-empty one";
searching the output for the word `yes` would flip the bug the other way.
"""

from __future__ import annotations

import pytest

from agentic_bi.guest_task import TaskRunnerMixin
from agentic_bi.guest_types import StageError


def _exists(answer: str) -> bool:
    runner = TaskRunnerMixin()
    runner.ps = lambda script, **kw: answer  # type: ignore[method-assign]
    return runner._exists(r"C:\pbi\out\probe.payload.ps1")


@pytest.mark.parametrize(
    "answer",
    [
        "yes",
        "yes\r\n",
        "WARNING: something happened\r\nyes\r\n",
        "WARNING: remote path\nyes",
        "\r\nWARNING: noise\r\nyes\r\n\r\n",
    ],
)
def test_the_last_answer_line_decides(answer: str) -> None:
    assert _exists(answer)


@pytest.mark.parametrize(
    "answer",
    ["", "\r\n", "no", "WARNING: yes/no pattern\nthe answer is no", "missing\nyes/no"],
)
def test_a_missing_path_stays_absent(answer: str) -> None:
    assert not _exists(answer)


def test_an_answer_that_mentions_yes_but_ends_with_no_is_false() -> None:
    assert not _exists("WARNING: 'yes' was not expected\nno")


class TestThePayloadProbeUsesTheNewContract:
    def test_a_warning_before_yes_no_longer_fails_the_run(self) -> None:
        runner = TaskRunnerMixin()
        runner.config = type("C", (), {"out": r"C:\pbi\out"})()  # type: ignore[attr-defined]
        state = {"marker": False}

        def ps(script: str, **kw: object) -> str:
            if "Register-ScheduledTask -TaskName" in script:
                state["marker"] = True
                return ""
            if "Get-Content -LiteralPath" in script:
                return "EXITCODE=0\r\n" if state["marker"] else ""
            if "Remove-Item -LiteralPath" in script:
                return ""
            if "'yes'" in script and "'no'" in script:
                if ".payload.ps1" in script:
                    return "WARNING: noisy guest\r\nyes\r\n"
                return "no\r\n"
            return ""

        runner.ps = ps  # type: ignore[method-assign]
        runner.write_text = lambda path, text: None  # type: ignore[attr-defined]
        runner.read_text = lambda path: ""  # type: ignore[attr-defined]
        _, code = runner.run_task(
            name="probe",
            script="Write-Output hi",
            deadline=type("D", (), {"expired": False, "slice": lambda _s, v: 0})(),
            poll=0,
        )
        assert code == 0

    def test_a_genuinely_missing_payload_is_still_loud(self) -> None:
        runner = TaskRunnerMixin()
        runner.config = type("C", (), {"out": r"C:\pbi\out"})()  # type: ignore[attr-defined]
        runner.ps = lambda script, **kw: "no\r\n"  # type: ignore[method-assign]
        runner.write_text = lambda path, text: None  # type: ignore[attr-defined]
        with pytest.raises(StageError, match="payload"):
            runner.run_task(
                name="probe",
                script="Write-Output hi",
                deadline=type("D", (), {"expired": False, "slice": lambda _s, v: 0})(),
                poll=0,
            )
