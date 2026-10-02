"""Visual container/config construction for the from-scratch .pbix layout."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_VISUAL_TYPES = {
    "table": "tableEx",
    "matrix": "pivotTable",
    "card": "card",
    "column": "columnChart",
    "bar": "barChart",
    "line": "lineChart",
    "pie": "pieChart",
    "donut": "donutChart",
    "slicer": "slicer",
}

_AGG_FUNC = {"sum": 0, "avg": 1, "average": 1, "min": 2, "max": 3, "count": 4,
             "count_nonnull": 5, "median": 6, "stddev": 7, "var": 8}
_AGG_LABEL = {"sum": "Sum", "avg": "Avg", "average": "Avg", "min": "Min",
              "max": "Max", "count": "Count", "count_nonnull": "Count",
              "median": "Median", "stddev": "StDev", "var": "Var"}


@dataclass
class Visual:
    """A single visual on a page.

    kind    - table/matrix/card/column/bar/line/pie/donut/slicer
    table   - the model table name
    columns - a list of columns (table; for matrix - the row hierarchy)
    axis    - the category/axis column (charts) or the slicer field (slicer)
    value   - the value column (charts/matrix); aggregated by `agg`
    agg     - the value aggregation
    title   - an optional title
    pos     - an optional position (x, y, w, h)
    """

    kind: str
    table: str
    columns: list[str] = field(default_factory=list)
    axis: str | None = None
    value: str | None = None
    agg: str = "sum"
    title: str | None = None
    pos: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if self.kind not in _VISUAL_TYPES:
            raise ValueError(f"unknown visual kind: {self.kind}")


def _src() -> str:
    """The source alias inside a visual query (ASCII, safe for all encoders)."""
    return "t"


def _col_ref(src: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Source": src}},
                       "Property": prop}}


def _agg_ref(src: str, prop: str, agg: str) -> dict:
    return {"Aggregation": {"Expression": _col_ref(src, prop),
                            "Function": _AGG_FUNC.get(agg.lower(), 0)}}


def _visual_config(v: Visual) -> dict:
    """Assemble the config of one visualContainer from a Visual description.

    It always builds `projections` - without them Power BI does not bind the
    fields and the visual renders empty.
    """
    src = _src()
    select: list[dict] = []
    order: list[dict] = []
    projections: dict[str, list[dict]] = {}

    if v.kind == "table":
        refs = []
        for name in v.columns:
            qref = f"{v.table}.{name}"
            select.append({**_col_ref(src, name), "Name": qref,
                           "NativeReferenceName": name})
            refs.append({"queryRef": qref})
        projections["Values"] = refs
    elif v.kind == "card":
        agg_label = _AGG_LABEL.get(v.agg.lower(), "Sum")
        qref = f"{agg_label}({v.table}.{v.value})"
        select.append({**_agg_ref(src, v.value, v.agg), "Name": qref,
                       "NativeReferenceName": f"{agg_label} {v.value}"})
        projections["Values"] = [{"queryRef": qref}]
    elif v.kind == "slicer":
        order.append({"Direction": 1, "Expression": _col_ref(src, v.axis)})
        projections["Values"] = [
            {"queryRef": f"{v.table}.{v.axis}", "active": True}]
        select.append({**_col_ref(src, v.axis), "Name": f"{v.table}.{v.axis}",
                       "NativeReferenceName": v.axis})
    elif v.kind == "matrix":
        agg_label = _AGG_LABEL.get(v.agg.lower(), "Sum")
        row_refs = []
        for d in v.columns:
            dref = f"{v.table}.{d}"
            select.append({**_col_ref(src, d), "Name": dref,
                           "NativeReferenceName": d})
            row_refs.append({"queryRef": dref})
            order.append({"Direction": 1, "Expression": _col_ref(src, d)})
        projections["Rows"] = row_refs
        if v.value:
            val_ref = f"{agg_label}({v.table}.{v.value})"
            select.append({**_agg_ref(src, v.value, v.agg), "Name": val_ref,
                           "NativeReferenceName": f"{agg_label} {v.value}"})
            projections["Values"] = [{"queryRef": val_ref}]
    else:  # charts: category + aggregated value
        axis_ref = f"{v.table}.{v.axis}"
        select.append({**_col_ref(src, v.axis), "Name": axis_ref,
                       "NativeReferenceName": v.axis})
        agg_label = _AGG_LABEL.get(v.agg.lower(), "Sum")
        val_ref = f"{agg_label}({v.table}.{v.value})"
        select.append({**_agg_ref(src, v.value, v.agg), "Name": val_ref,
                       "NativeReferenceName": f"{agg_label} {v.value}"})
        order.append({"Direction": 1, "Expression": _col_ref(src, v.axis)})
        projections["Category"] = [{"queryRef": axis_ref}]
        projections["Y"] = [{"queryRef": val_ref}]

    objects = {}
    if v.title:
        objects["title"] = [{"properties": {"text": {"expr":
            {"Literal": {"Value": f"'{v.title}'"}}}}}]
    if v.kind == "slicer":
        objects["data"] = [{"properties": {"mode": {"expr":
            {"Literal": {"Value": "'Dropdown'"}}}}}]
    if v.kind == "matrix":
        objects["rowHeaders"] = [{"properties": {
            "stepped": {"expr": {"Literal": {"Value": "true"}}},
            "steppedLayoutIndentation": {"expr": {"Literal": {"Value": "15D"}}},
        }}]

    return {
        "name": str(uuid.uuid4()),
        "layouts": [{"id": 0, "position": {"x": 20, "y": 20, "z": 0,
                                           "width": 600, "height": 400}}],
        "singleVisual": {
            "visualType": _VISUAL_TYPES[v.kind],
            "projections": projections,
            "prototypeQuery": {"Version": 2,
                               "From": [{"Name": src, "Entity": v.table, "Type": 0}],
                               "Select": select,
                               **({"OrderBy": order} if order else {})},
            "drillFilterOtherVisuals": True,
            "objects": objects,
            "vcObjects": {},
        },
        "howCreated": "manual",
    }


def _container(v: Visual, x: int, y: int, w: int, h: int) -> dict:
    cfg = _visual_config(v)
    for lay in cfg.get("layouts", []):
        lay["position"] = {"x": x, "y": y, "z": 0, "width": w, "height": h}
        break
    return {"x": x, "y": y, "z": 0, "width": w, "height": h,
            "config": json.dumps(cfg, ensure_ascii=False),
            "filters": "[]"}


