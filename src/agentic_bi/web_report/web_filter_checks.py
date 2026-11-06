"""`Condition.In` safety for a visual container's `filters` blob.

The structural decision lives in `visual_check_filters` (shared with
`engine.verify_filters`) so the web clone cannot drift from the engine again:
Desktop's inline `Values` IN and its Top-N `Table`/`subquery` IN are legitimate,
and only a structurally unresolvable `In` - a `SourceRef.Source` the filter's own
`From` does not declare, or an `In` with neither `Values` nor `Table` - is
reported. The old shape/substring heuristic flagged every word containing "In".

Public API:
    unsafe_in_filter(raw) -> bool | None
    has_in_filter(raw) -> bool
    filter_issues(raw) -> list[Issue]
"""

from __future__ import annotations

from agentic_bi.visual_check_filters import (
    filters_of,
    find_unsafe_in,
    source_aliases,
)
from agentic_bi.web_report.web_model import Issue

__all__ = ["filter_issues", "has_in_filter", "unsafe_in_filter"]


def unsafe_in_filter(raw: object) -> bool | None:
    """Whether a filter blob carries an unresolvable `Condition.In`.

    Args:
        raw: the `filters` value - a JSON string, an already parsed list, or
            anything else untrusted (`filters_of` decides).

    Returns:
        True for a structurally unsafe `In`, False for a blob that parsed and
        carries none, and None when the blob cannot be parsed at all. The
        tri-state keeps "unsafe" and "unreadable" distinguishable; the boolean
        `has_in_filter` is the fail-closed view of the same answer.
    """
    filters, error = filters_of({"filters": raw})
    if error is not None:
        return None
    return _any_unsafe_in(filters)


def has_in_filter(raw: object) -> bool:
    """Fail-closed boolean form of `unsafe_in_filter`.

    True for a genuinely unsafe `In` and also for a payload that cannot be
    parsed at all: an unreadable filter cannot be certified. Inline `Values` and
    `Table`/`subquery` IN filters are safe.
    """
    return unsafe_in_filter(raw) is not False


def filter_issues(raw: object) -> list[Issue]:
    """Diagnostics for one container `filters` blob (at most one issue).

    An unresolvable `In` keeps the historical `filter` error. A payload that
    cannot be parsed is reported as its own error (the `filters_of` reason)
    instead of being conflated with a real `In`; nothing here raises.
    """
    filters, error = filters_of({"filters": raw})
    if error is not None:
        return [Issue("FILTER-UNREADABLE", "error", error, "filter")]
    if _any_unsafe_in(filters):
        return [
            Issue(
                "FILTER-UNSAFE-IN",
                "error",
                "unsafe Condition.In filter on the visual",
                "filter",
            )
        ]
    return []


def _any_unsafe_in(filters: list[object]) -> bool:
    """Whether a parsed filter list carries a structurally unresolvable `In`."""
    return any(find_unsafe_in(filt, source_aliases(filt)) for filt in filters)
