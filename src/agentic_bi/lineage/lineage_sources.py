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
