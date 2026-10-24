# Bundle 2: antipatterns + dax_detail

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/antipatterns/__init__.py ====================

"""Vendored DAX/M antipattern analysis."""

==================== FILE: src/agentic_bi/antipatterns/antipattern_registry.py ====================

"""Antipattern registry: definitions of all detected antipatterns."""

from __future__ import annotations

from dataclasses import dataclass


# --------------------------------------------------------------------------- #
#  Antipattern registry: id -> description
# --------------------------------------------------------------------------- #
@dataclass
class Antipattern:
    """A definition of one antipattern."""

    id: str
    name: str
    level: str  # source | measure | calc_column | table | board
    critical: bool
    detail: str
    fix: str


ANTIPATTERNS: list[Antipattern] = [
    # ---------- sources (M code) ----------
    Antipattern(
        "m.hardcoded_paths",
        "Hardcoded file paths",
        "source",
        False,
        "A file path is hardcoded in M code (File.Contents('C:\\...'))",
        "Move the path into a Power Query parameter / environment config",
    ),
    Antipattern(
        "m.fixed_date",
        "Fixed date in a query",
        "source",
        False,
        "A literal date in an SQL template/M code (#date(2026,1,1), '2026-')",
        "Replace with dynamic period bounds via a parameter/calendar",
    ),
    Antipattern(
        "m.local_now",
        "DateTime.LocalNow() (unstable)",
        "source",
        False,
        "Using DateTime.LocalNow()/FixedLocalNow()",
        "For 'as of today' use a reporting-period parameter",
    ),
    Antipattern(
        "m.whole_table",
        "Reading a table without a source filter",
        "source",
        True,
        "SELECT * / no WHERE - the whole table is pulled into M",
        "Push WHERE/projection to the source (query folding)",
    ),
    Antipattern(
        "m.no_parameterization",
        "Hardcoded DSN/connection without a parameter",
        "source",
        False,
        "Odbc.Query('dsn=...', ...) with a hardcoded DSN in the text",
        "Parameterize the source, use shared wrapper functions",
    ),
    Antipattern(
        "m.heavy_steps",
        "Heavy M steps without folding",
        "source",
        True,
        "Multiple Table.AddColumn/Transform after the source",
        "Move processing to the source/mart, not M",
    ),
    Antipattern(
        "m.multi_source_union",
        "Assembly from many sources without a contract",
        "source",
        False,
        "Several File.Contents/Odbc.Query in one let",
        "A single contract/mart instead of gluing in M",
    ),
    Antipattern(
        "m.json_expand_fragile",
        "Expanding source JSON into fixed columns",
        "source",
        True,
        "JSON from the source is parsed into hardcoded columns; when the key "
        "set in the source changes, the columns disappear and the refresh fails "
        "with 'column wasn't found'",
        "Require a stable JSON contract from the source (a fixed key set or null "
        "instead of absence) and/or build columns dynamically from the actual keys "
        "(Record.FieldOrDefault, Table.ColumnNames); do not hardcode the columns",
    ),
    # ---------- DAX measures ----------
    Antipattern(
        "dax.calculate_no_filter",
        "CALCULATE without a filter (empty wrapper)",
        "measure",
        False,
        "CALCULATE(<expr>) without a context modifier",
        "Remove CALCULATE; keep it only with a real filter",
    ),
    Antipattern(
        "dax.row_scan",
        "Row-by-row iteration (SUMX/EARLIER/FILTER ALL)",
        "measure",
        True,
        "SUMX / EARLIER / FILTER(ALL()) in a measure",
        "Replace with native aggregates/context design",
    ),
    Antipattern(
        "dax.filter_all",
        "FILTER/ALL without need",
        "measure",
        True,
        "FILTER(ALL(...)) / ALL( removes context",
        "Use ALLEXCEPT/ALLSELECTED/REMOVEFILTERS surgically",
    ),
    Antipattern(
        "dax.crossjoin",
        "CROSSJOIN/GENERATE (Cartesian)",
        "measure",
        True,
        "CROSSJOIN( or GENERATE( in an expression",
        "Rework the model/mart instead of a Cartesian product",
    ),
    Antipattern(
        "dax.hardcoded_value",
        "Hardcoded thresholds in measure code",
        "measure",
        False,
        "A literal number/string inside IF/SWITCH",
        "Move thresholds into parameters/config/a table",
    ),
    Antipattern(
        "dax.measure_arith_ref",
        "Arithmetic over measure references",
        "measure",
        True,
        "'1 - [Measure]' / '[A] + [B]' without a filter context",
        "Wrap in CALCULATE / use a correct context",
    ),
    Antipattern(
        "dax.isblank_default",
        "IF(ISBLANK(x), '...', x) as a default",
        "measure",
        False,
        "IF(ISBLANK( <literal> )) for substitution",
        "Use COALESCE(x, default) or a type-safe measure",
    ),
    Antipattern(
        "dax.var_no_return",
        "Many VARs and one RETURN (branching)",
        "measure",
        False,
        "Several VARs, a single RETURN at the end",
        "Split into separate measures / simplify the logic",
    ),
    Antipattern(
        "dax.switch_const",
        "SWITCH over literals (measure bloat)",
        "measure",
        False,
        "SWITCH( SELECTEDVALUE( ... N constant branches)",
        "Parameterize the category selection instead of N branches",
    ),
    # ---------- calculated columns ----------
    Antipattern(
        "dax.format_column",
        "FORMAT() in a calculated column",
        "calc_column",
        True,
        "FORMAT(date/number) in dax_columns.Expression",
        "Format at the visual level, do not materialize a date string",
    ),
    Antipattern(
        "dax.calc_business_logic",
        "Business logic in a calculated column",
        "calc_column",
        True,
        "Complex IF/SWITCH in a business-table column",
        "Move to a measure/mart; a column materializes and slows things down",
    ),
    Antipattern(
        "dax.date_from_raw",
        "Date access without a calendar table",
        "calc_column",
        False,
        "YEAR([Date])/MONTH([Date]) over a raw date",
        "Use a calendar table with relationships",
    ),
    # ---------- tables ----------
    Antipattern(
        "dax.many_measures_table",
        "Table overloaded with measures",
        "table",
        False,
        ">30 measures in one table",
        "Group measures by subject table/folders",
    ),
    Antipattern(
        "dax.duplicate_measure_pattern",
        "Repeating same-type measures",
        "table",
        True,
        "N measures with the same CALCULATE(count(...)) template",
        "Parameterize SWITCH/dynamic category selection",
    ),
    # ---------- dashboard ----------
    Antipattern(
        "board.page_overload",
        "Page overloaded with visuals",
        "board",
        False,
        "n_visuals > 15 on a page",
        "Split the page, use bookmarks",
    ),
    Antipattern(
        "board.decor_heavy",
        "Many decorative elements",
        "board",
        False,
        "shape/textbox > 50% of page elements",
        "Move decor into the layout, do not mix it with data",
    ),
    Antipattern(
        "board.unbound_page",
        "Page without data",
        "board",
        False,
        "A page without any table bindings",
        "Remove it or explicitly mark it as a reference page",
    ),
    Antipattern(
        "board.color_overuse",
        "Palette overuse",
        "board",
        False,
        "Unique colors on a page > 10",
        "Reduce the palette to the brand one",
    ),
]


