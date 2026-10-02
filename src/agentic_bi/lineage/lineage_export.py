"""Export/formatting mixin: summary, Excel, Markdown, JSON, brand metrics."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from agentic_bi.lineage.lineage_brand import (
    brand_audit_pages,
    brand_label,
    visual_brand_metrics,
)
from agentic_bi.lineage.lineage_origins import origin_json_block
from agentic_bi.lineage.lineage_types import _brand_level_ru

logger = logging.getLogger(__name__)


class ExportMixin:
    def print_summary(self) -> None:
        """A short console summary."""
        print(f"File: {self.pbix_path.name}")
        print(f"Pages: {self.page_count}, visuals: {self.visual_count}")
        print(f"Model tables: {len(self.tables)} "
              f"(business: {len(self.business_tables())}, "
              f"technical: {len(self.technical_tables())})")
        print(f"Measures: {self.total_measures}, calc columns: {self.total_calc_columns}")
        print(f"Power Query: {len(self.power_query)}, sources with data: "
              f"{sum(1 for s in self.sources.values() if s.type != 'No Power Query')}")
        print("\nData sources:")
        for tbl, src in self.sources.items():
            if src.type != "No Power Query":
                status = ""
                if src.status in ("access_error", "unresolved"):
                    status = f" [{src.status}]"
                print(f"  {tbl:30} {src.type:10} {src.detail}{status}")
        if self.unresolved_sources:
            print("\n! Unavailable / undetermined sources:")
            for u in self.unresolved_sources:
                print(f"  {u['table']:30} {u['type']:10} [{u['status']}] {u.get('error') or ''}")
        print("\nPages -> tables:")
        for p in self.pages:
            if p.tables:
                print(f"  {p.index:2}. {p.name:32} {', '.join(sorted(p.tables))}")

        s = self.brand_metrics()["summary"]
        if s:
            print("\nBrand-book compliance (fonts/colors by page):")
            print(f"  pages: {s.get('pages')}  ok: {s.get('ok')}  "
                  f"warnings: {s.get('warnings')}  errors: {s.get('errors')}  "
                  f"no data: {s.get('unknown')}")
            print(f"  fonts: {s.get('fonts_compliance')}%  "
                  f"colors: {s.get('colors_compliance')}%")
            if s.get("error_pages"):
                print(f"  violations: {', '.join(s['error_pages'])}")

    def export_excel(self, out_path: str | Path) -> Path:
        """Save pages/visuals/tables to xlsx (3 sheets)."""
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            self.pages_dataframe.to_excel(writer, sheet_name="pages", index=False)
            self.visuals_dataframe.to_excel(writer, sheet_name="visuals", index=False)
            self.tables_dataframe.to_excel(writer, sheet_name="tables", index=False)
        return out

    def export_markdown(self, out_path: str | Path) -> Path:
        """Save a human-readable lineage report to Markdown."""
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        md = [
            f"# Data Lineage: {self.pbix_path.name}\n",
            f"**Analysis date:** {datetime.now():%Y-%m-%d %H:%M}  \n",
            f"Pages: **{self.page_count}**, visuals: **{self.visual_count}**, "
            f"model tables: **{len(self.tables)}**, measures: **{self.total_measures}**, "
            f"calc columns: **{self.total_calc_columns}**, "
            f"Power Query: **{len(self.power_query)}**.\n",
            "\n## Data sources (Power Query)\n",
            "| Model table | Source type | Source |",
            "|---|---|---|",
        ]
        for tbl in sorted(self.tables, key=lambda t: (self.sources[t].type, t)):
            src = self.sources.get(tbl, Source("No Power Query", None))
            if src.type != "No Power Query":
                md.append(f"| {tbl} | {src.type} | {src.detail} |")

        md.append("\n## Pages and tables used\n")
        md.append("| # | Page | Visuals | Tables used |")
        md.append("|---|---|---|---|")
        for _, row in self.pages_dataframe.iterrows():
            md.append(f"| {row['PageIdx']} | {row['Page']} | {row['Visuals']} | {row['BoundTables']} |")

        s = self.brand_metrics()["summary"]
        if s:
            md.append("\n## Brand-book compliance (page elements)\n")
            md.append(f"Pages: **{s.get('pages')}** - compliant: {s.get('ok')}, "
                      f"warnings: {s.get('warnings')}, errors: {s.get('errors')}, "
                      f"no data: {s.get('unknown')}. "
                      f"Averages: fonts **{s.get('fonts_compliance')}%**, "
                      f"colors **{s.get('colors_compliance')}%**.\n")
            md.append("| # | Page | Fonts, % | Colors, % | Red | Status |")
            md.append("|---|---|---|---|---|---|")
            brand = self.brand_metrics()["pages"]
            for p in self.pages:
                m = brand.get(p.name, {})
                fnt = m.get("fonts", {})
                col = m.get("colors", {})
                red = "yes" if col.get("has_red") else "no"
                md.append(f"| {p.index} | {p.name} | "
                          f"{fnt.get('compliance') if fnt.get('compliance') is not None else '—'} | "
                          f"{col.get('compliance') if col.get('compliance') is not None else '—'} | "
                          f"{red} | {_brand_level_ru(m.get('level'))} |")

        md.append("\n## Breakdown by visual types\n")
        type_by_page: dict[str, Counter] = defaultdict(Counter)
        for _, row in self.visuals_dataframe.iterrows():
            type_by_page[row["Page"]][row["VisualType"]] += 1
        for p in self.pages:
            if not p.visuals:
                continue
            cnt = dict(type_by_page.get(p.name, {}))
            md.append(f"**{p.index}. {p.name}**: " +
                      ", ".join(f"{k} ({v})" for k, v in cnt.items()) + "\n")

        text = "\n".join(md)
        out.write_text(text, encoding="utf-8")
        return out

    def to_json(self, include_plantuml: bool = True) -> dict:
        """The full structured lineage model (a dict ready for serialization).

