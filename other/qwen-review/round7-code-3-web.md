# Bundle 3: web-report model + checks

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/web_report/web_model.py ====================

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

==================== FILE: src/agentic_bi/web_report/web_checks.py ====================

"""Per-element checks for the dashboard web clone.

Mirrors the structure of `engine_verify_checks`: every check produces typed
`Issue`s with a stable id, a severity and a category, so the clone (and any
other consumer) can render or filter them. Structural checks need no
dependencies; field checks need a model registry.

Categories: ``structure`` (visual shape), ``binding`` (query/model membership),
``filter`` (unsafe filters).

Public API:
    NON_DATA_TYPES
    element_issues(sv, vc, roles, registry=None) -> list[Issue]
    has_in_filter(raw) -> bool
"""

from __future__ import annotations

import json
from typing import Any

from agentic_bi.web_report.web_model import Issue

# Decorative/static visuals that legitimately carry no data projections. They are
# reported as info (not errors) so a clone of an arbitrary report stays readable.
NON_DATA_TYPES = {
    "textbox",
    "image",
    "shape",
    "basicShape",
    "actionButton",
    "bookmarkNavigator",
    "pageNavigator",
    "qnaVisual",
    "groupContainer",
    "shapeMap",
    "rectangle",
}


def has_in_filter(raw: Any) -> bool:
    """Whether a visual/page filter blob contains an unsafe `Condition.In`."""
    if not raw or raw == "[]":
        return False
    try:
        flts = json.loads(raw)
    except (ValueError, TypeError):
        return True
    for f in flts or []:
        for w in f.get("filter", {}).get("Where", []):
            if "In" in w.get("Condition", {}):
                return True
    return False


def element_issues(
    sv: dict, vc: dict, roles: list[str], registry: dict | None = None
) -> list[Issue]:
    """Evaluate one element and return its issues (empty == clean).

    Args:
        sv: the `singleVisual` block of the container.
        vc: the whole visualContainer (for its `filters`).
        roles: the projection roles present on the visual.
        registry: optional `{table:{columns,measures}}` for membership checks.
    """
    issues: list[Issue] = []
    if not sv:
        return [
            Issue(
                "STRUCT-NO-SINGLEVISUAL",
                "error",
                "container has no singleVisual",
                "structure",
            )
        ]
    vt = sv.get("visualType") or "unknown"
    decorative = vt in NON_DATA_TYPES

    issues.extend(_shape_issues(vt, sv, roles, decorative))
    issues.extend(_projection_issues(vt, sv))
    if has_in_filter(vc.get("filters", "[]")):
        issues.append(
            Issue(
                "FILTER-UNSAFE-IN",
                "error",
                "unsafe Condition.In filter on the visual",
                "filter",
            )
        )
    if registry is not None:
        issues.extend(_field_issues(vt, sv.get("prototypeQuery") or {}, registry))
    return issues


def _shape_issues(vt: str, sv: dict, roles: list[str], decorative: bool) -> list[Issue]:
    """Projection presence + role allow/required checks."""
    issues: list[Issue] = []
    if not sv.get("projections"):
        if decorative:
            issues.append(
                Issue(
                    "INFO-STATIC-VISUAL",
                    "info",
                    f"{vt} has no data projections (static element)",
                    "structure",
                )
            )
        else:
            issues.append(
                Issue(
                    "STRUCT-NO-PROJECTIONS",
                    "error",
                    f"{vt} has no projections (renders empty)",
                    "structure",
                )
            )

    from agentic_bi.visual_check import ALLOWED, REQUIRED  # avoid import cycle

    allowed = ALLOWED.get(vt)
    if allowed is None:
        issues.append(
            Issue(
                "STRUCT-UNKNOWN-TYPE",
                "info" if decorative else "warning",
                f"unknown visualType '{vt}'",
                "structure",
            )
        )
        return issues
    for role in roles:
        if role not in allowed:
            issues.append(
                Issue(
                    "STRUCT-ROLE-NOT-ALLOWED",
                    "error",
                    f"{vt} role '{role}' not allowed (allowed: {sorted(allowed)})",
                    "structure",
                )
            )
    for role in REQUIRED.get(vt, []):
        if role not in roles:
            issues.append(
                Issue(
                    "STRUCT-MISSING-ROLE",
                    "error",
                    f"{vt} missing required role '{role}'",
                    "structure",
                )
            )
    return issues