def _registry() -> dict[str, Antipattern]:
    return {a.id: a for a in ANTIPATTERNS}


# --------------------------------------------------------------------------- #
#  Per-level detectors

==================== FILE: src/agentic_bi/antipatterns/antipattern_detectors.py ====================

"""Per-level detectors: scan M code / DAX measures / calc columns / tables / board."""

from __future__ import annotations

import re

from agentic_bi.antipatterns.antipattern_registry import (
    Antipattern,
    _registry,
)


def _fragile_json_expand(m_code: str) -> bool:
    """Whether there is fragile expansion of source JSON into fixed columns.

    Fires when M takes a source JSON column (e.g. ``*_params``) and expands it
    into hardcoded columns without guarding against a change in the source key set.
    """
    has_json = any(
        k in m_code
        for k in ("Json.Document(", "Table.ExpandRecordColumn(", "Record.Field(")
    )
    # hardcoded "expanded" columns from source JSON - a marker of fragile
    # expansion even when wrapped in a custom function.
    if re.search(r'"[A-Za-z0-9_]+_params_[A-Za-z0-9_]+"', m_code):
        return True
    if not has_json:
        return False
    # Table.ExpandRecordColumn with an explicit name list and no dynamic guard
    if (
        "Table.ExpandRecordColumn(" in m_code
        and "Record.FieldOrDefault" not in m_code
        and "Table.ColumnNames" not in m_code
    ):
        return True
    return False


