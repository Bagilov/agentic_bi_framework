# Bundle 3: engine verify + rebuild

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/engine_verify.py ====================

"""Reverse self-testing of a built `.pbix`.

Reads a produced `.pbix` back and checks that all required elements are present
on the pages and that the model returns the expected data. The module does not
need Desktop for structural checks; model reading is done via `pbixray` (if
installed).

This module is a **facade** over focused submodules:
    engine_verify_core.py   - CheckResult / VerifyReport + shared helpers
    engine_verify_checks.py - container/layout/bindings/filters/model-data checks
    engine_verify_brand.py  - report-theme extraction + brand-style comparison

Public API:
    CheckResult           - the result of one check
    VerifyReport          - a set of checks (+ summary/raise)
    verify_container(pbix)                       -> list[CheckResult]
    verify_layout(layout, spec, pages=None)      -> list[CheckResult]
    verify_bindings(layout, spec)                -> list[CheckResult]
    verify_safe_filters(layout)                  -> list[CheckResult]
    verify_model_data(pbix, spec, sample=50)     -> list[CheckResult]
    extract_report_theme(pbix)                   -> dict (fonts/colors/background)
    verify_brand(pbix, theme=None, strict=False) -> list[CheckResult]
    verify_pbix(pbix, spec, pages=None, strict=True, sample=50) -> VerifyReport

Regression guard: visual/page-level filters of the form `column IN (...)`
crash the pivot serializer on expand (`visitIn`/`serializeAll`), so
`verify_safe_filters` treats such filters as an error.

The final element-verification stage includes a **comparison with the brand
style** (`brand.py`): fonts, colors (palette, mandatory accent, at least 2
primary-range colors) and background (validity + WCAG contrast). By default
brand findings are soft (they do not fail the build); `brand_strict=True` makes
level-`error` violations critical.
"""

from __future__ import annotations

from pathlib import Path

from agentic_bi.engine_verify_brand import (  # noqa: F401
    extract_report_theme,
    verify_brand,
)
from agentic_bi.engine_verify_checks import (  # noqa: F401
    verify_bindings,
    verify_container,
    verify_layout,
    verify_model_data,
    verify_safe_filters,
)
from agentic_bi.engine_verify_core import (  # noqa: F401
    CheckResult,
    VerifyReport,
    load_layout,
    spec_objects,
)


def verify_pbix(
    pbix: Path,
    spec: dict,
    pages: dict[str, int] | None = None,
    sample: int = 50,
    model: bool = True,
    layout_checks: bool = True,
    expected_types: set[str] | None = None,
    brand: bool = True,
    brand_strict: bool = False,
) -> VerifyReport:
    """Full reverse check of a `.pbix`: container, layout, binding, data, brand.

    `layout_checks=False` skips the layout/binding checks (needed for a donor
    layout that references donor-model objects rather than spec objects).
    `brand=True` runs the final theme-vs-brand comparison (`verify_brand`);
    `brand_strict=True` makes level-`error` brand violations fail the build.
    """
    report = VerifyReport()
    pbix = Path(pbix)
    report.extend(verify_container(pbix))
    from agentic_bi.engine_verify_checks import _zip_ok

    if not pbix.exists() or not _zip_ok(pbix):
        return report

    layout = load_layout(pbix)
    if layout_checks:
        report.extend(
            verify_layout(layout, spec, pages=pages, expected_types=expected_types)
        )
        report.extend(verify_bindings(layout, spec))
        report.extend(verify_safe_filters(layout))
    if model:
        report.extend(verify_model_data(pbix, spec, sample=sample))
    if brand:
        report.extend(verify_brand(pbix, strict=brand_strict))
    return report


__all__ = [
    "CheckResult",
    "VerifyReport",
    "load_layout",
    "spec_objects",
    "verify_container",
    "verify_layout",
    "verify_bindings",
    "verify_safe_filters",
    "verify_model_data",
    "verify_pbix",
    "extract_report_theme",
    "verify_brand",
]

