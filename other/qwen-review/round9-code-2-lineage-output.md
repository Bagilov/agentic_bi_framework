# Bundle 2: lineage output

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/lineage/lineage_sources.py ====================

"""Data-source resolution from Power Query M code (mixin)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from agentic_bi.lineage.lineage_types import Source

logger = logging.getLogger(__name__)


class SourceMixin:
    def _file_access(self, file_path: str) -> tuple[str, str, str]:
        """Check the availability of a local source file.

        Returns:
            (status, detail, error):
                status  -> 'ok' | 'access_error' | 'unresolved'
                detail  -> the final path to display
                error   -> the error text ('' if available/unresolved without error)
        """
        if not file_path or file_path in ("?", ""):
            return "unresolved", "?", ""
        # UNC / network paths and non-existent ones - flag, but do not fail
        if file_path.startswith(r"\\"):
            return "ok", file_path, ""
        p = Path(file_path)
        if not p.is_absolute():
            # a relative path - cannot check
            return "unresolved", file_path, ""
        try:
            if p.exists() and os.access(p, os.R_OK):
                return "ok", file_path, ""
            return (
                "access_error",
                file_path,
                f"File does not exist or is inaccessible: {file_path}",
            )
        except OSError as e:
            return "access_error", file_path, f"File access error: {file_path} ({e})"

    def _resolve_file_source(self, type_: str, expr: str) -> Source:
        """Build a file-type Source with a File.Contents access check."""
        m_file = re.search(r'File\.Contents\("([^"]+)"\)', expr)
        file_path = m_file.group(1) if m_file else "?"
        status, detail, error = self._file_access(file_path)
        return Source(type_, detail, status=status, error=error, path=file_path)

    def _source_from_m(self, expr: str) -> Source:
        """Determine the data source from M code: (type, source/details + status).

        Never raises on an unavailable source: if the local file is missing/
        inaccessible, the source is marked `status="access_error"` rather than a
        silent `Unknown`. The parsed type is always returned even when unavailable.
        """
        if not expr:
            return Source(
                "Unknown",
                "?",
                status="no_power_query",
                error="No M code (Power Query) for the table",
            )

        # --- ODBC (including Hive/Impala and others via DSN) ---
        if "Odbc.Query(" in expr:
            m_dsn = re.search(r'Odbc\.Query\("([^"]+)"', expr)
            dsn = m_dsn.group(1) if m_dsn else "?"
            tables_found = re.findall(r"FROM\s+([\w.]+)", expr, re.IGNORECASE)
            joins = re.findall(r"JOIN\s+([\w.]+)", expr, re.IGNORECASE)
            all_tables = list(dict.fromkeys(tables_found + joins))
            suffix = " / " + ", ".join(all_tables) if all_tables else ""
            path = dsn
            if all_tables:
                path = f"{dsn} / {', '.join(all_tables)}"
            # ODBC access via DSN cannot be checked statically -> unresolved
            return Source(
                "ODBC",
                f"{dsn}{suffix}",
                status="unresolved",
                error="ODBC access check requires a live connection",
                path=path,
            )

        # --- SQL Server (Sql.Database / Sql.Databases) ---
        if "Sql.Database(" in expr or "Sql.Databases(" in expr:
            m_srv = re.search(r'Sql\.Database\(\s*"([^"]+)"', expr)
            srv = m_srv.group(1) if m_srv else "?"
            m_db = re.search(r'Sql\.Database\(\s*"[^"]+"\s*,\s*"([^"]+)"', expr)
            db = m_db.group(1) if m_db else ""
            path = f"{srv} / {db}" if db else srv
            return Source(
                "SQL Server",
                path,
                status="unresolved",
                error="Server check requires a live connection",
                path=path,
            )

        # --- PostgreSQL / Postgre(che) ---
        if any(
            k in expr
            for k in (
                "PostgreSQL.Database(",
                "PostgreSql.Database(",
                "Npgsql",
                "PgSource",
                "PostgreSource",
            )
        ):
            m_srv = re.search(r'\.Database\(\s*"([^"]+)"', expr)
            srv = m_srv.group(1) if m_srv else "?"
            return Source(
                "PostgreSQL",
                srv,
                status="unresolved",
                error="Server check requires a live connection",
            )

        # --- MySQL / MariaDB ---
        if any(k in expr for k in ("MySql.Data", "MySql.Database", "MySql", "MariaDB")):
            m_conn = re.search(
                r'MySql\.Data\.MySqlClient\.MySqlConnection\("([^"]+)"', expr
            )
            conn = m_conn.group(1) if m_conn else "?"
            return Source(
                "MySQL",
                conn,
                status="unresolved",
                error="Server check requires a live connection",
            )

        # --- Oracle ---
        if any(
            k in expr
            for k in (
                "Oracle.Database",
                "OracleDataAccess",
                "Oracle.ManagedDataAccess",
                "Odp.Net",
            )
        ):
            m_conn = re.search(r'Oracle\.Database\(\s*"([^"]+)"', expr)
            conn = m_conn.group(1) if m_conn else "?"
            return Source(
                "Oracle",
                conn,
                status="unresolved",
                error="Server check requires a live connection",
            )

        # --- Hive/Impala via ODBC/emulator ---
        if any(k in expr for k in ("Hive.Query(", "Impala", "Spark.SQL", "CDP", "HDP")):
            return Source(
                "Hive",
                "Hive/Impala via connector",
                status="unresolved",
                error="Cluster check requires a live connection",
            )

        # --- Power Query (M) functions for flat files (with an access check) ---
        if "Excel.Workbook(" in expr or "Excel.Worksheet(" in expr:
            return self._resolve_file_source("Excel", expr)
        if "Csv.Document(" in expr or "Csv.Import(" in expr or ".csv" in expr:
            return self._resolve_file_source("CSV", expr)
        if "Json.Document(" in expr:
            # Json.Document(Binary.Decompress(...)) - embedded data without File.Contents;
            # Json.Document(File.Contents(...)) - an external JSON file.
            if "File.Contents(" not in expr:
                return Source("Embedded", "data embedded in M code")
            return self._resolve_file_source("JSON", expr)
        if "Parquet.Document(" in expr or "Parquet.Contents(" in expr:
            return self._resolve_file_source("Parquet", expr)
        if "Xml.Tables(" in expr or "Xml.Document(" in expr:
            return self._resolve_file_source("XML", expr)

        # --- embedded data (base64) ---
        if "Binary.Decompress" in expr or "Binary.FromText" in expr:
            return Source("Embedded", "data embedded in M code")

        return Source(
            "Unknown",
            "?",
            status="unresolved",
            error="Source type not recognized in M code",
        )

    # ---------------- helper for service tables ----------------

==================== FILE: src/agentic_bi/lineage/lineage_export.py ====================

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

==================== FILE: src/agentic_bi/lineage/lineage_export_data.py ====================

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

==================== FILE: src/agentic_bi/lineage/lineage_plantuml.py ====================

"""PlantUML data-flow diagram generation mixin."""

from __future__ import annotations

import re

from agentic_bi.lineage.lineage_types import Source


class PlantUmlMixin:
    # -------- PlantUML diagram autogeneration --------
    _PU_TECH_NAMES = {"DateTableTemplate", "LocalDateTable", "DateCalendar"}
    _PU_STYLE = """\