def _projection_issues(vt: str, sv: dict) -> list[Issue]:
    """Every projection `queryRef` must match a `prototypeQuery.Select` name."""
    issues: list[Issue] = []
    pq = sv.get("prototypeQuery") or {}
    select_names = {
        s.get("Name") for s in (pq.get("Select") or []) if isinstance(s, dict)
    }
    for role, refs in (sv.get("projections") or {}).items():
        for ref in refs:
            qr = ref.get("queryRef")
            if qr and qr not in select_names:
                issues.append(
                    Issue(
                        "BIND-NO-SELECT",
                        "error",
                        f"{vt} projection {role} queryRef '{qr}' has no matching "
                        "Select",
                        "binding",
                    )
                )
    return issues


def _field_issues(vt: str, pq: dict, registry: dict) -> list[Issue]:
    """Check that every Select/aggregation references objects in the model."""
    alias2ent = {f.get("Name"): f.get("Entity") for f in (pq.get("From") or [])}
    issues: list[Issue] = []
    for sel in pq.get("Select") or []:
        if not isinstance(sel, dict):
            continue
        for kind, bucket in (("Column", "columns"), ("Measure", "measures")):
            spec = sel.get(kind)
            if not spec:
                continue
            issues.extend(
                _resolution_issues(vt, f"{kind}", spec, bucket, alias2ent, registry)
            )
        agg = sel.get("Aggregation")
        if agg:
            col = (agg.get("Expression") or {}).get("Column")
            if col:
                issues.extend(
                    _resolution_issues(vt, "agg", col, "columns", alias2ent, registry)
                )
    return issues


def _resolution_issues(
    vt: str, what: str, spec: dict, bucket: str, alias2ent: dict, registry: dict
) -> list[Issue]:
    """Resolve one Column/Measure/aggregation Column against the registry."""
    sr = spec.get("Expression", {}).get("SourceRef") or {}
    ent = alias2ent.get(sr.get("Source")) or sr.get("Entity")
    prop = spec.get("Property")
    if ent not in registry:
        return [
            Issue(
                "BIND-TABLE-MISSING",
                "error",
                f"{vt} {what} table '{ent}' not in model",
                "binding",
            )
        ]
    if prop not in registry[ent].get(bucket, []):
        return [
            Issue(
                "BIND-FIELD-MISSING",
                "error",
                f"{vt} {what} {ent}.{prop} not in model",
                "binding",
            )
        ]
    return []

==================== FILE: src/agentic_bi/web_report/web_inspect.py ====================

"""Inspect a `.pbix` report element by element and collect issues.

This adapts the "one record per element with a tooltip of its metrics" idea from
the process-mining HTML report to the structure of a Power BI `Report/Layout`:
every `visualContainer` becomes an `ElementReport` carrying its identity,
geometry, projected fields and the checks it failed (see `web_checks`).

Public API:
    build_model(pbix, registry=None) -> WebReportModel
    inspect_layout(layout, registry=None, source=...) -> WebReportModel
    load_layout(pbix) -> dict
    registry_from_pbix(pbix) -> dict          (needs pbixray)
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

from agentic_bi.web_report.web_checks import element_issues
from agentic_bi.web_report.web_model import (
    ElementReport,
    PageReport,
    WebReportModel,
)

logger = logging.getLogger(__name__)

_HEX_RE = re.compile(r"#([0-9A-Fa-f]{6})\b")
# `fontFamily` appears either as a plain string or as a literal expression
# (`"fontFamily": {"expr": {"Literal": {"Value": "'Brand Sans'"}}}`).
_FONT_RE = re.compile(r'"fontFamily"\s*:\s*"([^"]+)"')
_FONT_LITERAL_RE = re.compile(
    r'"fontFamily"\s*:\s*\{\s*"expr"\s*:\s*\{\s*"Literal"\s*:\s*\{\s*'
    r'"Value"\s*:\s*"\'?([^"\']+)\'?"'
)


# ─── layout helpers ───────────────────────────────────────────


def _decode_layout(raw: bytes) -> dict:
    for enc in ("utf-16-le", "utf-8-sig", "utf-8"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:  # noqa: BLE001
            continue
    raise ValueError("cannot decode Report/Layout")


def load_layout(pbix: str | Path) -> dict:
    """Read and decode `Report/Layout` from a `.pbix`."""
    with zipfile.ZipFile(pbix) as z:
        return _decode_layout(z.read("Report/Layout"))


def _visual_title(cfg: dict) -> str:
    """Best-effort title of a visual from its `objects.title` literal."""
    try:
        props = cfg["singleVisual"]["objects"]["title"][0]["properties"]
        literal = props["text"]["expr"]["Literal"]["Value"]
        return str(literal).strip("'")
    except (KeyError, IndexError, TypeError):
        return ""


def _projected_fields(sv: dict) -> tuple[list[str], list[str]]:
    """Return (fields, roles) from the visual's projections."""
    fields: list[str] = []
    roles: list[str] = []
    for role, refs in (sv.get("projections") or {}).items():
        roles.append(role)
        for ref in refs:
            qref = ref.get("queryRef")
            if qref:
                fields.append(qref)
    return fields, roles


