"""Guest-side task execution: interactive scheduled tasks and zip extraction.

Two operations that both need WinRM but nothing from each other:

* `run_task` runs a script as an **interactive** scheduled task. That is required
  because WinRM lands in session 0, while Power BI Desktop only brings its engine
  up in session 1.
* `extract_zip` stages an archive into a fresh directory, working around Windows
  PowerShell 5.1 quirks (`Expand-Archive` silently stops part-way) and files held
  open by a running Desktop/engine.

Completion is signalled by a **marker file**, never by a string in the log: a
PowerShell `*>` redirect writes UTF-16 while `Out-File -Encoding utf8` appends
UTF-8, so a text sentinel comes back mangled.

Public API:
    parse_exitcode(marker) -> int | None
    TaskRunnerMixin.run_task(...) -> tuple[str, int]
    TaskRunnerMixin.extract_zip(...) -> int
"""

from __future__ import annotations

import time

from agentic_bi.guest_types import ChainTimeout, Deadline, StageError, ps_quote

_MARKER_TOKEN = "EXITCODE="


def _task_argument(runner: str) -> str:
    """The `powershell.exe` argument line that runs the task's `.ps1` runner.

    `-File` needs the path wrapped in double quotes (paths may contain spaces),
    and the whole line is later embedded in a single-quoted PowerShell literal,
    so an embedded `"` is backslash-escaped for the Windows command line.
    """
    safe = runner.replace('"', '\\"')
    return f'-NoProfile -ExecutionPolicy Bypass -File "{safe}"'


def parse_exitcode(marker: str) -> int | None:
    """Parse the `EXITCODE=<n>` a task runner writes into its marker.

    Returns None when the marker is empty, lacks the token, or was read mid-write
    (token present but the digits not yet flushed), so a partial read keeps polling
    instead of raising.
    """
    if _MARKER_TOKEN not in marker:
        return None
    tail = marker.split(_MARKER_TOKEN, 1)[1].strip()
    head = tail.split()[0] if tail.split() else ""
    try:
        return int(head)
    except ValueError:
        return None


class TaskRunnerMixin:
    """Run guest scripts as scheduled tasks and stage archives onto the guest."""

    def run_task(
        self,
        *,
        name: str,
        script: str,
        log_path: str,
        marker_path: str,
        files_before: str = "",
        deadline: Deadline,
        poll: float = 10.0,
        limit_min: int = 20,
    ) -> tuple[str, int]:
        """Run `script` as an interactive scheduled task; wait for its marker.

        The task is registered, started and polled, and is **always** unregistered
        afterwards (success, failure or timeout). Returns ``(log, exit_code)``.

        `files_before` is a cleanup expression run before the task starts (e.g.
        deleting a stale output), so a later "file exists" check cannot be
        satisfied by a previous run's artifact.

        The marker and log are also deleted here, **before** the task starts, and
        the deletion is verified: the runner repeats the cleanup, but a scheduled
        task takes a moment to launch, so without this a previous run's marker
        (`EXITCODE=1`, say) would be read back instantly as this run's result.

        A poll can catch the marker mid-write (`EXITCODE=` with the digits not yet
        flushed); a match is only accepted when the code is actually present.

        Raises:
            ChainTimeout: when the marker does not appear before `deadline`.
        """
        runner = f"{self.config.out}\\{name}.ps1"
        cleanup = f"{files_before}\r\n" if files_before else ""
        self.write_text(
            runner,
            f"Remove-Item {ps_quote(log_path)} -Force -EA SilentlyContinue\r\n"
            f"Remove-Item {ps_quote(marker_path)} -Force -EA SilentlyContinue\r\n"
            f"{cleanup}"
            f"{script}\r\n"
            f"Set-Content -Path {ps_quote(marker_path)} -Value "
            f'"{_MARKER_TOKEN}$LASTEXITCODE" -Encoding ascii\r\n',
        )
        for _ in range(3):
            self.ps(
                f"Remove-Item {ps_quote(marker_path)} -Force -EA SilentlyContinue\n"
                f"Remove-Item {ps_quote(log_path)} -Force -EA SilentlyContinue\n"
            )
            gone = self.ps(
                f"if (Test-Path {ps_quote(marker_path)}) "
                "{ 'present' } else { 'absent' }"
            )
            if "absent" in gone:
                break
            time.sleep(deadline.slice(2.0))
        setup = (
            f"Unregister-ScheduledTask -TaskName {ps_quote(name)} -Confirm:$false "
            "-EA SilentlyContinue | Out-Null\n"
            "$act=New-ScheduledTaskAction -Execute 'powershell.exe' "
            f"-Argument {ps_quote(_task_argument(runner))}\n"
            "$pr=New-ScheduledTaskPrincipal -UserId $env:USERNAME "
            "-LogonType Interactive -RunLevel Highest\n"
            "$set=New-ScheduledTaskSettingsSet -ExecutionTimeLimit "
            f"(New-TimeSpan -Minutes {int(limit_min)})\n"
            f"Register-ScheduledTask -TaskName {ps_quote(name)} -Action $act "
            "-Principal $pr -Settings $set -Force | Out-Null\n"
            f"Start-ScheduledTask -TaskName {ps_quote(name)}\n"
        )
        try:
            self.ps(setup)
            marker = ""
            while not deadline.expired:
                marker = self.ps(
                    f"if (Test-Path {ps_quote(marker_path)}) "
                    f"{{ Get-Content {ps_quote(marker_path)} -Raw }}"
                ).strip()
                code = parse_exitcode(marker)
                if code is not None:
                    return self.read_text(log_path), code
                time.sleep(deadline.slice(poll))
            raise ChainTimeout(f"{name}: marker not seen within the budget")
        finally:
            self.ps(
                f"Unregister-ScheduledTask -TaskName {ps_quote(name)} "
                "-Confirm:$false -EA SilentlyContinue"
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
        self.ps(
            "foreach ($p in 'PBIDesktop','msmdsrv') "
            "{ Stop-Process -Name $p -Force -EA SilentlyContinue }\n"
            "Start-Sleep -Seconds 2\n"
        )
        for attempt in (1, 2):
            self.ps(
                f"Remove-Item {ps_quote(dest_dir)} -Recurse -Force "
                "-EA SilentlyContinue\n"
            )
            still = self.ps(
                f"if (Test-Path {ps_quote(dest_dir)}) {{ 'yes' }} else {{ 'no' }}"
            )
            if "yes" not in still:
                break
            if attempt == 2:
                raise StageError(
                    f"cannot clear {dest_dir}: a process still holds it "
                    "(Desktop/engine not stopped)"
                )
            self.ps(
                "foreach ($p in 'PBIDesktop','msmdsrv') "
                "{ Stop-Process -Name $p -Force -EA SilentlyContinue }\n"
                "Start-Sleep -Seconds 3\n"
            )
        self.ps(
            f"New-Item -ItemType Directory -Force -Path {ps_quote(dest_dir)} "
            "| Out-Null\n"
        )
        script = (
            "Add-Type -AssemblyName System.IO.Compression.FileSystem\n"
            f"[IO.Compression.ZipFile]::ExtractToDirectory("
            f"{ps_quote(zip_path)}, {ps_quote(dest_dir)})\n"
            f"(Get-ChildItem {ps_quote(dest_dir)} -Recurse -File).Count\n"
        )
        out = self.ps(script)
        digits = [ln.strip() for ln in out.splitlines() if ln.strip().isdigit()]
        count = int(digits[-1]) if digits else 0
        if expected and count != expected:
            raise StageError(
                f"staging incomplete: extracted {count} of {expected} files"
            )
        return count
