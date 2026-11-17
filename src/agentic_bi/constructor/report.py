"""The constructor report: one machine-readable list of checks plus aggregates.

A build is only useful if its outcome can be read by a machine: the CLI prints
the summary, `--json` emits the whole report, and a caller can assert
`critical_ok` before shipping an artifact. Checks are grouped by what they
verify (`design`, `registry`, `pbix`, `merged`, `layout`, `build`).

Public API:
    SCHEMA_VERSION
    Check(group, name, ok, detail, critical, level).as_dict()
    TestReport(title, checks, meta).add() / .extend() / .write(path)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = "constructor.report/1"


@dataclass
class Check:
    """One check in the report."""

    group: str
    name: str
    ok: bool
    detail: str = ""
    critical: bool = True
    level: str = "check"

    def as_dict(self) -> dict[str, object]:
        """Return the check as a JSON-ready object."""
        return {
            "group": self.group,
            "name": self.name,
            "ok": self.ok,
            "critical": self.critical,
            "level": self.level,
            "detail": self.detail,
        }


@dataclass
class TestReport:
    """The aggregate report: checks plus counters derived from them."""

    title: str = "constructor"
    checks: list[Check] = field(default_factory=list)
    meta: dict[str, object] = field(default_factory=dict)

    def add(
        self,
        group: str,
        name: str,
        ok: bool,
        detail: str = "",
        *,
        critical: bool = True,
        level: str = "check",
    ) -> None:
        """Append one check."""
        self.checks.append(Check(group, name, ok, detail, critical, level))

    def extend(self, checks: list[Check]) -> None:
        """Append already-built checks."""
        self.checks.extend(checks)

    @property
    def passed(self) -> int:
        """Number of checks that reported success."""
        return sum(1 for check in self.checks if check.ok)

    @property
    def failed(self) -> list[Check]:
        """The checks that failed (critical or not)."""
        return [check for check in self.checks if not check.ok]

    @property
    def warnings(self) -> list[Check]:
        """The checks that carry the `warning` level."""
        return [check for check in self.checks if check.level == "warning"]

    @property
    def ok(self) -> bool:
        """True when every check passed."""
        return not self.failed

    @property
    def critical_ok(self) -> bool:
        """True when no critical check failed (the artifact may ship)."""
        return not [check for check in self.checks if not check.ok and check.critical]

    def as_dict(self) -> dict[str, object]:
        """Return the report as a JSON-ready object."""
        return {
            "schema": SCHEMA_VERSION,
            "title": self.title,
            "ok": self.ok,
            "critical_ok": self.critical_ok,
            "passed": self.passed,
            "failed": len(self.failed),
            "warnings": len(self.warnings),
            "meta": dict(self.meta),
            "checks": [check.as_dict() for check in self.checks],
        }

    def to_json(self) -> str:
        """Return the report as JSON text."""
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        """Return the report as a compact Markdown document."""
        lines = [f"# {self.title}", ""]
        for key, value in self.meta.items():
            lines.append(f"- **{key}**: {value}")
        lines += ["", "| group | checks | FAIL |", "|---|---:|---:|"]
        groups: dict[str, list[Check]] = {}
        for check in self.checks:
            groups.setdefault(check.group, []).append(check)
        for group, items in groups.items():
            failures = sum(1 for check in items if not check.ok)
            lines.append(f"| {group} | {len(items)} | {failures} |")
        for title, items in (("Errors", self.failed), ("Warnings", self.warnings)):
            if not items:
                continue
            lines += ["", f"## {title}", ""]
            lines.extend(
                f"- `{check.group}` / {check.name}: {check.detail}" for check in items
            )
        lines += [
            "",
            f"**Result:** {self.passed} passed, {len(self.failed)} failed, "
            f"{len(self.warnings)} warnings",
        ]
        return "\n".join(lines) + "\n"

    def write(self, path: str | Path) -> Path:
        """Write the report as `.json` or Markdown (by suffix) and return the path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".json":
            path.write_text(self.to_json(), encoding="utf-8")
        else:
            path.write_text(self.to_markdown(), encoding="utf-8")
        return path


__all__ = ["SCHEMA_VERSION", "Check", "TestReport"]