' ============ STRICT ARCHITECTURAL STYLE ============
hide stereotype
hide <<package>> stereotype
skinparam backgroundColor #FFFFFF
skinparam defaultFontName Arial
skinparam defaultFontSize 11
skinparam shadowing false
skinparam roundcorner 4
skinparam linetype ortho
skinparam ArrowThickness 1.4
skinparam packageBorderColor #2C3E50
skinparam packageBackgroundColor #FFFFFF
skinparam packageFontStyle bold
skinparam packageFontSize 12
skinparam componentStyle rectangle
skinparam component {
    BackgroundColor #FFFFFF
    BorderColor #2C3E50
    FontSize 9
    FontColor #1a1a1a
    BorderThickness 1
}
skinparam NoteBackgroundColor #F4F6F8
left to right direction
!pragma layout smetana
"""
    _PU_HEADER = "@startuml lineage_{name}"

    def _pu_escape(self, text: str) -> str:
        """Escape special characters for PlantUML node text.

        Underscore is NOT escaped (it renders correctly inside a component),
        and newlines are replaced with the literal \\n so label parsing is not broken.
        """
        return (
            text.replace("\\", "\\\\")
            .replace("#", r"\#")
            .replace("[", r"\[")
            .replace("]", r"\]")
            .replace("{", r"\{")
            .replace("}", r"\}")
            .replace("\n", r"\n")
        )

    def _pu_id(self, prefix: str, name: str) -> str:
        """A stable unique PlantUML node identifier from a name.

        Memoizes the id by (prefix, name) so the declaration and edges reference
        the same node. Non-latin characters are collapsed
        to '_' and may collide, so when there is no latin text
        a short hash of the full name is appended.
        """
        key = (prefix, name)
        if key in self._pu_ids:
            return self._pu_ids[key]
        keep = re.sub(r"[^A-Za-z0-9_]", "_", name) or "x"
        base = f"{prefix}_{keep}"
        nid = base
        if not re.search(r"[A-Za-z]", keep):
            nid = f"{base}_{abs(hash(name)) % 100000}"
        # guaranteed uniqueness when names of different entities repeat
        k = nid
        i = 0
        while k in self._pu_seen:
            i += 1
            k = f"{nid}_{i}"
        self._pu_seen.add(k)
        self._pu_ids[key] = k
        return k

    def _source_group(self, src: Source) -> str:
        """Determine the source store group/type from the type and details.

        Classification by the `type`/`detail` features of the source, extracted
        from M code (see `_source_from_m`). Covers: Hive/Impala, DBs
        (MSSQL/MySQL/Postgres/Oracle), files (Excel/CSV/JSON/Parquet/XML),
        HDFS/cloud, embedded and other.
        """
        t = (src.type or "").lower()
        d = (src.detail or "").lower()

        # --- initial categorization by type (from _source_from_m) ---
        if t in ("hive", "impala"):
            return "Hadoop / Hive"
        if t == "sql server":
            return "RDBMS (SQL Server)"
        if t == "mysql":
            return "RDBMS (MySQL)"
        if t == "postgresql":
            return "RDBMS (PostgreSQL)"
        if t == "oracle":
            return "RDBMS (Oracle)"
        if t in ("excel", "csv", "json", "parquet", "xml"):
            return t.upper()
        if t == "embedded":
            return "Embedded (M code)"

        # --- platforms / Hive by details ---
        if any(k in d for k in ("hive", "hadoop", "impala", "spark")):
            return "Hadoop / Hive"
        if "odbc" in t or (
            "dsn=" in d and not any(k in d for k in ("sqlserver", "mssql"))
        ):
            return "ODBC"

        # --- relational DBs by details ---
        if any(k in d for k in ("sqlserver", "ms sql", "mssql", "odbc driver 17")):
            return "RDBMS (SQL Server)"
        if any(k in d for k in ("mysql", "mariadb")):
            return "RDBMS (MySQL)"
        if any(k in d for k in ("postgres", "postgre", "npgsql", "cockroach")):
            return "RDBMS (PostgreSQL)"
        if "oracle" in d:
            return "RDBMS (Oracle)"
        if any(
            k in d
            for k in (
                "teradata",
                "snowflake",
                "redshift",
                "bigquery",
                "databricks",
                "athena",
                "synapse",
                "netezza",
                "vertica",
            )
        ):
            return "Columnar DB / Data Lakehouse"

        # --- files by details ---
        if any(
            k in d
            for k in ("xlsx", ".xls", "excel", "spreadsheet", "fileserver", "share")
        ):
            return "Excel"
        if any(k in d for k in (".csv", "text/csv")):
            return "CSV"
        if any(k in d for k in (".json", "application/json")):
            return "JSON"
        if any(k in d for k in (".parquet", "parquet")):
            return "Parquet"
        if any(k in d for k in (".xml", "application/xml")):
            return "XML"

        # --- HDFS / cloud / embedded / web ---
        if any(
            k in d
            for k in (
                "hdfs://",
                "wasbs://",
                "abfss://",
                "gs://",
                "s3://",
                "adls",
                "azure blob",
                "databricks dbfs",
            )
        ):
            return "HDFS / Object Storage"
        if "embedded" in d or "binary.decompress" in d:
            return "Embedded (M code)"
        if "sharepoint" in d or "onedrive" in d or "web" in t or "folder" in t:
            return "Files / Web"

        return "Other sources"

    def to_plantuml(self) -> str:
        """Generate the data-flow PlantUML diagram (wrapper).

        The diagram is built FROM the `to_json()` JSON -> single source `_render_plantuml_from_data`.
        """
        data = self.to_json(include_plantuml=False)
        return self._render_plantuml_from_data(data)

    def _render_plantuml_from_data(self, data: dict) -> str:
        """Build the PlantUML diagram from the lineage JSON structure (`to_json()`)."""
        from agentic_bi.lineage.lineage_plantuml_render import render_plantuml_from_data

        return render_plantuml_from_data(self, data)

==================== FILE: src/agentic_bi/lineage/lineage_plantuml_render.py ====================

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

==================== FILE: src/agentic_bi/lineage/lineage_brand.py ====================

"""Brand-compliance metrics of a dashboard page's elements.

