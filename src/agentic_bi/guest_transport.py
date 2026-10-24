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
