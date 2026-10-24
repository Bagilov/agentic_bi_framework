# Bundle 1: lineage core

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/lineage/lineage_types.py ====================

"""Lineage value types and small helpers (no heavy dependencies)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_brand_config(path: str | Path | None):
    """Load brand rules (`brand_config.yaml`) for sheet metrics.

    Defaults to `agentic_bi/brand_config.yaml`; if missing or on error returns
    ``None`` (the metrics module then uses defaults from brand.py).
    """
    from pathlib import Path as _Path

    pkg_dir = _Path(__file__).resolve().parents[1]
    try:
        from agentic_bi.brand_config import BrandConfig
    except ImportError:
        return None
    cfg_path = _Path(path) if path else pkg_dir / "brand_config.yaml"
    if not cfg_path.exists():
        return None
    try:
        return BrandConfig.load(cfg_path)
    except Exception as exc:  # noqa: BLE001 — config is optional
        logger.warning("brand config load failed (%s): %s", cfg_path, exc)
        return None


# --------------------------------------------------------------------------- #
#  Utilities
# --------------------------------------------------------------------------- #
def _brand_level_ru(level: str | None) -> str:
    return {
        "ok": "compliant",
        "warning": "warnings",
        "error": "violation",
        "unknown": "no data",
    }.get(level or "", "")


def _split_table_col(query_ref: str) -> tuple[str, str | None]:
    """Split a queryRef 'Table.Column' into (table, column)."""
    if "." not in query_ref:
        return query_ref, None
    tbl, col = query_ref.split(".", 1)
    return tbl, col


def _strip_agg(token: str) -> str:
    """Strip aggregation wrappers like 'Min(Table.column)' -> 'Table'."""
    m = re.match(r"^(\w+)\(", token)
    if m:
        inner = token[m.end() :]
        if inner.endswith(")"):
            return inner[:-1].split(".", 1)[0]
    return token


# --------------------------------------------------------------------------- #
#  Lineage layers
# --------------------------------------------------------------------------- #
@dataclass
class Source:
    """A data source (top lineage layer).

    Fields:
        type: source type (Excel/CSV/ODBC/...).
        detail: details (path/DSN/table).
        status: access status ('ok'/'access_error'/'unresolved'/'no_power_query').
        error: error text if the source is unavailable/undetermined.
    """

    type: str
    detail: str | None = None
    status: str = "ok"
    error: str | None = None
    path: str | None = None


class SourceAccessError(Exception):
    """An explicit data-source access/unavailability error.

    Raised when a source cannot be read/resolved: the local file does not exist
    or is inaccessible, the model does not open, M code does not determine the
    source. Always accompanied by a clear message (never a silent failure).
    """


@dataclass
class VisualBinding:
    """A single visual-to-data binding (queryRef)."""

    role: str
    query_ref: str
    table: str | None = None
    column: str | None = None


@dataclass
class Visual:
    """A visual from a dashboard page."""

    page: str
    page_idx: int
    visual_type: str
    z_index: str
    bindings: list[VisualBinding] = field(default_factory=list)
    colors: set[str] = field(default_factory=set)
    fonts: set[str] = field(default_factory=set)

    @property
    def tables(self) -> set[str]:
        return {b.table for b in self.bindings if b.table}


@dataclass
class Page:
    """A dashboard page with visuals."""

    index: int
    name: str
    visuals: list[Visual] = field(default_factory=list)

    @property
    def tables(self) -> set[str]:
        out = set()
        for v in self.visuals:
            out |= v.tables
        return out


# --------------------------------------------------------------------------- #
#  Main class
# --------------------------------------------------------------------------- #

==================== FILE: src/agentic_bi/lineage/lineage_model.py ====================

"""Model extraction, report-layout parsing and data-source resolution mixin."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from pbixray import LiveConnectionError, NoEmbeddedModelError, PBIXRay