Embedded in the data-lineage process: for each page it computes the compliance
of the **used fonts and colors** with the brand style. The result is compliance
percentages (fonts/colors), a level (`ok`/`warning`/`error`/`unknown`) and a
list of `color`/`font` findings.

This module is a **facade** over:
    lineage_brand_metrics.py - the metric computation
    lineage_brand_report.py  - the human-readable report + CLI

The single source of rules is :class:`agentic_bi.brand_config.BrandConfig`
(palette/ΔRGB tolerance/`allow_extra`/fonts/weights/severity). It is the same
config as the document audit (`brand_audit.py`), so tolerances and severity are
set in one place (`brand_config.yaml`).

The metrics go into:
- the `PbiLineage.to_json()` JSON -> the `brand` key (+ `pages[].brand`);
- the PlantUML diagram, layer 7 "Elements and palette" (metrics on the page node).

Neutral colors (R==G==B) are not violations. The primary accent is recognized
with a "near-accent" tolerance.

Public API:
    page_brand_metrics(page, cfg=None)  -> dict  - metrics of one page
    visual_brand_metrics(visual, cfg=None) -> dict - metrics of one visual
    brand_audit_pages(pages, cfg=None)  -> dict  - metrics of all pages + summary
    brand_label(metrics)                -> str   - a string for PlantUML/report
    format_report(audit)                -> str   - a human-readable report
    audit_pbix(path) / audit_json(path) -> dict  - run over a .pbix / lineage.json
