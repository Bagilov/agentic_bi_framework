# Code bundle A: guest chain

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/guest_types.py ====================

"""Shared types for the Windows-guest chain: budget, errors and endpoint config.

Everything that is pure configuration or accounting lives here, so the transport,
the task runner and the orchestrator all agree on one wall-clock budget and one
error taxonomy without importing each other.

Public API:
    Deadline                 - one wall-clock budget shared by all stages
    ChainTimeout             - raised when a stage runs out of budget
    StageError               - raised when a stage fails for a non-timeout reason
    GuestConfig.from_env()   - guest endpoint/user/paths (None when unset)
    GuestConfig.available()  - True when the guest is configured
    ps_quote(text)           - a value as a single-quoted PowerShell literal
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

DEFAULT_PYTHON = r"C:\pbi\py\python.exe"
DEFAULT_ROOT = r"C:\pbi\abf"
DEFAULT_OUT = r"C:\pbi\out"


def ps_quote(value: object) -> str:
    """Render `value` as a safe single-quoted PowerShell literal.

    Anything interpolated into PowerShell source must go through this: a value
    containing `'` (or a newline/`;`/`|`) would otherwise close the literal and
    inject a statement. PowerShell escapes a single quote by doubling it.
    """
    return "'" + str(value).replace("'", "''") + "'"


class ChainTimeout(RuntimeError):
    """A chain stage exceeded the shared wall-clock budget."""


class StageError(RuntimeError):
    """A chain stage failed for a non-timeout reason (e.g. partial staging)."""


class Deadline:
    """One wall-clock budget for a whole chain; stages share the remainder."""

    def __init__(self, seconds: float) -> None:
        if seconds <= 0:
            raise ValueError("deadline must be positive")
        self.seconds = float(seconds)
        self._start = time.monotonic()

    @property
    def elapsed(self) -> float:
        """Seconds spent since the budget started."""
        return time.monotonic() - self._start

    @property
    def remaining(self) -> float:
        """Seconds left in the budget (never negative)."""
        return max(0.0, self.seconds - self.elapsed)

    @property
    def expired(self) -> bool:
        """True once the budget is used up."""
        return self.remaining <= 0

    def check(self, stage: str) -> None:
        """Raise `ChainTimeout` when the budget is used up."""
        if self.expired:
            raise ChainTimeout(f"{stage}: exceeded the {self.seconds:.0f}s budget")

    def slice(self, cap: float) -> float:
        """A pause that never overshoots the remaining budget."""
        return max(0.0, min(cap, self.remaining))


@dataclass(frozen=True)
class GuestConfig:
    """Where and how to reach the Windows guest that runs the engine/oracle."""

    winrm: str
    user: str
    password: str
    transport: str = "ntlm"
    python: str = DEFAULT_PYTHON
    root: str = DEFAULT_ROOT
    out: str = DEFAULT_OUT
    desktop: str | None = None
    ws_root: str | None = None

    @classmethod
    def from_env(cls) -> GuestConfig | None:
        """Build the config from the environment, or None when unset."""
        endpoint = os.environ.get("AGENTIC_BI_GUEST_WINRM")
        user = os.environ.get("AGENTIC_BI_GUEST_USER")
        password = os.environ.get("AGENTIC_BI_GUEST_PASSWORD")
        if not (endpoint and user and password):
            return None
        return cls(
            winrm=endpoint,
            user=user,
            password=password,
            transport=os.environ.get("AGENTIC_BI_GUEST_TRANSPORT", "ntlm"),
            python=os.environ.get("AGENTIC_BI_GUEST_PYTHON", cls.python),
            root=os.environ.get("AGENTIC_BI_GUEST_ROOT", cls.root),
            out=os.environ.get("AGENTIC_BI_GUEST_OUT", cls.out),
            desktop=os.environ.get("PBI_RS_DESKTOP"),
            ws_root=os.environ.get("PBI_RS_WS_ROOT"),
        )

    @staticmethod
    def available() -> bool:
        """True when the guest is configured via the environment."""
        return GuestConfig.from_env() is not None

==================== FILE: src/agentic_bi/guest_vm.py ====================

"""UTM VM control and host-reachability helpers for the guest chain.

The chain must be able to bring the VM up before WinRM can answer, and to tell
the guest which host address to fetch staged files from. Both are environment
concerns, so they live apart from the WinRM transport.

Public API:
    VMController(uuid)      - utmctl start/stop/status (macOS host)
    host_reachable_ip(cfg)  - the host IP the guest should fetch from
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from agentic_bi.guest_types import GuestConfig

logger = logging.getLogger(__name__)


