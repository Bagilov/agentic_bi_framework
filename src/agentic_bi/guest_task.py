"""Guest-side task execution: interactive scheduled tasks and zip extraction.

`run_task` runs a script as an **interactive** scheduled task, because WinRM
lands in session 0 while Power BI Desktop only brings its engine up in session 1.
`extract_zip` stages an archive into a fresh directory, working around Windows
PowerShell 5.1 quirks (`Expand-Archive` silently stops part-way) and files held
open by a running Desktop/engine.

Completion is signalled by a **marker file**, never by a string in the log: a
PowerShell `*>` redirect writes UTF-16 while `Out-File -Encoding utf8` appends
UTF-8, so a text sentinel comes back mangled.

A `run_task` call owns every artifact of its own run: the task, runner, payload,
log and marker all carry one random per-run token (`run_paths`), so two runs with
the same `name` can neither overwrite nor delete each other's files. A finished
run then removes its payload, runner and marker (keeping the log, which is its
output); a failed run keeps all of them as evidence. The final `.pbix` stays where
the caller declared it and is only replaced by a finished build (see
`guest_chain_build.run_build`).

Public API:
    TaskRunnerMixin.run_task / extract_zip
    the re-exported `guest_task_script` helpers (`check_name`, `remove_script`,
    `run_paths`, `runner_script`, `parse_exitcode`) and `_EXIT_FOOTER`.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from agentic_bi.guest_task_script import (
    _task_argument,
    check_name,
    parse_exitcode,
    payload_footer,
    remove_script,
    run_paths,
    runner_script,
)
from agentic_bi.guest_types import ChainTimeout, Deadline, StageError, ps_quote

if TYPE_CHECKING:  # only needed for the mixin's attribute declarations
    from agentic_bi.guest_types import GuestConfig

logger = logging.getLogger(__name__)

_EXIT_FOOTER = payload_footer()

# Deleting a path that is already gone is normal here (a first run has no marker,
# no log, no staging directory). Measured on the guest (Windows 11 ARM, Windows
# PowerShell 5.1): `Remove-Item <missing> -EA SilentlyContinue` still exits 1 while
# `$ErrorActionPreference='Stop'` is in effect, and `run_ps` treats a non-zero exit
# as a failed stage. Every removal is therefore guarded by `Test-Path` (and every
# `Stop-Process` by `Get-Process`) so "nothing to clean" stays a success.
_STOP_ENGINE = (
    "foreach ($p in 'PBIDesktop','msmdsrv') "
    "{ if (Get-Process -Name $p -EA SilentlyContinue) "
    "{ Stop-Process -Name $p -Force } }\n"
)


class TaskRunnerMixin:
    """Run guest scripts as scheduled tasks and stage archives onto the guest."""

    if TYPE_CHECKING:
        # The composed `WinRMTransport` inherits `config`/`ps`/`write_text`/
        # `read_text` from `WinRMChannel`, but this mixin is checked on its own,
        # so those members are declared here. The signatures are copied verbatim
        # from `WinRMChannel` on purpose: an override that differs there would
        # make the composed class's bases incompatible.
        config: GuestConfig

        def ps(self, script: str, *, attempts: int = 4) -> str: ...

        def write_text(self, guest_path: str, text: str) -> None: ...

        def read_text(self, guest_path: str) -> str: ...

    def _exists(self, guest_path: str) -> bool:
        """True when `guest_path` exists on the guest (literal, not a wildcard).

        Only the **last non-empty line** is compared against `yes`: PowerShell
        may prepend a warning line, and comparing the whole output made a present
        payload look absent (a false `StageError` on verification and cleanup).
        """
        answer = self.ps(
            f"if (Test-Path -LiteralPath {ps_quote(guest_path)}) "
            "{ 'yes' } else { 'no' }"
        )
        lines = [line.strip() for line in answer.splitlines() if line.strip()]
        return bool(lines) and lines[-1] == "yes"

    def run_task(
        self,
        *,
        name: str,
        script: str,
        files_before: str = "",
        deadline: Deadline,
        poll: float = 10.0,
        limit_min: int = 20,
    ) -> tuple[str, int]:
        """Run `script` as an interactive scheduled task; wait for its marker.

        The task is registered, started and polled, and is **always** unregistered
        afterwards (success, failure or timeout). Returns ``(log, exit_code)``.

        All artifact paths (task name, runner, payload, log, marker) come from
        `run_paths`, i.e. from `name` plus a random per-run token, and the caller
        cannot supply them. Two concurrent calls with the same `name` therefore
        never share a payload, a runner, a log or a marker: the second run used to
        overwrite the first run's payload and delete its live marker and log.

        `files_before` is a cleanup expression run before the task starts (e.g.
        deleting this run's own stale output), so a later "file exists" check
        cannot be satisfied by a previous run's artifact. It must name only
        per-run paths — a shared artifact must be replaced by a finished build
        instead of deleted up front.

        The marker (and its `.tmp`) and the log are deleted here, **before** the
        task starts, and the deletion is verified: a scheduled task takes a moment
        to launch, so a previous run's marker (`EXITCODE=1`, say) would be read
        back instantly as this run's result, and a leftover log would be returned
        as this run's output.

        A poll can catch the marker mid-write (`EXITCODE=` with the digits not yet
        flushed); a match is only accepted when a complete, terminated code is
        present (see `parse_exitcode`).

        An empty (or non-`str`) `script` is refused: the payload would only carry
        the exit footer, and the run would report a success that did no work. The
        written payload is verified before the task is registered, so a failed
        `write_text` raises here instead of producing an `EXITCODE=1` that looks
        like a real task result.

        Raises:
            ValueError: when `script` is empty/not a string, or `name` is not a
                safe task/file name.
            StageError: when the payload is missing, or a stale marker/log
                survives cleanup (reading it would report a previous run).
            ChainTimeout: when the marker does not appear before `deadline`.
        """
        if not isinstance(script, str) or not script.strip():
            raise ValueError(
                "run_task needs a non-empty script: an empty task would write a "
                "marker without doing any work and pass as a real result"
            )
        paths = run_paths(self.config.out, name)
        # The payload runs as a **child** process and carries its own exit footer:
        # a payload `exit N` has to leave the process, and a payload ending on a
        # failing native command (the builder) must still be reported. Neither is
        # possible when the payload is dot-sourced into the marker writer: `exit`
        # would skip the marker write (the chain then polls until its deadline) and
        # `$LASTEXITCODE` after a cmdlet is empty, which also never parses.
        self.write_text(paths.payload, f"{script}\r\n{_EXIT_FOOTER}")
        if not self._exists(paths.payload):
            raise StageError(
                f"{name}: the task payload {paths.payload} was not written"
            )
        self.write_text(
            paths.runner,
            runner_script(
                payload=paths.payload,
                log_path=paths.log,
                marker_path=paths.marker,
                files_before=files_before,
            ),
        )
        for _ in range(3):
            self.ps(remove_script(paths.marker, paths.log, paths.marker + ".tmp"))
            if not self._exists(paths.marker) and not self._exists(paths.log):
                break
            time.sleep(deadline.slice(2.0))
        else:
            raise StageError(
                f"{name}: the stale marker {paths.marker} or log {paths.log} could "
                "not be removed; refusing to read a previous run's result"
            )
        setup = (
            f"Unregister-ScheduledTask -TaskName {ps_quote(paths.task)} "
            "-Confirm:$false -EA SilentlyContinue | Out-Null\n"
            "$act=New-ScheduledTaskAction -Execute 'powershell.exe' "
            f"-Argument {ps_quote(_task_argument(paths.runner))}\n"
            "$pr=New-ScheduledTaskPrincipal -UserId $env:USERNAME "
            "-LogonType Interactive -RunLevel Highest\n"
            "$set=New-ScheduledTaskSettingsSet -ExecutionTimeLimit "
            f"(New-TimeSpan -Minutes {int(limit_min)})\n"
            f"Register-ScheduledTask -TaskName {ps_quote(paths.task)} -Action $act "
            "-Principal $pr -Settings $set -Force | Out-Null\n"
            f"Start-ScheduledTask -TaskName {ps_quote(paths.task)}\n"
        )
        completed = False
        try:
            self.ps(setup)
            marker = ""
            while not deadline.expired:
                # Not stripped: `parse_exitcode` requires the terminator the
                # atomic writer always emits, so trimming it would turn a
                # complete marker into a truncated one.
                marker = self.ps(
                    f"if (Test-Path -LiteralPath {ps_quote(paths.marker)}) "
                    f"{{ Get-Content -LiteralPath {ps_quote(paths.marker)} -Raw }}"
                )
                code = parse_exitcode(marker)
                if code is not None:
                    log = self.read_text(paths.log)
                    completed = True
                    return log, code
                time.sleep(deadline.slice(poll))
            raise ChainTimeout(f"{name}: marker not seen within the budget")
        finally:
            # Best effort: a dead transport here must not replace the original
            # ChainTimeout with a StageError, nor overrun the budget. `attempts=1`
            # is part of that: the default four attempts with a 60 s operation
            # timeout and the retry backoff would add minutes per teardown call
            # after the chain's own timeout has already expired.
            #
            # A **running** task cannot be unregistered (`Unregister-ScheduledTask`
            # fails), and `-EA SilentlyContinue` hides that; the task would stay
            # registered and later write its marker into this run's name. It is
            # therefore stopped first, and only when it is registered, so a first
            # run's teardown does not fail on `Stop-ScheduledTask`.
            try:
                self.ps(
                    f"if (Get-ScheduledTask -TaskName {ps_quote(paths.task)} "
                    "-EA SilentlyContinue) "
                    f"{{ Stop-ScheduledTask -TaskName {ps_quote(paths.task)} "
                    "-EA SilentlyContinue }\n"
                    f"Unregister-ScheduledTask -TaskName {ps_quote(paths.task)} "
                    "-Confirm:$false -EA SilentlyContinue",
                    attempts=1,
                )
            except Exception:
                logger.warning(
                    "%s: could not stop/unregister the scheduled task %s",
                    name,
                    paths.task,
                    exc_info=True,
                )
            # A finished run owns no artifact any more: the payload, runner and
            # marker (plus the marker's `.tmp`) are left only after a failed run,
            # where they are the evidence for the failure. The log is always kept:
            # it is the run's output. Best effort like the teardown above, so a
            # dead transport cannot turn a finished run into an error.
            if completed:
                try:
                    self.ps(
                        remove_script(
                            paths.payload,
                            paths.runner,
                            paths.marker,
                            paths.marker + ".tmp",
                        ),
                        attempts=1,
                    )
                except Exception:
                    logger.warning(
                        "%s: could not remove the finished run's artifacts",
                        name,
                        exc_info=True,
                    )

    def extract_zip(self, zip_path: str, dest_dir: str, *, expected: int) -> int:
        """Extract `zip_path` into a **fresh** `dest_dir`; return files written.

        `Expand-Archive -Force` into a pre-existing directory is unreliable under
        Windows PowerShell 5.1: on the donor tree it silently stopped after 14 of
        113 files, leaving the package half-staged while reporting success, and its
        module-internal `Remove-Item` turns a missing file into a terminating error
        when `$ErrorActionPreference='Stop'`. So the destination is removed first,
        extraction uses the .NET `ZipFile.ExtractToDirectory` (deterministic, no
        module quirks), and the resulting file count is compared with `expected`
        (the zip's entry count) to turn a partial extraction into a loud failure.

        A leftover `PBIDesktop`/`msmdsrv` keeps a handle on the staged template, in
        which case `Remove-Item` silently leaves files behind and the extraction
        aborts with "file already exists"; the removal is therefore verified and
        retried after killing those processes.

        Raises:
            StageError: when the destination cannot be emptied or the extracted
                file count does not match `expected`.
        """
        self.ps(_STOP_ENGINE + "Start-Sleep -Seconds 2\n")
        for attempt in (1, 2):
            self.ps(remove_script(dest_dir))
            if not self._exists(dest_dir):
                break
            if attempt == 2:
                raise StageError(
                    f"cannot clear {dest_dir}: a process still holds it "
                    "(Desktop/engine not stopped)"
                )
            self.ps(_STOP_ENGINE + "Start-Sleep -Seconds 3\n")
        # `[IO.Directory]::CreateDirectory` rather than `New-Item -LiteralPath`:
        # idempotent, no wildcard semantics, and no dependency on a parameter
        # whose presence on Windows PowerShell 5.1 is uncertain (a missing
        # parameter binding fails the whole staging stage).
        self.ps(
            "$ErrorActionPreference='Stop'\n"
            f"[IO.Directory]::CreateDirectory({ps_quote(dest_dir)}) | Out-Null\n"
        )
        script = (
            "Add-Type -AssemblyName System.IO.Compression.FileSystem\n"
            f"[IO.Compression.ZipFile]::ExtractToDirectory("
            f"{ps_quote(zip_path)}, {ps_quote(dest_dir)})\n"
            f"(Get-ChildItem -LiteralPath {ps_quote(dest_dir)} -Recurse -File).Count\n"
        )
        out = self.ps(script)
        digits = [ln.strip() for ln in out.splitlines() if ln.strip().isdigit()]
        count = int(digits[-1]) if digits else 0
        if expected and count != expected:
            raise StageError(
                f"staging incomplete: extracted {count} of {expected} files"
            )
        return count


__all__ = [
    "TaskRunnerMixin",
    "_EXIT_FOOTER",
    "check_name",
    "parse_exitcode",
    "remove_script",
    "run_paths",
    "runner_script",
]