def analyze_source_m(m_code: str, table: str) -> list[dict]:
    """Find antipatterns in a source's M code (Power Query)."""
    out = []
    reg = _registry()
    if not isinstance(m_code, str):
        return out
    hits: list[str] = []

    if re.search(r'File\.Contents\(\s*"[A-Za-z]:\\\\|\\\\', m_code):
        hits.append("m.hardcoded_paths")
    if re.search(r"#date\(\s*\d{4}\s*,", m_code) or re.search(
        r"'(19|20)\d{2}-", m_code
    ):
        hits.append("m.fixed_date")
    if "DateTime.LocalNow(" in m_code or "DateTime.FixedLocalNow(" in m_code:
        hits.append("m.local_now")
    if re.search(r"SELECT\s+\*", m_code, re.IGNORECASE) or (
        re.search(r"SELECT", m_code, re.IGNORECASE)
        and not re.search(r"\bWHERE\b", m_code, re.IGNORECASE)
    ):
        hits.append("m.whole_table")
    # hardcoded DSN in Odbc.Query("dsn=...", ...)
    if re.search(r'Odbc\.Query\(\s*"(dsn=[^"]+)"', m_code):
        hits.append("m.no_parameterization")
    # heavy steps
    heavy = len(
        re.findall(r"Table\.(AddColumn|TransformColumnTypes|RepeatedField)", m_code)
    )
    if heavy >= 4:
        hits.append("m.heavy_steps")
    # several glued sources
    n_conn = len(re.findall(r"(Odbc\.Query|File\.Contents)\(", m_code))
    if n_conn > 1:
        hits.append("m.multi_source_union")
    # fragile expansion of source JSON into fixed columns
    if _fragile_json_expand(m_code):
        hits.append("m.json_expand_fragile")

    return _emit(hits, reg, level_name="source", scope_name=table)


def analyze_measure(name: str, expr: str) -> list[dict]:
    """Find antipatterns in a DAX measure expression."""
    out = []
    reg = _registry()
    if not isinstance(expr, str):
        return out
    hits: list[str] = []

    # CALCULATE( without a filter) - an approximation
    if (
        re.search(r"CALCULATE\s*\(\s*[A-Za-z_\[\]\s'\.]+\s*\)", expr)
        and "CALCULATE" in expr
        and not re.search(r"CALCULATE\s*\([^)]*,[^)]*\)", expr)
    ):
        hits.append("dax.calculate_no_filter")
    if re.search(r"\bSUMX\s*\(", expr, re.IGNORECASE) or re.search(
        r"\bEARLIER\s*\(", expr, re.IGNORECASE
    ):
        hits.append("dax.row_scan")
    if re.search(r"FILTER\s*\(\s*ALL\s*\(", expr, re.IGNORECASE) or re.search(
        r"CALCULATE\s*\([^)]*ALL\s*\(", expr, re.IGNORECASE
    ):
        hits.append("dax.filter_all")
    if re.search(r"\bCROSSJOIN\s*\(", expr, re.IGNORECASE) or re.search(
        r"\bGENERATE\s*\(", expr, re.IGNORECASE
    ):
        hits.append("dax.crossjoin")
    if re.search(r"(=|RETURN\s)1\s*-\s*\[", expr) or re.search(
        r"\[\w+\]\s*[+\-*/]\s*\[", expr
    ):
        hits.append("dax.measure_arith_ref")
    if re.search(r"IF\s*\(\s*ISBLANK\s*\(", expr, re.IGNORECASE):
        hits.append("dax.isblank_default")
    n_var = len(re.findall(r"\bVAR\b", expr, re.IGNORECASE))
    n_ret = len(re.findall(r"\bRETURN\b", expr, re.IGNORECASE))
    if n_var > 3 and n_ret <= 1:
        hits.append("dax.var_no_return")
    if (
        re.search(r"SWITCH\s*\([^)]*\n?\s*\)", expr, re.IGNORECASE)
        and expr.count("SWITCH")
        and expr.count(",") > 6
    ):
        hits.append("dax.switch_const")
    if re.search(r'"\d+"|\b\d{2,4}\b', expr) and ("IF(" in expr or "SWITCH(" in expr):
        # a constant next to IF/SWITCH - likely a hard threshold; only a low marker
        hits.append("dax.hardcoded_value")
    return _emit(hits, reg, level_name="measure", scope_name=name)


