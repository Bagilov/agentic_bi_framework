"""Layout-level helpers for the board guide (untrusted `Report/Layout` input).

`Report/Layout` is untrusted data: a container may carry no `config`, a `config`
that is not JSON, a position with string coordinates or a `prototypeQuery`
serialized as a string. Every helper here tolerates that and degrades to a
neutral value instead of raising, so a malformed visual is skipped rather than
aborting the whole guide.

Public API:
    load_layout(pbix) -> dict
    is_hidden(section) -> bool
    visual_title(cfg) -> str
    projections(sv) -> (fields, measures)
    filter_refs(raw) -> list[str]
    position(vc, cfg) -> (x, y, width, height, z)
"""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from typing import Any

from agentic_bi.layout_meta import decode_layout

_COMPARISON = {0: "=", 1: ">", 2: ">=", 3: "<>", 4: "<", 5: "<="}


def as_dict(value: Any) -> dict:
    """`value` when it is a dict, else an empty dict (untrusted layouts).

    A `.pbix` may serialize any node as a string, list or number; every helper
    that walks the layout needs a dict or nothing, never an exception.
    """
    return value if isinstance(value, dict) else {}


def load_layout(pbix: str | Path) -> dict:
    """Read and decode `Report/Layout` from a `.pbix`.

    A layout whose top level is not an object (a bare list or scalar) is
    untrusted and yields an empty mapping, so callers can walk it without a
    guard of their own.
    """
    with zipfile.ZipFile(pbix) as z:
        return as_dict(decode_layout(z.read("Report/Layout")))


def is_hidden(section: Any) -> bool:
    """Whether a page is hidden in reading view (and so has no screenshot).

    Only `hideInReadingView` marks a page as hidden. `displayOption` is **not** a
    hide marker: measured on the shipped donor, Desktop writes `1` for every
    ordinary page, while the framework's own engine writes `3` for pages it
    builds and that Desktop renders normally. Treating `3` as hidden (as an
    earlier implementation did) silently dropped every page of a
    framework-built board.
    """
    return bool(as_dict(section).get("hideInReadingView"))