"""

from __future__ import annotations

from agentic_bi.lineage.lineage_brand_metrics import (  # noqa: F401
    brand_audit_pages,
    brand_label,
    page_brand_metrics,
    visual_brand_metrics,
)
from agentic_bi.lineage.lineage_brand_report import (  # noqa: F401
    _main,
    audit_json,
    audit_pbix,
    format_report,
)

__all__ = [
    "audit_json",
    "audit_pbix",
    "brand_audit_pages",
    "brand_label",
    "format_report",
    "page_brand_metrics",
    "visual_brand_metrics",
]


if __name__ == "__main__":
    raise SystemExit(_main())

==================== FILE: src/agentic_bi/lineage/lineage_brand_metrics.py ====================

"""Brand-compliance metrics of a dashboard page's elements.

Embedded in the data-lineage process: for each page it computes the compliance
of the **used fonts and colors** with the corporate style. The result is
compliance percentages (fonts/colors), a level (`ok`/`warning`/`error`/`unknown`)
and a list of `color`/`font` findings.

The single source of rules is :class:`agentic_bi.brand_config.BrandConfig`
(palette/ΔRGB tolerance/`allow_extra`/fonts/weights/severity). It is the same
config as the document audit (`brand_audit.py`), so tolerances and severity are
set in one place (`brand_config.yaml`).

