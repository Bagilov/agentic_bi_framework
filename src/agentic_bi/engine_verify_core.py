"""Result types and shared helpers for `.pbix` verification."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# aggregations like "Sum(Table.col)"/"Count(Table.col)" in queryRef
_AGG_QREF = re.compile(r"^[A-Za-z]+\((.+)\)$")


@dataclass
class CheckResult:
    """A single check.

    critical=True - a structural guarantee (container/layout/binding/filters);
    a failed critical check fails the strict mode.
    critical=False - best-effort (model read-back via pbixray); a failure is
    reported but by default does not fail the build (third-party decoder).
    """

    name: str
    ok: bool
    detail: str = ""
    critical: bool = True


@dataclass
class VerifyReport:
    """A set of checks with an outcome."""

    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.ok)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]

    @property
    def critical_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok and c.critical]

    @property
    def soft_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok and not c.critical]

    def ok(self) -> bool:
        return self.failed == 0

    def critical_ok(self) -> bool:
        return not self.critical_failures

    def extend(self, checks: list[CheckResult]) -> VerifyReport:
        self.checks.extend(checks)
        return self

    def raise_if_failed(self, strict_soft: bool = False) -> None:
        """Raise RuntimeError on failed checks.

        Critical checks are considered strict; with `strict_soft=True` any checks
        are (including the model read-back).
        """
        bad = self.failures if strict_soft else self.critical_failures
        if bad:
            lines = [f"  - {c.name} :: {c.detail}" for c in bad]
            raise RuntimeError(
                f"verification failed: {len(bad)} check(s)\n" + "\n".join(lines)
            )

    def format(self, verbose: bool = True) -> str:
        lines = []
        if verbose:
            for c in self.checks:
                mark = "PASS" if c.ok else ("FAIL" if c.critical else "WARN")
                suffix = f" :: {c.detail}" if (c.detail and not c.ok) else ""
                lines.append(f"  [{mark}] {c.name}{suffix}")
        lines.append(
            f"RESULT: {self.passed} passed, {self.failed} failed "
            f"({len(self.critical_failures)} critical, "
            f"{len(self.soft_failures)} soft)"
        )
        return "\n".join(lines)


# ─── helpers ──────────────────────────────────────────────────


def _check(name: str, ok: bool, detail: str = "", critical: bool = True) -> CheckResult:
    if not ok:
        logger.debug("check failed: %s (%s)", name, detail)
    return CheckResult(name, ok, detail, critical)


def load_layout(pbix: Path) -> dict:
    """Read `Report/Layout` from a `.pbix` as a dict."""
    with zipfile.ZipFile(pbix) as z:
        return json.loads(z.read("Report/Layout").decode("utf-16-le"))


def _iter_visuals(layout: dict):
    """Iterator (page_name, singleVisual, container) over all visuals."""
    for s in layout.get("sections", []):
        for c in s.get("visualContainers", []):
            cfg = json.loads(c["config"])
            yield s.get("displayName"), cfg.get("singleVisual", {}), c


def spec_objects(spec: dict) -> tuple[dict[str, set[str]], set[str]]:
    """Return (table -> set of columns, set of measures) from the spec."""
    tables: dict[str, set[str]] = {}
    for t in spec.get("tables", []):
        tables[t["name"]] = {c["name"] for c in t.get("columns", [])}
    measures = {m["name"] for m in spec.get("measures", []) if m.get("name")}
    return tables, measures


def _resolve_qref(qref: str) -> str:
    """Strip the aggregation from a queryRef: 'Sum(T.c)' -> 'T.c'."""
    m = _AGG_QREF.match(qref)
    return m.group(1) if m else qref
