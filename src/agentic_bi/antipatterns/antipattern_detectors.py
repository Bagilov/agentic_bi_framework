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


def _calculate_without_filter(expr: str) -> bool:
    """Whether a `CALCULATE(...)` call has no top-level filter argument.

    Scans each `CALCULATE(` occurrence with balanced parentheses so a nested call
    (`CALCULATE(SUM([A]))`) is seen in full; it is a smell only when there is no
    comma at the top level of that call (a comma would introduce a filter).
    """
    upper = expr.upper()
    idx = upper.find("CALCULATE(")
    while idx != -1:
        depth = 0
        top_comma = False
        for ch in expr[idx + len("CALCULATE") :]:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                top_comma = True
        if not top_comma:
            return True
        idx = upper.find("CALCULATE(", idx + len("CALCULATE("))
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

    # CALCULATE( without a filter): a `CALCULATE` whose call has no top-level
    # comma (balanced-paren scan, so `CALCULATE(SUM([A]))` is caught).
    if _calculate_without_filter(expr):
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