The metrics go into:
- the `PbiLineage.to_json()` JSON -> the `brand` key (+ `pages[].brand`);
- the PlantUML diagram, layer 7 "Elements and palette" (metrics on the page node);
- the flat matrix `lineage_table.py` ("Brand book · ..." columns) - right side.

Neutral colors (R==G==B) are not violations. The primary accent is recognized with a
"near-accent" tolerance (`#D0302A`/`#D3212A`).

Public API:
    page_brand_metrics(page, cfg=None)  -> dict  - metrics of one page
    brand_audit_pages(pages, cfg=None)  -> dict  - metrics of all pages + summary
    brand_label(metrics)                -> str   - a string for PlantUML/report
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# Font placeholders in the visual config (not real fonts).
_PLACEHOLDER_FONTS = {"+mn-lt", "+mj-lt", "+mn-ea", "+mj-ea", "themefont", ""}


def _load_config():
    """Lazy import of `BrandConfig` (no hard dependency) + YAML load."""
    pkg_dir = Path(__file__).resolve().parents[1]
    from agentic_bi.brand_config import BrandConfig  # type: ignore

    yaml_path = pkg_dir / "brand_config.yaml"
    if yaml_path.exists():
        try:
            return BrandConfig.load(yaml_path)
        except Exception as exc:  # noqa: BLE001 - config optional, default() exists
            _log.debug("brand_config.yaml load failed: %s", exc)
    return BrandConfig.default()


def _hex_from(token: str) -> str:
    """Extract '#rrggbb' from a lineage token ('hex#D32F2F', 'theme#0')."""
    if not token or not isinstance(token, str):
        return ""
    i = token.find("#")
    if i < 0:
        return ""
    v = token[i + 1 :].strip()
    if len(v) >= 6:
        v = v[:6]
    if len(v) != 6:
        return ""
    try:
        int(v, 16)
    except ValueError:
        return ""
    return "#" + v.lower()


def _is_neutral(hex_color: str) -> bool:
    h = hex_color.lstrip("#")
    return h[0:2] == h[2:4] == h[4:6]


def _clean_fonts(fonts: list[str] | None) -> list[str]:
    seen: list[str] = []
    for f in fonts or []:
        name = str(f).replace("\ufffd", "").strip()
        if name.lower() in _PLACEHOLDER_FONTS:
            continue
        if name and name not in seen:
            seen.append(name)
    return seen


def _pct(part: int, total: int) -> int | None:
    if total <= 0:
        return None
    return round(100 * part / total)


def _allow_extra(cfg) -> set[str]:
    """Normalize the config's `allow_extra` to lowercase '#rrggbb' (case-insensitive)."""
    out = set()
    for c in getattr(cfg, "allow_extra", []) or []:
        h = _hex_from(str(c)) or (str(c) if str(c).startswith("#") else "")
        if h:
            out.add(h.lower())
    return out


def _finding(
    rule_id: str, level: str, category: str, message: str, detail: str = ""
) -> dict:
    return {
        "rule_id": rule_id,
        "level": level,
        "category": category,
        "message": message,
        "detail": detail,
    }