from agentic_bi.lineage.lineage_types import (
    Page,
    Source,
    SourceAccessError,
    Visual,
    VisualBinding,
    _split_table_col,
    _strip_agg,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from agentic_bi.lineage.pbi_lineage import PbiLineage

logger = logging.getLogger(__name__)


class ModelMixin:
    def _open_model(self) -> None:
        try:
            self._model = PBIXRay(str(self.pbix_path))
        except LiveConnectionError as e:
            raise ValueError(
                f"Thin report (no embedded model): {getattr(e, 'database_name', None)}"
            ) from e
        except NoEmbeddedModelError as e:
            raise ValueError("No embedded data model") from e
        except zipfile.BadZipFile as e:
            raise SourceAccessError(
                f"File is corrupted or is not a .pbix: {self.pbix_path}"
            ) from e
        except PermissionError as e:
            raise SourceAccessError(
                f"No permission to read the file: {self.pbix_path}"
            ) from e
        except OSError as e:
            raise SourceAccessError(
                f"Could not open the file (OSError): {self.pbix_path} ({e})"
            ) from e
        except Exception as e:
            # any other pbixray errors (corrupted model, unsupported
            # compression, etc.) - an explicit clear error instead of a traceback
            raise SourceAccessError(
                f"Could not open the model in {self.pbix_path.name}: {e}"
            ) from e

    def close(self) -> None:
        """Close the pbixray model."""
        if self._model is not None:
            try:
                self._model.close()
            finally:
                self._model = None

    def __enter__(self) -> PbiLineage:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------- extract artifacts ----------------
    def _load_model_artifacts(self) -> None:
        assert self._model is not None
        m = self._model

        self.tables: list[str] = list(m.tables)

        self.measures: dict[str, list[str]] = defaultdict(list)
        for _, row in m.dax_measures.iterrows():
            self.measures[row["TableName"]].append(row["Name"])

        self.calc_columns: dict[str, list[str]] = defaultdict(list)
        for _, row in m.dax_columns.iterrows():
            self.calc_columns[row["TableName"]].append(row["ColumnName"])

        self.power_query: dict[str, str] = {}
        for _, row in m.power_query.iterrows():
            self.power_query[row["TableName"]] = row["Expression"]

        self.columns: dict[str, list[str]] = defaultdict(list)
        for _, row in m.schema.iterrows():
            self.columns[row["TableName"]].append(row["ColumnName"])

        self.relationships = m.relationships

    def _load_layout(self) -> None:
        try:
            with zipfile.ZipFile(self.pbix_path) as z:
                raw = z.read("Report/Layout")
        except (zipfile.BadZipFile, KeyError) as e:
            raise SourceAccessError(
                f"Could not read Report/Layout from the .pbix: {e}"
            ) from e
        for enc in ("utf-16", "utf-8", "utf-8-sig"):
            try:
                self._layout = json.loads(raw.decode(enc))
                return
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        raise ValueError("Could not decode Report/Layout")

    # ---------------- normalize the table name ----------------
    def _resolve_table(self, token: str) -> str | None:
        """Resolve a display/layout name to the physical model table."""
        raw = token.strip()
        if raw.startswith(
            tuple(agg + "(" for agg in ("Min", "Max", "Sum", "Avg", "Count"))
        ):
            raw = _strip_agg(raw)
        # strip a possible aggregate suffix of the form 'Table.Column'
        raw = raw.split(".", 1)[0].strip()
        phys = self.display_aliases.get(raw, raw)
        if phys in self.tables:
            return phys
        self._unresolved_table_refs.add(raw)
        return None

    # ---------------- build pages/visuals ----------------
    _HEX_RE = re.compile(r"#([0-9A-Fa-f]{6,8})\b")
    _THEME_RE = re.compile(r'"ThemeDataColor"\s*:\s*\{\s*"ColorId"\s*:\s*(\d+)')
    _FONT_RE = re.compile(r'"fontFamily"\s*:\s*"([^"]+)"')

    def _collect_colors(self, sv: dict) -> set[str]:
        """Collect the unique colors of a singleVisual: hex + ThemeDataColor(ColorId)."""
        text = json.dumps(sv, ensure_ascii=False)
        colors: set[str] = set()
        for m in self._HEX_RE.finditer(text):
            hexv = m.group(1).upper()
            colors.add(f"hex#{hexv[:6]}")
        for m in self._THEME_RE.finditer(text):
            colors.add(f"theme#{m.group(1)}")
        return colors

    def _collect_fonts(self, sv: dict) -> set[str]:
        """Collect the unique families actually set in a singleVisual."""
        text = json.dumps(sv, ensure_ascii=False)
        return {m.group(1) for m in self._FONT_RE.finditer(text)}

    def _collect_visual_fonts(self, page: Page) -> list[str]:
        """Unique fonts used by the page visuals (stable order)."""
        fonts: set[str] = set()
        for v in page.visuals:
            fonts |= v.fonts
        return sorted(fonts)

    def _parse_visual(self, vc: dict, page_idx: int, page_name: str) -> Visual | None:
        cfg = vc.get("config", "")
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except json.JSONDecodeError:
                cfg = None
        if not isinstance(cfg, dict):
            return None
        sv = cfg.get("singleVisual", {})
        proj = sv.get("projections", {})
        bindings: list[VisualBinding] = []
        for role, items in proj.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict) and it.get("queryRef"):
                    qr = it["queryRef"]
                    tbl, col = _split_table_col(qr)
                    bindings.append(
                        VisualBinding(
                            role=role,
                            query_ref=qr,
                            table=self._resolve_table(tbl),
                            column=col,
                        )
                    )
        return Visual(
            page=page_name,
            page_idx=page_idx,
            visual_type=sv.get("visualType", "?"),
            z_index=str(vc.get("z", "")),
            bindings=bindings,
            colors=self._collect_colors(sv),
            fonts=self._collect_fonts(sv),
        )

    def _build(self) -> None:
        sections = self._layout.get("sections", [])
        sections = sorted(sections, key=lambda s: s.get("ordinal", 0))

        self.pages: list[Page] = []
        for i, sec in enumerate(sections):
            name = sec.get("displayName") or sec.get("name") or f"Page{i + 1}"
            visuals: list[Visual] = []
            for vc in sec.get("visualContainers", []):
                v = self._parse_visual(vc, i + 1, name)
                if v is not None:
                    visuals.append(v)
            self.pages.append(Page(index=i + 1, name=name, visuals=visuals))

        # sources by table
        self.sources: dict[str, Source] = {}
        self.unresolved_sources: list[
            dict
        ] = []  # explicit report of unavailable/undetermined
        for tbl in self.tables:
            expr = self.power_query.get(tbl)
            if expr:
                src = self._source_from_m(expr)
            else:
                src = Source(
                    "No Power Query",
                    None,
                    status="no_power_query",
                    error=f"No M code (Power Query) for table {tbl}",
                )
            self.sources[tbl] = src
            if src.status in ("access_error", "unresolved", "no_power_query"):
                self.unresolved_sources.append(
                    {
                        "table": tbl,
                        "type": src.type,
                        "status": src.status,
                        "detail": src.detail,
                        "error": src.error,
                    }
                )

        # --- count references from the visual bindings ---
        # How many times a table/measure/column is used in visuals (board code).
        self.table_refs: Counter = Counter()
        self.field_refs: Counter = Counter()  # by the whole queryRef
        for p in self.pages:
            for v in p.visuals:
                for b in v.bindings:
                    self.field_refs[b.query_ref] += 1
                    if b.table:
                        self.table_refs[b.table] += 1

    def _resolve_refs(self) -> dict:
        """Map queryRef -> (measure|column -> name) for detailed counting.

        A queryRef of the form 'Table.Name' for columns and 'Name' /
        'Table.Measure' for measures. Returns {measure: count, column: count}.
        """
        measure_map: dict[str, str] = {}  # displayed -> name
        for tbl, names in self.measures.items():
            for n in names:
                measure_map[f"{tbl}.{n}"] = n
                measure_map[n] = n
        col_map: dict[str, str] = {}
        for tbl, names in self.columns.items():
            for n in names:
                col_map[f"{tbl}.{n}"] = n
        out = {"measures": Counter(), "columns": Counter()}
        for qr, cnt in self.field_refs.items():
            if qr in measure_map:
                out["measures"][measure_map[qr]] += cnt
            elif qr in col_map:
                out["columns"][qr] += cnt
            else:
                # try to split 'Table.col'
                if "." in qr:
                    t, c = qr.split(".", 1)
                    if c in measure_map:
                        out["measures"][c] += cnt
                    elif c in col_map:
                        out["columns"][c] += cnt
        return out

    # ---------------- determine the source from M code ----------------

