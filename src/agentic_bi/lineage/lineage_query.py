"""Query/introspection helpers over the parsed lineage (counts, DataFrames)."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, TypedDict

import pandas as pd

from agentic_bi.lineage.lineage_brand import brand_audit_pages, visual_brand_metrics
from agentic_bi.lineage.lineage_state import LineageState
from agentic_bi.lineage.lineage_types import Source, Visual, _brand_level_ru

logger = logging.getLogger(__name__)


class PageAnalysis(TypedDict):
    """Element/palette summary of one page (`QueryMixin.page_analysis`)."""

    page: str
    elements: dict[str, int]
    n_elements: int
    colors: list[str]


class BrandMetrics(TypedDict):
    """Brand-book metrics: per-page results plus the aggregated summary.

    Leaf metric dictionaries stay open (`dict[str, Any]`): the metric shape is
    owned by `lineage_brand_metrics`, and the lineage layer only passes it
    through to the JSON/Excel/Markdown/PlantUML writers.
    """

    summary: dict[str, Any]
    pages: dict[str, dict[str, Any]]


class QueryMixin:
    # The brand-metrics cache owns no other state; see `LineageState` for the
    # attributes it reads from sibling mixins.
    _brand_cache: BrandMetrics | None

    def is_technical(self: LineageState, table: str) -> bool:
        return table.startswith(self._TECH_PREFIXES)

    # ======================= Public API ======================= #

    # -------- per-page element and color analysis --------
    def page_analysis(self: LineageState) -> list[PageAnalysis]:
        """Analyze each page: element types, counts, unique colors.

        Returns:
            One `PageAnalysis` per page:
                {page, elements: {type: count}, n_elements, colors: [hex/theme]}
        """
        result: list[PageAnalysis] = []
        for p in self.pages:
            etypes: Counter[str] = Counter()
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
    def page_count(self: LineageState) -> int:
        return len(self.pages)

    @property
    def visual_count(self: LineageState) -> int:
        return sum(len(p.visuals) for p in self.pages)

    @property
    def total_measures(self: LineageState) -> int:
        return sum(len(v) for v in self.measures.values())

    @property
    def total_calc_columns(self: LineageState) -> int:
        return sum(len(v) for v in self.calc_columns.values())

    def technical_tables(self: LineageState) -> list[str]:
        return [t for t in self.tables if self.is_technical(t)]

    def business_tables(self: LineageState) -> list[str]:
        return [t for t in self.tables if not self.is_technical(t)]

    # -------- brand-book compliance metrics --------
    def _visual_brand(self: LineageState, v: Visual) -> dict[str, Any]:
        """Brand metrics of a single visual (uses the class config)."""
        return visual_brand_metrics(
            {"colors": sorted(v.colors), "fonts": sorted(v.fonts)}, self._brand_cfg
        )

    def brand_metrics(self: LineageState) -> BrandMetrics:
        """Brand-book metrics by page (fonts/colors) + summary.

        Only a successful audit is cached, so a transient failure (or a failed
        page analysis) is retried on the next call instead of poisoning the
        cache for the lifetime of the instance. The cache is read through
        `getattr` so a duck-typed model that never initialises it is valid.

        Returns:
            {"summary": {...}, "pages": {page: metrics}} - a single computation for
            JSON, Excel, Markdown and PlantUML (see `lineage_brand`).
        """
        cached: BrandMetrics | None = getattr(self, "_brand_cache", None)
        if cached is not None:
            return cached
        try:
            colors_by_page = {
                a["page"]: list(a["colors"]) for a in self.page_analysis()
            }
            audit = brand_audit_pages(
                [
                    {
                        "name": p.name,
                        "colors": colors_by_page.get(p.name, []),
                        "fonts": self._collect_visual_fonts(p),
                    }
                    for p in self.pages
                ],
                self._brand_cfg,
            )
            cache: BrandMetrics = {
                "summary": audit["summary"],
                "pages": {r["name"]: r["metrics"] for r in audit["pages"]},
            }
        except Exception as exc:  # noqa: BLE001 - brand metrics are optional
            logger.warning("brand metrics unavailable: %s", exc)
            return {"summary": {}, "pages": {}}
        self._brand_cache = cache
        return cache

    # -------- DataFrames --------
    @property
    def pages_dataframe(self: LineageState) -> pd.DataFrame:
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
    def visuals_dataframe(self: LineageState) -> pd.DataFrame:
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
    def tables_dataframe(self: LineageState) -> pd.DataFrame:
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

    def tables_for_page(self: LineageState, page_name: str) -> set[str]:
        """Tables used on a specific page."""
        for p in self.pages:
            if p.name == page_name:
                return set(p.tables)
        return set()

    def tables_for_visual(
        self: LineageState, visual_type: str | None = None
    ) -> Counter[str]:
        """Tables used by visuals of a given type (or all)."""
        out: Counter[str] = Counter()
        for p in self.pages:
            for v in p.visuals:
                if visual_type and v.visual_type != visual_type:
                    continue
                for t in v.tables:
                    out[t] += 1
        return out

    # -------- export --------
    @property
    def unresolved_table_refs(self: LineageState) -> list[str]:
        """Display/layout table names that did not match any model table.

        Not an exception (parsing continues), but recorded explicitly so there are
        no silent losses in the visual -> table mapping.
        """
        return sorted(self._unresolved_table_refs)