==================== FILE: src/agentic_bi/engine_verify_core.py ====================

"""Result types and shared helpers for `.pbix` verification."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# aggregations like "Sum(Table.col)"/"Count(Table.col)" in queryRef
_AGG_QREF = re.compile(r"^[A-Za-z]+\((.+)\)$")


@dataclass
class CheckResult:
    """A single check.

    critical=True - a structural guarantee (container/layout/binding/filters);
    a failed critical check fails the strict mode.
    critical=False - best-effort (model read-back via pbixray); a failure is
    reported but by default does not fail the build (third-party decoder).
    """

    name: str
    ok: bool
    detail: str = ""
    critical: bool = True


@dataclass
class VerifyReport:
    """A set of checks with an outcome."""

    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.ok)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]

    @property
    def critical_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok and c.critical]

    @property
    def soft_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok and not c.critical]

    def ok(self) -> bool:
        return self.failed == 0

    def critical_ok(self) -> bool:
        return not self.critical_failures

    def extend(self, checks: list[CheckResult]) -> VerifyReport:
        self.checks.extend(checks)
        return self

    def raise_if_failed(self, strict_soft: bool = False) -> None:
        """Raise RuntimeError on failed checks.

        Critical checks are considered strict; with `strict_soft=True` any checks
        are (including the model read-back).
        """
        bad = self.failures if strict_soft else self.critical_failures
        if bad:
            lines = [f"  - {c.name} :: {c.detail}" for c in bad]
            raise RuntimeError(
                f"verification failed: {len(bad)} check(s)\n" + "\n".join(lines)
            )

    def format(self, verbose: bool = True) -> str:
        lines = []
        if verbose:
            for c in self.checks:
                mark = "PASS" if c.ok else ("FAIL" if c.critical else "WARN")
                suffix = f" :: {c.detail}" if (c.detail and not c.ok) else ""
                lines.append(f"  [{mark}] {c.name}{suffix}")
        lines.append(
            f"RESULT: {self.passed} passed, {self.failed} failed "
            f"({len(self.critical_failures)} critical, "
            f"{len(self.soft_failures)} soft)"
        )
        return "\n".join(lines)


# ─── helpers ──────────────────────────────────────────────────


def _check(name: str, ok: bool, detail: str = "", critical: bool = True) -> CheckResult:
    if not ok:
        logger.debug("check failed: %s (%s)", name, detail)
    return CheckResult(name, ok, detail, critical)


def load_layout(pbix: Path) -> dict:
    """Read `Report/Layout` from a `.pbix` as a dict."""
    with zipfile.ZipFile(pbix) as z:
        return json.loads(z.read("Report/Layout").decode("utf-16-le"))


def _iter_visuals(layout: dict):
    """Iterator (page_name, singleVisual, container) over all visuals."""
    for s in layout.get("sections", []):
        for c in s.get("visualContainers", []):
            cfg = json.loads(c["config"])
            yield s.get("displayName"), cfg.get("singleVisual", {}), c


def spec_objects(spec: dict) -> tuple[dict[str, set[str]], set[str]]:
    """Return (table -> set of columns, set of measures) from the spec."""
    tables: dict[str, set[str]] = {}
    for t in spec.get("tables", []):
        tables[t["name"]] = {c["name"] for c in t.get("columns", [])}
    measures = {m["name"] for m in spec.get("measures", []) if m.get("name")}
    return tables, measures


def _resolve_qref(qref: str) -> str:
    """Strip the aggregation from a queryRef: 'Sum(T.c)' -> 'T.c'."""
    m = _AGG_QREF.match(qref)
    return m.group(1) if m else qref

==================== FILE: src/agentic_bi/engine_verify_checks.py ====================

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

==================== FILE: src/agentic_bi/engine_verify_brand.py ====================

"""Brand-style comparison of a report theme (`extract_report_theme`, `verify_brand`)."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path