==================== FILE: src/agentic_bi/lineage/lineage_query.py ====================

"""Query/introspection helpers over the parsed lineage (counts, DataFrames)."""

from __future__ import annotations

import logging
from collections import Counter

import pandas as pd

from agentic_bi.lineage.lineage_brand import brand_audit_pages, visual_brand_metrics
from agentic_bi.lineage.lineage_types import Source, Visual, _brand_level_ru

logger = logging.getLogger(__name__)


class QueryMixin:
    def is_technical(self, table: str) -> bool:
        return table.startswith(self._TECH_PREFIXES)

    # ======================= Public API ======================= #

    # -------- per-page element and color analysis --------
    def page_analysis(self) -> list[dict]:
        """Analyze each page: element types, counts, unique colors.

        Returns:
            A list of dicts:
                {page, elements: {type: count}, n_elements, colors: [set hex/theme]}
        """
        result = []
        for p in self.pages:
            etypes: Counter = Counter()
            colors: set[str] = set()
            for v in p.visuals:
                etypes[v.visual_type] += 1
                colors |= v.colors
            result.append(
                {
                    "page": p.name,
                    "elements": dict(etypes),
                    "n_elements": sum(etypes.values()),
                    "colors": sorted(colors),
                }
            )
        return result

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def visual_count(self) -> int:
        return sum(len(p.visuals) for p in self.pages)

    @property
    def total_measures(self) -> int:
        return sum(len(v) for v in self.measures.values())

    @property
    def total_calc_columns(self) -> int:
        return sum(len(v) for v in self.calc_columns.values())

    def technical_tables(self) -> list[str]:
        return [t for t in self.tables if self.is_technical(t)]

    def business_tables(self) -> list[str]:
        return [t for t in self.tables if not self.is_technical(t)]

    # -------- brand-book compliance metrics --------
    def _visual_brand(self, v: Visual) -> dict:
        """Brand metrics of a single visual (uses the class config)."""
        return visual_brand_metrics(
            {"colors": sorted(v.colors), "fonts": sorted(v.fonts)}, self._brand_cfg
        )

    def brand_metrics(self) -> dict:
        """Brand-book metrics by page (fonts/colors) + summary.

        Returns:
            {"summary": {...}, "pages": {page: metrics}} - a single computation for
            JSON, Excel, Markdown and PlantUML (see `lineage_brand`).
        """
        if getattr(self, "_brand_cache", None) is not None:
            return self._brand_cache
        analysis = {a["page"]: a for a in self.page_analysis()}
        try:
            audit = brand_audit_pages(
                [
                    {
                        "name": p.name,
                        "colors": list(analysis.get(p.name, {}).get("colors", [])),
                        "fonts": self._collect_visual_fonts(p),
                    }
                    for p in self.pages
                ],
                self._brand_cfg,
            )
            self._brand_cache = {
                "summary": audit["summary"],
                "pages": {r["name"]: r["metrics"] for r in audit["pages"]},
            }
        except Exception as exc:  # noqa: BLE001 - brand metrics are optional
            logger.warning("brand metrics unavailable: %s", exc)
            self._brand_cache = {"summary": {}, "pages": {}}
        return self._brand_cache

    # -------- DataFrames --------
    @property
    def pages_dataframe(self) -> pd.DataFrame:
        brand = self.brand_metrics()["pages"]
        rows = []
        for p in self.pages:
            m = brand.get(p.name, {})
            fnt = m.get("fonts", {})
            col = m.get("colors", {})
            rows.append(
                {
                    "PageIdx": p.index,
                    "Page": p.name,
                    "Visuals": len(p.visuals),
                    "BoundTables": ", ".join(sorted(p.tables)),
                    "BindingCount": sum(len(v.bindings) for v in p.visuals),
                    "BrandFontsPct": fnt.get("compliance"),
                    "BrandColorsPct": col.get("compliance"),
                    "BrandHasRed": col.get("has_red"),
                    "BrandStatus": _brand_level_ru(m.get("level")),
                }
            )
        return pd.DataFrame(rows)

    @property
    def visuals_dataframe(self) -> pd.DataFrame:
        rows = []
        for p in self.pages:
            for v in p.visuals:
                m = self._visual_brand(v)
                rows.append(
                    {
                        "PageIdx": v.page_idx,
                        "Page": v.page,
                        "VisualIdx": v.z_index,
                        "VisualType": v.visual_type,
                        "Bindings": "; ".join(
                            f"{b.role}={b.query_ref}" for b in v.bindings
                        ),
                        "Tables": ", ".join(sorted(v.tables)),
                        "BrandFontsPct": (m.get("fonts") or {}).get("compliance"),
                        "BrandColorsPct": (m.get("colors") or {}).get("compliance"),
                        "BrandStatus": _brand_level_ru(m.get("level")),
                        "BrandIssues": "; ".join(m.get("off", []) or []),
                    }
                )
        return pd.DataFrame(rows)

    @property
    def tables_dataframe(self) -> pd.DataFrame:
        rows = []
        for tbl in self.tables:
            src = self.sources.get(tbl, Source("No Power Query", None))
            rows.append(
                {
                    "Table": tbl,
                    "Technical": self.is_technical(tbl),
                    "ColumnsCount": len(self.columns.get(tbl, [])),
                    "MeasuresCount": len(self.measures.get(tbl, [])),
                    "CalcColumnsCount": len(self.calc_columns.get(tbl, [])),
                    "HasPowerQuery": tbl in self.power_query,
                    "SourceType": src.type,
                    "Source": src.detail,
                    "SourceStatus": src.status,
                    "SourceError": src.error or "",
                }
            )
        return pd.DataFrame(rows)

    def tables_for_page(self, page_name: str) -> set[str]:
        """Tables used on a specific page."""
        for p in self.pages:
            if p.name == page_name:
                return set(p.tables)
        return set()

    def tables_for_visual(self, visual_type: str | None = None) -> Counter:
        """Tables used by visuals of a given type (or all)."""
        out: Counter = Counter()
        for p in self.pages:
            for v in p.visuals:
                if visual_type and v.visual_type != visual_type:
                    continue
                for t in v.tables:
                    out[t] += 1
        return out

    # -------- export --------
    @property
    def unresolved_table_refs(self) -> list[str]:
        """Display/layout table names that did not match any model table.

        Not an exception (parsing continues), but recorded explicitly so there are
        no silent losses in the visual -> table mapping.
        """
        return sorted(self._unresolved_table_refs)

