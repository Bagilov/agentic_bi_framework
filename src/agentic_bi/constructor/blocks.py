"""Catalogue of constructor blocks: a block is one declarative visual.

The constructor never decides what belongs on a page. An agent passes a `kind`
and its fields, and `make_visual` turns the block into an
`engine.layout_visual.Visual` deterministically. The catalogue is data, so the
same table answers three questions: which kinds exist, which fields each kind
requires, and how wide a block sits by default.

Power BI's own visualType names are accepted on input as aliases
(`tableEx`, `pivotTable`, `columnChart`, ...), so a block list copied from a
`Report/Layout` still compiles.

Public API:
    AGGREGATIONS, ALIASES, BLOCKS, BlockSpec
    resolve_kind(kind) -> str
    catalog() -> list[dict]
    make_visual(block) -> Visual
"""

# Size exception (>300 lines): this module is a data table (one entry per block
# kind with its required/optional fields and aliases), not logic. Splitting it
# would scatter one catalogue across files and make a kind's contract harder to
# read in one place.

from __future__ import annotations

from dataclasses import dataclass

from agentic_bi.constructor.model import norm_pos
from agentic_bi.engine.layout_catalog import _VISUAL_TYPES
from agentic_bi.engine.layout_visual import Visual

AGGREGATIONS = (
    "sum",
    "avg",
    "average",
    "min",
    "max",
    "count",
    "count_nonnull",
    "median",
    "stddev",
    "var",
)


@dataclass(frozen=True)
class BlockSpec:
    """One block kind: its engine visual type and the fields it accepts."""

    kind: str
    visual_type: str
    description: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    default_span: int = 1


BLOCKS: dict[str, BlockSpec] = {
    "card": BlockSpec(
        "card",
        _VISUAL_TYPES["card"],
        "KPI card: a measure, or one aggregated column",
        required=("table",),
        optional=(
            "measure",
            "value",
            "agg",
            "title",
            "description",
            "tooltip",
            "pos",
            "span",
        ),
    ),
    "table": BlockSpec(
        "table",
        _VISUAL_TYPES["table"],
        "Table: a list of columns and measures",
        required=("table", "columns"),
        optional=("title", "description", "tooltip", "pos", "span"),
        default_span=2,
    ),
    "matrix": BlockSpec(
        "matrix",
        _VISUAL_TYPES["matrix"],
        "Matrix/pivot: a row hierarchy plus a value",
        required=("table", "columns"),
        optional=(
            "value",
            "agg",
            "measure",
            "title",
            "description",
            "tooltip",
            "pos",
            "span",
        ),
        default_span=2,
    ),
    "column": BlockSpec(
        "column",
        _VISUAL_TYPES["column"],
        "Column chart: category plus one or more values",
        required=("table", "axis"),
        optional=(
            "value",
            "measure",
            "agg",
            "extra_values",
            "title",
            "description",
            "tooltip",
            "pos",
            "span",
        ),
    ),
    "bar": BlockSpec(
        "bar",
        _VISUAL_TYPES["bar"],
        "Bar chart: category plus one or more values",
        required=("table", "axis"),
        optional=(
            "value",
            "measure",
            "agg",
            "extra_values",
            "title",
            "description",
            "tooltip",
            "pos",
            "span",
        ),
    ),
    "line": BlockSpec(
        "line",
        _VISUAL_TYPES["line"],
        "Line chart: category plus one or more values",
        required=("table", "axis"),
        optional=(
            "value",
            "measure",
            "agg",
            "extra_values",
            "title",
            "description",
            "tooltip",
            "pos",
            "span",
        ),
    ),
    "pie": BlockSpec(
        "pie",
        _VISUAL_TYPES["pie"],
        "Pie chart: category plus a value",
        required=("table", "axis"),
        optional=(
            "value",
            "measure",
            "agg",
            "title",
            "description",
            "tooltip",
            "pos",
            "span",
        ),
    ),
    "donut": BlockSpec(
        "donut",
        _VISUAL_TYPES["donut"],
        "Donut chart: category plus a value",
        required=("table", "axis"),
        optional=(
            "value",
            "measure",
            "agg",
            "title",
            "description",
            "tooltip",
            "pos",
            "span",
        ),
    ),
    "slicer": BlockSpec(
        "slicer",
        _VISUAL_TYPES["slicer"],
        "Slicer (dropdown) over one column",
        required=("table", "axis"),
        optional=("title", "description", "tooltip", "pos", "span"),
    ),
}

ALIASES: dict[str, str] = {
    "kpi": "card",
    "cardVisual": "card",
    "tableEx": "table",
    "pivotTable": "matrix",
    "columnChart": "column",
    "clusteredColumnChart": "column",
    "barChart": "bar",
    "clusteredBarChart": "bar",
    "lineChart": "line",
    "pieChart": "pie",
    "donutChart": "donut",
}


def resolve_kind(kind: str) -> str:
    """Return the canonical block name for `kind` or a Power BI alias.

    Raises:
        ValueError: when the name is not a known block or alias.
    """
    key = (kind or "").strip()
    key = ALIASES.get(key, key)
    if key not in BLOCKS:
        raise ValueError(f"unknown block kind: {kind!r}; available: {sorted(BLOCKS)}")
    return key


def catalog() -> list[dict[str, object]]:
    """Return the machine-readable block catalogue (for an agent or `--catalog`)."""
    return [
        {
            "kind": b.kind,
            "visual_type": b.visual_type,
            "description": b.description,
            "required": list(b.required),
            "optional": list(b.optional),
            "default_span": b.default_span,
        }
        for b in BLOCKS.values()
    ]


def _names(block: dict[str, object], field: str, kind: str) -> list[str]:
    """Read a list-of-names field; a bare string is an error, not characters."""
    raw = block.get(field)
    if raw in (None, ""):
        return []
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise ValueError(f"{kind}: {field} must be a list of names")
    return [str(item) for item in raw]


def make_visual(block: dict[str, object]) -> Visual:
    """Turn one declarative block into an `engine.layout_visual.Visual`.

    Args:
        block: the block object (`kind`, `table`, `columns`/`axis`/`value`, ...).

    Raises:
        ValueError: unknown `kind`, malformed `pos`, or an unsupported `agg`.
    """
    kind = resolve_kind(str(block.get("kind") or ""))
    position = norm_pos(block.get("pos"), kind)
    agg = str(block.get("agg") or "sum").lower()
    if agg not in AGGREGATIONS:
        raise ValueError(f"{kind}: unsupported agg {agg!r}")
    axis = block.get("axis")
    value = block.get("value")
    measure = block.get("measure")
    title = block.get("title")
    description = block.get("description")
    tooltip = block.get("tooltip")
    return Visual(
        kind=kind,
        table=str(block.get("table") or ""),
        columns=_names(block, "columns", kind),
        axis=None if axis is None else str(axis),
        value=None if value is None else str(value),
        agg=agg,
        title=None if title is None else str(title),
        description=None if description is None else str(description),
        tooltip=None if tooltip is None else str(tooltip),
        pos=position,
        measure=None if measure is None else str(measure),
        extra_values=_names(block, "extra_values", kind),
    )


__all__ = [
    "AGGREGATIONS",
    "ALIASES",
    "BLOCKS",
    "BlockSpec",
    "catalog",
    "make_visual",
    "resolve_kind",
]