from agentic_bi.engine_verify_core import CheckResult, _check

logger = logging.getLogger(__name__)


# ─── style guide (final element comparison) ────────────────────

# Report theme in a .pbix: Report/Layout.theme -> JSON name + registered resources.
_THEME_MEMBER_RE = re.compile(r"^(Report/StaticResources/.*/[^/]+\.json)$")
_VIS_HEX_RE = re.compile(r"#([0-9A-Fa-f]{6})\b")
_VIS_FONT_RE = re.compile(r'"fontFamily"\s*:\s*"([^"]+)"')
# Primary accent and a "near-accent" tolerance (dashboards often use #D0302A / #D3212A
# instead of the canonical #D32F2F).
_BRAND_ACCENT = (0xD3, 0x2F, 0x2F)
_ACCENT_TOLERANCE = 20


def _is_near_brand_accent(hex_color: str) -> bool:
    """Whether a color is close to the primary accent #D32F2F (within tolerance)."""
    try:
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return False
    return (
        abs(r - _BRAND_ACCENT[0]) <= _ACCENT_TOLERANCE
        and abs(g - _BRAND_ACCENT[1]) <= _ACCENT_TOLERANCE
        and abs(b - _BRAND_ACCENT[2]) <= _ACCENT_TOLERANCE
    )


def extract_report_theme(pbix: Path) -> dict:
    """Extract the report theme from a `.pbix`: fonts, colors, background.

    Colors and fonts are taken from the **actually used** visual settings
    (`visualContainers[].config`), while background/text come from the report
    theme (`Report/Layout.theme` -> JSON in `Report/StaticResources/**`). Returns
    a dict in the `brand.check_brand_compliance` format:

        {"colors": {"visual_0": "#D32F2F", "accent": "#D32F2F", ...},
         "fonts": ["Verdana", "Segoe UI", ...],
         "background": "#FFFFFF",
         "text_color": "#252423",
         "has_logo": True,
         "theme_name": "CY23SU02"}

    If the theme is not found, returns an empty dict. The ``accent`` key is added if
    one of the used colors is close to the primary accent.
    """
    pbix = Path(pbix)
    with zipfile.ZipFile(pbix) as z:
        names = z.namelist()
        try:
            layout = json.loads(z.read("Report/Layout").decode("utf-16-le"))
        except (KeyError, ValueError):
            return {}
        theme_name = layout.get("theme")
        cand = None
        if theme_name:
            cand = next(
                (
                    n
                    for n in names
                    if n.endswith(theme_name) and _THEME_MEMBER_RE.match(n)
                ),
                None,
            )
        if cand is None:
            cand = next((n for n in names if _THEME_MEMBER_RE.match(n)), None)
        theme = {}
        if cand is not None:
            try:
                theme = json.loads(z.read(cand).decode("utf-8"))
            except (KeyError, ValueError):
                theme = {}

    # --- colors/fonts actually used in the visuals ---
    used_colors: dict[str, int] = {}
    used_fonts: dict[str, int] = {}
    for sec in layout.get("sections", []):
        for vc in sec.get("visualContainers", []):
            cfg = vc.get("config", "")
            text = cfg if isinstance(cfg, str) else json.dumps(cfg, ensure_ascii=False)
            for m in _VIS_HEX_RE.finditer(text):
                h = "#" + m.group(1).upper()
                used_colors[h] = used_colors.get(h, 0) + 1
            for m in _VIS_FONT_RE.finditer(text):
                used_fonts[m.group(1)] = used_fonts.get(m.group(1), 0) + 1

    colors: dict[str, str] = {}
    for h in sorted(used_colors, key=lambda k: -used_colors[k]):
        colors[h] = h  # key = the HEX itself: violation messages stay readable
    # if there is a near-accent, record the 'accent' key with the canonical value
    if any(_is_near_brand_accent(h) for h in used_colors):
        colors["accent"] = "#D32F2F"

    fonts = list(used_fonts)
    # add theme fonts as fallback context (when visuals do not set them)
    for cls in (theme.get("textClasses") or {}).values():
        ff = cls.get("fontFace") if isinstance(cls, dict) else None
        if ff and ff not in fonts:
            fonts.append(ff)

    text_color = None
    for cls in (theme.get("textClasses") or {}).values():
        if isinstance(cls, dict) and cls.get("color"):
            text_color = cls["color"]
            break

    has_logo = any("logo" in n.lower() for n in names)
    return {
        "colors": colors,
        "fonts": fonts,
        "background": theme.get("background"),
        "text_color": text_color,
        "has_logo": has_logo,
        "theme_name": theme.get("name") or (str(theme_name) if theme_name else None),
    }