def page_brand_metrics(page: dict, cfg=None) -> dict:
    """Brand-book compliance metrics of one page.

    Args:
        page: an element of the `pages` list from `PbiLineage.to_json()` (or a
            compatible dict with `colors[]` and `fonts[]` keys).
        cfg: :class:`BrandConfig`; defaults to `brand_config.yaml`/`brand.py`.

    Returns:
        A metrics dict: font/color percentages, level, findings.
    """
    if cfg is None:
        cfg = _load_config()

    raw_colors = {_hex_from(c) for c in page.get("colors", [])}
    raw_colors.discard("")
    chromatic = sorted(c for c in raw_colors if not _is_neutral(c))
    allow_extra = _allow_extra(cfg)
    off_palette = sorted(
        c for c in chromatic if cfg.match(c) is None and c not in allow_extra
    )
    has_accent = any((m := cfg.match(c)) and m.mandatory for c in chromatic)
    color_compliance = _pct(len(chromatic) - len(off_palette), len(chromatic))

    fonts = _clean_fonts(page.get("fonts"))
    allowed = [f.lower() for f in cfg.fonts_allowed]
    fallback = [f.lower() for f in cfg.fonts_fallback]
    brand_fonts = [f for f in fonts if any(a in f.lower() for a in allowed)]
    off_fonts = [
        f
        for f in fonts
        if not any(a in f.lower() for a in allowed)
        and not any(fb in f.lower() for fb in fallback)
    ]
    font_compliance = _pct(len(fonts) - len(off_fonts), len(fonts))

    # --- color/font findings (severity from the config) ---
    findings: list[dict] = []
    if chromatic and not has_accent:
        findings.append(
            _finding(
                "BRAND-ACCENT-MANDATORY",
                cfg.severity_of("BRAND-ACCENT-MANDATORY"),
                "color",
                "The mandatory primary accent #D32F2F was not found.",
            )
        )
    if off_palette:
        findings.append(
            _finding(
                "BRAND-PALETTE-MEMBERSHIP",
                cfg.severity_of("BRAND-PALETTE-MEMBERSHIP"),
                "color",
                "Colors outside the brand palette: " + ", ".join(off_palette) + ".",
            )
        )
    if off_fonts:
        findings.append(
            _finding(
                "FONT-FAMILY-BRAND",
                cfg.severity_of("FONT-FAMILY-BRAND"),
                "font",
                "Families outside the brand ones: " + ", ".join(off_fonts) + ".",
            )
        )

    parts = [v for v in (font_compliance, color_compliance) if v is not None]
    score = round(sum(parts) / len(parts)) if parts else None

    if not chromatic and not fonts:
        level = "unknown"
    elif any(f["level"] == "error" for f in findings):
        level = "error"
    elif findings:
        level = "warning"
    else:
        level = "ok"

    return {
        "fonts": {
            "total": len(fonts),
            "brand": len(brand_fonts),
            "allowed": len(fonts) - len(off_fonts),
            "off": off_fonts,
            "compliance": font_compliance,
        },
        "colors": {
            "total": len(chromatic),
            "palette": len(chromatic) - len(off_palette),
            "off": off_palette,
            "has_accent": has_accent,
            "compliance": color_compliance,
        },
        "score": score,
        "level": level,
        "findings": findings,
    }


