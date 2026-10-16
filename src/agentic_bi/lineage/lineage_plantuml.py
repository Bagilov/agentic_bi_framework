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
