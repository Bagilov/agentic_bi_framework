"""PlantUML renderer: builds the data-flow diagram from the lineage JSON."""

from __future__ import annotations

from collections import defaultdict

from agentic_bi.lineage.lineage_brand import brand_label
from agentic_bi.lineage.lineage_origins import (
    ORIGIN_COLORS,
    ORIGIN_LABEL,
    ORIGIN_STAGE_COLORS,
    ORIGIN_STAGE_LABEL,
)


def render_plantuml_from_data(ctx, data: dict) -> str:
    """Build the PlantUML diagram from the lineage JSON structure (`to_json()`).

    Layers, left to right:
        1. Data origin (generating process/repository, sub-stages
           source -> processing -> load)
        2. Sources (grouping by store type) + reference counts
        3. Power Query (M queries)
        4. Model tables + refs
        5. Semantics (measures/columns by table) + refs
        6. Dashboard pages + refs
        7. Elements and palette by page

    Args:
        data: a dict in the `to_json()` structure (origin/sources/tables/...).

    Returns:
        A string with the full PlantUML code (@startuml ... @enduml).
    """
    ctx._pu_seen = set()  # reset unique ids on each call
    ctx._pu_ids = {}

    origins = data.get("origin", {})
    sources = data.get("sources", {})
    tables_json = data.get("tables", {})
    semantics = data.get("semantics", {})
    pages_json = data.get("pages", [])

    # layer 2: sources by type groups
    src_by_group: dict[str, list[dict]] = defaultdict(list)
    for group, items in sources.get("by_group", {}).items():
        for it in items:
            src_by_group[group].append(it)

    # tables with sources (for pq/tables)
    tables_with_data = [
        t for t, tbl in tables_json.items() if tbl.get("has_power_query")
    ]
    business = [t for t, tbl in tables_json.items() if not tbl.get("technical")]
    pages_with_data = [p for p in pages_json if p.get("tables")]

    out = [
        ctx._PU_HEADER.format(name=ctx._pu_escape(ctx.pbix_path.stem)),
        ctx._PU_STYLE.strip(),
    ]

    # ---- layer 1: data origin (initial layer) ----
    origin_nodes: dict[str, str] = {}
    origin_to_tables: dict[str, list[str]] = {}
    out.append('\npackage "1 · DATA ORIGIN" {')
    for it in origins.get("items", []):
        cat = it.get("category", "origin-unknown")
        tables = it.get("tables", []) or []
        ntables = len(tables)
        label = it.get("label", it.get("key", "?"))
        tail = f" -> {ntables} src" if ntables else ""
        okey = it.get("key", label)
        origin_to_tables[okey] = tables
        color = ORIGIN_COLORS.get(cat, "#f5f5f5")
        cat_label = ORIGIN_LABEL.get(cat, cat)
        stages = it.get("stages", []) or []

        if not stages:
            nid = ctx._pu_id("O", okey)
            origin_nodes[okey] = nid
            lbl = f"{label}\n{cat_label}" + (f"\n{tail}" if tail else "")
            out.append(f"  [**{ctx._pu_escape(lbl)}**] as {nid} {color}")
            continue

        # nested sub-stage chain: SOURCE -> PROCESSING -> LOAD
        out.append(f'  package "{ctx._pu_escape(label)}\\n{cat_label}" {{')
        prev = None
        for si, st in enumerate(stages):
            stage = st.get("stage", "")
            slab = ORIGIN_STAGE_LABEL.get(stage, stage.upper())
            slbl = f"{st.get('label') or ''}\n{slab}"
            sid = ctx._pu_id("O", f"{okey}:{stage}:{si}")
            scol = ORIGIN_STAGE_COLORS.get(stage, color)
            out.append(f"    [**{ctx._pu_escape(slbl)}**] as {sid} {scol}")
            if prev is not None:
                out.append(f"    {prev} --> {sid}")
            prev = sid
        origin_nodes[okey] = prev  # the last sub-stage feeds layer-2 sources
        out.append("  }")
    out.append("}")

    # ---- layer 2: sources ----
    out.append('\npackage "2 · DATA SOURCES" {')
    source_tables: set[str] = set()
    for group in sorted(src_by_group):
        out.append(f'  package "{group}" {{')
        for it in src_by_group[group]:
            tbl = it["table"]
            source_tables.add(tbl)
            refs = tables_json.get(tbl, {}).get("refs", 0)
            detail = it.get("detail") or ""
            label = f"{tbl}\n{detail}"
            if refs:
                label += f"\n{refs} refs"
            nid = ctx._pu_id("S", tbl)
            out.append(f"    [**{ctx._pu_escape(label)}**] as {nid}")
        out.append("  }")
    out.append("}")

    # ---- layer 3: Power Query ----
    pq_nodes = {}
    out.append('\npackage "3 · POWER QUERY" {')
    for tbl in sorted(tables_with_data):
        nid = ctx._pu_id("PQ", tbl)
        pq_nodes[tbl] = nid
        out.append(f"  [**M query {ctx._pu_escape(tbl)}**] as {nid}")
    out.append("}")

    # ---- layer 4: model tables ----
    t_nodes = {}
    out.append('\npackage "4 · MODEL (tables)" {')
    for tbl in business:
        nid = ctx._pu_id("T", tbl)
        t_nodes[tbl] = nid
        refs = tables_json.get(tbl, {}).get("refs", 0)
        label = tbl if not refs else f"{tbl}\n{refs} refs"
        out.append(f"  [**{ctx._pu_escape(label)}**] as {nid}")
    out.append("}")

    # ---- layer 5: semantics (aggregation by table) + refs ----
    sem_nodes: dict[str, str] = {}
    out.append('\npackage "5 · SEMANTICS" {')
    for tbl in business:
        sem = semantics.get(tbl)
        if not sem:
            continue
        nm = len(sem.get("measures", []))
        nc = len(sem.get("calc_columns", []))
        trefs = sem.get("table_refs", 0)
        parts = []
        if nm:
            parts.append(f"{nm} meas")
        if nc:
            parts.append(f"{nc} col")
        label = f"{tbl}: {', '.join(parts)}"
        if trefs:
            label += f"\n{trefs} refs"
        nid = ctx._pu_id("SEM", tbl)
        sem_nodes[tbl] = nid
        out.append(f"  [**{ctx._pu_escape(label)}**] as {nid}")
    out.append("}")

    # ---- layer 6: pages ----
    page_nodes = {}
    out.append('\npackage "6 · PAGES" {')
    for p in pages_with_data:
        refs = p.get("refs", 0)
        label = p["name"] if not refs else f"{p['name']}\n{refs} refs"
        nid = ctx._pu_id("P", p["name"])
        page_nodes[p["name"]] = nid
        out.append(f"  [**{ctx._pu_escape(label)}**] as {nid}")
    out.append("}")

    # ---- layer 7: elements and palette by page ----
    elem_nodes = {}
    out.append('\npackage "7 · ELEMENTS AND PALETTE" {')
    for p in pages_with_data:
        etypes = p.get("elements", {})
        if not etypes:
            continue
        total = p.get("n_visuals", 0)
        colors = p.get("colors", [])
        ncolors = len(colors)
        top = ", ".join(
            f"{t}:{c}" for t, c in sorted(etypes.items(), key=lambda kv: -kv[1])[:5]
        )
        label = f"Visuals {total}\n{top}\nColors {ncolors}: "
        label += ", ".join(colors[:6]) + (("…") if ncolors > 6 else "")
        # brand-book compliance metrics (fonts/colors) on the page node
        bm = p.get("brand") or {}
        if bm:
            label += "\n" + brand_label(bm)
        nid = ctx._pu_id("E", p["name"])
        elem_nodes[p["name"]] = nid
        out.append(f"  [**{ctx._pu_escape(label)}**] as {nid}")
    out.append("}")

    # ---- edges ----
    out.append("\n' ==== DATA FLOWS ====")
    # origin -> the sources it generates
    for okey, tables in origin_to_tables.items():
        if okey not in origin_nodes:
            continue
        for tbl in tables:
            if tbl in source_tables:
                out.append(f"{origin_nodes[okey]} --> {ctx._pu_id('S', tbl)}")
    # source -> power query (if the table has an M query)
    for tbl in pq_nodes:
        out.append(f"{ctx._pu_id('S', tbl)} --> {pq_nodes[tbl]}")
    # power query -> table
    for tbl, nid in pq_nodes.items():
        out.append(f"{nid} --> {t_nodes[tbl]}")
    # table -> its semantic node
    for tbl, nid in t_nodes.items():
        if tbl in sem_nodes:
            out.append(f"{nid} --> {sem_nodes[tbl]}")
    # semantics (table) -> pages where the table is used
    page_tables = {p["name"]: set(p.get("tables", [])) for p in pages_json}
    for tbl, snid in sem_nodes.items():
        for pname, ts in page_tables.items():
            if tbl in ts and pname in page_nodes:
                out.append(f"{snid} --> {page_nodes[pname]}")
    # page -> its elements/palette
    for pname, nid in page_nodes.items():
        if pname in elem_nodes:
            out.append(f"{nid} --> {elem_nodes[pname]}")

    # ---- legend: brand-book compliance summary for the whole dashboard ----
    bsum = getattr(ctx, "_brand_summary", {}) or {}
    if bsum:
        out.append("\n' ==== BRAND-BOOK COMPLIANCE (summary) ====")
        out.append("legend right")
        out.append("  **Brand-book compliance (page elements)**")
        out.append(
            f"  pages: {bsum.get('pages', 0)}  |  "
            f"ok: {bsum.get('ok', 0)}  |  "
            f"warnings: {bsum.get('warnings', 0)}  |  "
            f"errors: {bsum.get('errors', 0)}"
        )
        out.append(
            f"  averages: fonts {bsum.get('fonts_compliance')}%, "
            f"colors {bsum.get('colors_compliance')}%"
        )
        if bsum.get("error_pages"):
            out.append("  violations: " + ", ".join(bsum["error_pages"][:6]))
        out.append("end legend")

    out.append("\n@enduml")
    return "\n".join(out)
