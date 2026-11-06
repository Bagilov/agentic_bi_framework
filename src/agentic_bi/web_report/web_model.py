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


#: U+FFFD REPLACEMENT CHARACTER, used for a code point no UTF-8 file can carry.
_REPLACEMENT = "\ufffd"


def _is_surrogate(char: str) -> bool:
    """True for a UTF-16 surrogate code point (U+D800-U+DFFF)."""
    return 0xD800 <= ord(char) <= 0xDFFF


def _scrub(text: str) -> str:
    """Replace characters the document cannot carry with U+FFFD.

    `Report/Layout` is JSON, so `"\\ud800"` is a legal escape and reaches the
    model as a lone surrogate. `_e()` escapes it and the renderer keeps it in the
    document string, but no such character can be encoded into the output file:
    `write_html` raised `UnicodeEncodeError` and produced no document at all.
    A NUL is scrubbed too: an HTML parser maps a literal NUL in an attribute to
    U+FFFD, so an element key containing one could never be looked up by the
    client. Scrubbing at the model boundary keeps every later consumer (renderer,
    JSON payload, other exporters) on valid, round-trippable text.
    """
    if not any(_is_surrogate(char) or char == "\x00" for char in text):
        return text
    return "".join(
        _REPLACEMENT if _is_surrogate(char) or char == "\x00" else char for char in text
    )


def _text(value: object, default: str) -> str:
    """`value` as a non-empty string, else `default` (no `repr`, no exception)."""
    if isinstance(value, str):
        return _scrub(value) or default
    return default


def _page_name(value: object) -> str:
    """A page display name as text.

    A layout may carry a number where a name is expected. `ElementReport.page`
    is coerced to its string form, and the two must match: the details table, the
    `data-page` filter and the client model all compare them. A value with no
    text form (a list, an object) falls back to a neutral name instead of
    crashing the renderer.
    """
    if isinstance(value, str) and value:
        return _scrub(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return "Page"


def _issues(value: object) -> list[Issue]:
    """Keep only `Issue` entries: a public model must not crash the renderer."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Issue)]


@dataclass
class Issue:
    """One violated check on one element."""

    check_id: str
    severity: Severity
    message: str
    category: str = "structure"

    def __post_init__(self) -> None:
        """Keep the message renderable: a lone surrogate cannot be written."""
        self.message = _scrub(str(self.message))


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
    #: Position of the owning page in `WebReportModel.pages`. It qualifies the
    #: element key, because a Power BI report may hold two pages with the same
    #: `displayName` and `page#index` alone would then collide.
    page_ordinal: int = 0

    def __post_init__(self) -> None:
        """Coerce the identity fields the renderer uses as keys to plain strings.

        `ElementReport` is public, so a caller may pass a list or a number as
        `visual_type`. Set/dict membership (`NON_DATA_TYPES`, `ALLOWED`) and
        `sorted()` over those values would raise on such a value, so the model
        stores the string form and the renderer stays total. `issues` is filtered
        the same way: a dict or a string in it would make `metrics` raise.
        """
        self.page = _page_name(self.page)
        self.title = _text(self.title, "")
        self.visual_type = _text(self.visual_type, "unknown")
        self.fields = [_scrub(str(f)) for f in self.fields]
        self.roles = [_scrub(str(r)) for r in self.roles]
        self.issues = _issues(self.issues)

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
        """A stable, page-scoped id (`<ordinal>:<page>#<index>`).

        The page ordinal is part of the key because `displayName` is not unique:
        two pages called "Overview" produced one `Overview#0` key, so one page's
        element opened the other page's details and the filter jumped pages.
        """
        return f"{self.page_ordinal}:{self.page}#{self.index}"

    @property
    def label(self) -> str:
        """A human label: title when present, else `type #index`."""
        return self.title or f"{self.visual_type} #{self.index}"


@dataclass
class PageReport:
    """A report page: display name, canvas size, its elements and filters."""

    name: str
    width: float = 1280
    height: float = 1050
    elements: list[ElementReport] = field(default_factory=list)
    filter_issues: list[Issue] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Coerce the page name and drop non-`Issue` filter entries.

        `PageReport` is public: `displayName: 7` gave a numeric name while the
        elements' `page` was the string form, so the filter matched nothing, and a
        dict in `filter_issues` raised `AttributeError` from the renderer.
        """
        self.name = _page_name(self.name)
        self.filter_issues = _issues(self.filter_issues)

    @property
    def issues(self) -> int:
        """Total issues on the page, including its page-level filters."""
        return sum(e.metrics.issues for e in self.elements) + len(self.filter_issues)


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
        """Count issues by severity across the report, page filters included."""
        counts = {"error": 0, "warning": 0, "info": 0}
        for e in self.elements:
            for i in e.issues:
                counts[i.severity] = counts.get(i.severity, 0) + 1
        for p in self.pages:
            for i in p.filter_issues:
                counts[i.severity] = counts.get(i.severity, 0) + 1
        return counts

    @property
    def errors(self) -> int:
        """Total error-severity issues."""
        return self.by_severity()["error"]

    @property
    def issues(self) -> int:
        """Total issues across the report, page-level filters included."""
        return sum(p.issues for p in self.pages)

    def summary(self) -> dict[str, int]:
        """The header counters shown in the clone."""
        return {
            "pages": len(self.pages),
            "elements": len(self.elements),
            "issues": self.issues,
            **self.by_severity(),
        }
