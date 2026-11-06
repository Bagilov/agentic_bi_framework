"""Per-element and document checks for the dashboard web clone.

Mirrors the structure of `engine_verify_checks`: every check produces typed
`Issue`s with a stable id, a severity and a category, so the clone (and any
other consumer) can render or filter them. Structural checks need no
dependencies; field checks need a model registry; document checks inspect the
generated (or any already-built) HTML document.

Categories: ``structure`` (visual shape), ``binding`` (query/model membership),
``filter`` (unsafe filters), ``html`` (accessibility/responsiveness of the
generated document).

Public API:
    NON_DATA_TYPES
    visual_type(sv) -> str
    element_issues(sv, vc, roles, registry=None) -> list[Issue]
    unsafe_in_filter(raw) -> bool | None
    has_in_filter(raw) -> bool
    filter_issues(raw) -> list[Issue]
    html_issues(markup) -> list[Issue]

`unsafe_in_filter`/`has_in_filter`/`filter_issues` are re-exported from
`web_filter_checks`, which delegates the `Condition.In` structure to
`visual_check_filters`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agentic_bi.layout_meta import DECORATIVE_VISUAL_TYPES
from agentic_bi.web_report.web_filter_checks import (
    filter_issues,
    has_in_filter,
    unsafe_in_filter,
)
from agentic_bi.web_report.web_model import Issue

__all__ = [
    "HTML_REQUIRED_MARKUP",
    "NON_DATA_TYPES",
    "element_issues",
    "filter_issues",
    "has_in_filter",
    "html_issues",
    "unsafe_in_filter",
    "visual_type",
]

# Size exception (>300 lines): the check catalogue (markers, element checks,
# document checks) is one registry; splitting it would hide which markers the
# renderer must keep.

# Required markers in the generated document. Each pair is (check id, snippet);
# a missing snippet means an a11y/media-query regression in the renderer.
HTML_REQUIRED_MARKUP: tuple[tuple[str, str], ...] = (
    ("HTML-A11Y-LANG", '<html lang="'),
    ("HTML-A11Y-FOCUS", ":focus-visible"),
    ("HTML-A11Y-TABS", 'role="tablist"'),
    ("HTML-A11Y-TAB-STATE", 'aria-selected="'),
    ("HTML-A11Y-CONTROLS", "aria-label="),
    ("HTML-A11Y-INTERACTIVE", 'role="button" tabindex="0"'),
    ("HTML-A11Y-DETAIL-TARGET", 'aria-controls="detailCard"'),
    ("HTML-A11Y-DETAIL-CLOSE", 'id="detailClose"'),
    ("HTML-A11Y-MODAL", 'aria-modal="false"'),
    ("HTML-A11Y-INERT", "inert"),
    ("HTML-MEDIA-DARK", "@media (prefers-color-scheme: dark)"),
    ("HTML-MEDIA-MOTION", "@media (prefers-reduced-motion: reduce)"),
    ("HTML-MEDIA-NARROW", "@media (max-width: 720px)"),
    ("HTML-MEDIA-PRINT", "@media print"),
)

_HEADING_RE = re.compile(r"<h([1-6])\b")
# Script/style bodies are code, not document content: report data (a page title,
# a visual label) can contain "<h4>" or "@media print" and must not satisfy a
# marker check or be counted as a heading.
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE
)
_SCRIPT_ELEMENT_RE = re.compile(
    r"<script\b[^>]*>.*?</script\s*>", re.DOTALL | re.IGNORECASE
)
_STYLE_BLOCK_RE = re.compile(
    r"<style\b[^>]*>(.*?)</style\s*>", re.DOTALL | re.IGNORECASE
)
# An HTML comment is not rendered, so a `<style>`/`<h1>` inside one is neither a
# stylesheet nor a heading. Comments are stripped before any parse.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Markers that belong to the stylesheet, not to markup or report-derived text.
_STYLE_ONLY_CHECKS = frozenset(
    {
        "HTML-A11Y-FOCUS",
        "HTML-MEDIA-DARK",
        "HTML-MEDIA-MOTION",
        "HTML-MEDIA-NARROW",
        "HTML-MEDIA-PRINT",
    }
)
# Each of these controls needs its own accessible name; a single `aria-label=`
# anywhere in the document (e.g. on the detail popover) is not enough.
_LABELLED_CONTROLS = ('data-el="1"', 'id="filterToggle"', 'class="btn-close"')

# Tab/control markup only exists when the report has elements; an empty-state
# document is legitimately tab-free, so these checks are skipped there.
_ELEMENT_ONLY_CHECKS = frozenset(
    {
        "HTML-A11Y-TABS",
        "HTML-A11Y-TAB-STATE",
        "HTML-A11Y-CONTROLS",
        "HTML-A11Y-INTERACTIVE",
        "HTML-A11Y-DETAIL-TARGET",
        "HTML-A11Y-INERT",
    }
)

# Boolean attributes are valid both bare (`inert`) and with an empty value
# (`inert=""`), so these are matched as an attribute inside an opening tag
# rather than as a literal snippet.
_BOOLEAN_ATTRIBUTE_CHECKS = frozenset({"HTML-A11Y-INERT"})


# Decorative/static visuals that legitimately carry no data projections. They are
# reported as info (not errors) so a clone of an arbitrary report stays readable.
# The list itself lives in `layout_meta` (shared with `engine_verify_checks`).
NON_DATA_TYPES = DECORATIVE_VISUAL_TYPES


def visual_type(sv: dict) -> str:
    """The `visualType` of a `singleVisual` block as a non-empty string.

    The layout is untrusted, so `visualType` may be a list, an object or a
    number. Such a value can neither be a dictionary/set key (`vt in
    NON_DATA_TYPES`, `ALLOWED.get(vt)`) nor be ordered with real type names, so
    anything that is not a non-empty string degrades to ``"unknown"`` and the
    element still gets its diagnostics instead of aborting the inspection.
    """
    value = sv.get("visualType")
    return value if isinstance(value, str) and value else "unknown"


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
    vt = visual_type(sv)
    decorative = vt in NON_DATA_TYPES

    issues.extend(_shape_issues(vt, sv, roles, decorative))
    issues.extend(_projection_issues(vt, sv))
    issues.extend(filter_issues(vc.get("filters", "[]")))
    if registry is not None:
        issues.extend(_field_issues(vt, _as_prototype_query(sv), registry))
    return issues


def _projections(sv: dict) -> dict:
    """The visual's `projections` map; a non-mapping value counts as absent."""
    projections = sv.get("projections")
    return projections if isinstance(projections, dict) else {}


