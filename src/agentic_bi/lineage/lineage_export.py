"""Export/formatting mixin: summary, Excel, Markdown, JSON, brand metrics.

The structured dict returned by `to_json()` is assembled by
`lineage_export_data.build_lineage_data`; this module owns the console/Excel/
Markdown writers and the JSON file writer.

Public API:
    ExportMixin.print_summary() / export_excel() / export_markdown()
    ExportMixin.to_json(include_plantuml=True) -> dict
    ExportMixin.export_json(out_path) -> Path
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from agentic_bi.lineage.lineage_export_data import build_lineage_data
from agentic_bi.lineage.lineage_types import Source, _brand_level_ru

logger = logging.getLogger(__name__)


class ExportMixin:
    def print_summary(self) -> None:
        """A short console summary."""
        print(f"File: {self.pbix_path.name}")
        print(f"Pages: {self.page_count}, visuals: {self.visual_count}")
        print(
            f"Model tables: {len(self.tables)} "
            f"(business: {len(self.business_tables())}, "
            f"technical: {len(self.technical_tables())})"
        )
        print(
            f"Measures: {self.total_measures}, calc columns: {self.total_calc_columns}"
        )
        print(
            f"Power Query: {len(self.power_query)}, sources with data: "
            f"{sum(1 for s in self.sources.values() if s.type != 'No Power Query')}"
        )
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
                print(
                    f"  {u['table']:30} {u['type']:10} [{u['status']}] {u.get('error') or ''}"
                )
        print("\nPages -> tables:")
        for p in self.pages:
            if p.tables:
                print(f"  {p.index:2}. {p.name:32} {', '.join(sorted(p.tables))}")

        s = self.brand_metrics()["summary"]
        if s:
            print("\nBrand-book compliance (fonts/colors by page):")
            print(
                f"  pages: {s.get('pages')}  ok: {s.get('ok')}  "
                f"warnings: {s.get('warnings')}  errors: {s.get('errors')}  "
                f"no data: {s.get('unknown')}"
            )
            print(
                f"  fonts: {s.get('fonts_compliance')}%  "
                f"colors: {s.get('colors_compliance')}%"
            )
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
            md.append(
                f"| {row['PageIdx']} | {row['Page']} | {row['Visuals']} | {row['BoundTables']} |"
            )

        s = self.brand_metrics()["summary"]
        if s:
            md.append("\n## Brand-book compliance (page elements)\n")
            md.append(
                f"Pages: **{s.get('pages')}** - compliant: {s.get('ok')}, "
                f"warnings: {s.get('warnings')}, errors: {s.get('errors')}, "
                f"no data: {s.get('unknown')}. "
                f"Averages: fonts **{s.get('fonts_compliance')}%**, "
                f"colors **{s.get('colors_compliance')}%**.\n"
            )
            md.append("| # | Page | Fonts, % | Colors, % | Red | Status |")
            md.append("|---|---|---|---|---|---|")
            brand = self.brand_metrics()["pages"]
            for p in self.pages:
                m = brand.get(p.name, {})
                fnt = m.get("fonts", {})
                col = m.get("colors", {})
                red = "yes" if col.get("has_red") else "no"
                md.append(
                    f"| {p.index} | {p.name} | "
                    f"{fnt.get('compliance') if fnt.get('compliance') is not None else '—'} | "
                    f"{col.get('compliance') if col.get('compliance') is not None else '—'} | "
                    f"{red} | {_brand_level_ru(m.get('level'))} |"
                )

        md.append("\n## Breakdown by visual types\n")
        type_by_page: dict[str, Counter] = defaultdict(Counter)
        for _, row in self.visuals_dataframe.iterrows():
            type_by_page[row["Page"]][row["VisualType"]] += 1
        for p in self.pages:
            if not p.visuals:
                continue
            cnt = dict(type_by_page.get(p.name, {}))
            md.append(
                f"**{p.index}. {p.name}**: "
                + ", ".join(f"{k} ({v})" for k, v in cnt.items())
                + "\n"
            )

        text = "\n".join(md)
        out.write_text(text, encoding="utf-8")
        return out

    def to_json(self, include_plantuml: bool = True) -> dict:
        """The full structured lineage model (a dict ready for serialization).

        Single source of truth: the PlantUML diagram is built from this same dict
        (see `_render_plantuml_from_data`), i.e. "script -> JSON -> PlantUML".

        Args:
            include_plantuml: whether to embed the 'plantuml' key (built from the dict).

        See `lineage_export_data` for the exact structure.
        """
        return build_lineage_data(self, include_plantuml=include_plantuml)

    def export_json(self, out_path: str | Path) -> Path:
        """Save the full lineage structure to JSON (from `to_json()`)."""
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(self.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out
