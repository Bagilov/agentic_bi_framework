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
