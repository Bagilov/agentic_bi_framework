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