def analyze_calc_column(table: str, name: str, expr: str) -> list[dict]:
    """Find antipatterns in a calculated column's DAX expression."""
    out = []
    reg = _registry()
    if not isinstance(expr, str):
        return out
    is_tech_calendar = table.startswith(("DateTableTemplate_", "LocalDateTable_"))
    hits: list[str] = []
    # FORMAT in a calendar column (Month) is fine; outside a calendar it is a smell
    if re.search(r"\bFORMAT\s*\(", expr, re.IGNORECASE) and not is_tech_calendar:
        hits.append("dax.format_column")
    if not is_tech_calendar and re.search(
        r"\bIF\s*\([^)]*IF\s*\(|\bSWITCH\s*\(", expr, re.IGNORECASE
    ):
        hits.append("dax.calc_business_logic")
    # YEAR/MONTH over a raw date - outside technical calendar tables (which is fine)
    if not is_tech_calendar and re.search(
        r"\b(?:YEAR|MONTH|QUARTER)\s*\(\[?Date\]?", expr, re.IGNORECASE
    ):
        hits.append("dax.date_from_raw")
    return _emit(hits, reg, level_name="calc_column", scope_name=f"{table}.{name}")


def analyze_table(tbl: str, info: dict, measures_exprs: list[str]) -> list[dict]:
    """Aggregated table-level antipatterns."""
    reg = _registry()
    hits: list[str] = []
    n_measures = info.get("measures_count", 0)
    if n_measures > 30:
        hits.append("dax.many_measures_table")
    # repeating measure pattern
    if len(measures_exprs) >= 3:
        base = re.sub(r'".*?"', '"X"', " ".join(measures_exprs))
        base = re.sub(
            r"CALCULATE\s*\(\s*count\s*\(\s*'?[^']+?'?\[[^\]]+\]",
            "CALCULATE(count('[t]'[c])",
            base,
        )
        if len(measures_exprs) >= 4 and len(set(measures_exprs)) == len(measures_exprs):
            n_calc_count = sum(
                "CALCULATE" in e and "count(" in e.lower() for e in measures_exprs
            )
            if n_calc_count >= 3:
                hits.append("dax.duplicate_measure_pattern")
    return _emit(hits, reg, level_name="table", scope_name=tbl)


def analyze_board(meta: dict, pages: list[dict], total: dict) -> list[dict]:
    """Dashboard-level antipatterns (by page)."""
    reg = _registry()
    hits: list[str] = []
    for p in pages:
        n = p.get("n_visuals", 0)
        if n > 15:
            hits.append("board.page_overload")
        elems = p.get("elements", {})
        decor = elems.get("shape", 0) + elems.get("textbox", 0) + elems.get("image", 0)
        if n and decor / n > 0.5:
            hits.append("board.decor_heavy")
        if n and not p.get("tables"):
            hits.append("board.unbound_page")
        if len(p.get("colors", [])) > 10:
            hits.append("board.color_overuse")
    return _emit(hits, reg, level_name="board", scope_name=meta.get("file", "board"))


