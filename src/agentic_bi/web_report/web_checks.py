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

from agentic_bi.layout_meta import DECORATIVE_VISUAL_TYPES
from agentic_bi.web_report.web_model import Issue

# Decorative/static visuals that legitimately carry no data projections. They are
# reported as info (not errors) so a clone of an arbitrary report stays readable.
# The list itself lives in `layout_meta` (shared with `engine_verify_checks`).
NON_DATA_TYPES = DECORATIVE_VISUAL_TYPES


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