def verify_brand(
    pbix: Path, theme: dict | None = None, strict: bool = False
) -> list[CheckResult]:
    """Compare the report theme with the brand style guide (`brand.py`).

    Checks fonts (Brand Sans/Text), colors (palette, mandatory accent, at least 2
    primary-range colors) and background (validity + WCAG contrast). Every brand
    finding becomes a `CheckResult`; criticality is
    `critical=strict and level=="error"` (soft by default so brand preferences
    do not fail the build).

    Args:
        pbix: path to the `.pbix` (used if `theme` is not passed).
        theme: an already extracted theme (avoids re-reading the archive).
        strict: make level-`error` violations critical.
    """
    from agentic_bi.brand import check_brand_compliance  # local import: optional

    theme = theme if theme is not None else extract_report_theme(pbix)
    if not theme:
        return [
            _check(
                "brand: report theme found",
                False,
                "no registered report theme in the .pbix",
                critical=False,
            )
        ]
    report = check_brand_compliance(
        colors=theme.get("colors"),
        fonts=theme.get("fonts"),
        background=theme.get("background"),
        text_color=theme.get("text_color"),
        has_logo=bool(theme.get("has_logo")),
    )
    out: list[CheckResult] = []
    name = theme.get("theme_name") or "report"
    findings = report.get("findings", [])
    if not findings:
        out.append(_check(f"brand: theme '{name}' complies", True, critical=False))
        return out
    for f in findings:
        critical = bool(strict and f.get("level") == "error")
        out.append(
            _check(
                f"brand: {f.get('rule_id')}",
                False,
                f"[{f.get('level')}] {f.get('message')}",
                critical=critical,
            )
        )
    return out

==================== FILE: src/agentic_bi/rebuild.py ====================