def visual_brand_metrics(visual: dict, cfg=None) -> dict:
    """Fast brand metric of one visual (element).

    Unlike :func:`page_brand_metrics`, it does not build `findings` (for an
    element "has violation / not" is enough), so it is cheaper to call per visual.
    Returns ``{"fonts": {...}, "colors": {...}, "off": [...],
    "level": "ok"|"warning"|"error"|"unknown"}``.

    Args:
        visual: an element of `pages[].visuals[]` from `PbiLineage.to_json()`
            (`colors[]`, `fonts[]` keys).
        cfg: :class:`BrandConfig`; defaults to `brand_config.yaml`/`brand.py`.
    """
    if cfg is None:
        cfg = _load_config()

    raw_colors = {_hex_from(c) for c in visual.get("colors", [])}
    raw_colors.discard("")
    chromatic = sorted(c for c in raw_colors if not _is_neutral(c))
    off_palette = sorted(
        c for c in chromatic if cfg.match(c) is None and c not in _allow_extra(cfg)
    )
    has_accent = any((m := cfg.match(c)) and m.mandatory for c in chromatic)

    fonts = _clean_fonts(visual.get("fonts"))
    allowed = [f.lower() for f in cfg.fonts_allowed]
    fallback = [f.lower() for f in cfg.fonts_fallback]
    off_fonts = [
        f
        for f in fonts
        if not any(a in f.lower() for a in allowed)
        and not any(fb in f.lower() for fb in fallback)
    ]

    off = [f"color {c}" for c in off_palette] + [f"font {f}" for f in off_fonts]
    if not chromatic and not fonts:
        level = "unknown"
    elif chromatic and not has_accent:
        level = "error"
    elif off:
        level = "warning"
    else:
        level = "ok"
    return {
        "fonts": {
            "total": len(fonts),
            "off": off_fonts,
            "compliance": _pct(len(fonts) - len(off_fonts), len(fonts)),
        },
        "colors": {
            "total": len(chromatic),
            "off": off_palette,
            "has_accent": has_accent,
            "compliance": _pct(len(chromatic) - len(off_palette), len(chromatic)),
        },
        "off": off,
        "level": level,
    }


def brand_audit_pages(pages: list[dict], cfg=None) -> dict:
    """Compute metrics across all pages and an aggregated summary."""
    if cfg is None:
        cfg = _load_config()
    result = []
    font_scores: list[int] = []
    color_scores: list[int] = []
    off_pages: list[str] = []
    errors: list[str] = []
    for p in pages:
        m = page_brand_metrics(p, cfg)
        name = p.get("name", "?")
        result.append({"name": name, "metrics": m})
        if m["fonts"]["compliance"] is not None:
            font_scores.append(m["fonts"]["compliance"])
        if m["colors"]["compliance"] is not None:
            color_scores.append(m["colors"]["compliance"])
        if m["colors"]["off"] or m["fonts"]["off"]:
            off_pages.append(name)
        if m["level"] == "error":
            errors.append(name)

    def _avg(vals: list[int]) -> int | None:
        return round(sum(vals) / len(vals)) if vals else None

    summary = {
        "pages": len(pages),
        "ok": sum(1 for r in result if r["metrics"]["level"] == "ok"),
        "warnings": sum(1 for r in result if r["metrics"]["level"] == "warning"),
        "errors": len(errors),
        "unknown": sum(1 for r in result if r["metrics"]["level"] == "unknown"),
        "fonts_compliance": _avg(font_scores),
        "colors_compliance": _avg(color_scores),
        "off_brand_pages": off_pages,
        "error_pages": errors,
    }
    return {"summary": summary, "pages": result}


def brand_label(metrics: dict) -> str:
    """A short brand label for PlantUML/report (lines separated by '\\n')."""
    if not metrics:
        return "Brand: n/a"
    f = metrics.get("fonts", {})
    c = metrics.get("colors", {})
    fc = f.get("compliance")
    cc = c.get("compliance")
    lines = [f"Brand: fonts {fc if fc is not None else 'n/a'}%"]
    accent = "yes" if c.get("has_accent") else "no"
    lines.append(f"colors {cc if cc is not None else 'n/a'}% · accent: {accent}")
    return "\n".join(lines)


_LEVEL_ORDER = {"error": 3, "warning": 2, "ok": 1, "unknown": 0}

==================== FILE: src/agentic_bi/lineage/lineage_brand_report.py ====================

"""Reporting and CLI over the brand metrics of dashboard pages."""

