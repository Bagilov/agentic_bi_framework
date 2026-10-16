"""The structured lineage model behind `ExportMixin.to_json()`.

Building the dict is the bulk of the export logic and needs nothing from the
Excel/Markdown writers, so it lives here: `build_lineage_data(model)` takes a
`PbiLineage` instance (duck-typed; any object exposing the same attributes) and
returns the serializable dict, optionally embedding the PlantUML diagram.

Structure:
    {
      "meta": {...},            analysis metadata (file, version, date)
      "summary": {...},         overall stats (pages, visuals, tables, ...)
      "sources": {...},         sources by table + grouping by type
      "origin": {...},          source origins (process/repository)
      "tables": {...},          model tables (measures, columns, relationships, source, refs)
      "semantics": {...},       semantics by table (measures/columns, refs)
      "pages": [...],           pages: visuals + bindings + elements + palette
      "plantuml": "...",        diagram generated from `sources/tables/...` (optional)
    }

Public API:
    build_lineage_data(model, include_plantuml=True) -> dict
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from agentic_bi.lineage.lineage_origins import origin_json_block


def _summary(model) -> dict:
    """Analysis metadata + overall counters."""
    return {
        "file": model.pbix_path.name,
        "path": str(model.pbix_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "version": 1,
        "pages": model.page_count,
        "visuals": model.visual_count,
        "tables": len(model.tables),
        "business_tables": len(model.business_tables()),
        "technical_tables": len(model.technical_tables()),
        "measures": model.total_measures,
        "calc_columns": model.total_calc_columns,
        "power_queries": len(model.power_query),
        "sources_with_data": sum(
            1 for s in model.sources.values() if s.type != "No Power Query"
        ),
        "sources_access_error": sum(
            1 for u in model.unresolved_sources if u["status"] == "access_error"
        ),
        "sources_unresolved": sum(
            1 for u in model.unresolved_sources if u["status"] == "unresolved"
        ),
        "sources_no_power_query": sum(
            1 for u in model.unresolved_sources if u["status"] == "no_power_query"
        ),
        "unresolved_table_refs": len(model._unresolved_table_refs),
        "relationships": len(model.relationships)
        if isinstance(model.relationships, list)
        else int(getattr(model.relationships, "shape", (0,))[0]),
    }


def _sources(model, summary: dict) -> dict:
    """Table -> source info, plus grouping by store type and unresolved list."""
    sources_tables = {
        t: {
            "type": s.type,
            "detail": s.detail,
            "path": s.path,
            "status": s.status,
            "error": s.error,
        }
        for t, s in model.sources.items()
        if s.type != "No Power Query"
    }
    by_group: dict[str, list[dict]] = defaultdict(list)
    for tbl, info in sources_tables.items():
        src = model.sources[tbl]
        by_group[model._source_group(src)].append(
            {
                "table": tbl,
                "type": info["type"],
                "detail": info["detail"],
                "path": src.path,
                "status": src.status,
                "error": src.error,
            }
        )
    return {
        "by_table": sources_tables,
        "by_group": dict(by_group),
        "unresolved": model.unresolved_sources,
    }


def _tables(model) -> dict:
    """Per-table detail: counts, members, source and reference count."""
    return {
        t: {
            "technical": model.is_technical(t),
            "columns_count": len(model.columns.get(t, [])),
            "columns": model.columns.get(t, []),
            "measures_count": len(model.measures.get(t, [])),
            "measures": model.measures.get(t, []),
            "calc_columns_count": len(model.calc_columns.get(t, [])),
            "calc_columns": model.calc_columns.get(t, []),
            "has_power_query": t in model.power_query,
            "source": {
                "type": model.sources[t].type,
                "detail": model.sources[t].detail,
                "path": model.sources[t].path,
                "status": model.sources[t].status,
                "error": model.sources[t].error,
            },
            "refs": model.table_refs.get(t, 0),  # table references in visuals
        }
        for t in model.tables
    }


def _semantics(model, refs: dict) -> dict:
    """Semantics per business table: measures/calc columns and their refs."""
    semantics = {}
    for t in model.business_tables():
        measures = model.measures.get(t, [])
        calc_cols = model.calc_columns.get(t, [])
        if not (measures or calc_cols):
            continue
        semantics[t] = {
            "measures": [
                {"name": m, "refs": refs["measures"].get(m, 0)} for m in measures
            ],
            "calc_columns": [
                {"name": c, "refs": model.table_refs.get(f"{t}.{c}", 0)}
                for c in calc_cols
            ],
            "table_refs": model.table_refs.get(t, 0),
        }
    return semantics


def _pages(model, brand_pages: dict) -> list[dict]:
    """Per-page detail: visuals, bindings, elements and brand metrics."""
    analysis = {a["page"]: a for a in model.page_analysis()}
    pages = []
    for p in model.pages:
        a = analysis.get(p.name, {})
        n_bindings = sum(len(v.bindings) for v in p.visuals)
        pages.append(
            {
                "index": p.index,
                "name": p.name,
                "n_visuals": len(p.visuals),
                "n_bindings": n_bindings,
                "refs": n_bindings,  # total data references on the page
                "tables": sorted(p.tables),
                "elements": a.get("elements", {}),
                "colors": a.get("colors", []),
                "fonts": model._collect_visual_fonts(p),
                "brand": brand_pages.get(p.name, {}),
                "visuals": [
                    {
                        "type": v.visual_type,
                        "z": v.z_index,
                        "colors": sorted(v.colors),
                        "fonts": sorted(v.fonts),
                        "brand": model._visual_brand(v),
                        "n_bindings": len(v.bindings),
                        "bindings": [
                            {
                                "role": b.role,
                                "queryRef": b.query_ref,
                                "table": b.table,
                                "column": b.column,
                            }
                            for b in v.bindings
                        ],
                    }
                    for v in p.visuals
                ],
            }
        )
    return pages


def build_lineage_data(model, include_plantuml: bool = True) -> dict:
    """Build the full structured lineage dict for `model` (a `PbiLineage`).

    Single source of truth: the PlantUML diagram is built from this same dict,
    i.e. "script -> JSON -> PlantUML".

    Args:
        model: a `PbiLineage` (or any object with the same attributes).
        include_plantuml: whether to embed the 'plantuml' key (built from the dict).
    """
    summary = _summary(model)
    sources = _sources(model, summary)
    refs = model._resolve_refs()
    # brand-book compliance metrics by page (fonts/colors)
    _bm = model.brand_metrics()
    brand_pages = _bm["pages"]
    model._brand_summary = _bm["summary"]
    pages = _pages(model, brand_pages)

    data = {
        "meta": summary,
        "summary": summary,
        "sources": sources,
        "origin": origin_json_block(model.origins, list(sources["by_table"].keys())),
        "tables": _tables(model),
        "semantics": _semantics(model, refs),
        "pages": pages,
        "brand": {
            "summary": getattr(model, "_brand_summary", {}),
            "pages": {p["name"]: p.get("brand", {}) for p in pages},
        },
        "unresolved_table_refs": model.unresolved_table_refs,
    }
    if include_plantuml:
        data["plantuml"] = {"lineage": model._render_plantuml_from_data(data)}
    return data