==================== FILE: src/agentic_bi/lineage/lineage_origins.py ====================

"""Taxonomy of data-source origins (lineage layer 0).

Answers "where did the initial layer of sources come from": every top-level
source (a warehouse mart, an Excel file, an inline M-code table) is mapped to the
**generating process/repository** and an origin category.

A data source does not "start" lineage by itself: it has an upstream - an
industrial pipeline, an operator's manual Excel, or a constant inside the model.

Origin categories (fixed layer order):

    origin-pipeline    - pipeline - marts, Readme
    origin-manual      - manual source
    origin-reference   - inline reference table
    origin-etl         - ETL (legacy)
    origin-unknown     - other

The map can be managed via a YAML config (``origins.yaml``) when provided;
otherwise the built-in DEFAULT_ORIGINS is used. This lets you adapt lineage to
any dashboard without changing code. The built-in default is a NEUTRAL sample -
override it with your own map.

The constants and the default map live in ``lineage_origins_data.py``; this
module re-exports them and provides the lookup/assembly helpers.
"""

from __future__ import annotations

import re
from pathlib import Path

try:  # PyYAML is optional: the source map has a built-in default
    import yaml
except ImportError:  # pragma: no cover - without PyYAML we use the default
    yaml = None

from agentic_bi.lineage.lineage_origins_data import (  # noqa: F401
    DEFAULT_ORIGINS,
    ORIGIN_COLORS,
    ORIGIN_LABEL,
    ORIGIN_LEVEL,
    ORIGIN_LEVEL_LABEL,
    ORIGIN_ORDER,
    ORIGIN_STAGE_COLORS,
    ORIGIN_STAGE_LABEL,
    ORIGIN_STAGE_ORDER,
    Origin,
)


