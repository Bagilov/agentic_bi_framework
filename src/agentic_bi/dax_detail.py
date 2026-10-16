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