def _shape_issues(vt: str, sv: dict, roles: list[str], decorative: bool) -> list[Issue]:
    """Projection presence + role allow/required checks."""
    issues: list[Issue] = []
    if not _projections(sv):
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


def _as_prototype_query(sv: dict) -> dict:
    """Return the visual's `prototypeQuery` as a dict.

    `prototypeQuery` is usually a dict in `config`, but a layout may carry it as a
    JSON string (Power BI does this for `query`), and the layout is untrusted: a
    string (or any non-dict) must not make `.get` raise, so a non-dict yields {}.
    """
    pq = sv.get("prototypeQuery")
    if isinstance(pq, str):
        try:
            pq = json.loads(pq)
        except (ValueError, TypeError, RecursionError):
            return {}
    return pq if isinstance(pq, dict) else {}


def _projection_issues(vt: str, sv: dict) -> list[Issue]:
    """Every projection `queryRef` must match a `prototypeQuery.Select` name.

    The projections come from the untrusted layout: a list-typed `projections`,
    a scalar role value or a non-object reference is skipped, not fatal.
    """
    issues: list[Issue] = []
    pq = _as_prototype_query(sv)
    # `Name` and `queryRef` come from an untrusted layout and may be lists or
    # objects: a set member / dict key must be hashable, and a list here used to
    # abort the whole clone with `TypeError: unhashable type`.
    select_names = {
        name
        for s in _as_list(pq.get("Select"))
        if isinstance(s, dict) and isinstance(name := s.get("Name"), str)
    }
    malformed: list[str] = []
    for role, refs in _projections(sv).items():
        if not isinstance(refs, list):
            malformed.append(str(role))
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                malformed.append(str(role))
                continue
            qr = ref.get("queryRef")
            if not isinstance(qr, str):
                malformed.append(str(role))
                continue
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
    for role in dict.fromkeys(malformed):
        issues.append(
            Issue(
                "STRUCT-BAD-PROJECTIONS",
                "error",
                f"{vt} projection '{role}' is not a list of objects",
                "structure",
            )
        )
    return issues