def _norm(name: str) -> str:
    """Normalize a table name for matching (case/whitespace)."""
    return re.sub(r"\s+", " ", str(name).strip()).lower()


def load_origins(config: dict | str | Path | None = None) -> list[Origin]:
    """Load the origin map: from a dict/YAML path or the built-in default.

    Args:
        config: a dict with an `origins` list, a YAML file path, or None.

    Returns:
        list[Origin] - the origin map.
    """
    raw: list[dict] = DEFAULT_ORIGINS

    if isinstance(config, (str, Path)):
        p = Path(config)
        if p.exists() and yaml is not None:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and "origins" in data:
                raw = data["origins"]
            elif isinstance(data, list):
                raw = data
    elif isinstance(config, dict) and "origins" in config:
        raw = config["origins"]

    out: list[Origin] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            Origin(
                key=str(item.get("key") or "origin-unknown"),
                category=str(item.get("category") or "origin-unknown"),
                label=str(item.get("label") or item.get("key") or "?"),
                detail=item.get("detail"),
                tables=list(item.get("tables") or []),
                stages=_norm_stages(item.get("stages")),
            )
        )
    return out


def _norm_stages(raw) -> list[dict]:
    """Normalize sub-stages: keep only known stages in a fixed order."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "").strip().lower()
        if stage not in ORIGIN_STAGE_ORDER:
            continue
        out.append(
            {
                "stage": stage,
                "label": str(item.get("label") or ""),
                "detail": str(item.get("detail") or ""),
            }
        )
    out.sort(key=lambda s: ORIGIN_STAGE_ORDER.index(s["stage"]))
    return out


def classify_origin(table: str, origins: list[Origin]) -> Origin | None:
    """Find the origin of a source table by its name."""
    t = _norm(table)
    for o in origins:
        for name in o.tables:
            if _norm(name) == t:
                return o
    return None


def origin_json_block(origins: list[Origin], source_tables: list[str]) -> dict:
    """The `origin` JSON block for `PbiLineage.to_json()`.

    Every origin contains the list of source tables it generates; tables without
    an explicit mapping fall into the `origin-unknown` category.
    """
    known = {_norm(n) for o in origins for n in o.tables}
    unknown = [t for t in source_tables if _norm(t) not in known]

    items = []
    for sort_idx, o in enumerate(sorted(origins, key=lambda x: _cat_rank(x.category))):
        if not o.tables:
            continue
        items.append(
            {
                "key": o.key,
                "category": o.category,
                "label": o.label,
                "detail": o.detail,
                "tables": list(o.tables),
                "stages": list(o.stages),
                "sort": sort_idx,
            }
        )

    if unknown:
        items.append(
            {
                "key": "origin-unknown",
                "category": "origin-unknown",
                "label": ORIGIN_LABEL["origin-unknown"],
                "detail": None,
                "tables": sorted(unknown),
                "stages": [],
                "sort": len(items),
            }
        )

    return {
        "level": ORIGIN_LEVEL,
        "label": ORIGIN_LEVEL_LABEL,
        "categories": ORIGIN_ORDER,
        "stage_order": ORIGIN_STAGE_ORDER,
        "stage_label": ORIGIN_STAGE_LABEL,
        "items": items,
    }


def _cat_rank(category: str) -> int:
    try:
        return ORIGIN_ORDER.index(category)
    except ValueError:
        return len(ORIGIN_ORDER)


__all__ = [
    "Origin",
    "DEFAULT_ORIGINS",
    "ORIGIN_COLORS",
    "ORIGIN_LABEL",
    "ORIGIN_LEVEL",
    "ORIGIN_LEVEL_LABEL",
    "ORIGIN_ORDER",
    "ORIGIN_STAGE_COLORS",
    "ORIGIN_STAGE_LABEL",
    "ORIGIN_STAGE_ORDER",
    "load_origins",
    "classify_origin",
    "origin_json_block",
]

==================== FILE: src/agentic_bi/lineage/lineage_origins_data.py ====================

"""Built-in origin taxonomy constants and a neutral default origin map.

