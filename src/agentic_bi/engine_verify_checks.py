"""Structural checks of a produced `.pbix` (container/layout/bindings/data)."""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from agentic_bi.engine_verify_core import (
    CheckResult,
    _check,
    _iter_visuals,
    _resolve_qref,
    spec_objects,
)

logger = logging.getLogger(__name__)


# ─── checks ───────────────────────────────────────────────────


def verify_container(pbix: Path) -> list[CheckResult]:
    """OPC container integrity."""
    pbix = Path(pbix)
    out = [_check("pbix exists", pbix.exists(), str(pbix))]
    if not pbix.exists():
        return out
    out.append(_check("zip valid (no CRC errors)", _zip_ok(pbix)))
    with zipfile.ZipFile(pbix) as z:
        names = set(z.namelist())
    for member in ("Report/Layout", "DataModel", "[Content_Types].xml"):
        out.append(_check(f"member present: {member}", member in names))
    return out


def _zip_ok(pbix: Path) -> bool:
    try:
        with zipfile.ZipFile(pbix) as z:
            return z.testzip() is None
    except zipfile.BadZipFile:
        return False


def verify_layout(
    layout: dict,
    spec: dict,
    pages: dict[str, int] | None = None,
    expected_types: set[str] | None = None,
) -> list[CheckResult]:
    """Check the Layout pages and visuals.

    pages - expected page name -> number of visuals (optional).
    expected_types - allowed visualType values (not checked by default).
    """
    out: list[CheckResult] = []
    sections = layout.get("sections", [])
    out.append(_check("has pages", bool(sections), "layout has no sections"))

    if pages is not None:
        names = {s.get("displayName") for s in sections}
        out.append(
            _check(
                "page count",
                len(sections) == len(pages),
                f"expected={len(pages)} actual={len(sections)}",
            )
        )
        for name, n in pages.items():
            out.append(_check(f"page present: {name}", name in names))
            if name in names:
                sec = next(s for s in sections if s.get("displayName") == name)
                actual = len(sec.get("visualContainers", []))
                out.append(
                    _check(
                        f"page '{name}' visual count",
                        actual == n,
                        f"expected={n} actual={actual}",
                    )
                )

    visuals = list(_iter_visuals(layout))
    no_proj = [
        sv.get("visualType") for _, sv, _ in visuals if not sv.get("projections")
    ]
    out.append(_check("all visuals have projections", not no_proj, str(no_proj)))
    if expected_types is not None:
        bad = [
            sv.get("visualType")
            for _, sv, _ in visuals
            if sv.get("visualType") not in expected_types
        ]
        out.append(_check("all visual types known", not bad, str(bad)))
    return out


def verify_bindings(
    layout: dict, spec: dict, model_cols: dict[str, set[str]] | None = None
) -> list[CheckResult]:
    """Check that all visual fields reference existing objects.

    The check is done against the build spec (tables/measures). If `model_cols`
    is passed (from pbixray), the real model columns are also compared.
    """
    tables, measures = spec_objects(spec)
    known_tables = set(tables)
    if model_cols:
        known_tables |= set(model_cols)
    bad: list[str] = []
    for page, sv, _ in _iter_visuals(layout):
        vt = sv.get("visualType")
        for role, refs in sv.get("projections", {}).items():
            for ref in refs:
                qref = ref.get("queryRef", "")
                inner = _resolve_qref(qref)
                if "." not in inner:
                    bad.append(f"{page}/{vt}/{role}: '{qref}' without table.column")
                    continue
                table, col = inner.rsplit(".", 1)
                if table not in known_tables:
                    bad.append(f"{page}/{vt}/{role}: no table '{table}'")
                    continue
                cols = (model_cols or {}).get(table) or tables.get(table)
                if cols is not None and col not in cols and col not in measures:
                    bad.append(f"{page}/{vt}/{role}: no column '{table}.{col}'")
    return [_check("all projected fields resolve", not bad, str(bad[:5]))]


