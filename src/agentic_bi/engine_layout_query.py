"""Semantic-query building blocks for a from-scratch `.pbix` layout.

Power BI persists a visual's query in two places: `prototypeQuery` (legacy) inside
`singleVisual`, and a container-level `query` holding a
`SemanticQueryDataShapeCommand` (what current Desktop actually renders from).
Without the latter a data-bound visual renders blank.

This module builds both halves:

* the raw refs - `_col_ref`, `_agg_ref`, `_measure_ref`;
* the `Select` items and the queryRef each projection points at - `_col_item`,
  `_agg_item`, `_measure_item`;
* `_data_query`, which serializes the container-level command.

Aggregation codes/labels mirror the QOM `AggregationFunction` values.

Public API:
    _src() -> str
    _col_ref(src, prop) / _agg_ref(src, prop, agg) / _measure_ref(src, name)
    _col_item(src, table, name) / _agg_item(src, table, prop, agg)
    _measure_item(src, table, name)
    _data_query(single_visual) -> str | None
"""

from __future__ import annotations

import json

# QOM AggregationFunction codes and their display labels.
_AGG_FUNC = {
    "sum": 0,
    "avg": 1,
    "average": 1,
    "count": 2,
    "min": 3,
    "max": 4,
    "count_nonnull": 5,
    "median": 6,
    "stddev": 7,
    "var": 8,
}
_AGG_LABEL = {
    "sum": "Sum",
    "avg": "Avg",
    "average": "Avg",
    "min": "Min",
    "max": "Max",
    "count": "Count",
    "count_nonnull": "Count",
    "median": "Median",
    "stddev": "StDev",
    "var": "Var",
}


def _src() -> str:
    """The source alias inside a visual query (ASCII, safe for all encoders)."""
    return "t"


def _col_ref(src: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Source": src}}, "Property": prop}}


def _agg_ref(src: str, prop: str, agg: str) -> dict:
    return {
        "Aggregation": {
            "Expression": _col_ref(src, prop),
            "Function": _AGG_FUNC.get(agg.lower(), 0),
        }
    }


def _measure_ref(src: str, name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Source": src}}, "Property": name}}


def _col_item(src: str, table: str, name: str) -> tuple[dict, str]:
    """A `Column` select item; returns (item, queryRef)."""
    qref = f"{table}.{name}"
    return ({**_col_ref(src, name), "Name": qref, "NativeReferenceName": name}, qref)


def _agg_item(src: str, table: str, prop: str, agg: str) -> tuple[dict, str]:
    """An `Aggregation` select item; returns (item, queryRef)."""
    label = _AGG_LABEL.get(agg.lower(), "Sum")
    qref = f"{label}({table}.{prop})"
    return (
        {
            **_agg_ref(src, prop, agg),
            "Name": qref,
            "NativeReferenceName": f"{label} {prop}",
        },
        qref,
    )


def _measure_item(src: str, table: str, name: str) -> tuple[dict, str]:
    """A `Measure` select item; returns (item, queryRef)."""
    qref = f"{table}.{name}"
    return (
        {**_measure_ref(src, name), "Name": qref, "NativeReferenceName": name},
        qref,
    )


def _data_query(single_visual: dict) -> str | None:
    """Serialize the container-level semantic query newer Desktop needs to bind data.

    Power BI Desktop persists the visual query in two places: `prototypeQuery`
    inside `singleVisual` (legacy) and a container-level `query` holding a
    `SemanticQueryDataShapeCommand` (what current Desktop actually renders from).
    Without the latter a data-bound visual renders blank.
    """
    pq = single_visual.get("prototypeQuery")
    if not pq:
        return None
    projections = list(range(len(pq.get("Select", []))))
    return json.dumps(
        {
            "Commands": [
                {
                    "SemanticQueryDataShapeCommand": {
                        "Query": pq,
                        "Binding": {
                            "Primary": {
                                "Groupings": [
                                    {"Projections": projections, "Subtotal": 1}
                                ]
                            },
                            "DataReduction": {
                                "DataVolume": 3,
                                "Primary": {"Window": {"Count": 500}},
                            },
                            "Version": 1,
                        },
                        "ExecutionMetricsKind": 1,
                    }
                }
            ]
        },
        ensure_ascii=False,
    )
