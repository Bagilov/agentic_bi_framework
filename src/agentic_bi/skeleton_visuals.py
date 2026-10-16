"""Visual and filter builders for the PBIP skeleton (format verified on real .pbix)."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Function in Select for columns (from a real layout): 0=None, 4=min (donor uses 4)
COL_AGG_FUNCTION = 4


def _source_ref(source: str, entity: str) -> dict:
    return {"SourceRef": {"Source": source, "Entity": entity}}


def page_filter(column: str, table: str, source: str = "m") -> dict:
    """Page-level Categorical filter on a column (a slicer in the filter pane).

    howCreated=1 -> "added manually" (visible as a filter on the page).
    """
    filtered = f"FilterAuto_{hash(column) & 0xFFFFFFFF:08x}"
    return {
        "name": filtered,
        "expression": {
            "Column": {
                "Expression": _source_ref(source, table),
                "Property": column,
            }
        },
        "type": "Categorical",
        "howCreated": 1,
        "isHiddenInViewMode": False,
        "objects": {},
    }


# ─── visuals ───────────────────────────────────────────────


def _query_item(
    pq_query,
    table: str,
    source: str,
    measure_table: str | None = None,
    measure_alias: str | None = None,
):
    """Build the Select item and queryRef for a prototypeQuery.

    measure_table/measure_alias: if set, measures reference ANOTHER table (e.g. a
    dedicated measures table in the donor) while columns reference the main one.
    By default measures come from the same table as columns.

    pq_query — a field description: {"kind":"measure"|"column","property":...,
                                      "agg":bool, "display":"..."}
    Returns (select_item, query_ref, is_measure).

    Format verified against a real .pbix (donor):
      - measure                 -> {"Measure": {"Property": prop}}
      - column with aggregation -> {"Aggregation": {"Column":{...}, "Function": N}}
      - column WITHOUT agg      -> {"Column": {"Property": prop}}
    queryRef: "table.prop" for a column, "Sum(table.prop)" for Aggregation.
    """
    prop = pq_query["property"]
    display = pq_query.get("display", prop)
    kind = pq_query.get("kind", "column")
    agg = bool(pq_query.get("agg", False))

    m_table = measure_table if kind == "measure" and measure_table else table
    m_source = measure_alias if kind == "measure" and measure_alias else source

    if kind == "measure":
        item = {
            "Measure": {"Expression": _source_ref(m_source, m_table)},
            "Name": f"{m_table}.{prop}",
            "NativeReferenceName": display,
        }
        item["Measure"]["Property"] = prop
        return item, f"{m_table}.{prop}", True

    if agg:
        # value column with aggregation (as in the donor: Function=0)
        item = {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": _source_ref(source, table),
                        "Property": prop,
                    }
                },
                "Function": pq_query.get("aggFunction", COL_AGG_FUNCTION),
            },
            "Name": f"Sum({table}.{prop})",
            "NativeReferenceName": display,
        }
        return item, f"Sum({table}.{prop})", False

    # column without aggregation (category/date axis, series)
    item = {
        "Column": {"Expression": _source_ref(source, table)},
        "Name": f"{table}.{prop}",
        "NativeReferenceName": display,
    }
    item["Column"]["Property"] = prop
    return item, f"{table}.{prop}", False


def card_visual(
    query: dict,
    table: str,
    source: str = "m",
    x: int = 20,
    y: int = 20,
    w: int = 240,
    h: int = 120,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """KPI card: a single measure."""
    item, qref, _ = _query_item(query, table, source, measure_table, measure_alias)
    _from = [{"Name": source, "Entity": table, "Type": 0}]
    if measure_alias:
        _from.append({"Name": measure_alias, "Entity": measure_table, "Type": 0})
    single = {
        "visualType": "card",
        "projections": {"Values": [{"queryRef": qref}]},
        "prototypeQuery": {
            "Version": 2,
            "From": _from,
            "Select": [item],
            "OrderBy": [
                {
                    "Direction": 1,
                    "Expression": {
                        "Measure"
                        if query.get("kind") == "measure"
                        else "Aggregation": item.get("Measure")
                        or item.get("Aggregation")
                    },
                }
            ],
        },
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "objects": {
            "labels": [
                {
                    "properties": {
                        "fontSize": {"expr": {"Literal": {"Value": "1A"}}},
                        "fontFamily": {
                            "expr": {
                                "Literal": {
                                    "Value": "''Segoe UI'', wf_segoe-ui_normal, helvetica, arial, sans-serif'"
                                }
                            }
                        },
                    }
                }
            ]
        },
    }
    return {
        "config": json.dumps(
            {
                "name": f"KPI_{query['property']}",
                "layouts": [
                    {
                        "id": 0,
                        "position": {"x": x, "y": y, "width": w, "height": h, "z": 0},
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def chart_visual(
    visual_type: str,
    axis: dict,
    value: dict,
    table: str,
    source: str = "m",
    x: int = 20,
    y: int = 160,
    w: int = 620,
    h: int = 320,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """Chart (lineChart/clusteredColumnChart): axis (column) + value (measure or agg column)."""
    ax_item, ax_ref, _ = _query_item(axis, table, source, measure_table, measure_alias)
    val_item, val_ref, _ = _query_item(
        value, table, source, measure_table, measure_alias
    )
    _from = [{"Name": source, "Entity": table, "Type": 0}]
    if measure_alias:
        _from.append({"Name": measure_alias, "Entity": measure_table, "Type": 0})
    single = {
        "visualType": visual_type,
        "projections": {
            "Values": [{"queryRef": val_ref}],
            "Category": [{"queryRef": ax_ref}],
        },
        "prototypeQuery": {
            "Version": 2,
            "From": _from,
            "Select": [ax_item, val_item],
        },
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "objects": {},
    }
    return {
        "config": json.dumps(
            {
                "name": f"Chart_{visual_type}",
                "layouts": [
                    {
                        "id": 0,
                        "position": {"x": x, "y": y, "width": w, "height": h, "z": 0},
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def table_visual(
    fields: list[dict],
    table: str,
    source: str = "m",
    x: int = 20,
    y: int = 520,
    w: int = 1240,
    h: int = 240,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """Table: a list of fields (column/measure)."""
    selects = []
    qrefs = []
    for f in fields:
        it, qref, _ = _query_item(f, table, source, measure_table, measure_alias)
        selects.append(it)
        qrefs.append({"queryRef": qref})
    _from = [{"Name": source, "Entity": table, "Type": 0}]
    if measure_alias:
        _from.append({"Name": measure_alias, "Entity": measure_table, "Type": 0})
    single = {
        "visualType": "tableEx",
        "projections": {"Values": qrefs},
        "prototypeQuery": {"Version": 2, "From": _from, "Select": selects},
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "objects": {},
    }
    return {
        "config": json.dumps(
            {
                "name": "Table_main",
                "layouts": [
                    {
                        "id": 0,
                        "position": {"x": x, "y": y, "width": w, "height": h, "z": 0},
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def _query_layout(name: str, single: dict, x: int, y: int, w: int, h: int) -> dict:
    """Wrap a singleVisual into a visual container with a position."""
    return {
        "config": json.dumps(
            {
                "name": name,
                "layouts": [
                    {
                        "id": 0,
                        "position": {"x": x, "y": y, "width": w, "height": h, "z": 0},
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def _full_query(
    table: str,
    source: str,
    selects: list[dict],
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """prototypeQuery From + Select (a shared wrapper)."""
    _from = [{"Name": source, "Entity": table, "Type": 0}]
    if measure_alias:
        _from.append({"Name": measure_alias, "Entity": measure_table, "Type": 0})
    return {"Version": 2, "From": _from, "Select": selects}