def as_float(value: Any, default: float = 0.0) -> float:
    """Coerce a layout coordinate to float; a non-finite value gives `default`.

    `NaN`/`Infinity` (which `json.loads` accepts as bare tokens and `float()`
    accepts as strings) are rejected like any other unparsable value: they would
    otherwise render as `nan%` CSS and produce non-standard JSON downstream.
    """
    try:
        result = float(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def as_list(value: Any) -> list:
    """Coerce a layout field (list, or a JSON string of a list) to a list."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    return value if isinstance(value, list) else []


def _literal(value: Any) -> str:
    """Unwrap a DAX literal: a trailing `L` (long) and matching quotes go.

    A non-string value (`null`, a number) has no DAX text, so it becomes an
    empty string rather than the Python repr (`"None"`, `"5"`), which would
    otherwise leak into the filter/measure captions.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text.endswith("L") and text[:-1].lstrip("-").isdigit():
        text = text[:-1]
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text


def visual_title(cfg: Any) -> str:
    """Best-effort title from the visual's `objects`/`vcObjects` `title` slot.

    Power BI writes a visual's own title under `singleVisual.objects.title` (or
    `vcObjects.title` when it was set in the formatting pane); both are read.
    """
    sv = as_dict(as_dict(cfg).get("singleVisual"))
    for bucket in (
        sv.get("objects"),
        sv.get("vcObjects"),
        as_dict(cfg).get("vcObjects"),
    ):
        for item in as_list(as_dict(bucket).get("title")):
            try:
                value = item["properties"]["text"]["expr"]["Literal"]["Value"]
            except (KeyError, TypeError):
                continue
            text = _literal(value)
            if text:
                return text
    return ""


def projections(sv: Any) -> tuple[list[str], list[str]]:
    """Return (fields, measures) from the visual's prototype query selects.

    Three select shapes are recognised, in the order Power BI writes them:

    * `Measure` — a model measure reference;
    * `Aggregation` — a column aggregate (`Sum(Table.Col)`, `Avg(...)`); its
      display label is the aggregation, so it is reported as a field;
    * `Column` — a plain column.

    The label is `NativeReferenceName` when present (that is what Desktop shows),
    else the property/name. The `prototypeQuery` may be a dict or a JSON string;
    anything else yields empty lists.
    """
    fields: list[str] = []
    measures: list[str] = []
    pq = as_dict(sv).get("prototypeQuery")
    if isinstance(pq, str):
        try:
            pq = json.loads(pq)
        except (ValueError, TypeError):
            pq = {}
    for sel in as_dict(pq).get("Select") or []:
        if not isinstance(sel, dict):
            continue
        native = str(sel.get("NativeReferenceName") or "").strip()
        if isinstance(sel.get("Measure"), dict):
            name = str(sel["Measure"].get("Property") or "").strip()
            measures.append(native or name)
        elif isinstance(sel.get("Aggregation"), dict):
            agg = sel["Aggregation"]
            col = as_dict(as_dict(agg.get("Expression")).get("Column"))
            name = str(col.get("Property") or "").strip()
            label = native or (str(sel.get("Name") or "").strip() or name)
            fields.append(label)
        elif isinstance(sel.get("Column"), dict):
            name = str(sel["Column"].get("Property") or "").strip()
            fields.append(native or name)
    return fields, measures


def _filter_ref(flt: dict) -> str | None:
    """One human-readable filter reference, or None when it is unreadable."""
    entity = prop = None
    expression = as_dict(flt.get("expression"))
    for key in ("Column", "HierarchyLevel", "Measure"):
        node = expression.get(key)
        if isinstance(node, dict):
            entity = as_dict(as_dict(node.get("Expression")).get("SourceRef")).get(
                "Entity"
            )
            prop = node.get("Property")
            break
    if not prop:
        agg = as_dict(expression.get("Aggregation"))
        col = as_dict(as_dict(agg.get("Expression")).get("Column"))
        if col:
            entity = as_dict(as_dict(col.get("Expression")).get("SourceRef")).get(
                "Entity"
            )
            prop = col.get("Property")
    if not prop:
        return None
    ref = f"{entity}[{prop}]" if entity else str(prop)
    where = as_dict(flt.get("filter")).get("Where") or []
    if not isinstance(where, list):
        return ref
    parts: list[str] = []
    for cond in where:
        comparison = as_dict(as_dict(as_dict(cond).get("Condition")).get("Comparison"))
        left = as_dict(as_dict(comparison.get("Left")).get("Column")).get("Property")
        kind = comparison.get("ComparisonKind")
        op = _COMPARISON.get(kind, "?") if isinstance(kind, int) else "?"
        right = as_dict(comparison.get("Right"))
        if "Literal" in right:
            value = _literal(as_dict(right["Literal"]).get("Value"))
        elif "Column" in right:
            value = f"[{as_dict(right['Column']).get('Property') or '?'}]"
        else:
            value = "..."
        parts.append(f"{left or prop} {op} {value}")
    return f"{ref}: " + "; ".join(parts)


def filter_refs(raw: Any) -> list[str]:
    """Human-readable descriptions of a container's visual filters."""
    out: list[str] = []
    for flt in as_list(raw):
        if not isinstance(flt, dict):
            continue
        ref = _filter_ref(flt)
        if ref:
            out.append(ref)
    return out


def _numeric(value: Any) -> float | None:
    """A finite numeric coordinate as float, or None when absent/unparsable."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def position(vc: Any, cfg: Any) -> tuple[float, float, float, float, float]:
    """The visual's box: the config `layouts[0].position`, else the container.

    The config box wins only when *both* `x` and `y` are finite numbers; a
    malformed coordinate (`"abc"`, `null`, `nan`, a missing key) falls back to
    the container's box rather than silently producing a `0` origin, which would
    place the hotspot in the top-left corner. `width`/`height`/`z` fall back per
    value.
    """
    vc = as_dict(vc)
    container = (
        _numeric(vc.get("x")) or 0.0,
        _numeric(vc.get("y")) or 0.0,
        _numeric(vc.get("width")) or 0.0,
        _numeric(vc.get("height")) or 0.0,
    )
    layouts = as_dict(cfg).get("layouts")
    if isinstance(layouts, list) and layouts:
        pos = as_dict(as_dict(layouts[0]).get("position"))
        x, y = _numeric(pos.get("x")), _numeric(pos.get("y"))
        if x is not None and y is not None:
            return (
                x,
                y,
                _numeric(pos.get("width")) or container[2],
                _numeric(pos.get("height")) or container[3],
                _numeric(pos.get("z")) or 0.0,
            )
    return (*container, 0.0)


__all__ = [
    "as_dict",
    "as_float",
    "as_list",
    "filter_refs",
    "is_hidden",
    "load_layout",
    "position",
    "projections",
    "visual_title",
]