def _emit(
    hits: list[str], reg: dict[str, Antipattern], level_name: str, scope_name: str
) -> list[dict]:
    """Turn id hits into found antipattern records."""
    out = []
    seen = set()
    for hid in hits:
        if hid in seen:
            continue
        seen.add(hid)
        a = reg.get(hid)
        if not a:
            continue
        out.append(
            {
                "id": a.id,
                "name": a.name,
                "level": a.level,
                "critical": a.critical,
                "detail": a.detail,
                "fix": a.fix,
                "scope": scope_name,
                "level_name": level_name,
            }
        )
    return out


# --------------------------------------------------------------------------- #
#  Assemble the full metric
# --------------------------------------------------------------------------- #

==================== FILE: src/agentic_bi/antipatterns/pbi_antipatterns.py ====================

"""Antipattern analysis of Power BI calculations/scripts.

Scans ALL dashboard calculations - both at the **source** level (Power Query M
code) and **inside the dashboard** (DAX measures, calculated columns) - and
returns a JSON metric of **antipatterns tied to the analyzed level**:

    source       -> table (source), M code
    table        -> model table (aggregated: measures/columns/source)
    measure      -> a specific DAX measure
    calc_column  -> a specific calculated column
    board        -> the whole dashboard (summary statistics)

Every finding: {id, name, level, critical, detail, fix}.

This module is a **facade** over focused submodules:
    antipattern_registry.py  - Antipattern dataclass + ANTIPATTERNS list
    antipattern_detectors.py - per-level detectors

The data source is a `.pbix` (via `PbiLineage`), from which `power_query` (M code),
`dax_measures.Expression`, `dax_columns.Expression` are available.

Usage:
    python -m agentic_bi.antipatterns.pbi_antipatterns "C:\\path\\to\\report.pbix" -o out.json
    python -m agentic_bi.antipatterns.pbi_antipatterns "C:\\path\\to\\report.pbix" --summary

CLI exit codes: 0 on success, 2 on a bad input (missing/unreadable .pbix).
Default output is `output_files/<name>_antipatterns.json` (relative to the CWD).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from agentic_bi.antipatterns.antipattern_detectors import (  # noqa: F401
    analyze_board,
    analyze_calc_column,
    analyze_measure,
    analyze_source_m,
    analyze_table,
)
from agentic_bi.antipatterns.antipattern_registry import (  # noqa: F401
    ANTIPATTERNS,
    Antipattern,
    _registry,
)


def analyze_board_objects(m: object, pages: list[dict] | None = None) -> dict:
    """Build the full antipattern metric by level.

    Args:
        m: a pbixray object (self._model) - with tables, dax_measures,
            dax_columns, power_query, schema, relationships.
        pages: a list of pages from lineage (for board patterns), optional.

    Returns:
        dict {meta, summary, findings}
    """
    reg = _registry()
    meta = {
        "type": "pbi_antipatterns",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "anti_patterns": len(reg),
    }

    findings: dict[str, list] = defaultdict(list)  # level -> list of findings

    # ---- sources (M code) ----
    pq = m.power_query
    if hasattr(pq, "iterrows"):
        for _, row in pq.iterrows():
            findings["source"] += analyze_source_m(row["Expression"], row["TableName"])
    else:
        for tbl, expr in pq.items():
            findings["source"] += analyze_source_m(expr, tbl)

    # ---- DAX measures ----
    measures_exprs_by_table: dict[str, list[str]] = defaultdict(list)
    for _, row in m.dax_measures.iterrows():
        t = row["TableName"]
        expr = row["Expression"]
        findings["measure"] += analyze_measure(row["Name"], expr)
        measures_exprs_by_table[t].append(expr)

    # ---- calculated columns ----
    for _, row in m.dax_columns.iterrows():
        findings["calc_column"] += analyze_calc_column(
            row["TableName"], row["ColumnName"], row["Expression"]
        )

    # ---- tables (aggregated) ----
    tables_json = {}
    n_cols_by_table = defaultdict(int)
    for _, row in m.schema.iterrows():
        n_cols_by_table[row["TableName"]] += 1
    for t in m.tables:
        tables_json[t] = {
            "measures_count": len(measures_exprs_by_table.get(t, [])),
            "columns_count": n_cols_by_table.get(t, 0),
        }
        exprs = [e for e in measures_exprs_by_table.get(t, []) if isinstance(e, str)]
        findings["table"] += analyze_table(t, tables_json[t], exprs)

    # ---- board ----
    total = {
        "sources": len(m.power_query),
        "measures": len(m.dax_measures),
        "calc_columns": len(m.dax_columns),
        "tables": len(m.tables),
    }
    if pages is not None:
        findings["board"] = analyze_board(
            {"file": meta.get("file", "board")}, pages, total
        )

    # ---- summary by id ----
    id_counter: Counter = Counter()
    for items in findings.values():
        for it in items:
            id_counter[it["id"]] += 1

    return {
        "meta": meta,
        "summary": {
            "total_findings": sum(len(v) for v in findings.values()),
            "by_level": {lv: len(v) for lv, v in findings.items()},
            "by_id": dict(id_counter),
            "critical": sum(1 for v in findings.values() for it in v if it["critical"]),
            "counts": total,
        },
        "findings": {lv: findings[lv] for lv in sorted(findings)},
    }


def analyze_pbix(pbix_path: str) -> dict:
    """Analyze a .pbix for antipatterns: input .pbix, output JSON metric."""
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    with PbiLineage(pbix_path) as lg:
        m = lg._model
        pages_json = lg.to_json(include_plantuml=False).get("pages", [])
        data = analyze_board_objects(m, pages=pages_json)
        data["meta"]["file"] = lg.pbix_path.name
        return data


def _write(data: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    from agentic_bi.cli_support import fail, run_boundary

    parser = argparse.ArgumentParser(
        prog="agentic-bi-antipatterns",
        description="Antipattern analysis of Power BI calculations (source M code + DAX inside the board).\n"
        "Output: JSON with an antipattern metric tied to the level (source/measure/calc/table/board).",
    )
    parser.add_argument("pbix", help="path to the .pbix file")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="output JSON (default output_files/<name>_antipatterns.json)",
    )
    parser.add_argument(
        "--summary", action="store_true", help="print a short console summary"
    )
    args = parser.parse_args(argv)

    pbix = Path(args.pbix)
    if not pbix.exists():
        return fail("agentic-bi-antipatterns", f"input not found: {pbix}")

    def body() -> int:
        data = analyze_pbix(str(pbix))
        out = (
            Path(args.output)
            if args.output
            else Path("output_files") / f"{pbix.stem}_antipatterns.json"
        )
        _write(data, out)
        print(f"Antipatterns saved: {out}")
        if args.summary:
            s = data["summary"]
            print(f"Total findings: {s['total_findings']} (critical: {s['critical']})")
            for lv, cnt in s["by_level"].items():
                print(f"  {lv:12} {cnt}")
            print("By type:")
            for aid, cnt in sorted(s["by_id"].items(), key=lambda kv: -kv[1]):
                name = _registry().get(aid).name if _registry().get(aid) else aid
                print(f"  {aid:32} x{cnt}  {name}")
        return 0

    return run_boundary(body, prog="agentic-bi-antipatterns")


if __name__ == "__main__":
    raise SystemExit(main())

==================== FILE: src/agentic_bi/dax_detail.py ====================

"""Deep DAX/M analysis of a `.pbix` for data-distortion diagnostics.