def _as_list(value: Any) -> list:
    """A layout collection coerced to a list; a scalar or mapping is empty."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    """A layout object coerced to a dict; anything else is empty."""
    return value if isinstance(value, dict) else {}


def _field_issues(vt: str, pq: dict, registry: dict) -> list[Issue]:
    """Check that every Select/aggregation references objects in the model."""
    alias2ent = {
        alias: f.get("Entity")
        for f in _as_list(pq.get("From"))
        if isinstance(f, dict) and isinstance(alias := f.get("Name"), str)
    }
    issues: list[Issue] = []
    for sel in _as_list(pq.get("Select")):
        if not isinstance(sel, dict):
            continue
        for kind, bucket in (("Column", "columns"), ("Measure", "measures")):
            spec = sel.get(kind)
            if not isinstance(spec, dict) or not spec:
                continue
            issues.extend(
                _resolution_issues(vt, f"{kind}", spec, bucket, alias2ent, registry)
            )
        agg = _as_dict(sel.get("Aggregation"))
        if agg:
            col = _as_dict(_as_dict(agg.get("Expression")).get("Column"))
            if col:
                issues.extend(
                    _resolution_issues(vt, "agg", col, "columns", alias2ent, registry)
                )
    return issues


def _resolution_issues(
    vt: str,
    what: str,
    spec: dict,
    bucket: str,
    alias2ent: dict,
    registry: dict,
) -> list[Issue]:
    """Resolve one Column/Measure/aggregation Column against the registry."""
    sr = _as_dict(_as_dict(spec.get("Expression")).get("SourceRef"))
    source = sr.get("Source")
    ent = (alias2ent.get(source) if isinstance(source, str) else None) or sr.get(
        "Entity"
    )
    prop = spec.get("Property")
    table = registry.get(ent) if isinstance(ent, str) else None
    if not isinstance(table, dict):
        return [
            Issue(
                "BIND-TABLE-MISSING",
                "error",
                f"{vt} {what} table '{ent}' not in model",
                "binding",
            )
        ]
    if prop not in _as_list(table.get(bucket)):
        return [
            Issue(
                "BIND-FIELD-MISSING",
                "error",
                f"{vt} {what} {ent}.{prop} not in model",
                "binding",
            )
        ]
    return []


def _strip_script_style(markup: str) -> str:
    """Drop `<script>`/`<style>` bodies before scanning document structure."""
    return _SCRIPT_STYLE_RE.sub("", markup)


def _strip_comments(markup: str) -> str:
    """Drop HTML comments; their content is not rendered as document content."""
    return _COMMENT_RE.sub("", markup)


def _style_text(markup: str) -> str:
    """Concatenated text of every rendered `<style>` element.

    Comments and `<script>` elements are removed first, so a `<style>` that only
    exists inside an HTML comment or a JS string cannot satisfy a stylesheet
    marker for an already-built document.
    """
    cleaned = _SCRIPT_ELEMENT_RE.sub("", _strip_comments(markup))
    return "\n".join(m.group(1) for m in _STYLE_BLOCK_RE.finditer(cleaned))


def _markup_text(markup: str) -> str:
    """Document markup with comments, scripts and stylesheets removed."""
    return _strip_script_style(_strip_comments(markup))


def _has_attribute(markup: str, name: str) -> bool:
    """Whether some opening tag carries `name` as an attribute."""
    pattern = re.compile(
        r"<[A-Za-z][^>]*\s" + re.escape(name) + r"(?=[\s=>/])", re.IGNORECASE
    )
    return bool(pattern.search(markup))


def _opening_tags(markup: str, needle: str) -> list[str]:
    """Opening tags that carry `needle` inside their attribute list."""
    pattern = re.compile(r"<[A-Za-z][^>]*" + re.escape(needle) + r"[^>]*>")
    return pattern.findall(markup)


def _has_control_labels(markup: str) -> bool:
    """Every interactive control has its own `aria-label`."""
    for needle in _LABELLED_CONTROLS:
        tags = _opening_tags(markup, needle)
        if not tags or not all("aria-label=" in tag for tag in tags):
            return False
    return True


def _heading_issues(markup: str) -> list[Issue]:
    """Heading levels must start at h1 and never skip a level (h1 -> h3)."""
    levels = [int(m.group(1)) for m in _HEADING_RE.finditer(markup)]
    if not levels:
        return [Issue("HTML-HEADING-MISSING", "warning", "no headings", "html")]
    issues: list[Issue] = []
    if levels[0] != 1:
        issues.append(
            Issue(
                "HTML-HEADING-START",
                "warning",
                f"first heading is h{levels[0]}, expected h1",
                "html",
            )
        )
    for prev, cur in zip(levels, levels[1:], strict=False):
        if cur > prev + 1:
            issues.append(
                Issue(
                    "HTML-HEADING-SKIP",
                    "warning",
                    f"heading level jumps from h{prev} to h{cur}",
                    "html",
                )
            )
            break
    return issues


def html_issues(markup: str) -> list[Issue]:
    """Check the generated document for required a11y/media-query markers.

    Args:
        markup: the full rendered HTML document.

    Returns:
        One issue per missing marker (severity ``error``) plus heading-order
        warnings. An empty list means the document keeps the accessibility,
        responsive and print contract of the renderer.

    Comments and script/style bodies never count as markup or stylesheet: an
    already-built document may carry `<style>@media print</style>` in a comment
    or a JS string, and that must not hide a removed print block.
    """
    style_text = _style_text(markup)
    markup_text = _markup_text(markup)
    issues: list[Issue] = []
    for check_id, needle in HTML_REQUIRED_MARKUP:
        if check_id in _ELEMENT_ONLY_CHECKS and 'data-el="1"' not in markup_text:
            continue
        if check_id == "HTML-A11Y-CONTROLS":
            present = _has_control_labels(markup_text)
        elif check_id in _BOOLEAN_ATTRIBUTE_CHECKS:
            present = _has_attribute(markup_text, needle)
        else:
            haystack = style_text if check_id in _STYLE_ONLY_CHECKS else markup_text
            present = needle in haystack
        if not present:
            issues.append(
                Issue(
                    check_id,
                    "error",
                    f"generated HTML is missing {needle!r}",
                    "html",
                )
            )
    issues.extend(_heading_issues(markup_text))
    return issues
