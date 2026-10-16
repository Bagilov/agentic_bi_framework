"""Data model for the web clone of a dashboard (`web_report`).

The clone is a *pre-rendered, dependency-free* view of a `.pbix` report: one
record per page, one per visual element, plus the checks each element violated.
The model is deliberately renderer-agnostic so the HTML renderer, tests and any
future exporter share the same source of truth.

Public API:
    Severity (Literal)          - "error" | "warning" | "info"
    Issue                       - one violated check on one element
    ElementMetrics              - the numbers shown for an element
    ElementReport               - an element: identity, geometry, fields, issues
    PageReport                  - a page: name + elements
    WebReportModel              - the whole report + summary counters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["error", "warning", "info"]

# Order used when ranking/aggregating severities (higher = worse).
SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "error": 2}


@dataclass
class Issue:
    """One violated check on one element."""

    check_id: str
    severity: Severity
    message: str
    category: str = "structure"


@dataclass
class ElementMetrics:
    """The per-element numbers surfaced in the clone and the metrics table."""

    fields: int = 0
    roles: int = 0
    filters: int = 0
    colors: int = 0
    fonts: int = 0
    errors: int = 0
    warnings: int = 0
    infos: int = 0

    @property
    def issues(self) -> int:
        """Total number of issues on the element."""
        return self.errors + self.warnings + self.infos

    @property
    def worst(self) -> Severity:
        """The worst severity present (drives the element badge color)."""
        if self.errors:
            return "error"
        if self.warnings:
            return "warning"
        return "info"


@dataclass
class ElementReport:
    """One visual element: identity, geometry (design px), fields and issues."""

    page: str
    index: int
    visual_type: str
    title: str = ""
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    fields: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    colors: int = 0
    fonts: int = 0
    visual_filters: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def metrics(self) -> ElementMetrics:
        """Aggregate the element's shape and issues into metrics."""
        m = ElementMetrics(
            fields=len(self.fields),
            roles=len(self.roles),
            filters=self.visual_filters,
            colors=self.colors,
            fonts=self.fonts,
        )
        for i in self.issues:
            if i.severity == "error":
                m.errors += 1
            elif i.severity == "warning":
                m.warnings += 1
            else:
                m.infos += 1
        return m

    @property
    def key(self) -> str:
        """A stable id for the element (`page#index`) used in HTML/JSON."""
        return f"{self.page}#{self.index}"

    @property
    def label(self) -> str:
        """A human label: title when present, else `type #index`."""
        return self.title or f"{self.visual_type} #{self.index}"


@dataclass
class PageReport:
    """A report page: display name, canvas size and its elements."""

    name: str
    width: float = 1280
    height: float = 1050
    elements: list[ElementReport] = field(default_factory=list)

    @property
    def issues(self) -> int:
        """Total issues on the page."""
        return sum(e.metrics.issues for e in self.elements)


@dataclass
class WebReportModel:
    """The whole cloned report plus summary counters."""

    source: str
    pages: list[PageReport] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    fields_checked: bool = False

    @property
    def elements(self) -> list[ElementReport]:
        """Every element across every page, in page order."""
        return [e for p in self.pages for e in p.elements]

    def by_severity(self) -> dict[str, int]:
        """Count issues by severity across the report."""
        counts = {"error": 0, "warning": 0, "info": 0}
        for e in self.elements:
            for i in e.issues:
                counts[i.severity] = counts.get(i.severity, 0) + 1
        return counts

    @property
    def errors(self) -> int:
        """Total error-severity issues."""
        return self.by_severity()["error"]

    @property
    def issues(self) -> int:
        """Total issues across the report."""
        return sum(e.metrics.issues for e in self.elements)

    def summary(self) -> dict[str, int]:
        """The header counters shown in the clone."""
        return {
            "pages": len(self.pages),
            "elements": len(self.elements),
            "issues": self.issues,
            **self.by_severity(),
        }
