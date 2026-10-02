"""Flat level matrix of data lineage built from ``PbiLineage.to_json()``.

Every row is a single node of one of the seven lineage levels:

    1 · Origin -> 2 · Source -> 3 · Power Query -> 4 · Table
    -> 5 · Semantics -> 6 · Page -> 7 · Visual

Levels are unfolded into dedicated columns (``L1..L7``), so they stay visible
and can be filtered/sorted. Links between levels are exposed through the
``Parent`` / ``Came from`` / ``Goes to`` columns.

The output is a plain ``list[dict]`` and is intentionally renderer-agnostic:
the PDF report and the Excel export both consume it.
"""

from __future__ import annotations

from agentic_bi.lineage.lineage_origins import ORIGIN_STAGE_LABEL
from agentic_bi.report.lineage_brand_cols import (
    brand_row,
    page_brand_index,
    visual_brand_row,
)

LEVEL = {
    1: "1 · Origin",
    2: "2 · Source",
    3: "3 · Power Query",
    4: "4 · Table",
    5: "5 · Semantics",
    6: "6 · Page",
    7: "7 · Visual",
}

COLUMNS = [
    "Level", "Layer",
    "L1 · Origin", "L2 · Source", "L3 · Power Query", "L4 · Table",
    "L5 · Semantics", "L6 · Page", "L7 · Visual",
    "Parent", "Type", "Detail / Source", "Refs",
    "Came from", "Goes to",
    "Brand · fonts, %", "Brand · colors, %", "Brand · status", "Brand · notes",
]

def _blank_row(level: int) -> dict:
    """A row skeleton for a given level with all level columns empty."""
    row = {c: "" for c in COLUMNS}
    row["Level"] = level
    row["Layer"] = LEVEL[level]
    return row


