"""Filter-safety checks for a decoded `Report/Layout`.

`verify_safe_filters` accepts the two `Condition.In` shapes Desktop writes
(inline `Values` and a Top-N `Table` subquery) and reports an `In` only when it
is structurally unresolvable: a `SourceRef.Source` missing from the filter's own
`From`, or an `In` with neither `Values` nor `Table`. Such a dangling `IN` is
the construct that crashes the pivot serializer on expand
(`QueryExpressionBuilder.visitIn` -> `exprs[i].accept is not a function`).

Both page-level (`sections[].filters`) and visual-level
(`visualContainers[].filters`) blobs are walked. They are untrusted: an
unreadable one is returned as a non-critical diagnostic instead of raising, and
a container is reported at most once.

Public API:
    verify_safe_filters(layout) -> list[CheckResult]
"""

from __future__ import annotations

from agentic_bi.engine.verify_core import CheckResult, _check
from agentic_bi.visual_check_filters import (
    filters_of,
    find_unsafe_in,
    source_aliases,
)

__all__ = ["verify_safe_filters"]


def verify_safe_filters(layout: dict) -> list[CheckResult]:
    """Report only structurally unresolvable page/visual `Condition.In` filters.

    The blob is untrusted, so a broken payload yields the soft check
    `filters payload readable` rather than a traceback, and a container whose
    filters are fine adds nothing.
    """
    bad: list[str] = []
    unreadable: list[str] = []
    for section in _layout_sections(layout):
        page = section.get("displayName")
        _scan_filters(section, f"page '{page}'", bad, unreadable)
        for container in _layout_containers(section):
            _scan_filters(container, f"visual in '{page}'", bad, unreadable)
    out = [_check("no unsafe IN filters", not bad, str(bad))]
    if unreadable:
        out.append(
            _check(
                "filters payload readable",
                False,
                str(unreadable[:5]),
                critical=False,
            )
        )
    return out


def _layout_sections(layout: dict) -> list[dict]:
    """Dict sections of an untrusted layout (odd entries are skipped)."""
    raw = layout.get("sections") if isinstance(layout, dict) else None
    return [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []


def _layout_containers(section: dict) -> list[dict]:
    """Dict visual containers of a section (the owners of a `filters` blob)."""
    raw = section.get("visualContainers")
    return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []


def _scan_filters(
    container: dict, label: str, bad: list[str], unreadable: list[str]
) -> None:
    """Append `label` once when the container's filter blob has an unsafe `In`."""
    filters, error = filters_of(container)
    if error is not None:
        unreadable.append(f"{label}: {error}")
        return
    for filt in filters:
        if find_unsafe_in(filt, source_aliases(filt)):
            bad.append(label)
            return