Covers the inline techniques from real cases: extracting from a `.pbix` all DAX
measures with full expressions, calculated columns, Power Query M code and
markers indicating a distortion risk (hardcoded thresholds, FILTER(ALL), fixed
dates/paths, LocalNow). Returns a JSON-serializable dict.

Usage (CLI):
    python -m agentic_bi.dax_detail "C:\\\\path\\\\to\\\\report.pbix" -o out.json
    python -m agentic_bi.dax_detail "C:\\\\path\\\\to\\\\report.pbix" --summary

As an API:
    from agentic_bi.dax_detail import analyze_dax_detail
    data = analyze_dax_detail("C:/path/to/report.pbix")
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from agentic_bi.dax_markers import (
    DAX_DISTORT_MARKERS,
    M_DISTORT_MARKERS,
)
from agentic_bi.dax_markers import (
    scan_markers as _scan,
)

logger = logging.getLogger(__name__)

OUT_DIR = Path(__file__).resolve().parent / "output_files"


def _flatten_exprs(measures: list[dict]) -> str:
    """Join all measure expressions into one string for fast scanning."""
    return "\n".join(m.get("expr") or "" for m in measures)


def extract_measures(pbix: Path) -> list[dict]:
    """Extract all DAX measures with expressions via pbixray.

    Args:
        pbix: path to the .pbix.

    Returns:
        List[dict]: [{table, name, expr}].
    """
    from pbixray import PBIXRay

    xr = PBIXRay(str(pbix))
    try:
        dm = xr.dax_measures
        out: list[dict] = []
        for _, row in dm.iterrows():
            out.append(
                {
                    "table": str(row.get("TableName") or "").strip(),
                    "name": str(row.get("Name") or "").strip(),
                    "expr": str(row.get("Expression") or "").strip(),
                }
            )
        return out
    finally:
        xr.close()


