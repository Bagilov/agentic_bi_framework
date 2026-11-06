"""Regression tests for the lineage mixin typing pass (R2/F).

`PbiLineage` is composed from mixins whose shared state is described by
`LineageState`; the mixin methods now declare that state through a `self`
annotation. These tests pin the runtime consequences of that pass:

- the composed class still exposes the state the protocol promises;
- the PlantUML renderer still chains origin sub-stages and feeds the sources
  from the *last* stage (the node id is no longer an optional variable);
- the brand-metrics cache keeps its single-computation contract, including the
  fallback when the audit itself fails.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_bi.lineage.lineage_plantuml import PlantUmlMixin
from agentic_bi.lineage.lineage_plantuml_render import render_plantuml_from_data
from agentic_bi.lineage.lineage_query import QueryMixin
from agentic_bi.lineage.lineage_types import Page

STATE_ATTRIBUTES = (
    "pbix_path",
    "display_aliases",
    "tables",
    "measures",
    "calc_columns",
    "columns",
    "power_query",
    "pages",
    "sources",
    "unresolved_sources",
    "table_refs",
    "field_refs",
    "unresolved_table_refs",
    "_unresolved_table_refs",
    "_model",
    "_brand_cache",
)

STATE_METHODS = (
    "brand_metrics",
    "business_tables",
    "technical_tables",
    "is_technical",
    "to_json",
    "export_json",
    "to_plantuml",
)

STATE_PROPERTIES = (
    "page_count",
    "visual_count",
    "total_measures",
    "total_calc_columns",
    "pages_dataframe",
    "visuals_dataframe",
    "tables_dataframe",
)


def test_pbi_lineage_exposes_the_mixin_state(template_pbix: Path) -> None:
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    with PbiLineage(str(template_pbix)) as lg:
        for name in STATE_ATTRIBUTES:
            assert hasattr(lg, name), f"missing state attribute: {name}"
        for name in STATE_METHODS:
            assert callable(getattr(lg, name)), f"missing method: {name}"
        for name in STATE_PROPERTIES:
            assert getattr(lg, name) is not None, f"missing property: {name}"
        assert lg.page_count == len(lg.pages)
        assert lg.visual_count == sum(len(p.visuals) for p in lg.pages)
        assert isinstance(lg.unresolved_table_refs, list)


def test_enter_returns_the_composed_instance(template_pbix: Path) -> None:
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    lg = PbiLineage(str(template_pbix))
    try:
        assert lg.__enter__() is lg
    finally:
        lg.close()
    assert lg._model is None


class _RenderCtx(PlantUmlMixin):
    def __init__(self) -> None:
        self.pbix_path = Path("sample.pbix")


def _render_data(stages: list[dict]) -> dict:
    return {
        "origin": {
            "items": [
                {
                    "key": "k",
                    "label": "Load",
                    "category": "origin-unknown",
                    "tables": ["T"],
                    "stages": stages,
                }
            ]
        },
        "sources": {"by_group": {"Other sources": [{"table": "T", "detail": ""}]}},
        "tables": {"T": {"has_power_query": True, "technical": False, "refs": 1}},
        "semantics": {},
        "pages": [],
    }


def test_origin_stages_are_chained_and_the_last_stage_feeds_sources() -> None:
    data = _render_data(
        [
            {"stage": "source", "label": "Extract"},
            {"stage": "load", "label": "Load"},
        ]
    )
    out = render_plantuml_from_data(_RenderCtx(), data)

    assert out.startswith("@startuml") and out.rstrip().endswith("@enduml")
    assert "O_k_source_0 --> O_k_load_1" in out
    assert "O_k_load_1 --> S_T" in out
    assert "None" not in out


def test_origin_without_stages_is_a_single_node() -> None:
    out = render_plantuml_from_data(_RenderCtx(), _render_data([]))

    assert "as O_k " in out
    assert "O_k --> S_T" in out
    assert "None" not in out


class _BrandCtx(QueryMixin):
    def __init__(self) -> None:
        self.pages = [Page(index=1, name="Overview", visuals=[])]
        self._brand_cfg = None
        self._brand_cache = None

    def _collect_visual_fonts(self, page: Page) -> list[str]:
        return []


def test_brand_metrics_are_computed_once_and_cached() -> None:
    ctx = _BrandCtx()

    first = ctx.brand_metrics()
    assert ctx._brand_cache is first
    assert ctx.brand_metrics() is first
    assert set(first) == {"summary", "pages"}


def test_brand_metrics_fall_back_to_an_empty_cache_on_audit_failure(
    monkeypatch,
) -> None:
    from agentic_bi.lineage import lineage_query

    def _boom(pages: list[dict], cfg: object) -> dict:
        raise RuntimeError("brand rules unavailable")

    monkeypatch.setattr(lineage_query, "brand_audit_pages", _boom)
    ctx = _BrandCtx()

    assert ctx.brand_metrics() == {"summary": {}, "pages": {}}
    assert ctx.brand_metrics() == {"summary": {}, "pages": {}}
    assert ctx._brand_cache is None


def test_builder_rejects_a_model_missing_a_member(tmp_path: Path) -> None:
    """The JSON builder is typed: mypy sees a model that drifts from the state."""
    pytest.importorskip("mypy")
    repo = Path(__file__).resolve().parents[1]
    snippet = tmp_path / "builder_drift.py"
    snippet.write_text(
        "from agentic_bi.lineage.lineage_export_data import build_lineage_data\n"
        "\n"
        "\n"
        "class FakeModel:\n"
        "    pass\n"
        "\n"
        "\n"
        "def run(model: FakeModel) -> object:\n"
        "    return build_lineage_data(model)\n",
        encoding="utf-8",
    )
    env = dict(os.environ, MYPYPATH=str(repo / "src"))
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-error-summary", str(snippet)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "build_lineage_data" in output
    assert 'incompatible type "FakeModel"' in output
    assert "LineageState" in output
