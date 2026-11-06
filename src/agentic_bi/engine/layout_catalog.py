"""Catalogue for `engine.layout_visual`: kinds, Series support and required inputs.

Kept apart from the visual builder so `layout_visual` stays within the file-size
budget. The kind table is data, not logic, and `_REQUIRED` documents per kind
which fields a visual must carry before it is assembled.

Public API (re-exported by `engine.layout_visual`):
    _VISUAL_TYPES   - kind -> QOM visualType
    _SERIES_KINDS   - kinds whose projections accept a `Series` role
    _REQUIRED       - kind -> groups of required attributes (one per group)
"""

from __future__ import annotations

# kind -> QOM visualType. The names follow Power BI's own catalogue, which is
# not the obvious one: a plain "column" kind is the *clustered* column
# (`clusteredColumnChart`) and a stacked column is `columnChart`; bars split the
# same way (`bar` -> `clusteredBarChart`, `stackedBar` -> `barChart`). There is no
# `stackedColumnChart`/`stackedBarChart`: Desktop treats those as an uninstalled
# custom visual (measured on the guest: 1 visual error for each invented name).
_VISUAL_TYPES = {
    "table": "tableEx",
    "matrix": "pivotTable",
    "card": "card",
    "column": "clusteredColumnChart",
    "bar": "clusteredBarChart",
    "line": "lineChart",
    "area": "areaChart",
    "pie": "pieChart",
    "donut": "donutChart",
    "treemap": "treemap",
    "funnel": "funnel",
    "waterfall": "waterfallChart",
    "stackedColumn": "columnChart",
    "stackedBar": "barChart",
    "scatter": "scatterChart",
    "gauge": "gauge",
    "kpi": "kpi",
    "slicer": "slicer",
}

# Kinds whose projections can carry a `Series` (legend) role. Clustered columns
# and bars support a legend in Desktop just like the stacked ones, so `series`
# is honoured for them instead of being dropped silently.
_SERIES_KINDS = frozenset(
    {"column", "bar", "stackedColumn", "stackedBar", "line", "area", "pie", "donut"}
)

# Per-kind required inputs, checked in `Visual.__post_init__`. Each entry is a
# *group*: the visual needs at least one of the listed attributes. Checking here
# (not at render time) rejects a half-built visual before it reaches the layout,
# where a missing input silently becomes `Sum(table.None)` and renders blank.
_REQUIRED: dict[str, tuple[tuple[str, ...], ...]] = {
    "table": (("columns",),),
    "matrix": (("columns",),),
    "card": (("measure", "value"),),
    "gauge": (("measure", "value"),),
    "kpi": (("measure", "value"),),
    "slicer": (("axis",),),
    "treemap": (("axis",), ("measure", "value")),
    "scatter": (("x", "value"), ("y", "axis")),
}
# category charts (column/bar/line/area/pie/donut/funnel/waterfall/stacked*)
for _category_kind in (
    "column",
    "bar",
    "line",
    "area",
    "pie",
    "donut",
    "funnel",
    "waterfall",
    "stackedColumn",
    "stackedBar",
):
    _REQUIRED[_category_kind] = (("axis",), ("measure", "value"))