"""Iteration 3+4: rebuild a binary `.pbix` from an existing working file.

Strategy (verified against real files):
- A `.pbix` is an ordinary zip: binary VertiPaq `DataModel` + `Report/Layout` (JSON).
- The binary `DataModel` CANNOT be generated from scratch by hand (closed
  xpress/ABF format).
- The reliable path: take the `DataModel` from a ready working `.pbix` as-is
  (byte-for-byte), replace `[Content_Types].xml` with a full one, and embed our
  `Report/Layout` whose visuals reference EXISTING model objects (table/measure/
  column names from the taken DataModel). Rebuild the zip.

Layout and DataModel are independent — the layout references the model by name,
so as long as object names match, the visuals work in Desktop and on a Report
Server.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _default_content_types(parts: list[str]) -> str:
    """Produce a full [Content_Types].xml from the package part names."""
    defaults = {
        "json": 'ContentType="application/json"',
        "xml": 'ContentType="application/xml"',
    }
    lines = []
    for ext, ct in defaults.items():
        lines.append(f'  <Default Extension="{ext}" {ct} />')
    # Overrides for specific parts; DataModel and Layout are the key ones
    override_map = {
        "/Version": "",
        "/DiagramLayout": "",
        "/Report/Layout": 'ContentType="application/x-powerbi-report-layout"',
        "/Settings": 'ContentType="application/json"',
        "/Metadata": 'ContentType="application/json"',
        "/Report/LinguisticSchema": "",
        "/SecurityBindings": "",
        "/DataModel": 'ContentType="application/x-msapplication#DataModel"',
    }
    for part in parts:
        if part in override_map:
            ct = override_map[part]
            attr = f" {ct}" if ct else ""
            if f'PartName="{part}"' not in "\n".join(lines):
                lines.append(f'  <Override PartName="{part}"{attr} />')
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        + "\n".join(lines)
        + "\n</Types>"
    )


def _extract_layout(src: Path) -> tuple[dict, str]:
    """Extract Report/Layout from a ready .pbix (sample of model references)."""
    with zipfile.ZipFile(src) as z:
        raw = z.read("Report/Layout")
    # Real format: UTF-16LE without BOM. Decode by sniffing the bytes.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or (len(raw) > 1 and raw[1] == 0):
        return json.loads(raw.decode("utf-16")), "utf-16le"
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return json.loads(raw.decode(enc)), enc
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError("Could not decode the source Report/Layout")


def _new_layout(
    display_name: str, table: str, col: str, measure: str, base_layout: dict
) -> dict:
    """Build a layout with a single visual referencing the source model."""
    layout = dict(base_layout)
    layout["sections"] = [
        {
            "name": "ReportSectionCustom",
            "displayName": display_name,
            "filters": "[]",
            "ordinal": 0,
            "visualContainers": [
                {
                    "x": 20,
                    "y": 20,
                    "z": 0,
                    "width": 400,
                    "height": 300,
                    "config": json.dumps(
                        {
                            "name": "visual1",
                            "layouts": [
                                {
                                    "id": 0,
                                    "position": {
                                        "x": 20,
                                        "y": 20,
                                        "width": 400,
                                        "height": 300,
                                        "z": 0,
                                    },
                                }
                            ],
                            "singleVisual": {
                                "visualType": "clusteredColumnChart",
                                "objects": {},
                                "prototypeQuery": {
                                    "Version": 2,
                                    "From": [{"Name": "e", "Entity": table}],
                                    "Select": [
                                        {
                                            "Column": {
                                                "Expression": {
                                                    "SourceRef": {"Source": "e"}
                                                },
                                                "Property": col,
                                            },
                                            "Name": col,
                                        },
                                        {
                                            "Measure": {
                                                "Expression": {
                                                    "MeasureRef": {"Property": measure}
                                                }
                                            },
                                            "Name": measure,
                                        },
                                    ],
                                },
                            },
                        },
                        ensure_ascii=False,
                    ),
                    "filters": "[]",
                    "tabOrder": 0,
                }
            ],
        }
    ]
    layout["id"] = base_layout.get("id", 0)
    return layout


def rebuild_pbix(
    src: Path,
    out: Path,
    display_name: str = "Rebuilt report",
    table: str = "fact_table",
    col: str = "metric",
    measure: str = "score",
    layout: dict | None = None,
) -> Path:
    """Rebuild a .pbix: take the DataModel and binary parts from src, embed our
    layout and re-save the zip.

    Args:
        src: an existing working .pbix (source of truth for the DataModel).
        out: where to save the new .pbix.
        display_name: page name in the new layout.
        table/col/measure: model objects from the DataModel referenced by the new
            visual (must exist in the src model).
        layout: a ready layout dict (e.g. from skeleton). Contains `sections`
            and `id`. If given, it is used as-is instead of `_new_layout`.
    """
    out.parent.mkdir(parents=True, exist_ok=True)

    # source base layout, to preserve resourcePackages/config
    base_layout, layout_enc = _extract_layout(src)
    if layout is None:
        new_layout = _new_layout(display_name, table, col, measure, base_layout)
    else:
        new_layout = layout

    # read all parts of the source zip, replacing Report/Layout
    with zipfile.ZipFile(src) as zin:
        names = zin.namelist()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in names:
                data = zin.read(name)
                if name == "Report/Layout":
                    # Keep the same encoding as the source — plain UTF-16LE
                    # without BOM (otherwise Desktop/analyzers cannot decode the
                    # layout; the source has no BOM).
                    utf16 = json.dumps(new_layout, ensure_ascii=False).encode(
                        "utf-16-le"
                    )
                    data = (
                        b"\xff\xfe" + utf16
                        if layout_enc == "utf-16be"
                        else utf16
                        if layout_enc == "utf-16le"
                        else json.dumps(new_layout, ensure_ascii=False).encode("utf-8")
                    )
                zout.writestr(name, data)

    logger.info(
        "Rebuilt .pbix: %s (%d parts, %.1f KB)",
        out,
        len(names),
        out.stat().st_size / 1024,
    )
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    import argparse

    parser = argparse.ArgumentParser(description="Rebuild a .pbix from a donor")
    parser.add_argument("src", help="donor .pbix (DataModel source)")
    parser.add_argument("--out", default="output_files/rebuilt.pbix")
    parser.add_argument("--display", default="Rebuilt report")
    args = parser.parse_args()
    rebuild_pbix(Path(args.src), Path(args.out), display_name=args.display)


if __name__ == "__main__":
    main()

==================== FILE: src/agentic_bi/engine_container.py ====================

"""OPC operations on the `.pbix` container (zip): read members, swap the
DataModel, build a clean "scaffolding + our Layout + DataModel" package.

