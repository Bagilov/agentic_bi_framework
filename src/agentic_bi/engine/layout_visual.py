"""Visual container/config construction for the from-scratch .pbix layout.

Supported visual kinds (see `_VISUAL_TYPES`):
    table matrix card column bar line area pie donut funnel waterfall
    treemap stackedColumn stackedBar scatter gauge kpi slicer

Projection roles follow real Power BI `Report/Layout` conventions:
    cartesian / pie / funnel / waterfall : Category + Y (+ optional Series)
    treemap                              : Group + Values
    scatter                              : X + Y (+ Size)
    gauge / kpi                          : Y / Indicator (+ TrendLine)
    table / card / slicer / matrix       : Values (matrix: Rows + Values)

The query primitives live in `engine_layout_query`, the kind/role catalogue in
`engine_layout_catalog`; this module owns the `Visual` description and the
container assembly. Public API:
`Visual(kind, table, ...)`, `_VISUAL_TYPES`, `_visual_config(v)`,
`_container(v, x, y, w, h)`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from agentic_bi.engine.layout_catalog import (
    _EXTRA_VALUE_KINDS,
    _REQUIRED,
    _SERIES_KINDS,
    _VISUAL_TYPES,
)
from agentic_bi.engine.layout_query import (
    _agg_item,
    _col_item,
    _col_ref,
    _data_query,
    _measure_item,
    _src,
    dax_literal,
    stable_id,
)

logger = logging.getLogger(__name__)


@dataclass
class Visual:
    """A single visual on a page.

    kind    - one of `_VISUAL_TYPES`
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
    series  - optional Series breakdown column (see `_SERIES_KINDS`)
    extra_values - extra value columns on the Y role (see `_EXTRA_VALUE_KINDS`)
    title   - an optional title (a container object: `vcObjects.title`)
    description - optional subtitle rendered under the title
    tooltip - optional tooltip text (`objects.visualTooltip`)
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
    description: str | None = None
    tooltip: str | None = None
    extra_values: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in _VISUAL_TYPES:
            raise ValueError(f"unknown visual kind: {self.kind}")
        for group in _REQUIRED.get(self.kind, ()):
            if not any(getattr(self, f) for f in group):
                raise ValueError(
                    f"visual '{self.kind}' requires one of: {', '.join(group)}"
                )
        if self.series and self.kind not in _SERIES_KINDS:
            # Dropping it would build a chart whose legend silently disappears.
            raise ValueError(
                f"visual '{self.kind}' has no Series role; "
                f"kind must be one of: {', '.join(sorted(_SERIES_KINDS))}"
            )
        if self.extra_values and self.kind not in _EXTRA_VALUE_KINDS:
            # A second Y value on a pie/donut/card has no meaning; silently
            # dropping it would produce a visual that ignores a declared field.
            raise ValueError(
                f"visual '{self.kind}' has no multi-value Y role; "
                f"kind must be one of: {', '.join(sorted(_EXTRA_VALUE_KINDS))}"
            )


def _required(value: str | None, kind: str, field: str) -> str:
    """Narrow a required column to `str`, failing loudly when it is missing.

    `Visual` is a mutable dataclass: `__post_init__` validates the initial
    state, but a field can be cleared afterwards. Returning `str | None` into
    the query builders used to be a mypy-only complaint, yet at runtime a
    `None` produced `Sum(table.None)`/a dropped projection - a visual that
    renders blank with no diagnostic. Raising keeps the failure next to the
    descriptor that caused it.
    """
    if not value:
        raise ValueError(f"visual '{kind}': {field} column is missing")
    return value


def _visual_config(v: Visual) -> dict:
    """Assemble the config of one visualContainer from a Visual description.

    It always builds `projections` - without them Power BI does not bind the
    fields and the visual renders empty. A required field that is `None` raises
    `ValueError` instead of producing a silently partial visual.
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
        return add_agg(_required(v.value, v.kind, "value"))

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
        axis = _required(v.axis, v.kind, "axis")
        projections["Values"] = [{"queryRef": add_column(axis), "active": True}]
        order.append({"Direction": 1, "Expression": _col_ref(src, axis)})
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
        axis = _required(v.axis, v.kind, "group")
        projections["Group"] = [{"queryRef": add_column(axis)}]
        projections["Values"] = [{"queryRef": add_value()}]
    elif v.kind == "scatter":
        x_col = _required(v.x or v.value, v.kind, "x")
        y_col = _required(v.y or v.axis, v.kind, "y")
        projections["X"] = [{"queryRef": add_agg(x_col)}]
        projections["Y"] = [{"queryRef": add_agg(y_col)}]
        if v.size:
            projections["Size"] = [{"queryRef": add_agg(v.size)}]
    else:  # category charts (incl. stacked with optional Series)
        axis = _required(v.axis, v.kind, "category")
        axis_ref = add_column(axis)
        val_ref = add_value()
        order.append({"Direction": 1, "Expression": _col_ref(src, axis)})
        projections["Category"] = [{"queryRef": axis_ref}]
        y_refs = [{"queryRef": val_ref}]
        y_refs.extend({"queryRef": add_agg(extra)} for extra in v.extra_values)
        projections["Y"] = y_refs
        if v.series:  # `__post_init__` guarantees the kind supports Series
            projections["Series"] = [{"queryRef": add_column(v.series)}]

    objects: dict[str, list[dict]] = {}
    vc_objects: dict[str, list[dict]] = {}
    if v.title:
        # A title is a *container* object: Desktop ignores `objects.title` and
        # draws an automatic title from the field name instead (measured on the
        # guest), so the text has to live in `singleVisual.vcObjects`.
        title_props: dict[str, dict] = {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "text": {"expr": {"Literal": {"Value": dax_literal(v.title)}}},
        }
        if v.description:
            title_props["subTitle"] = {
                "expr": {"Literal": {"Value": dax_literal(v.description)}}
            }
        vc_objects["title"] = [{"properties": title_props}]
    if v.tooltip:
        objects["visualTooltip"] = [
            {
                "properties": {
                    "type": {"expr": {"Literal": {"Value": "'Default'"}}},
                    "text": {"expr": {"Literal": {"Value": dax_literal(v.tooltip)}}},
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
        # The real name is a content hash assigned by `_container` once the
        # position is known, so the same design always yields the same layout.
        "name": "",
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
            "vcObjects": vc_objects,
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
    _, cfg["name"] = stable_id(json.dumps(cfg, sort_keys=True, ensure_ascii=False))
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