def verify_safe_filters(layout: dict) -> list[CheckResult]:
    """Guard: filters of the form `column IN (...)` crash the pivot on drill.

    Such visual/page-level filters (`Condition.In`) trigger
    `QueryExpressionBuilder.visitIn` -> `exprs[i].accept is not a function`.
    """
    bad: list[str] = []
    for s in layout.get("sections", []):
        if _has_in_filter(s.get("filters", "[]")):
            bad.append(f"page '{s.get('displayName')}'")
        for c in s.get("visualContainers", []):
            if _has_in_filter(c.get("filters", "[]")):
                bad.append(f"visual in '{s.get('displayName')}'")
    return [_check("no unsafe IN filters", not bad, str(bad))]


def _has_in_filter(raw: str) -> bool:
    if not raw or raw == "[]":
        return False
    try:
        flts = json.loads(raw)
    except (ValueError, TypeError):
        return True
    for f in flts:
        where = f.get("filter", {}).get("Where", [])
        for w in where:
            if "In" in w.get("Condition", {}):
                return True
    return False


def verify_model_data(pbix: Path, spec: dict, sample: int = 50) -> list[CheckResult]:
    """Compare the read-back model against the source spec (data/schema).

    Checks are marked `critical=False`: the read is done by a third-party decoder
    (`pbixray`) that does not always parse certain types correctly (e.g. tables
    with DATETIME columns). A failure is a warning, not a guarantee.
    """
    try:
        from pbixray import PBIXRay
    except ImportError:
        return [
            _check(
                "pbixray available",
                False,
                "pip install pbixray for model read-back",
                critical=False,
            )
        ]
    out: list[CheckResult] = []
    with PBIXRay(str(pbix)) as pb:
        have = set(pb.tables)
        for t in spec.get("tables", []):
            name = t["name"]
            cols = [c["name"] for c in t.get("columns", [])]
            nrows = len(t["columns"][0]["values"]) if t.get("columns") else 0
            if name not in have:
                out.append(
                    _check(
                        f"table present: {name}",
                        False,
                        f"tables={sorted(have)}",
                        critical=False,
                    )
                )
                continue
            df = pb.get_table(name)
            out.append(
                _check(
                    f"table '{name}' columns present",
                    all(c in df.columns for c in cols),
                    f"missing={[c for c in cols if c not in df.columns]}",
                    critical=False,
                )
            )
            out.append(
                _check(
                    f"table '{name}' row count",
                    len(df) == nrows,
                    f"expected={nrows} actual={len(df)}",
                    critical=False,
                )
            )
            if t.get("columns"):
                out.extend(_verify_values(df, t, sample))
    return out


def _verify_values(df, table_spec: dict, sample: int) -> list[CheckResult]:
    """Compare column values (first `sample` rows, NaN -> None)."""
    out: list[CheckResult] = []
    name = table_spec["name"]
    n = min(sample, len(table_spec["columns"][0]["values"]))
    mismatch_cols: list[str] = []
    for col in table_spec["columns"]:
        cname = col["name"]
        if cname not in df.columns:
            continue
        expected = [_norm(x) for x in col["values"][:n]]
        actual = [_norm(x) for x in df[cname].tolist()[:n]]
        if expected != actual:
            # in numeric columns allow a comparison with type coercion
            if not _values_close(expected, actual):
                mismatch_cols.append(cname)
    out.append(
        _check(
            f"table '{name}' sample values ({n} rows)",
            not mismatch_cols,
            f"mismatch={mismatch_cols}",
            critical=False,
        )
    )
    return out


def _norm(x):
    if x is None:
        return None
    try:
        import math

        if isinstance(x, float) and math.isnan(x):
            return None
    except ImportError:  # pragma: no cover
        pass
    if isinstance(x, bool):
        return bool(x)
    if isinstance(x, float):
        return round(x, 10)
    return x


def _values_close(a: list, b: list) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b, strict=True):
        if x == y:
            continue
        try:
            if float(x) == float(y):
                continue
        except (TypeError, ValueError):
            return False
    return True
