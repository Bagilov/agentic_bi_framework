"""Visual container/config construction for the from-scratch .pbix layout.

Supported visual kinds (see `_VISUAL_TYPES`):
    table matrix card column bar line area pie donut funnel waterfall
    treemap stackedColumn stackedBar scatter gauge kpi slicer

Projection roles follow real Power BI `Report/Layout` conventions:
    cartesian / pie / funnel / waterfall : Category + Y (+ Series)
    treemap                              : Group + Values
    scatter                              : X + Y (+ Size)
    gauge                                : Y
    kpi                                  : Indicator + TrendLine
    table / card / slicer / matrix       : Values (matrix: Rows + Values)

The query primitives (`_col_ref`, `_agg_item`, `_data_query`, ...) live in
`engine_layout_query`; this module owns the `Visual` description, the kind table
and the container assembly.

Public API:
    Visual(kind, table, ...)                       - a visual description
    _VISUAL_TYPES                                  - kind -> QOM visualType
    _visual_config(v) -> dict                      - singleVisual config
    _container(v, x, y, w, h) -> dict              - a visualContainer
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from agentic_bi.engine_layout_query import (
    _agg_item,
    _col_item,
    _col_ref,
    _data_query,
    _measure_item,
    _src,
    dax_literal,
)

logger = logging.getLogger(__name__)

# kind -> QOM visualType
_VISUAL_TYPES = {
    "table": "tableEx",
    "matrix": "pivotTable",
    "card": "card",
    "column": "columnChart",
    "bar": "barChart",
    "line": "lineChart",
    "area": "areaChart",
    "pie": "pieChart",
    "donut": "donutChart",
    "treemap": "treemap",
    "funnel": "funnel",
    "waterfall": "waterfallChart",
    "stackedColumn": "stackedColumnChart",
    "stackedBar": "stackedBarChart",
    "scatter": "scatterChart",
    "gauge": "gauge",
    "kpi": "kpi",
    "slicer": "slicer",
}

# category charts that accept an optional Series breakdown
_SERIES_CHARTS = {"stackedColumn", "stackedBar"}

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
for _kind in (
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
    _REQUIRED[_kind] = (("axis",), ("measure", "value"))


@dataclass
class Visual:
    """A single visual on a page.

    kind    - one of `_VISUAL_TYPES` (table/matrix/card/column/bar/line/area/
              pie/donut/funnel/waterfall/treemap/stackedColumn/stackedBar/
              scatter/gauge/kpi/slicer)
    table   - the model table name
    columns - a list of columns (table; for matrix - the row hierarchy)
    axis    - the category/axis column (charts), the group column (treemap),
              or the slicer field
    value   - the value column (charts/matrix/gauge/kpi); aggregated by `agg`
    agg     - the value aggregation
    measure - an existing model measure to use as the value instead of
              `value`+`agg` (charts/card/gauge/kpi/matrix/treemap)
    x/y/size- scatter measures (X, Y, bubble Size); aggregated by `agg`
    trend   - KPI trend-axis column
    series  - optional Series breakdown column (stacked charts)
    title   - an optional title
    pos     - an optional position (x, y, w, h)
    """

    kind: str
    table: str
    columns: list[str] = field(default_factory=list)
    axis: str | None = None
    value: str | None = None
    agg: str = "sum"
    measure: str | None = None
    x: str | None = None
    y: str | None = None
    size: str | None = None
    trend: str | None = None
    series: str | None = None
    title: str | None = None
    pos: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if self.kind not in _VISUAL_TYPES:
            raise ValueError(f"unknown visual kind: {self.kind}")
        for group in _REQUIRED.get(self.kind, ()):
            if not any(getattr(self, f) for f in group):
                raise ValueError(
                    f"visual '{self.kind}' requires one of: {', '.join(group)}"
                )


def _visual_config(v: Visual) -> dict:
    """Assemble the config of one visualContainer from a Visual description.

    It always builds `projections` - without them Power BI does not bind the
    fields and the visual renders empty.
    """
    src = _src()
    select: list[dict] = []
    order: list[dict] = []
    projections: dict[str, list[dict]] = {}

    def add_column(name: str) -> str:
        item, qref = _col_item(src, v.table, name)
        select.append(item)
        return qref

    def add_agg(prop: str) -> str:
        item, qref = _agg_item(src, v.table, prop, v.agg)
        select.append(item)
        return qref

    def add_measure(name: str) -> str:
        item, qref = _measure_item(src, v.table, name)
        select.append(item)
        return qref

    def add_value() -> str:
        """The value role: an explicit measure, else `value` aggregated by `agg`."""
        if v.measure:
            return add_measure(v.measure)
        return add_agg(v.value)

    if v.kind == "table":
        projections["Values"] = [{"queryRef": add_column(n)} for n in v.columns]
    elif v.kind == "card":
        projections["Values"] = [{"queryRef": add_value()}]
    elif v.kind == "gauge":
        projections["Y"] = [{"queryRef": add_value()}]
    elif v.kind == "kpi":
        projections["Indicator"] = [{"queryRef": add_value()}]
        if v.trend:
            projections["TrendLine"] = [{"queryRef": add_column(v.trend)}]
    elif v.kind == "slicer":
        qref = add_column(v.axis)
        projections["Values"] = [{"queryRef": qref, "active": True}]
        order.append({"Direction": 1, "Expression": _col_ref(src, v.axis)})
    elif v.kind == "matrix":
        row_refs = []
        for d in v.columns:
            dref = add_column(d)
            row_refs.append({"queryRef": dref})
            order.append({"Direction": 1, "Expression": _col_ref(src, d)})
        projections["Rows"] = row_refs
        if v.value:
            projections["Values"] = [{"queryRef": add_value()}]
    elif v.kind == "treemap":
        projections["Group"] = [{"queryRef": add_column(v.axis)}]
        projections["Values"] = [{"queryRef": add_value()}]
    elif v.kind == "scatter":
        projections["X"] = [{"queryRef": add_agg(v.x or v.value)}]
        projections["Y"] = [{"queryRef": add_agg(v.y or v.axis)}]
        if v.size:
            projections["Size"] = [{"queryRef": add_agg(v.size)}]
    else:  # category charts (incl. stacked with optional Series)
        axis_ref = add_column(v.axis)
        val_ref = add_value()
        order.append({"Direction": 1, "Expression": _col_ref(src, v.axis)})
        projections["Category"] = [{"queryRef": axis_ref}]
        projections["Y"] = [{"queryRef": val_ref}]
        if v.series and v.kind in _SERIES_CHARTS:
            projections["Series"] = [{"queryRef": add_column(v.series)}]

    objects = {}
    if v.title:
        objects["title"] = [
            {
                "properties": {
                    "text": {"expr": {"Literal": {"Value": dax_literal(v.title)}}}
                }
            }
        ]
    if v.kind == "slicer":
        objects["data"] = [
            {"properties": {"mode": {"expr": {"Literal": {"Value": "'Dropdown'"}}}}}
        ]
    if v.kind == "matrix":
        objects["rowHeaders"] = [
            {
                "properties": {
                    "stepped": {"expr": {"Literal": {"Value": "true"}}},
                    "steppedLayoutIndentation": {"expr": {"Literal": {"Value": "15D"}}},
                }
            }
        ]

    return {
        "name": str(uuid.uuid4()),
        "layouts": [
            {
                "id": 0,
                "position": {"x": 20, "y": 20, "z": 0, "width": 600, "height": 400},
            }
        ],
        "singleVisual": {
            "visualType": _VISUAL_TYPES[v.kind],
            "projections": projections,
            "prototypeQuery": {
                "Version": 2,
                "From": [{"Name": src, "Entity": v.table, "Type": 0}],
                "Select": select,
                **({"OrderBy": order} if order else {}),
            },
            "drillFilterOtherVisuals": True,
            "objects": objects,
            "vcObjects": {},
        },
        "howCreated": "manual",
    }


def _container(v: Visual, x: int, y: int, w: int, h: int) -> dict:
    """Wrap the visual config into a positioned `visualContainer`."""
    cfg = _visual_config(v)
    for lay in cfg.get("layouts", []):
        lay["position"] = {
            "x": x,
            "y": y,
            "z": 0,
            "width": w,
            "height": h,
            "tabOrder": 0,
        }
        break
    container = {
        "x": x,
        "y": y,
        "z": 0,
        "width": w,
        "height": h,
        "config": json.dumps(cfg, ensure_ascii=False),
        "filters": "[]",
    }
    query = _data_query(cfg.get("singleVisual", {}))
    if query is not None:
        container["query"] = query
        container["dataTransforms"] = "[]"
    return container