Replace DEFAULT_ORIGINS with your own map (or supply an ``origins.yaml``) to
adapt lineage to any dashboard without changing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ORIGIN_LEVEL = 0
ORIGIN_LEVEL_LABEL = "0 · Origin"

# Display order of origin categories
ORIGIN_ORDER = [
    "origin-pipeline",
    "origin-manual",
    "origin-reference",
    "origin-etl",
    "origin-unknown",
]

# Human-readable category label (for PlantUML/Excel)
ORIGIN_LABEL = {
    "origin-pipeline": "INDUSTRIAL PIPELINE",
    "origin-manual": "MANUAL SOURCES (operators)",
    "origin-reference": "INLINE REFERENCE TABLES (M code)",
    "origin-etl": "ETL / LEGACY PROCESS",
    "origin-unknown": "OTHER / UNKNOWN",
}

# PlantUML node style (ref style, light palette)
ORIGIN_COLORS = {
    "origin-pipeline": "#d5e8d4",
    "origin-manual": "#ffe6cc",
    "origin-reference": "#e1d5e7",
    "origin-etl": "#f8cecc",
    "origin-unknown": "#f5f5f5",
}

# Sub-stages of the first stage: source -> processing -> load
ORIGIN_STAGE_ORDER = ["source", "process", "load"]
ORIGIN_STAGE_LABEL = {
    "source": "SOURCE",
    "process": "PROCESSING",
    "load": "LOAD",
}
ORIGIN_STAGE_COLORS = {
    "source": "#fff2cc",
    "process": "#dae8fc",
    "load": "#d5e8d4",
}


@dataclass
class Origin:
    """The origin of one source (generating process/repository).

    Fields:
        key: a stable origin identifier key.
        category: category (origin-pipeline/manual/reference/etl/unknown).
        label: a human-readable process/repository name.
        detail: details (repository, artifact, comment).
        tables: source-table names of the model belonging to this origin.
        stages: sub-stages of the first stage: [{stage, label, detail}, ...], where
            stage is one of {source, process, load}: from where -> processed by -> loaded to.
    """

    key: str
    category: str
    label: str
    detail: str | None = None
    tables: list[str] = field(default_factory=list)
    stages: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Neutral built-in origin map (sample - replace with your own)