Single source of truth: the PlantUML diagram is built from this same dict
        (see `_render_plantuml_from_data`), i.e. "script -> JSON -> PlantUML".

        Args:
            include_plantuml: whether to embed the 'plantuml' key (built from the dict).

        Structure:
            {
              "meta": {...},            analysis metadata (file, version, date)
              "summary": {...},         overall stats (pages, visuals, tables, ...)
              "sources": {...},         sources by table + grouping by type
              "origin": {...},          source origins (process/repository)
              "tables": {...},          model tables (measures, columns, relationships, source, refs)
              "semantics": {...},       semantics by table (measures/columns, refs)
              "pages": [...],           pages: visuals + bindings + elements + palette
              "plantuml": "...",        the PlantUML diagram generated from `sources/tables/...`
            }
        """
        # ---- summary ----
        summary = {
            "file": self.pbix_path.name,
            "path": str(self.pbix_path),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "version": 1,
            "pages": self.page_count,
            "visuals": self.visual_count,
            "tables": len(self.tables),
            "business_tables": len(self.business_tables()),
            "technical_tables": len(self.technical_tables()),
            "measures": self.total_measures,
            "calc_columns": self.total_calc_columns,
            "power_queries": len(self.power_query),
            "sources_with_data": sum(
                1 for s in self.sources.values() if s.type != "No Power Query"),
            "sources_access_error": sum(1 for u in self.unresolved_sources if u["status"] == "access_error"),
            "sources_unresolved": sum(1 for u in self.unresolved_sources if u["status"] == "unresolved"),
            "sources_no_power_query": sum(1 for u in self.unresolved_sources if u["status"] == "no_power_query"),
            "unresolved_table_refs": len(self._unresolved_table_refs),
            "relationships": len(self.relationships) if isinstance(self.relationships, list) else int(getattr(self.relationships, "shape", (0,))[0]),
        }

        # --- sources: table->{type,detail,path,status,error} + grouping by store type ---
        sources_tables = {
            t: {"type": s.type, "detail": s.detail, "path": s.path,
                "status": s.status, "error": s.error}
            for t, s in self.sources.items() if s.type != "No Power Query"
        }
        by_group: dict[str, list[dict]] = defaultdict(list)
        for tbl, info in sources_tables.items():
            src = self.sources[tbl]
            by_group[self._source_group(src)].append(
                {"table": tbl, "type": info["type"], "detail": info["detail"],
                 "path": src.path, "status": src.status, "error": src.error})
        sources = {"by_table": sources_tables, "by_group": dict(by_group),
                   "unresolved": self.unresolved_sources}

        # --- tables ---
        refs = self._resolve_refs()
        tables = {
            t: {
                "technical": self.is_technical(t),
                "columns_count": len(self.columns.get(t, [])),
                "columns": self.columns.get(t, []),
                "measures_count": len(self.measures.get(t, [])),
                "measures": self.measures.get(t, []),
                "calc_columns_count": len(self.calc_columns.get(t, [])),
                "calc_columns": self.calc_columns.get(t, []),
                "has_power_query": t in self.power_query,
                "source": {"type": self.sources[t].type, "detail": self.sources[t].detail,
                           "path": self.sources[t].path,
                           "status": self.sources[t].status, "error": self.sources[t].error},
                "refs": self.table_refs.get(t, 0),   # table references in visuals
            }
            for t in self.tables
        }

        # --- semantics (aggregation by table) + reference counts ---
        semantics = {}
        for t in self.business_tables():
            measures = self.measures.get(t, [])
            calc_cols = self.calc_columns.get(t, [])
            if not (measures or calc_cols):
                continue
            semantics[t] = {
                "measures": [
                    {"name": m,
                     "refs": refs["measures"].get(m, 0)}
                    for m in measures
                ],
                "calc_columns": [
                    {"name": c,
                     "refs": self.table_refs.get(f"{t}.{c}", 0)}
                    for c in calc_cols
                ],
                "table_refs": self.table_refs.get(t, 0),
            }

        # --- pages ---
        analysis = {a["page"]: a for a in self.page_analysis()}
        # brand-book compliance metrics by page (fonts/colors)
        _bm = self.brand_metrics()
        brand_pages = _bm["pages"]
        self._brand_summary = _bm["summary"]
        pages = []
        for p in self.pages:
            a = analysis.get(p.name, {})
            n_bindings = sum(len(v.bindings) for v in p.visuals)
            pages.append({
                "index": p.index,
                "name": p.name,
                "n_visuals": len(p.visuals),
                "n_bindings": n_bindings,
                "refs": n_bindings,   # total data references on the page
                "tables": sorted(p.tables),
                "elements": a.get("elements", {}),
                "colors": a.get("colors", []),
                "fonts": self._collect_visual_fonts(p),
                "brand": brand_pages.get(p.name, {}),
                "visuals": [
                    {
                        "type": v.visual_type,
                        "z": v.z_index,
                        "colors": sorted(v.colors),
                        "fonts": sorted(v.fonts),
                        "brand": self._visual_brand(v),
                        "n_bindings": len(v.bindings),
                        "bindings": [
                            {"role": b.role, "queryRef": b.query_ref,
                             "table": b.table, "column": b.column}
                            for b in v.bindings
                        ],
                    }
                    for v in p.visuals
                ],
            })

        data = {
            "meta": summary,
            "summary": summary,
            "sources": sources,
            "origin": origin_json_block(self.origins, list(sources_tables.keys())),
            "tables": tables,
            "semantics": semantics,
            "pages": pages,
            "brand": {"summary": getattr(self, "_brand_summary", {}),
                       "pages": {p["name"]: p.get("brand", {}) for p in pages}},
            "unresolved_table_refs": self.unresolved_table_refs,
        }
        if include_plantuml:
            data["plantuml"] = {"lineage": self._render_plantuml_from_data(data)}
        return data

    def export_json(self, out_path: str | Path) -> Path:
        """Save the full lineage structure to JSON (from `to_json()`)."""
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(self.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out