def lineage_to_table(data: dict) -> list[dict]:
    """Unfold lineage JSON into flat rows (one node per row), levels 1 -> 7.

    Args:
        data: a dict in the ``PbiLineage.to_json()`` structure.

    Returns:
        List of row dicts keyed by :data:`COLUMNS`.
    """
    rows: list[dict] = []
    tables = data.get("tables", {})
    pages = data.get("pages", [])
    sources = data.get("sources", {})
    semantics = data.get("semantics", {})
    origin = data.get("origin", {})
    src_by_table = sources.get("by_table", {})

    # map "source table -> origin label" (level 1 -> level 2)
    src_to_origin: dict[str, str] = {}
    for it in origin.get("items", []):
        olabel = it.get("label") or it.get("key") or "?"
        for tbl in it.get("tables", []) or []:
            src_to_origin[tbl] = olabel

    def _sem_label(tbl: str) -> str:
        sem = semantics.get(tbl)
        if not sem:
            return tbl
        parts = []
        nm = len(sem.get("measures", []))
        nc = len(sem.get("calc_columns", []))
        if nm:
            parts.append(f"{nm} measures")
        if nc:
            parts.append(f"{nc} cols")
        return f"{tbl}: {', '.join(parts)}" if parts else tbl

    # === LEVEL 1: ORIGIN ===
    for it in origin.get("items", []):
        okey = it.get("key", "")
        olabel = it.get("label") or okey
        cat = it.get("category", "origin-unknown")
        otables = it.get("tables", []) or []
        stages = it.get("stages", []) or []
        chain = " -> ".join(
            f"{ORIGIN_STAGE_LABEL.get(s.get('stage'), s.get('stage'))}: {s.get('label')}"
            for s in stages)
        n_targets = sum(1 for t in otables if t in src_by_table)
        detail = it.get("detail") or ""
        if chain:
            detail = f"{chain}\n{detail}" if detail else chain
        row = _blank_row(1)
        row.update({
            "L1 · Origin": olabel,
            "Type": cat,
            "Detail / Source": detail,
            "Refs": n_targets,
            "Goes to": ", ".join(t for t in otables if t in src_by_table),
        })
        rows.append(row)

    # === LEVEL 2: SOURCES ===
    for tbl, s in src_by_table.items():
        refs = tables.get(tbl, {}).get("refs", 0)
        row = _blank_row(2)
        row.update({
            "L1 · Origin": src_to_origin.get(tbl, ""),
            "L2 · Source": tbl,
            "Parent": src_to_origin.get(tbl, ""),
            "Type": s.get("type", ""),
            "Detail / Source": s.get("detail", ""),
            "Refs": refs,
            "Came from": src_to_origin.get(tbl, ""),
            "Goes to": (f"M-query {tbl}" if tables.get(tbl, {}).get("has_power_query")
                        else f"Table {tbl}"),
        })
        rows.append(row)

    # === LEVEL 3: POWER QUERY ===
    for tbl in sorted(t for t, tv in tables.items() if tv.get("has_power_query")):
        refs = tables.get(tbl, {}).get("refs", 0)
        row = _blank_row(3)
        row.update({
            "L2 · Source": tbl,
            "L3 · Power Query": f"M-query {tbl}",
            "Parent": tbl,
            "Type": "Power Query",
            "Refs": refs,
            "Came from": f"Source {tbl}",
            "Goes to": f"Table {tbl}",
        })
        rows.append(row)

    # === LEVEL 4: MODEL TABLES ===
    for tbl, tv in tables.items():
        if tv.get("technical"):
            continue
        src = tv.get("source", {})
        detail_parts = []
        cols = tv.get("columns_count", 0)
        meas = tv.get("measures_count", 0)
        ncalc = tv.get("calc_columns_count", 0)
        if cols:
            detail_parts.append(f"{cols} cols")
        if meas:
            detail_parts.append(f"{meas} measures")
        if ncalc:
            detail_parts.append(f"{ncalc} calc")
        row = _blank_row(4)
        row.update({
            "L2 · Source": tbl,
            "L3 · Power Query": f"M-query {tbl}" if tv.get("has_power_query") else "",
            "L4 · Table": tbl,
            "Parent": f"M-query {tbl}" if tv.get("has_power_query") else "",
            "Type": src.get("type") or "business",
            "Detail / Source": src.get("detail") or ", ".join(detail_parts),
            "Refs": tv.get("refs", 0),
            "Came from": (f"M-query {tbl}" if tv.get("has_power_query")
                          else f"Source {tbl}"),
            "Goes to": _sem_label(tbl) if semantics.get(tbl) else "",
        })
        rows.append(row)

    # === LEVEL 5: SEMANTICS ===
    for tbl, sem in semantics.items():
        nm = len(sem.get("measures", []))
        nc = len(sem.get("calc_columns", []))
        using_pages = [p["name"] for p in pages if tbl in p.get("tables", [])]
        row = _blank_row(5)
        row.update({
            "L2 · Source": tbl,
            "L4 · Table": tbl,
            "L5 · Semantics": _sem_label(tbl),
            "Parent": tbl,
            "Type": f"{nm} measures / {nc} calc" if (nm or nc) else "semantics",
            "Refs": sem.get("table_refs", 0),
            "Came from": f"Table {tbl}",
            "Goes to": ", ".join(using_pages) if using_pages else "",
        })
        rows.append(row)

    # === LEVEL 6: PAGES ===
    for p in pages:
        name = p["name"]
        tables_on_page = p.get("tables", [])
        n_vis = p.get("n_visuals", 0)
        from_label = ", ".join(_sem_label(t) for t in tables_on_page) if tables_on_page else ""
        row = _blank_row(6)
        row.update({
            "L6 · Page": name,
            "Parent": from_label,
            "Type": f"{n_vis} visuals" if n_vis else "page",
            "Detail / Source": ", ".join(tables_on_page),
            "Refs": p.get("refs", 0),
            "Came from": from_label,
            "Goes to": f"visuals ({n_vis})" if n_vis else "",
        })
        rows.append(row)

    # === LEVEL 7: VISUALS ===
    for p in pages:
        for vis in p.get("visuals", []):
            vtype = vis.get("type", "?")
            z = vis.get("z", "")
            bindings = "; ".join(
                f"{b.get('role')}={b.get('queryRef')}" for b in vis.get("bindings", []))
            colors = len(vis.get("colors", []))
            row = _blank_row(7)
            row.update({
                "L6 · Page": p["name"],
                "L7 · Visual": f"{p['name']} · {vtype} z={z}",
                "Parent": p["name"] if p.get("visuals") else "",
                "Type": vtype,
                "Detail / Source": bindings,
                "Refs": vis.get("n_bindings", 0),
                "Came from": ", ".join(p.get("tables", [])),
                "Goes to": f"{colors} colors" if colors else "",
            })
            if vis.get("brand"):
                row.update(visual_brand_row(vis))
            rows.append(row)

    # === RIGHT SIDE: brand compliance metrics ===
    brand_index = page_brand_index(data)
    if brand_index:
        empty = brand_row(None)
        for r in rows:
            if r.get("Level") == 7 and r.get("L7 · Visual"):
                continue  # keep element metrics, do not overwrite with page metrics
            metrics = brand_index.get(r.get("L6 · Page", ""))
            r.update(brand_row(metrics) if metrics else empty)
        summary = (data.get("brand") or {}).get("summary", {})
        if summary and rows:
            base = rows[0]
            fc, cc = summary.get("fonts_compliance"), summary.get("colors_compliance")
            base["Brand · fonts, %"] = fc if fc is not None else ""
            base["Brand · colors, %"] = cc if cc is not None else ""
            base["Brand · status"] = (
                "violations" if summary.get("errors")
                else ("warnings" if summary.get("warnings") else "compliant"))
            base["Brand · notes"] = (
                f"pages with deviations: {len(summary.get('off_brand_pages', []))}")

    return rows
