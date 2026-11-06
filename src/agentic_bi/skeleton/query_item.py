"""Prototype-query reference builders shared by the skeleton visual builders.

Owns the stable filter-id digest, the ``SourceRef`` constructor and
:func:`_query_item`, which turns one field description into the ``Select`` item
and ``queryRef`` pair of a ``prototypeQuery``. The visual builders that consume
them live in :mod:`agentic_bi.skeleton.visuals`.
"""

from __future__ import annotations

import hashlib

# Function in Select for columns (from a real layout): 0=None, 4=min (donor uses 4)
COL_AGG_FUNCTION = 4


def _stable_suffix(text: str, length: int = 8) -> str:
    """A short, process-stable hex digest of `text`.

    Built-in `hash()` is salted per process (`PYTHONHASHSEED`), so a name derived
    from it changes every run and makes the built .pbix non-reproducible (and
    un-diffable between builds). SHA-1 of the UTF-8 bytes is stable across runs
    and machines.
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def _source_ref(source: str, entity: str) -> dict:
    return {"SourceRef": {"Source": source, "Entity": entity}}


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
    prop = pq_query.get("property")
    if not prop:
        raise ValueError(
            f"a field needs a non-empty 'property', got {pq_query.get('property')!r}"
        )
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