# --------------------------------------------------------------------------- #
# Keys are model source-table names (as in the model table).
# stages: the chain "SOURCE -> PROCESSING -> LOAD" (source/process/load).
DEFAULT_ORIGINS: list[dict] = [
    {
        "key": "warehouse_pipeline",
        "category": "origin-pipeline",
        "label": "warehouse-pipeline",
        "detail": ("industrial pipeline that builds the fact/mart source table"),
        "tables": ["dim_registry"],
        "stages": [
            {
                "stage": "source",
                "label": "Registry (registry:excel)",
                "detail": "request forms -> 'registry.xlsx'",
            },
            {
                "stage": "process",
                "label": "combine (left join by id)",
                "detail": "merge registry and monitoring data",
            },
            {
                "stage": "load",
                "label": "sink:warehouse -> fact_table",
                "detail": "Spark/Parquet -> warehouse table (+ load_dt)",
            },
        ],
    },
    {
        "key": "manual_share",
        "category": "origin-manual",
        "label": "Manual Excel · \\\\fileserver\\share\\team",
        "detail": "operator-maintained Excel files on a network share (no auto pipeline)",
        "tables": [
            "Recommendation status",
            "Time in queue",
            "Comments",
        ],
        "stages": [
            {
                "stage": "source",
                "label": "Operator Excel files",
                "detail": "\\\\fileserver\\share\\team\\*.xlsx: statuses, time, comments",
            },
            {
                "stage": "process",
                "label": "Manual maintenance (operator)",
                "detail": "edits are made by hand in Excel; no auto pipeline",
            },
            {
                "stage": "load",
                "label": "Power Query (Excel.Workbook)",
                "detail": "M code reads the network share directly into model tables",
            },
        ],
    },
    {
        "key": "personal_disk",
        "category": "origin-manual",
        "label": "Manual Excel · personal drive",
        "detail": "source_merged.xlsx - a reference of business lines/owners",
        "tables": ["Business line"],
        "stages": [
            {
                "stage": "source",
                "label": "source_merged.xlsx",
                "detail": "C:\\path\\to\\source_merged.xlsx",
            },
            {
                "stage": "process",
                "label": "Manual reference assembly",
                "detail": "the business-line/owner reference is assembled by hand",
            },
            {
                "stage": "load",
                "label": "Power Query (Excel.Workbook)",
                "detail": "M code reads the personal-drive file -> Business line table",
            },
        ],
    },
    {
        "key": "inline_reference",
        "category": "origin-reference",
        "label": "Inline reference table",
        "detail": "a constant inside the .pbix M code; no external source",
        "tables": ["Materiality"],
        "stages": [
            {
                "stage": "source",
                "label": "M-code constant",
                "detail": "data is embedded directly in the .pbix (base64)",
            },
            {
                "stage": "process",
                "label": "No processing",
                "detail": "a ready table; no external process/ETL",
            },
            {
                "stage": "load",
                "label": "Model table",
                "detail": "M code -> an inline dimension table in the VertiPaq model",
            },
        ],
    },
]

==================== FILE: src/agentic_bi/lineage/pbi_lineage.py ====================

"""
Build data lineage of a Power BI dashboard (.pbix) without Power BI installed.

The `PbiLineage` class parses any .pbix (embedded VertiPaq model) and produces
the full linear data trail:

    Origin (process/repository) -> Source -> Power Query
    -> model tables -> semantics -> pages -> visuals.

Data sources:
- Model (tables, measures, calculated columns, schema, relationships, M code) via `pbixray`.
- Report layout (pages, visuals, queryRef bindings) from `Report/Layout` (JSON).

Usage example:

    from agentic_bi.lineage.pbi_lineage import PbiLineage

    lg = PbiLineage("C:/dashboards/report.pbix")
    lg.print_summary()                      # a short summary to the console
    lg.export_excel("out/lineage.xlsx")     # 3 sheets: pages/visuals/tables
    lg.export_markdown("out/REPORT.md")     # a human-readable report
    df_visuals = lg.visuals_dataframe       # visuals as a pandas.DataFrame

Dependencies: pbixray, pandas, openpyxl.

Implementation is split across mixins for readability:
    lineage_types.py    - Source/Visual/Page dataclasses + helpers
    lineage_model.py    - model extraction, layout parsing, source resolution
    lineage_query.py    - counts / DataFrames / lookup helpers
    lineage_export.py   - summary, Excel, Markdown, JSON, brand metrics
    lineage_plantuml.py - the PlantUML data-flow diagram
"""

from __future__ import annotations

import logging
from pathlib import Path

from agentic_bi.lineage.lineage_export import ExportMixin
from agentic_bi.lineage.lineage_model import ModelMixin
from agentic_bi.lineage.lineage_plantuml import PlantUmlMixin
from agentic_bi.lineage.lineage_query import QueryMixin
from agentic_bi.lineage.lineage_sources import SourceMixin
from agentic_bi.lineage.lineage_types import (  # noqa: F401
    Page,
    Source,
    SourceAccessError,
    Visual,
    VisualBinding,
    _load_brand_config,
)

