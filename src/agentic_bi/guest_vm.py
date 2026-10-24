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
