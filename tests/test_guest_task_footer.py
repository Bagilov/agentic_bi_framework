"""The exit rule must report 0 only on an explicit success, in both stages.

The footer used to let a **stale** `$LASTEXITCODE` outrank `$?`: a payload of
`python ok; Set-Content <fail>` reported 0 (the cmdlet failed, but the code from
the earlier native command survived), and `python fail; Write-Output ok` reported
a failure even when `$?` described the successful last statement. The runner had
the same flaw from the other side: `$?` after its pipeline describes `Out-File`,
not the child, so a refused redirect (ACL, disk, missing directory) was invisible
while `$LASTEXITCODE` still carried a stale value.

The rule is now: capture `$abfOk = $?` first; a false `$?` means 1 unless
`$LASTEXITCODE` is non-null and non-zero, and a true `$?` still yields a non-zero
`$LASTEXITCODE` when there is one. Both the payload footer and the runner use the
same statements.

PowerShell is not installed on the host, so the emitted statements are evaluated
by a small model of the process state: it understands exactly the five statement
shapes the rule is allowed to contain, and any other line fails the test (a
rewrite has to be re-reviewed here; restoring the old precedence fails too).
"""

from __future__ import annotations

import pytest

from agentic_bi.guest_task import _EXIT_FOOTER, runner_script
from agentic_bi.guest_task_script import payload_footer

_FAILED = "if (-not $abfOk) { $abfCode = 1 }"
_NATIVE = (
    "if (($null -ne $LASTEXITCODE) -and ($LASTEXITCODE -ne 0)) "
    "{ $abfCode = $LASTEXITCODE }"
)
_OLD_CODE_LINE = (
    "if ($null -ne $LASTEXITCODE) { $abfCode = $LASTEXITCODE } "
    "elseif (-not $abfOk) { $abfCode = 1 }"
)


def _exit_code(script: str, *, last_exit_code: int | None, last_success: bool) -> int:
    """Evaluate an emitted rule against a simulated last-statement result."""
    env: dict[str, object] = {"LASTEXITCODE": last_exit_code, "$?": last_success}
    for raw in script.splitlines():
        line = raw.strip()
        if line == "$abfOk = $?":
            env["abfOk"] = env["$?"]
        elif line == "$abfCode = 0":
            env["abfCode"] = 0
        elif line == _FAILED:
            if not env["abfOk"]:
                env["abfCode"] = 1
        elif line == _NATIVE:
            if env["LASTEXITCODE"] is not None and env["LASTEXITCODE"] != 0:
                env["abfCode"] = env["LASTEXITCODE"]
        elif line == "exit $abfCode":
            return int(env["abfCode"])  # type: ignore[arg-type]
        else:
            raise AssertionError(f"unexpected statement in the rule: {line!r}")
    raise AssertionError("the rule never exits")


class TestTheFooterPolicy:
    def test_a_successful_native_command_reports_zero(self) -> None:
        assert _exit_code(_EXIT_FOOTER, last_exit_code=0, last_success=True) == 0

    def test_a_failing_native_command_reports_its_own_code(self) -> None:
        assert _exit_code(_EXIT_FOOTER, last_exit_code=7, last_success=False) == 7

    def test_a_missing_exit_code_after_a_failed_statement_reports_one(self) -> None:
        assert _exit_code(_EXIT_FOOTER, last_exit_code=None, last_success=False) == 1

    def test_a_missing_exit_code_after_a_successful_cmdlet_reports_zero(self) -> None:
        assert _exit_code(_EXIT_FOOTER, last_exit_code=None, last_success=True) == 0

    def test_a_failed_cmdlet_after_a_stale_success_code_reports_one(self) -> None:
        # `python ok; Set-Content <fail>`: `$LASTEXITCODE` is still 0, but `$?`
        # describes the failed cmdlet. The old precedence returned 0 here.
        assert _exit_code(_EXIT_FOOTER, last_exit_code=0, last_success=False) == 1

    def test_a_stale_failure_code_does_not_outrank_a_successful_cmdlet(self) -> None:
        # `python fail; Write-Output ok`: `$?` is true, so the last *native* code
        # is the only evidence left and is reported.
        assert _exit_code(_EXIT_FOOTER, last_exit_code=3, last_success=True) == 3

    def test_the_old_precedence_would_report_the_stale_zero(self) -> None:
        with pytest.raises(AssertionError, match="unexpected statement"):
            _exit_code(
                _OLD_CODE_LINE + "\nexit $abfCode\n",
                last_exit_code=0,
                last_success=False,
            )


class TestTheFooterShape:
    def test_success_is_captured_before_anything_else(self) -> None:
        assert _EXIT_FOOTER.splitlines()[0] == "$abfOk = $?"

    def test_the_footer_matches_the_public_payload_footer(self) -> None:
        assert _EXIT_FOOTER == payload_footer()

    def test_the_footer_is_a_single_exit(self) -> None:
        assert _EXIT_FOOTER.count("exit ") == 1
        assert _EXIT_FOOTER.rstrip().endswith("exit $abfCode")

    def test_the_runner_uses_the_same_rule(self) -> None:
        runner = runner_script(
            payload=r"C:\pbi\out\p.payload.ps1",
            log_path=r"C:\pbi\out\p.log",
            marker_path=r"C:\pbi\out\p.done",
        )
        for statement in ("$abfOk = $?", _FAILED, _NATIVE):
            assert statement in runner
        assert _OLD_CODE_LINE not in runner


@pytest.mark.parametrize("code", [0, 1, 2, 127, -1])
def test_every_explicit_native_code_is_preserved(code: int) -> None:
    assert (
        _exit_code(_EXIT_FOOTER, last_exit_code=code, last_success=(code == 0)) == code
    )
