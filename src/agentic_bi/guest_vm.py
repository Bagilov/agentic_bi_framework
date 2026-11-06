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

    def _target(self) -> str | None:
        """The VM id to drive, or None when this controller is unconfigured.

        The single place that decides whether a call may shell out, so `status`/
        `start`/`stop` narrow one value instead of re-deriving `configured` and
        still handing `None` to `utmctl`.
        """
        if not self._has_utmctl:
            return None
        return self.uuid or None

    @property
    def configured(self) -> bool:
        """True when both a VM id and the `utmctl` tool are present."""
        return self._target() is not None

    def status(self) -> str:
        """The VM status string ('started', 'stopped', ...) or 'unknown'.

        The call is time-boxed: `utmctl status` on a wedged VM otherwise blocks
        the whole chain, and this runs inside `ensure_vm`, before any stage
        deadline can help.
        """
        vm = self._target()
        if vm is None:
            return "unknown"
        proc = subprocess.run(
            ["utmctl", "status", vm], capture_output=True, text=True, timeout=30
        )
        return (proc.stdout or "").strip() or "unknown"

    def start(self) -> None:
        """Start the VM in the background (utmctl blocks until it is booted)."""
        vm = self._target()
        if vm is None or self.status() == "started":
            return
        subprocess.Popen(
            ["utmctl", "start", vm],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("requested VM start: %s", vm)

    def stop(self) -> bool:
        """Stop the VM (used by teardown when the chain started it).

        Returns:
            True only when `utmctl` reported success. A non-zero exit is logged
            as a warning and never as a completed teardown: the previous version
            ignored the exit status, so a refused stop (a wedged VM, a lost
            session) still wrote a success line into the chain result.

        Raises:
            subprocess.TimeoutExpired: when `utmctl` does not answer in time; the
                chain catches it so the verdict survives.
        """
        vm = self._target()
        if vm is None or self.status() != "started":
            return False
        proc = subprocess.run(
            ["utmctl", "stop", vm], capture_output=True, text=True, timeout=180
        )
        if proc.returncode:
            detail = (proc.stderr or proc.stdout or "").strip()
            logger.warning(
                "utmctl stop %s failed (exit %s): %s", vm, proc.returncode, detail
            )
            return False
        logger.info("stopped VM: %s", vm)
        return True