def _count_filters(raw: Any) -> int:
    if not raw or raw == "[]":
        return 0
    try:
        flts = json.loads(raw)
    except (ValueError, TypeError):
        return 1
    return len(flts) if isinstance(flts, list) else 1


def _usage_counts(text: str) -> tuple[int, int]:
    """Distinct colors (HEX) and font families referenced in a config blob."""
    colors = {m.group(1).upper() for m in _HEX_RE.finditer(text)}
    fonts = {m.group(1) for m in _FONT_RE.finditer(text)}
    fonts |= {m.group(1) for m in _FONT_LITERAL_RE.finditer(text)}
    return len(colors), len(fonts)


# ─── model assembly ───────────────────────────────────────────


def inspect_layout(
    layout: dict, registry: dict | None = None, source: str = "<layout>"
) -> WebReportModel:
    """Turn a decoded `Report/Layout` into a `WebReportModel`."""
    model = WebReportModel(source=source, fields_checked=registry is not None)
    model.checks_run = ["structure", "binding", "filter"]
    if registry is not None:
        model.checks_run.append("model-membership")

    for sec in layout.get("sections", []):
        page = PageReport(
            name=sec.get("displayName") or f"Page {sec.get('ordinal', 0)}",
            width=float(sec.get("width") or 1280),
            height=float(sec.get("height") or 1050),
        )
        for idx, vc in enumerate(sec.get("visualContainers", [])):
            page.elements.append(_element(vc, idx, page.name, registry))
        model.pages.append(page)
    return model


def _element(vc: dict, idx: int, page: str, registry: dict | None) -> ElementReport:
    raw_cfg = vc.get("config", "")
    cfg_text = (
        raw_cfg if isinstance(raw_cfg, str) else json.dumps(raw_cfg, ensure_ascii=False)
    )
    try:
        cfg = json.loads(cfg_text or "{}")
    except (ValueError, TypeError):
        cfg = {}
    sv = cfg.get("singleVisual") or {}
    fields, roles = _projected_fields(sv)
    colors, fonts = _usage_counts(cfg_text)
    element = ElementReport(
        page=page,
        index=idx,
        visual_type=sv.get("visualType") or "unknown",
        title=_visual_title(cfg),
        x=float(vc.get("x") or 0),
        y=float(vc.get("y") or 0),
        width=float(vc.get("width") or 0),
        height=float(vc.get("height") or 0),
        fields=fields,
        roles=roles,
        colors=colors,
        fonts=fonts,
        visual_filters=_count_filters(vc.get("filters", "[]")),
    )
    element.issues = element_issues(sv, vc, roles, registry)
    return element


def build_model(pbix: str | Path, registry: dict | None = None) -> WebReportModel:
    """Build the `WebReportModel` for a `.pbix` (single entry point)."""
    pbix = Path(pbix)
    layout = load_layout(pbix)
    return inspect_layout(layout, registry=registry, source=pbix.name)


def registry_from_pbix(pbix: str | Path) -> dict:
    """Build a `{table:{columns,measures}}` registry via `pbixray`.

    Returns an empty dict when `pbixray` is unavailable; callers then skip the
    model-membership checks (the clone still works, just without that category).
    """
    try:
        from pbixray import PBIXRay
    except ImportError:
        logger.info("pbixray not installed; skipping model membership checks")
        return {}
    registry: dict[str, dict[str, list[str]]] = {}
    with PBIXRay(str(pbix)) as pb:
        for table in pb.tables:
            try:
                columns = list(pb.get_table(table).columns)
            except Exception:  # noqa: BLE001 - decoder is best-effort
                columns = []
            registry[table] = {"columns": columns, "measures": []}
        try:
            for row in pb.dax_measures.itertuples():
                table = getattr(row, "TableName", None)
                name = getattr(row, "Name", None)
                if table in registry and name:
                    registry[table]["measures"].append(name)
        except Exception:  # noqa: BLE001
            pass
    return registry

