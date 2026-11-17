"""Validation issues and the exception raised for an unusable design.

A design arrives as JSON/YAML, so a mistake must be reported as a list of
located problems (page, block, field) instead of the first `KeyError` that
happens to fire during compilation. `Issue` is that located problem;
`DesignError` carries all of them at once so one run reports everything.

Public API:
    Issue(severity, code, message, path).as_dict()
    DesignError(issues)
    has_errors(issues) -> bool
    raise_for_errors(issues) -> None
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Issue:
    """One validation finding, located by `path` (`pages[Sales].visuals[2]`)."""

    severity: Severity
    code: str
    message: str
    path: str = ""

    def as_dict(self) -> dict[str, str]:
        """Return the issue as a JSON-ready object."""
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
        }


class DesignError(ValueError):
    """The design is not usable; `issues` holds every error that was found."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = list(issues)
        text = "; ".join(f"{i.path}: {i.message}" for i in self.issues)
        super().__init__(text or "design is not valid")


def has_errors(issues: list[Issue]) -> bool:
    """True when at least one issue is an error (warnings do not block)."""
    return any(i.severity == "error" for i in issues)


def raise_for_errors(issues: list[Issue]) -> None:
    """Raise `DesignError` with the error issues; return when there are none."""
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise DesignError(errors)


__all__ = ["DesignError", "Issue", "Severity", "has_errors", "raise_for_errors"]