from __future__ import annotations

import logging
from pathlib import Path

from agentic_bi.lineage.lineage_brand_metrics import (
    _LEVEL_ORDER,
    brand_audit_pages,
    brand_label,
    page_brand_metrics,
    visual_brand_metrics,
)

_log = logging.getLogger(__name__)


def _as_page_list(audit: dict) -> list[dict]:
    """Normalize audit `pages` to a list [{name, metrics}] (dict or list)."""
    pages = audit.get("pages", []) or []
    if isinstance(pages, dict):
        return [{"name": k, "metrics": v or {}} for k, v in pages.items()]
    return pages


def format_report(audit: dict) -> str:
    """A human-readable summary report across all pages (text)."""
    s = audit.get("summary", {})
    lines = [
        "Brand-style compliance (page elements)",
        (
            f"  pages: {s.get('pages', 0)}  -  ok: {s.get('ok', 0)}, "
            f"warnings: {s.get('warnings', 0)}, errors: {s.get('errors', 0)}, "
            f"no data: {s.get('unknown', 0)}"
        ),
        (
            f"  averages: fonts {s.get('fonts_compliance')}%, "
            f"colors {s.get('colors_compliance')}%"
        ),
        "",
    ]
    pages = sorted(
        _as_page_list(audit),
        key=lambda r: -_LEVEL_ORDER.get((r.get("metrics") or {}).get("level", ""), 0),
    )
    for r in pages:
        m = r.get("metrics") or {}
        f, c = m.get("fonts", {}) or {}, m.get("colors", {}) or {}
        accent = "yes" if c.get("has_accent") else "no"
        msgs = [x.get("message", "") for x in m.get("findings", [])]
        note = "; ".join(msgs) or "-"
        lines.append(
            f"  [{m.get('level', ''):>7}] {r.get('name', ''):<32} "
            f"fonts {f.get('compliance') if f.get('compliance') is not None else '-'}%  "
            f"colors {c.get('compliance') if c.get('compliance') is not None else '-'}%  "
            f"accent: {accent}"
        )
        if note != "-":
            lines.append(f"           {note}")
    return "\n".join(lines)


def audit_pbix(pbix_path: str | Path, brand_config: str | Path | None = None) -> dict:
    """Run the brand metrics over a .pbix (via `PbiLineage`)."""
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    with PbiLineage(str(pbix_path), brand_config=brand_config) as lg:
        data = lg.to_json(include_plantuml=False)
    return data.get("brand") or {"summary": {}, "pages": {}}


def audit_json(lineage_json: str | Path) -> dict:
    """Brand metrics from a ready lineage.json (the `brand` key)."""
    import json

    data = json.loads(Path(lineage_json).read_text(encoding="utf-8"))
    if data.get("brand"):
        return data["brand"]
    return brand_audit_pages(data.get("pages", []))


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(
        description="Dashboard brand-style compliance: metrics by page (fonts/colors)."
    )
    ap.add_argument("input", help="path to a .pbix or lineage.json")
    ap.add_argument(
        "--brand-config",
        default=None,
        help="brand rules config (default agentic_bi/brand_config.yaml)",
    )
    ap.add_argument(
        "--json", dest="json_out", default=None, help="save metrics to JSON"
    )
    args = ap.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        print(f"Input not found: {src}")
        return 2
    audit = (
        audit_json(src)
        if src.suffix.lower() in (".json",)
        else audit_pbix(src, args.brand_config)
    )
    print(format_report(audit))
    if args.json_out:
        Path(args.json_out).write_text(
            _json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nJSON: {args.json_out}")
    s = audit.get("summary", {})
    return 1 if s.get("errors") else 0


__all__ = [
    "audit_json",
    "audit_pbix",
    "brand_audit_pages",
    "brand_label",
    "format_report",
    "page_brand_metrics",
    "visual_brand_metrics",
]


if __name__ == "__main__":
    raise SystemExit(_main())