logger = logging.getLogger(__name__)


class PbiLineage(ModelMixin, SourceMixin, QueryMixin, ExportMixin, PlantUmlMixin):
    """Extract data lineage from a .pbix.

    Args:
        pbix_path: path to the .pbix file.
        display_aliases: map of displayed table names -> physical ones
            (e.g. {"Sales Registry": "dim_registry"}).
            Used when visuals reference tables by display name.
        brand_config: path to `brand_config.yaml/json` (brand rules for page
            compliance metrics); defaults to `brand.py`.
    """

    # Technical tables (DateTable / LocalDateTable), created by Power BI
    _TECH_PREFIXES = ("DateTableTemplate_", "LocalDateTable_")

    def __init__(
        self,
        pbix_path: str | Path,
        display_aliases: dict[str, str] | None = None,
        origins: list | dict | str | Path | None = None,
        brand_config: str | Path | None = None,
    ):
        self.pbix_path = Path(pbix_path).resolve()
        if not self.pbix_path.exists():
            raise FileNotFoundError(f"File not found: {self.pbix_path}")
        self.display_aliases = display_aliases or {}
        self.origins = load_origins(origins)
        self._brand_cfg = _load_brand_config(brand_config)
        self._brand_cache: dict | None = None
        self._pu_seen: set[str] = set()
        self._pu_ids: dict[tuple[str, str], str] = {}
        self._unresolved_table_refs: set[str] = set()

        self._model = None
        self._open_model()

        try:
            self._load_model_artifacts()
            self._load_layout()
            self._build()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Close the pbixray model."""
        if self._model is not None:
            try:
                self._model.close()
            finally:
                self._model = None

    def __enter__(self) -> PbiLineage:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# Imported here to avoid a circular import at module definition time.
from agentic_bi.lineage.lineage_origins import load_origins  # noqa: E402


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json

    from agentic_bi.cli_support import run_boundary

    parser = argparse.ArgumentParser(
        prog="agentic-bi-lineage",
        description="Build data lineage of a Power BI dashboard (.pbix).\n"
        "Process: input .pbix -> output JSON with the analysis structure.",
    )
    parser.add_argument("pbix", help="path to the .pbix file (input)")
    parser.add_argument(
        "--json",
        dest="json_out",
        default=None,
        metavar="OUT.json",
        help="output JSON path (default: <out-dir>/lineage.json)",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="print the JSON analysis to stdout (instead of saving)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="output directory (default: output_files/pbi_lineage)",
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        metavar="DISPLAY=PHYSICAL",
        help="display table name -> physical alias (repeatable)",
    )
    parser.add_argument("--no-xlsx", action="store_true", help="do not save Excel")
    parser.add_argument("--no-md", action="store_true", help="do not save Markdown")
    parser.add_argument("--no-json", action="store_true", help="do not save JSON")
    parser.add_argument(
        "--plantuml",
        action="store_true",
        help="add the PlantUML diagram to the JSON 'plantuml' key",
    )
    parser.add_argument(
        "--brand-config",
        default=None,
        metavar="brand_config.yaml",
        help="brand rules config (page compliance metrics)",
    )
    args = parser.parse_args(argv)

    def body() -> int:
        aliases = {}
        for a in args.alias:
            if "=" in a:
                k, _, v = a.partition("=")
                aliases[k] = v

        out_dir = (
            Path(args.out_dir) if args.out_dir else Path("output_files") / "pbi_lineage"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        with PbiLineage(args.pbix, aliases, brand_config=args.brand_config) as lg:
            # main output - the structured JSON
            if args.print_json:
                # JSON to stdout (minimal object; plantuml per flag)
                print(_json.dumps(lg.to_json(), ensure_ascii=False, indent=2))
            else:
                if not args.no_json:
                    json_path = (
                        Path(args.json_out)
                        if args.json_out
                        else out_dir / "lineage.json"
                    )
                    p = lg.export_json(json_path)
                    print("JSON export:", p)
                lg.print_summary()
                if not args.no_xlsx:
                    p = lg.export_excel(out_dir / "lineage.xlsx")
                    print("Excel export:", p)
                if not args.no_md:
                    p = lg.export_markdown(out_dir / "REPORT.md")
                    print("Markdown export:", p)
        return 0

    return run_boundary(body, prog="agentic-bi-lineage")


if __name__ == "__main__":
    raise SystemExit(main())