def host_reachable_ip(config: GuestConfig) -> str:
    """The host IP the guest should fetch from.

    ``AGENTIC_BI_HOST_IP`` wins when set; otherwise the guest gateway (the
    endpoint's ``/24`` with ``.1``) is used, falling back to the endpoint host.
    """
    explicit = os.environ.get("AGENTIC_BI_HOST_IP")
    if explicit:
        return explicit
    host = config.winrm.split("//", 1)[-1].split(":", 1)[0]
    parts = host.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3] + ["1"])
    return host


class VMController:
    """Start/stop/query a UTM VM by UUID (`utmctl`); a no-op when unconfigured."""

    def __init__(self, uuid: str | None) -> None:
        self.uuid = uuid
        self._has_utmctl = shutil.which("utmctl") is not None

    @property
    def configured(self) -> bool:
        """True when both a VM id and the `utmctl` tool are present."""
        return bool(self.uuid) and self._has_utmctl

    def status(self) -> str:
        """The VM status string ('started', 'stopped', ...) or 'unknown'."""
        if not self.configured:
            return "unknown"
        proc = subprocess.run(
            ["utmctl", "status", self.uuid], capture_output=True, text=True
        )
        return (proc.stdout or "").strip() or "unknown"

    def start(self) -> None:
        """Start the VM in the background (utmctl blocks until it is booted)."""
        if not self.configured or self.status() == "started":
            return
        subprocess.Popen(
            ["utmctl", "start", self.uuid],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("requested VM start: %s", self.uuid)

    def stop(self) -> None:
        """Stop the VM (used by teardown when the chain started it)."""
        if not self.configured or self.status() != "started":
            return
        subprocess.run(
            ["utmctl", "stop", self.uuid], capture_output=True, text=True, timeout=180
        )
        logger.info("stopped VM: %s", self.uuid)

==================== FILE: src/agentic_bi/guest_winrm.py ====================

"""Bounded WinRM channel to the Windows guest: session, retries and readiness.

The guest is a UTM VM that may be booting, restarting, or whose engine holds
files open, so a one-shot call is never a readiness signal. This channel keeps a
single lazily-opened WinRM session, retries transient transport faults with a
fresh session, and exposes the small text helpers built on top of it.

Public API:
    new_session(config)   - one bounded WinRM session
    run_ps(session, s)    - decoded stdout of a PowerShell script
    WinRMChannel          - `session`, `ps`, `winrm_ready`, `ensure_vm`,
                            `write_text`, `read_text`
"""

from __future__ import annotations

import base64
import logging
import time

from agentic_bi.guest_types import ChainTimeout, Deadline, GuestConfig, ps_quote
from agentic_bi.guest_vm import VMController

logger = logging.getLogger(__name__)


def new_session(config: GuestConfig):
    """Open a bounded WinRM session (the timeouts stop a stalled read hanging)."""
    import winrm  # optional dependency, imported lazily

    return winrm.Session(
        config.winrm,
        auth=(config.user, config.password),
        transport=config.transport,
        operation_timeout_sec=60,
        read_timeout_sec=90,
    )


def run_ps(session, script: str) -> str:
    """Run a PowerShell script over WinRM and return its decoded stdout."""
    result = session.run_ps(script)
    return result.std_out.decode("utf-8", "replace")


def _transient_errors() -> tuple[type[BaseException], ...]:
    """Exception types worth retrying: a booting/restarted guest drops NTLM.

    Right after the VM comes up, WinRM can accept a shell and then fail the NTLM
    handshake ("did not respond with NTLM challenge token"), so a single attempt is
    not a reliable readiness signal. `winrm` is optional, so its error classes are
    looked up lazily and folded in when present.
    """
    errors: list[type[BaseException]] = [PermissionError, OSError, TimeoutError]
    try:
        import winrm.exceptions as wx

        errors += [
            wx.WinRMTransportError,
            wx.WSManFaultError,
            wx.InvalidCredentialsError,
        ]
    except Exception:  # noqa: BLE001 - winrm is an optional dependency
        pass
    return tuple(errors)


class WinRMChannel:
    """A bounded, retrying WinRM channel with a lazily-opened session."""

    def __init__(self, config: GuestConfig, *, vm_uuid: str | None = None) -> None:
        self.config = config
        self.vm = VMController(vm_uuid)
        self.started_vm = False
        self._session = None

    def session(self):
        """The lazily-opened WinRM session."""
        if self._session is None:
            self._session = new_session(self.config)
        return self._session

    def ps(self, script: str, *, attempts: int = 4) -> str:
        """Run a PowerShell script, retrying transient guest/transport failures.

        A freshly booted (or restarted) guest can accept a WinRM shell yet fail the
        NTLM handshake, so a one-shot call is not a reliable readiness signal. Each
        retry drops the cached session and backs off briefly.
        """
        errors = _transient_errors()
        last: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                return run_ps(self.session(), script)
            except errors as exc:  # noqa: BLE001 - retry transient transport faults
                last = exc
                logger.debug("ps attempt %d/%d failed: %s", attempt, attempts, exc)
                self._session = None
                if attempt < attempts:
                    time.sleep(min(2.0 * attempt, 8.0))
        raise last  # type: ignore[misc]  # the loop always sets it before falling out

    def winrm_ready(self, deadline: Deadline) -> bool:
        """True once two consecutive probes succeed within `deadline`.

        A single success is not enough right after a boot: WinRM can answer once and
        then fail the next NTLM handshake while the service stabilizes, so readiness
        requires the answer to hold across a short gap.
        """
        while not deadline.expired:
            try:
                self.ps("Write-Output ok", attempts=1)
                time.sleep(deadline.slice(3.0))
                self.ps("Write-Output ok", attempts=1)
                return True
            except Exception as exc:  # noqa: BLE001 - the guest may still be booting
                logger.debug("winrm not ready: %s", exc)
                time.sleep(deadline.slice(5.0))
        return False

    def ensure_vm(self, deadline: Deadline) -> str:
        """Ensure the VM is up and WinRM answers; return a human note.

        Raises:
            ChainTimeout: when WinRM never becomes ready within `deadline`.
        """
        note = "vm control not configured"
        if self.vm.configured:
            if self.vm.status() != "started":
                self.started_vm = True
                self.vm.start()
            note = f"vm {self.vm.status()}"
        if not self.winrm_ready(deadline):
            raise ChainTimeout("vm: WinRM did not become ready")
        return note

    def write_text(self, guest_path: str, text: str) -> None:
        """Write `text` to `guest_path` (base64, so quoting cannot break it).

        The content is base64-encoded, so it cannot terminate the script; the
        path is `ps_quote`d as usual.
        """
        b64 = base64.b64encode(text.encode("utf-16-le")).decode()
        self.ps(
            "$ErrorActionPreference='Stop'\n"
            f"$b=[Convert]::FromBase64String('{b64}')\n"
            "$t=[Text.Encoding]::Unicode.GetString($b)\n"
            f"$d=Split-Path -Parent {ps_quote(guest_path)}\n"
            "if ($d) { New-Item -ItemType Directory -Force -Path $d | Out-Null }\n"
            f"Set-Content -Path {ps_quote(guest_path)} -Value $t -Encoding UTF8\n"
        )

    def read_text(self, guest_path: str) -> str:
        """Read a small text file from the guest (empty string when missing)."""
        return self.ps(
            f"if (Test-Path {ps_quote(guest_path)}) "
            f"{{ Get-Content {ps_quote(guest_path)} -Raw }}"
        )

==================== FILE: src/agentic_bi/guest_staging.py ====================

"""Host-side file staging for the guest chain, over a quiet single-file server.

The guest cannot reach the host filesystem directly, so the host serves **one
file** on its guest-reachable address and the guest fetches it (`push_file`); the
reverse direction is done over WinRM as chunked base64 (`pull_file`), because a
single WinRM read of a multi-megabyte file is slow and brittle.

The staging server is deliberately tight, because whatever it serves is fetched
and then executed on the guest:

* it binds the address the guest actually uses (not every interface) where that
  address is local;
* it serves exactly one file, at a per-run unguessable path — no directory
  listing, no sibling reads, and any other path is a 404;
* the transfer is verified: the guest checks a SHA-256 the host computed, so a
  truncated or corrupted fetch fails loudly instead of being staged and run.

Every server this mixin opens is tracked and closed on `close()`, so a chain can
never leak a listening socket.

Public API:
    StagingMixin.push_file(local, dest, deadline)
    StagingMixin.pull_file(guest_path, local, deadline)
    StagingMixin.close()
"""

from __future__ import annotations

import base64
import functools
import hashlib
import http.server
import logging
import secrets
import socket
import threading
from pathlib import Path

from agentic_bi.guest_types import Deadline, StageError, ps_quote
from agentic_bi.guest_vm import host_reachable_ip

logger = logging.getLogger(__name__)


class _SingleFileHandler(http.server.BaseHTTPRequestHandler):
    """Serve exactly one file at one secret path; everything else is a 404.

    A stock directory handler would list (and serve) every sibling of the pushed
    file to anyone who can route to the host, so the path is checked against the
    per-run token and the directory itself is never exposed.
    """

    server_version = "abf-stage/1"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, file_path: Path, token: str, **kwargs) -> None:
        self._file_path = file_path
        self._token = token
        self._url_path = f"/{token}/{file_path.name}"
        super().__init__(*args, **kwargs)

    def log_message(self, *args, **kwargs) -> None:  # noqa: D102
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        """Return the staged file only for the exact tokenized path."""
        if self.path.split("?", 1)[0] != self._url_path:
            self.send_error(404, "Not Found")
            return
        payload = self._file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class StagingMixin:
    """Host->guest and guest->host file transfer, plus server teardown."""

    _servers: list[http.server.ThreadingHTTPServer]

    def _init_staging(self) -> None:
        """Create the server registry (called from the transport's `__init__`)."""
        self._servers = []

    def _bind_address(self) -> str:
        """The address to serve on: the guest-reachable IP when it is local.

        `AGENTIC_BI_HOST_IP` can name an address this host does not own (e.g. a
        forwarded/aliased address); binding it would fail, so a local bindability
        probe decides, and the fallback is logged rather than silent.
        """
        host = host_reachable_ip(self.config)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((host, 0))
            return host
        except OSError:
            logger.warning(
                "staging: %s is not a local address; falling back to all interfaces "
                "(the per-run token still scopes access to one file)",
                host,
            )
            return "0.0.0.0"
        finally:
            probe.close()

    def _serve(self, file_path: Path, token: str):
        handler = functools.partial(
            _SingleFileHandler, file_path=file_path, token=token
        )
        server = http.server.ThreadingHTTPServer((self._bind_address(), 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._servers.append(server)
        return server, server.server_address[1]

    def _stop_server(self, server) -> None:
        server.shutdown()
        server.server_close()
        if server in self._servers:
            self._servers.remove(server)

    def push_file(self, local: Path, dest: str, deadline: Deadline) -> None:
        """Serve `local` from the host and have the guest fetch it to `dest`.

        The guest verifies a SHA-256 computed here, so a corrupted transfer is a
        loud `StageError` rather than a silently truncated staged file.
        """
        local = Path(local)
        digest = hashlib.sha256(local.read_bytes()).hexdigest()
        token = secrets.token_urlsafe(24)
        server, port = self._serve(local, token)
        try:
            url = f"http://{host_reachable_ip(self.config)}:{port}/{token}/{local.name}"
            self.ps(
                "$ErrorActionPreference='Stop'\n"
                f"Invoke-WebRequest -UseBasicParsing -TimeoutSec 120 {ps_quote(url)} "
                f"-OutFile {ps_quote(dest)}\n"
            )
        finally:
            self._stop_server(server)
            deadline.check("push")
        actual = self.ps(
            f"(Get-FileHash {ps_quote(dest)} -Algorithm SHA256).Hash"
        ).strip()
        if actual.splitlines() and actual.splitlines()[-1].strip().lower() != digest:
            raise StageError(
                f"staged {dest} failed SHA-256 verification "
                f"(expected {digest[:12]}…, got {actual.splitlines()[-1][:12]}…)"
            )

    def pull_file(
        self,
        guest_path: str,
        local: Path,
        deadline: Deadline,
        *,
        chunk: int = 384 * 1024,
    ) -> int:
        """Fetch `guest_path` to `local` as base64, chunked and deadline-bounded."""
        raw_len = (
            self.ps(f"(Get-Item {ps_quote(guest_path)}).Length").strip().splitlines()
        )
        total = int(raw_len[-1]) if raw_len else 0
        out = bytearray()
        offset = 0
        while offset < total:
            deadline.check("pull")
            b64 = self.ps(
                f"$fs=[IO.File]::OpenRead({ps_quote(guest_path)});"
                f"$fs.Seek({int(offset)},'Begin');"
                f"$b=New-Object byte[] {chunk};"
                f"$n=$fs.Read($b,0,{chunk});$fs.Close();"
                f"[Convert]::ToBase64String($b,0,$n)"
            )
            blob = base64.b64decode(b64.strip().splitlines()[-1] or "")
            if not blob:
                break
            out += blob
            offset += len(blob)
        local = Path(local)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(bytes(out))
        return len(out)

    def close(self) -> None:
        """Release host resources; safe to call more than once."""
        for server in list(self._servers):
            try:
                self._stop_server(server)
            except Exception:  # noqa: BLE001 - teardown must not mask the verdict
                logger.debug("server already stopped", exc_info=True)

==================== FILE: src/agentic_bi/guest_task.py ====================

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

==================== FILE: src/agentic_bi/guest_transport.py ====================

"""Bounded transport to the Windows Power BI guest: the composed public surface.

This module is the single import point for the guest chain. The pieces live in
focused modules and are composed here:

* `guest_types`   - `Deadline`, `ChainTimeout`, `StageError`, `GuestConfig`
* `guest_vm`      - `VMController`, `host_reachable_ip`
* `guest_winrm`   - `new_session`, `run_ps`, `WinRMChannel`
* `guest_staging` - `StagingMixin` (host<->guest file transfer, server teardown)
* `guest_task`    - `TaskRunnerMixin` (interactive scheduled tasks, zip staging)

`WinRMTransport` is the one class callers use: a time-boxed WinRM session, HTTP
staging, execution as an interactive scheduled task (Desktop brings up its engine
only in session 1, while WinRM runs in session 0), and UTM VM start/stop.

Every wait takes a `Deadline`, so a stage either finishes or raises
`ChainTimeout`; nothing here can hang forever. Environment-specific values
(endpoint, user, paths, VM id) come from `GuestConfig`/`ChainConfig`, never
hardcoded.

Public API:
    Deadline, ChainTimeout, StageError, GuestConfig
    ps_quote
    VMController, host_reachable_ip
    new_session, run_ps, parse_exitcode
    WinRMTransport
"""

from __future__ import annotations

from agentic_bi.guest_staging import StagingMixin
from agentic_bi.guest_task import TaskRunnerMixin, parse_exitcode
from agentic_bi.guest_types import (
    ChainTimeout,
    Deadline,
    GuestConfig,
    StageError,
    ps_quote,
)
from agentic_bi.guest_vm import VMController, host_reachable_ip
from agentic_bi.guest_winrm import WinRMChannel, new_session, run_ps

__all__ = [
    "ChainTimeout",
    "Deadline",
    "GuestConfig",
    "StageError",
    "VMController",
    "WinRMTransport",
    "host_reachable_ip",
    "new_session",
    "parse_exitcode",
    "ps_quote",
    "run_ps",
]


class WinRMTransport(StagingMixin, TaskRunnerMixin, WinRMChannel):
    """The composed bounded transport: WinRM + staging + task running + VM control."""

    def __init__(self, config: GuestConfig, *, vm_uuid: str | None = None) -> None:
        super().__init__(config, vm_uuid=vm_uuid)
        self._init_staging()

==================== FILE: src/agentic_bi/guest_chain_build.py ====================

"""Guest build stage: stage the framework, run the builder, fetch the result.

The chain's middle stage, separated from the orchestrator so the verdict logic
stays readable. It owns the framework zip layout, the builder command line, and
the guest-side build invocation, but not the VM lifecycle or the oracle.

Public API:
    stage_framework(repo, dest_zip)      - zip the runtime pieces at archive root
    build_script(cfg, guest_pbix, log)   - the interactive-task body
    run_build(transport, cfg, deadline, result) -> bool
    tail(text, limit)                    - last characters, single-lined
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from agentic_bi.guest_transport import Deadline, ps_quote

if TYPE_CHECKING:  # avoid a runtime cycle with the orchestrator
    from agentic_bi.guest_chain import ChainConfig, ChainResult
    from agentic_bi.guest_transport import GuestConfig, WinRMTransport

_TASK = "agentic_bi_board"
_RUNTIME = ("src", "examples", "templates", "pyproject.toml", "README.md")


def _register_on_path(guest: GuestConfig) -> str:
    """The PowerShell that puts `<root>\\src` on the embeddable interpreter's path.

    The `._pth` file sits next to the configured interpreter and the appended
    entry is the configured root, so overriding `AGENTIC_BI_GUEST_ROOT` or
    `AGENTIC_BI_GUEST_PYTHON` stays consistent (a hardcoded path here would keep
    pointing at the default root while the framework is staged elsewhere).

    The guest paths are Windows paths and the host may be macOS, so the
    interpreter directory is split on `\\` rather than with `pathlib` (whose
    separators are host-specific).
    """
    py_dir = guest.python.rsplit("\\", 1)[0] if "\\" in guest.python else guest.python
    pth = f"{py_dir}\\python312._pth"
    src = f"{guest.root}\\src"
    return (
        f"$pth={ps_quote(pth)}\n"
        f"if (-not (Select-String -Path $pth -Pattern {ps_quote(src)} -Quiet)) "
        f"{{ Add-Content $pth {ps_quote(src)} }}\n"
    )


def tail(text: str, limit: int = 600) -> str:
    """The last `limit` characters of `text`, single-lined for the log."""
    flat = " ".join(text.split())
    return flat[-limit:]


def stage_framework(repo: Path, dest_zip: Path) -> None:
    """Zip the runtime pieces of `repo` at the archive root (no nesting level)."""
    repo = Path(repo)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in _RUNTIME:
            src = repo / name
            if src.is_file():
                zf.write(src, name)
                continue
            for path in sorted(src.rglob("*")):
                if "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                if path.is_file():
                    zf.write(path, str(path.relative_to(repo)))


def build_script(cfg: ChainConfig, guest_pbix: str, log_path: str) -> str:
    """The interactive-task body: run the builder and log its output.

    Every interpolated value is rendered with `ps_quote`, so a builder name,
    table, title or path containing a quote cannot break out of its literal and
    inject a statement into the highest-privilege interactive task.

    Completion is signalled by the marker file the runner writes afterwards, not
    by a string in this log (see `WinRMTransport.run_task` for why).
    """
    guest = cfg.guest
    root = guest.root
    bin_dir = r"C:\Program Files\Microsoft Power BI Desktop\bin"
    template = f"{root}\\templates\\template.pbix"
    src = f"{root}\\src"
    builder_path = f"{root}\\examples\\{cfg.builder}"
    data_path = f"{root}\\examples\\{Path(cfg.data).name}"
    title_flag = f" --title {ps_quote(cfg.title)}" if cfg.title else ""
    return (
        "$ErrorActionPreference='Continue'\n"
        f"$env:PBI_RS_BIN={ps_quote(bin_dir)}\n"
        f"$env:PBI_RS_TEMPLATE={ps_quote(template)}\n"
        f"$env:PYTHONPATH={ps_quote(src)}\n"
        f"& {ps_quote(guest.python)} {ps_quote(builder_path)} "
        f"--data {ps_quote(data_path)} "
        f"--table {ps_quote(cfg.table)} "
        f"--template {ps_quote(template)} "
        f"--out {ps_quote(guest_pbix)}{title_flag} *> {ps_quote(log_path)}\n"
    )


def run_build(
    transport: WinRMTransport,
    cfg: ChainConfig,
    deadline: Deadline,
    result: ChainResult,
) -> bool:
    """Stage the framework, run the build task; True only on exit 0 + a new file.

    The build's own exit code is authoritative: a non-zero code is a failure even
    when a `.pbix` of the right name exists, because the output is deleted before
    the task starts so an earlier run's artifact cannot be mistaken for this one's.
    """
    tmp = Path(tempfile.mkdtemp(prefix="abf-chain-"))
    try:
        guest = cfg.guest
        transport.ps(
            f"New-Item -ItemType Directory -Force -Path {ps_quote(guest.out)} "
            "| Out-Null"
        )
        zip_path = tmp / "abf.zip"
        stage_framework(cfg.repo, zip_path)
        entries = len(zipfile.ZipFile(zip_path).namelist())
        result.record(
            "stage", f"framework {zip_path.stat().st_size} B, {entries} files"
        )

        guest_zip = f"{guest.out}\\abf.zip"
        transport.push_file(zip_path, guest_zip, deadline)
        files = transport.extract_zip(guest_zip, guest.root, expected=entries)
        transport.ps(_register_on_path(guest))
        result.record("stage", f"framework extracted on guest ({files} files)")

        guest_pbix = f"{guest.out}\\{cfg.out.name}"
        log_path = f"{guest.out}\\{_TASK}.log"
        marker_path = f"{guest.out}\\{_TASK}.done"
        transport.push_file(
            Path(cfg.data).resolve(),
            f"{guest.root}\\examples\\{Path(cfg.data).name}",
            deadline,
        )
        log, code = transport.run_task(
            name=_TASK,
            script=build_script(cfg, guest_pbix, log_path),
            log_path=log_path,
            marker_path=marker_path,
            files_before=f"Remove-Item {ps_quote(guest_pbix)} -Force -EA SilentlyContinue",
            deadline=deadline,
        )
        result.record("build", f"exit={code} {tail(log)}")
        if code != 0:
            return False
        size = transport.ps(
            f"if (Test-Path {ps_quote(guest_pbix)}) "
            f"{{ (Get-Item {ps_quote(guest_pbix)}).Length }} else {{ 0 }}"
        )
        if not int((size.strip().splitlines() or ["0"])[-1]):
            result.record("build", "exit 0 but no .pbix produced")
            return False
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


__all__ = ["build_script", "run_build", "stage_framework", "tail"]

==================== FILE: src/agentic_bi/guest_chain.py ====================

"""Terminating chain: build a test dashboard in the Windows guest, end to end.

A single bounded call turns "make a test dashboard" into finished artifacts: it
brings the VM up, stages the framework, runs the engine build **in the guest's
interactive session** (Desktop brings up its AS engine only in session 1), pulls
the `.pbix` back to the host, optionally runs the strict Desktop oracle, and
always tears everything down — the interactive task is unregistered and the VM is
stopped only if this chain is what started it.

Nothing can hang: every stage shares one `Deadline`, and every stage's teardown
runs in a `finally`, so the process returns one verdict and never leaves a
registered task or a leaked HTTP server behind. Environment-specific values
(guest endpoint, VM id, paths) are configuration, never hardcoded.

The staging/build mechanics live in `guest_chain_build`; this module owns the
configuration, the verdict and the CLI.

Public API:
    ChainConfig.from_env()            - guest + build configuration
    ChainResult                       - verdict, artifacts and the stage log
    build_dashboard(config) -> ChainResult
    main(argv) -> int                 - CLI (`agentic-bi-guest-dashboard`)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from agentic_bi.guest_chain_build import run_build
from agentic_bi.guest_transport import (
    ChainTimeout,
    Deadline,
    GuestConfig,
    StageError,
    WinRMTransport,
)

logger = logging.getLogger(__name__)

# Chain outcome tokens (the process always ends on exactly one of these).
BUILT = "BUILT"
NOT_BUILT = "NOT_BUILT"
STAGE_FAILED = "STAGE_FAILED"
ORACLE_FAILED = "ORACLE_FAILED"
TIMEOUT = "TIMEOUT"


@dataclass
class ChainConfig:
    """Everything the chain needs: the guest plus the build request."""

    guest: GuestConfig
    data: Path
    table: str
    out: Path
    repo: Path = field(default_factory=lambda: Path.cwd())
    vm_uuid: str | None = None
    builder: str = "engine_table_board.py"
    timeout: int = 1800
    oracle: bool = False
    oracle_hold: int = 90
    stop_vm_on_exit: bool = True
    title: str | None = None

    @classmethod
    def from_env(cls) -> ChainConfig | None:
        """Build from the environment (guest vars + optional VM id/data)."""
        guest = GuestConfig.from_env()
        if guest is None:
            return None
        repo = Path(os.environ.get("AGENTIC_BI_REPO", Path.cwd())).resolve()
        return cls(
            guest=guest,
            data=Path(
                os.environ.get(
                    "AGENTIC_BI_DATA", repo / "examples" / "engine_sales.csv"
                )
            ),
            table=os.environ.get("AGENTIC_BI_TABLE", "Sales"),
            out=Path(
                os.environ.get(
                    "AGENTIC_BI_OUT", repo / "output_files" / "guest_board.pbix"
                )
            ),
            repo=repo,
            vm_uuid=os.environ.get("AGENTIC_BI_VM_UUID"),
            builder=os.environ.get("AGENTIC_BI_BUILDER", "engine_table_board.py"),
            timeout=int(os.environ.get("AGENTIC_BI_CHAIN_TIMEOUT", "1800")),
            oracle=os.environ.get("AGENTIC_BI_ORACLE", "") not in ("", "0", "false"),
            title=os.environ.get("AGENTIC_BI_TITLE"),
        )


@dataclass
class ChainResult:
    """The chain's single verdict, with artifacts and a per-stage log."""

    verdict: str
    pbix: Path | None = None
    bytes_written: int = 0
    oracle: str | None = None
    log: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True only when the board was built and (when enabled) opened in Desktop."""
        if self.verdict == BUILT:
            return self.oracle in (None, "MODEL_LOADED")
        return False

    def record(self, stage: str, detail: str) -> None:
        """Append one stage line to the log."""
        self.log.append(f"{stage}: {detail}")

    def as_dict(self) -> dict:
        """A JSON-friendly summary."""
        return {
            "verdict": self.verdict,
            "ok": self.ok,
            "pbix": str(self.pbix) if self.pbix else None,
            "bytes": self.bytes_written,
            "oracle": self.oracle,
            "log": self.log,
        }


def _run_oracle(
    config: ChainConfig, local_pbix: Path, deadline: Deadline, result: ChainResult
) -> None:
    """Run the strict Desktop oracle and fold its verdict into `result`."""
    from agentic_bi.desktop_oracle_guest import run_oracle

    try:
        oracle = run_oracle(
            local_pbix,
            config=config.guest,
            dest_name=local_pbix.name,
            hold=config.oracle_hold,
            open_timeout=int(deadline.remaining),
            timeout=int(deadline.remaining),
        )
        result.oracle = oracle.verdict
        result.record("oracle", oracle.verdict)
        if not oracle.loaded:
            result.verdict = ORACLE_FAILED
    except Exception as exc:  # noqa: BLE001 - oracle failure is a verdict
        result.oracle = f"ERROR:{type(exc).__name__}"
        result.record("oracle", f"{type(exc).__name__}: {exc}")
        result.verdict = ORACLE_FAILED


def build_dashboard(config: ChainConfig | None = None) -> ChainResult:
    """Run the whole chain once and return a single verdict; always terminates.

    Args:
        config: chain configuration; defaults to `ChainConfig.from_env()`.

    Returns:
        ChainResult whose `verdict` is one of BUILT / NOT_BUILT /
        ORACLE_FAILED / TIMEOUT. `log` carries per-stage detail.
    """
    config = config or ChainConfig.from_env()
    if config is None:
        raise RuntimeError(
            "guest not configured; set AGENTIC_BI_GUEST_WINRM, "
            "AGENTIC_BI_GUEST_USER and AGENTIC_BI_GUEST_PASSWORD"
        )
    deadline = Deadline(config.timeout)
    result = ChainResult(verdict=TIMEOUT)
    transport = WinRMTransport(config.guest, vm_uuid=config.vm_uuid)
    try:
        note = transport.ensure_vm(deadline)
        result.record("vm", note)
        try:
            built = run_build(transport, config, deadline, result)
        except ChainTimeout as exc:
            result.record("timeout", str(exc))
            result.verdict = TIMEOUT
            return result
        except StageError as exc:
            result.record("stage", f"FAILED: {exc}")
            result.verdict = STAGE_FAILED
            return result
        if not built:
            result.verdict = NOT_BUILT
            return result

        local_pbix = Path(config.out).resolve()
        size = transport.pull_file(
            f"{config.guest.out}\\{local_pbix.name}", local_pbix, deadline
        )
        result.pbix = local_pbix
        result.bytes_written = size
        result.record("pull", f"{size} B -> {local_pbix}")
        result.verdict = BUILT

        if config.oracle:
            _run_oracle(config, local_pbix, deadline, result)
        return result
    except ChainTimeout as exc:
        result.record("timeout", str(exc))
        result.verdict = TIMEOUT
        return result
    except Exception as exc:  # noqa: BLE001 - the chain always ends on a verdict
        result.record("error", f"{type(exc).__name__}: {exc}")
        result.verdict = STAGE_FAILED
        return result
    finally:
        transport.close()
        if config.stop_vm_on_exit and transport.started_vm:
            transport.vm.stop()
            result.record("vm", "stopped (started by this chain)")


if __name__ == "__main__":
    from agentic_bi.guest_chain_cli import main as _main

    raise SystemExit(_main())

==================== FILE: src/agentic_bi/guest_chain_cli.py ====================

"""Command-line front end for the one-shot guest dashboard chain.

Argument parsing, config overrides and the JSON verdict printer live here, so the
orchestrator module stays focused on the chain and its verdict.

Public API:
    main(argv) -> int   - run the chain once, print the JSON verdict
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from agentic_bi.guest_chain import ChainConfig, build_dashboard

# (attribute, caster) applied from parsed args over the environment-derived config.
_OVERRIDES: tuple[tuple[str, type], ...] = (
    ("data", Path),
    ("table", str),
    ("out", Path),
    ("repo", Path),
    ("vm_uuid", str),
    ("builder", str),
)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="agentic-bi-guest-dashboard",
        description=(
            "Build a test dashboard in the Windows guest (one terminating chain)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--data", help="CSV/JSON input (default: examples/engine_sales.csv)"
    )
    ap.add_argument("--table", help="table name in the model")
    ap.add_argument("--out", help="output .pbix path on the host")
    ap.add_argument("--repo", help="framework root to stage (default: cwd)")
    ap.add_argument("--vm-uuid", help="UTM VM id to start/stop (optional)")
    ap.add_argument("--builder", help="builder script in examples/ to run")
    ap.add_argument("--timeout", type=int, help="overall wall-clock budget (s)")
    ap.add_argument("--title", help="visible table title")
    ap.add_argument("--oracle", action="store_true", help="also run the Desktop oracle")
    ap.add_argument("--keep-vm", action="store_true", help="do not stop the VM on exit")
    ap.add_argument("--json", help="write the JSON verdict to this path")
    return ap


def _apply_overrides(config: ChainConfig, args: argparse.Namespace) -> None:
    """Apply CLI arguments over the environment-derived config."""
    for name, caster in _OVERRIDES:
        value = getattr(args, name)
        if value:
            setattr(config, name, caster(value))
    if args.timeout:
        config.timeout = args.timeout
    if args.title:
        config.title = args.title
    if args.oracle:
        config.oracle = True
    if args.keep_vm:
        config.stop_vm_on_exit = False


def _emit(payload: dict, json_path: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if json_path:
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(json_path).write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the chain once, print the JSON verdict, exit 0 only when ok."""
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = ChainConfig.from_env()
    if config is None:
        _emit(
            {
                "verdict": "NOT_CONFIGURED",
                "ok": False,
                "error": "set AGENTIC_BI_GUEST_WINRM, AGENTIC_BI_GUEST_USER, "
                "AGENTIC_BI_GUEST_PASSWORD",
            },
            None,
        )
        return 2
    _apply_overrides(config, args)
    try:
        result = build_dashboard(config)
    except RuntimeError as exc:
        _emit({"verdict": "NOT_CONFIGURED", "ok": False, "error": str(exc)}, None)
        return 2
    _emit(result.as_dict(), args.json)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