The single source of low-level zip handling (previously duplicated).

Public API:
    COPY_MEMBERS
    read_member(pbix, name) -> bytes
    list_members(pbix) -> list[tuple[str, int]]
    swap_datamodel(template, datamodel, out) -> int
    build_container(template, layout, datamodel, out, copy_members=None) -> int
"""

from __future__ import annotations

import logging
import struct
import zipfile
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)

# Environment scaffolding (theme/settings/bindings) independent of the model and
# the report, copied from the template container as-is.
COPY_MEMBERS = [
    "Version",
    "[Content_Types].xml",
    "DiagramLayout",
    "Settings",
    "Metadata",
    "Report/LinguisticSchema",
    "Report/StaticResources/SharedResources/BaseThemes/CY24SU05.json",
    "SecurityBindings",
]


def read_member(pbix: Path, name: str) -> bytes:
    """Return the bytes of a single `.pbix` member (OPC zip)."""
    with zipfile.ZipFile(pbix) as z:
        return z.read(name)


def list_members(pbix: Path) -> list[tuple[str, int]]:
    """Return (name, size) for each archive member in order."""
    with zipfile.ZipFile(pbix) as z:
        return [(i.filename, i.file_size) for i in z.infolist()]


def _locate_datamodel(orig: bytearray, template: Path) -> tuple[int, int, int, int]:
    """Return (local-header offset, data start, old stored length, method)."""
    with zipfile.ZipFile(template) as z:
        info = next(i for i in z.infolist() if i.filename == "DataModel")
    lho = info.header_offset
    name_len, extra_len = struct.unpack("<HH", orig[lho + 26 : lho + 30])
    data_start = lho + 30 + name_len + extra_len
    # The payload length is the stored size, NOT the distance to the central
    # directory: another member may follow DataModel in the archive.
    return lho, data_start, info.compress_size, info.compress_type


def _encode_payload(payload: bytes, method: int) -> bytes:
    """Encode a member payload with the entry's compression method."""
    if method == zipfile.ZIP_STORED:
        return payload
    if method == zipfile.ZIP_DEFLATED:
        compressor = zlib.compressobj(level=9, wbits=-zlib.MAX_WBITS)
        return compressor.compress(payload) + compressor.flush()
    raise ValueError(f"unsupported DataModel compression method: {method}")


def _rewrite_local_header(
    head: bytearray, lho: int, crc: int, usize: int, csize: int
) -> None:
    """Patch CRC and both size fields in the DataModel local header."""
    struct.pack_into("<I", head, lho + 14, crc)
    struct.pack_into("<I", head, lho + 18, csize)
    struct.pack_into("<I", head, lho + 22, usize)