def extract_calc_columns(pbix: Path) -> list[dict]:
    """Extract all calculated columns with expressions.

    Args:
        pbix: path to the .pbix.

    Returns:
        List[dict]: [{table, name, expr}].
    """
    from pbixray import PBIXRay

    xr = PBIXRay(str(pbix))
    try:
        dc = xr.dax_columns
        out: list[dict] = []
        for _, row in dc.iterrows():
            out.append(
                {
                    "table": str(row.get("TableName") or "").strip(),
                    "name": str(row.get("ColumnName") or "").strip(),
                    "expr": str(row.get("Expression") or "").strip(),
                }
            )
        return out
    finally:
        xr.close()


def extract_power_query(pbix: Path) -> dict[str, str]:
    """Extract the M code of all Power Query tables.

    Args:
        pbix: path to the .pbix.

    Returns:
        Dict[table_name -> m_expression].
    """
    from pbixray import PBIXRay

    xr = PBIXRay(str(pbix))
    try:
        pq = xr.power_query
        out: dict[str, str] = {}
        for _, row in pq.iterrows():
            out[str(row["TableName"])] = str(row["Expression"])
        return out
    finally:
        xr.close()


def _scan_markers(expr: str, markers: dict) -> list[str]:
    """Return the list of markers that fired for one expression."""
    return _scan(expr, markers)


def build_distort_index(
    measures: list[dict], calc_columns: list[dict], power_query: dict[str, str]
) -> dict:
    """Build a distortion-risk index across the DAX and M layers.

    Args:
        measures: result of extract_measures.
        calc_columns: result of extract_calc_columns.
        power_query: result of extract_power_query.

    Returns:
        Dict: {measure, calc_column, source} -> {marker -> [names]}.
    """
    idx: dict = {"measure": {}, "calc_column": {}, "source": {}}

    def _name(o: dict) -> str:
        return f"{o.get('table')}.{o.get('name')}"

    for m in measures:
        for hit in _scan_markers(m.get("expr") or "", DAX_DISTORT_MARKERS):
            if hit == "hardcoded_threshold" and not re.search(
                r"\b0\.\d{2,}\b|[<>]=?\s*0\.\d", m.get("expr") or ""
            ):
                continue
            idx["measure"].setdefault(hit, []).append(_name(m))

    for c in calc_columns:
        for hit in _scan_markers(c.get("expr") or "", DAX_DISTORT_MARKERS):
            if hit == "hardcoded_threshold" and not re.search(
                r"\b0\.\d{2,}\b|[<>]=?\s*0\.\d", c.get("expr") or ""
            ):
                continue
            idx["calc_column"].setdefault(hit, []).append(_name(c))

    for tbl, expr in power_query.items():
        for hit in _scan_markers(expr, M_DISTORT_MARKERS):
            idx["source"].setdefault(hit, []).append(tbl)

    return idx


