"""Shared state contract for the `PbiLineage` mixins.

`PbiLineage` is composed from `ModelMixin`/`SourceMixin`/`QueryMixin`/
`ExportMixin`/`PlantUmlMixin`: every mixin fills in part of the instance state
and reads attributes (and helper methods) that a sibling mixin provides. A type
checker checks each method against its own mixin only, so it cannot see the
sibling state and reports `attr-defined` errors on real annotations.

This module states the composed contract once. A mixin method declares the state
it needs through a PEP 484 self-annotation:

    class ExportMixin:
        def print_summary(self: LineageState) -> None: ...

That is the supported way to type a mixin: nothing inherits from
`LineageState` at runtime and the protocol carries no behaviour. The mixins
still declare the attributes they *own* as class-level annotations, so the
composed `PbiLineage` keeps exposing them; this protocol covers the cross-mixin
reads.

The JSON builder additionally reads `origins` and writes the `_brand_summary` it
attaches while assembling the payload, so both are part of the contract below;
the `_brand_summary` readers keep a `getattr` default because a duck-typed model
that never went through the build does not have to define it.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from agentic_bi.lineage.lineage_origins_data import Origin
from agentic_bi.lineage.lineage_types import Page, Source

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

    from agentic_bi.brand.config import BrandConfig
    from agentic_bi.lineage.lineage_query import BrandMetrics, PageAnalysis
    from agentic_bi.lineage.lineage_types import Visual

LineageSelf = TypeVar("LineageSelf", bound="LineageState")


class PbixModel(Protocol):
    """The `pbixray.PBIXRay` surface the lineage build relies on.

    `pbixray` ships no type information (`no py.typed`), so the handle is
    described here instead of being used as `Any`. Attributes are the public
    `PBIXRay` properties read by `ModelMixin._load_model_artifacts`.
    """

    tables: list[str]
    dax_measures: pd.DataFrame
    dax_columns: pd.DataFrame
    schema: pd.DataFrame
    power_query: pd.DataFrame
    relationships: object

    def close(self) -> None: ...


class LineageState(Protocol):
    """Composed `PbiLineage` state that the mixins share."""

    # ---- handled model / raw layout ----
    _model: PbixModel | None
    _layout: dict[str, Any]

    # ---- model artifacts (`ModelMixin._load_model_artifacts`) ----
    tables: list[str]
    _tables_lower: dict[str, str]
    measures: dict[str, list[str]]
    calc_columns: dict[str, list[str]]
    columns: dict[str, list[str]]
    power_query: dict[str, str]
    relationships: object

    # ---- report layout and resolved sources (`ModelMixin._build`) ----
    pages: list[Page]
    sources: dict[str, Source]
    unresolved_sources: list[dict[str, Any]]
    table_refs: Counter[str]
    field_refs: Counter[str]
    _unresolved_table_refs: set[str]

    # ---- constructor state (`PbiLineage.__init__`) ----
    pbix_path: Path
    display_aliases: dict[str, str]
    origins: list[Origin]
    _brand_cfg: BrandConfig | None
    _brand_cache: BrandMetrics | None
    _brand_summary: dict[str, Any]

    @property
    def _TECH_PREFIXES(self) -> tuple[str, ...]: ...

    # ---- PlantUML node registry (`PbiLineage.__init__`, reset per render) ----
    _pu_seen: set[str]
    _pu_ids: dict[tuple[str, str], str]
    _PU_HEADER: str
    _PU_STYLE: str

    # ---- model extraction / layout parsing (`ModelMixin`) ----
    _HEX_RE: re.Pattern[str]
    _THEME_RE: re.Pattern[str]
    _FONT_RE: re.Pattern[str]

    def _open_model(self) -> None: ...
    def _load_model_artifacts(self) -> None: ...
    def _load_layout(self) -> None: ...
    def _build(self) -> None: ...
    def _resolve_table(self, token: str) -> str | None: ...
    def _collect_colors(self, sv: dict) -> set[str]: ...
    def _collect_fonts(self, sv: dict) -> set[str]: ...
    def _collect_visual_fonts(self, page: Page) -> list[str]: ...
    def _parse_visual(
        self, vc: dict, page_idx: int, page_name: str
    ) -> Visual | None: ...
    def _resolve_refs(self) -> dict[str, Counter[str]]: ...
    def _source_from_m(self, expr: str) -> Source: ...
    def _source_group(self, src: Source) -> str: ...
    def close(self) -> None: ...

    # ---- queries (`QueryMixin`) ----
    def is_technical(self, table: str) -> bool: ...
    def page_analysis(self) -> list[PageAnalysis]: ...
    @property
    def page_count(self) -> int: ...
    @property
    def visual_count(self) -> int: ...
    @property
    def total_measures(self) -> int: ...
    @property
    def total_calc_columns(self) -> int: ...
    def technical_tables(self) -> list[str]: ...
    def business_tables(self) -> list[str]: ...
    def _visual_brand(self, v: Visual) -> dict[str, Any]: ...
    def brand_metrics(self) -> BrandMetrics: ...
    @property
    def pages_dataframe(self) -> pd.DataFrame: ...
    @property
    def visuals_dataframe(self) -> pd.DataFrame: ...
    @property
    def tables_dataframe(self) -> pd.DataFrame: ...
    def tables_for_page(self, page_name: str) -> set[str]: ...
    def tables_for_visual(self, visual_type: str | None = None) -> Counter[str]: ...
    @property
    def unresolved_table_refs(self) -> list[str]: ...

    # ---- export (`ExportMixin`) ----
    def to_json(self, include_plantuml: bool = True) -> dict[str, Any]: ...
    def export_json(self, out_path: str | Path) -> Path: ...

    # ---- PlantUML (`PlantUmlMixin`) ----
    def _pu_escape(self, text: str) -> str: ...
    def _pu_id(self, prefix: str, name: str) -> str: ...
    def to_plantuml(self) -> str: ...
    def _render_plantuml_from_data(self, data: dict) -> str: ...


if TYPE_CHECKING:  # pragma: no cover - static conformance check only
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    def _assert_pbi_lineage_state(obj: PbiLineage) -> LineageState:
        """Fail the type check when `PbiLineage` drifts from the protocol."""
        return obj
