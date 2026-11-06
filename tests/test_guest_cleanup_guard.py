"""The guest cleanup must treat "already gone" as success, not as a failed stage.

Measured on the guest (Windows 11 ARM, Windows PowerShell 5.1):
`Remove-Item <missing> -EA SilentlyContinue` exits 0 on its own, but with
`$ErrorActionPreference='Stop'` in effect — which the task runner and the staging
scripts both set — `-EA SilentlyContinue` does not override it and the script
still ends with exit code 1. `run_ps` maps a non-zero exit to `StageError`, so
unguarded cleanup broke the first run on a clean guest, exactly when a marker, log
or staging directory does not exist yet. These tests pin the guarded form and its
use in both cleanup paths.
"""

from __future__ import annotations

from agentic_bi.guest_task import TaskRunnerMixin, remove_script

_ENGINE_STOP_WORDS = ("Stop-Process", "Get-Process")


class TestRemoveScriptIsGuarded:
    """Every path is deleted only when it is there, so no exit code 1."""

    def test_single_path_is_wrapped_in_a_test_path_guard(self) -> None:
        script = remove_script(r"C:\pbi\out\board.pbix")
        assert "if (Test-Path" in script
        assert script.count("Remove-Item") == 1
        assert r"C:\pbi\out\board.pbix" in script

    def test_missing_path_is_never_deleted_unguarded(self) -> None:
        script = remove_script(r"C:\pbi\out\marker.done")
        guarded, _, rest = script.partition("Remove-Item")
        assert "if (Test-Path" in guarded
        assert "-EA SilentlyContinue" not in rest

    def test_two_paths_produce_two_guarded_removals(self) -> None:
        script = remove_script(r"C:\pbi\out\a.log", r"C:\pbi\out\b.done")
        assert script.count("if (Test-Path") == 2
        assert script.count("Remove-Item") == 2

    def test_single_quote_in_a_path_is_doubled(self) -> None:
        script = remove_script(r"C:\pbi\out\a'b.pbix")
        assert "a''b.pbix" in script

    def test_double_quote_in_a_path_stays_inside_the_literal(self) -> None:
        script = remove_script(r'C:\pbi\out\a" b.pbix')
        assert script.count("'") == 4, "each path is one single-quoted literal"
        assert r'a" b.pbix' in script


class TestRunTaskCleansUpWithoutFailingOnAnEmptyGuest:
    """`run_task` must not raise when the previous marker/log are absent."""

    def _runner(self, calls: list[str]) -> tuple[TaskRunnerMixin, list[str]]:
        written: list[str] = []
        state = {"marker": False}
        runner = TaskRunnerMixin()
        runner.config = type("C", (), {"out": r"C:\pbi\out"})()  # type: ignore[attr-defined]

        def ps(script: str, **kw: object) -> str:
            calls.append(script)
            if "Register-ScheduledTask -TaskName" in script:
                state["marker"] = True
                return ""
            if "Get-Content -LiteralPath" in script:
                return "EXITCODE=0\r\n" if state["marker"] else ""
            if "Remove-Item -LiteralPath" in script:
                state["marker"] = False
                return ""
            if "'yes'" in script and "'no'" in script:
                path = script.split("Test-Path -LiteralPath '", 1)[1].split("'", 1)[0]
                if path.endswith("payload.ps1"):
                    return "yes"
                return "yes" if state["marker"] else "no"
            return ""

        runner.ps = ps  # type: ignore[method-assign]
        runner.write_text = lambda path, text: written.append(text)  # type: ignore[attr-defined]
        runner.read_text = lambda path: "EXITCODE=0\r\n"  # type: ignore[attr-defined]
        return runner, written

    def test_pre_cleanup_uses_the_guard(self) -> None:
        calls: list[str] = []
        runner, written = self._runner(calls)
        runner.run_task(
            name="probe",
            script="Write-Output hi\r\n",
            deadline=type("D", (), {"expired": False, "slice": lambda _s, v: 0})(),
            poll=0,
        )
        assert calls, "run_task must probe the guest"
        cleanup = " ".join(calls)
        assert (
            "Remove-Item C:\\pbi\\out\\probe.done -Force -EA SilentlyContinue"
            not in cleanup
        )
        assert written, "run_task must write its runner"
        assert "if (Test-Path" in written[-1]


class TestExtractZipStopsTheEngineSafely:
    """A missing PBIDesktop/msmdsrv must not fail the staging stage."""

    def test_engine_stop_is_process_guarded(self) -> None:
        from agentic_bi.guest_task import _STOP_ENGINE

        assert "Stop-Process" in _STOP_ENGINE
        assert "if (Get-Process -Name $p -EA SilentlyContinue)" in _STOP_ENGINE
        assert _STOP_ENGINE.lstrip().startswith(
            "foreach ($p in 'PBIDesktop','msmdsrv')"
        )
        for word in _ENGINE_STOP_WORDS:
            assert word in _STOP_ENGINE