def _extract_thresholds(measures: list[dict]) -> list[dict]:
    """Extract "traffic-light" thresholds (<=/>= number) from measures."""
    out: list[dict] = []
    for m in measures:
        expr = m.get("expr") or ""
        found = re.findall(r"([<>]=?)\s*(\d+\.\d+)", expr)
        if found:
            out.append(
                {
                    "measure": f"{m.get('name')}",
                    "table": m.get("table"),
                    "thresholds": found,
                }
            )
    return out


def analyze_dax_detail(pbix: str | Path, run_antipatterns: bool = True) -> dict:
    """Full DAX/M analysis of a `.pbix`: measures, columns, M, distortion indices.

    Args:
        pbix: path to the .pbix artifact.
        run_antipatterns: also run the existing antipattern analysis and attach
            its summary to the result.

    Returns:
        Dict: file/name/analyzed_at, summary (counts), extraction (measures,
        columns, power_query), distort (risk index), antipatterns (summary of the
        existing analysis if run_antipatterns), thresholds.
    """
    pbix = Path(pbix).resolve()
    if not pbix.exists():
        raise FileNotFoundError(f"File not found: {pbix}")

    measures = extract_measures(pbix)
    calc_columns = extract_calc_columns(pbix)
    power_query = extract_power_query(pbix)

    # count measures per table
    per_table: dict[str, int] = {}
    for m in measures:
        per_table[m["table"]] = per_table.get(m["table"], 0) + 1

    result = {
        "file": pbix.name,
        "name": pbix.stem,
        "analyzed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "measures_total": len(measures),
            "measures_by_table": per_table,
            "calc_columns_total": len(calc_columns),
            "power_query_tables": list(power_query.keys()),
        },
        "extraction": {
            "measures": measures,
            "calc_columns": calc_columns,
            "power_query": power_query,
        },
        "distort": build_distort_index(measures, calc_columns, power_query),
        "thresholds": _extract_thresholds(measures),
    }

    if run_antipatterns:
        try:
            from agentic_bi.antipatterns import pbi_antipatterns as ap

            # call without stdout output: build in-memory
            res = ap.analyze_pbix(str(pbix))
            result["antipatterns"] = res.get("summary", {})
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not run antipattern analysis: %s", e)
            result["antipatterns"] = {"error": str(e)}

    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(
        description="DAX/M analysis of a .pbix: measures, columns, M, distortion risks"
    )
    p.add_argument("pbix", help="path to the .pbix artifact")
    p.add_argument(
        "-o",
        "--out",
        default=None,
        help="path to the JSON result file (default output_files/)",
    )
    p.add_argument(
        "--no-antipatterns",
        action="store_true",
        help="do not attach the antipattern summary",
    )
    p.add_argument(
        "--summary",
        action="store_true",
        help="print only the summary, without the JSON dump",
    )
    args = p.parse_args(argv)

    data = analyze_dax_detail(args.pbix, run_antipatterns=not args.no_antipatterns)

    if args.summary:
        s = data["summary"]
        print(
            f"Measures: {s['measures_total']} | Columns: {s['calc_columns_total']} | "
            f"PQ tables: {len(s['power_query_tables'])}"
        )
        dist = data["distort"]
        for level, markers in dist.items():
            if markers:
                print(f"[{level}]")
                for marker, names in markers.items():
                    print(f"   {marker}: {len(names)}")
        return 0

    out_path = (
        Path(args.out)
        if args.out
        else OUT_DIR / "dax_detail" / f"{Path(args.pbix).stem}_dax.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(data, ensure_ascii=False, indent=2))
    logger.info("Saved: %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

