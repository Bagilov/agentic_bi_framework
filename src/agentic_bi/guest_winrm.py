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

from agentic_bi.guest_types import (
    ChainTimeout,
    Deadline,
    GuestConfig,
    StageError,
    ps_quote,
)
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


def _one_line(text: str, limit: int = 300) -> str:
    """Collapse whitespace and keep at most `limit` of the tail for an error."""
    flat = " ".join(text.split())
    return flat[-limit:] if len(flat) > limit else flat


def run_ps(session, script: str) -> str:
    """Run a PowerShell script over WinRM and return its decoded stdout.

    A non-zero exit status means the script failed (an unhandled terminating
    error, or an explicit `exit 1`). `winrm` reports that in `status_code`, not in
    the return value, so it is checked here: returning the stdout anyway would let
    a failed `Get-FileHash`, `Expand-Archive` or `Set-Content` look like a success
    and mask the fault until much later. Benign, locally-suppressed errors
    (`-EA SilentlyContinue`) keep the status at 0 and are unaffected.

    Raises:
        StageError: when the script exits non-zero; `std_err` is included.
    """
    result = session.run_ps(script)
    out = result.std_out.decode("utf-8", "replace")
    if result.status_code:
        err = result.std_err.decode("utf-8", "replace").strip()
        raise StageError(
            f"PowerShell failed (exit {result.status_code}): "
            f"{_one_line(err) or _one_line(out) or '<no output>'}"
        )
    return out


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
            except errors as exc:
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
