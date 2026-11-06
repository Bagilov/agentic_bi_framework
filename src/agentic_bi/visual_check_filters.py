"""Structural `Condition.In` detection for `Report/Layout` filter blobs.

The original check serialized a whole filter with `json.dumps` and searched for
the substring `"In"`. Every word containing it (`Include`, `Income`, `Index`,
table/column names) matched, which produced 69 false errors on
`templates/template.pbix` and made the donor board impossible to certify. A
filter is an object graph, so the walk below looks only at the structural key
`Condition` and the `In` inside it.

Desktop writes two legitimate `Condition.In` shapes - inline `Values` and a
Top-N `Table` subquery. An `In` is therefore reported only when it is
unresolvable: an expression/`Table` `SourceRef.Source` that the filter's own
`From` does not declare, or an `In` with neither `Values` nor `Table`. That
keeps real report filters certifiable while a dangling hand-built `IN` (the
construct that crashes the pivot on drill) still fails.

Public API:
    find_unsafe_in(node, aliases=None) -> bool
    filters_of(container) -> (filters, error)
"""

from __future__ import annotations

import json


def source_aliases(filt: object) -> set[str]:
    """Aliases declared by a filter's own `filter.From` clause."""
    if not isinstance(filt, dict):
        return set()
    body = filt.get("filter")
    if not isinstance(body, dict):
        return set()
    items = body.get("From")
    if not isinstance(items, list):
        return set()
    return {
        item["Name"]
        for item in items
        if isinstance(item, dict) and isinstance(item.get("Name"), str)
    }


def _has_unresolved_source(node: object, aliases: set[str]) -> bool:
    """True when a `SourceRef.Source` under `node` is not declared in `aliases`.

    Iterative so a hostile/deeply nested filter cannot exhaust the stack. A
    `SourceRef` with a global `Entity` (no `Source`) needs no alias and is fine.
    """
    stack: list[object] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            source_ref = current.get("SourceRef")
            if isinstance(source_ref, dict):
                source = source_ref.get("Source")
                if isinstance(source, str) and source and source not in aliases:
                    return True
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return False


def _in_is_unsafe(operand: object, aliases: set[str]) -> bool:
    """Whether one `Condition.In` operand is a dangling/malformed IN filter."""
    if not isinstance(operand, dict):
        return True
    if "Values" in operand:
        expressions = operand.get("Expressions")
        if not isinstance(expressions, list) or not expressions:
            return True
        return _has_unresolved_source(expressions, aliases)
    if "Table" in operand:
        return _has_unresolved_source(operand["Table"], aliases)
    return True


def find_unsafe_in(node: object, aliases: set[str] | None = None) -> bool:
    """Walk `node` and report a real, unresolvable `Condition.In`.

    Only the structural key `Condition.In` counts: a `Condition` mapping holding
    an `In` key. Plain text such as "Income"/"Include" is never inspected, and
    non-dict/list leaves are skipped instead of raising.
    """
    names = aliases if aliases is not None else set()
    stack: list[object] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            condition = current.get("Condition")
            if isinstance(condition, dict) and "In" in condition:
                if _in_is_unsafe(condition["In"], names):
                    return True
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return False


def _filter_entries(items: list[object]) -> tuple[list[object], str | None]:
    """Validate the entries of a filter list: objects, or JSON objects as strings.

    A filter entry is an object graph. A plain string is either a mistakenly
    double-encoded filter (Power BI sometimes nests one) or junk; the first is
    parsed, the second is reported. Silently skipping a non-object entry made an
    unreadable filter look clean, which is the opposite of a fail-closed check.
    """
    filters: list[object] = []
    for item in items:
        if isinstance(item, dict):
            filters.append(item)
            continue
        if isinstance(item, str):
            try:
                inner = json.loads(item)
            except (TypeError, ValueError, RecursionError):
                return [], "a filters entry is not a filter object"
            if isinstance(inner, dict):
                filters.append(inner)
                continue
        return [], "a filters entry is not a filter object"
    return filters, None


def filters_of(container: dict) -> tuple[list[object], str | None]:
    """Parse a container `filters` blob -> (filters, error message).

    The blob is untrusted and the check is **fail-closed**: `None`, an empty
    string, `"null"` and `"[]"` mean "no filters", while anything else that is not
    a JSON list of filter objects yields a readable error. A payload that parses
    to a single object (or to a string/list of non-objects) used to be reported as
    "no filters", so an unreadable filter was certified as safe.
    """
    raw = container.get("filters", "[]")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "[]")
        except (TypeError, ValueError, RecursionError) as e:
            return [], f"filters JSON invalid: {e}"
    else:
        parsed = raw
    if parsed is None:
        return [], None
    if not isinstance(parsed, list):
        return [], f"filters must be a JSON list, got {type(parsed).__name__}"
    return _filter_entries(parsed)