def _central_dir_offset(pb: bytes) -> int:
    """Return the central-directory offset recorded in the EOCD record."""
    eocd = pb.rfind(b"PK\x05\x06")
    _cd_size, cd_off = struct.unpack("<II", pb[eocd + 12 : eocd + 20])
    return cd_off


def _rewrite_central_dir(
    pb: bytearray,
    new_cd_offset: int,
    crc: int,
    usize: int,
    csize: int,
    shift_from: int,
    shift: int,
) -> None:
    """Patch the central directory after the DataModel payload changed size.

    Rewrites the DataModel entry (CRC + both sizes) and adds `shift` to the local
    header offset of every member stored after the DataModel payload, then moves
    the central-directory offset in the EOCD record.
    """
    pos = new_cd_offset
    while pos + 46 <= len(pb) and pb[pos : pos + 4] == b"PK\x01\x02":
        name_len, extra_len, comment_len = struct.unpack(
            "<HHH", pb[pos + 28 : pos + 34]
        )
        name = pb[pos + 46 : pos + 46 + name_len].decode("utf-8", "replace")
        if name == "DataModel":
            struct.pack_into("<I", pb, pos + 16, crc)
            struct.pack_into("<II", pb, pos + 20, csize, usize)
        else:
            entry_off = struct.unpack("<I", pb[pos + 42 : pos + 46])[0]
            if entry_off >= shift_from:
                struct.pack_into("<I", pb, pos + 42, entry_off + shift)
        pos += 46 + name_len + extra_len + comment_len
    struct.pack_into("<I", pb, len(pb) - 22 + 16, new_cd_offset)


def swap_datamodel(template: Path, datamodel: bytes, out: Path) -> int:
    """Replace the `DataModel` member in `template` with `datamodel`, write `out`.

    Other members stay byte-for-byte. Works whether or not `DataModel` is the
    last archive member (the central directory and the local-header offsets of
    all following members are shifted by the size delta), and preserves the
    entry's compression method. Returns the output size.
    """
    orig = bytearray(template.read_bytes())
    lho, data_start, old_len, method = _locate_datamodel(orig, template)
    old_cd_offset = _central_dir_offset(orig)
    encoded = _encode_payload(datamodel, method)
    shift = len(encoded) - old_len
    crc = zlib.crc32(datamodel) & 0xFFFFFFFF
    head = bytearray(orig[:data_start])
    _rewrite_local_header(head, lho, crc, len(datamodel), len(encoded))
    pb = bytearray(bytes(head) + encoded + bytes(orig[data_start + old_len :]))
    new_cd_offset = old_cd_offset + shift
    _rewrite_central_dir(
        pb,
        new_cd_offset,
        crc,
        len(datamodel),
        len(encoded),
        shift_from=data_start + old_len,
        shift=shift,
    )
    out.write_bytes(bytes(pb))
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None:
            raise ValueError("output zip invalid")
    logger.info("swap_datamodel: %s -> %s (%d B)", template.name, out.name, len(pb))
    return len(pb)


def build_container(
    template: Path,
    layout: bytes,
    datamodel: bytes,
    out: Path,
    copy_members: list[str] | None = None,
) -> int:
    """Build a clean package: copy of the scaffolding + new `Report/Layout` + `DataModel`.

    Donor visuals are not carried over — the caller provides the full Layout.
    """
    members = copy_members or COPY_MEMBERS
    with (
        zipfile.ZipFile(template) as src,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for name in members:
            dst.writestr(name, src.read(name))
        dst.writestr("Report/Layout", layout)
        dst.writestr("DataModel", datamodel)
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None:
            raise ValueError("output zip invalid")
    logger.info("build_container: %s (%d B)", out.name, out.stat().st_size)
    return out.stat().st_size

