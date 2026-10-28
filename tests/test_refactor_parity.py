"""Refactor-parity tests for the modules split out of oversized files.

`brand_eval` / `brand_audit_eval` / `engine_layout_visual` / `lineage_export` each
exceeded the file-size budget after formatting, so cohesive parts moved into
`brand_eval_background`, `brand_audit_math`, `engine_layout_query` and
`lineage_export_data`. These tests pin the extracted behaviour and the re-exports
so the split stays invisible to callers.

Stage 4 then gave those families their own subpackages (`engine/`, `brand/`,
`skeleton/`). The historical flat paths remain as one-release shims that alias to
the moved module, which the tests at the bottom pin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi import brand_audit_math, brand_eval, brand_eval_background

# --------------------------------------------------------------------------
# brand_eval_background / brand_audit_math
# --------------------------------------------------------------------------


def test_contrast_ratio_black_on_white_is_max() -> None:
    assert brand_eval_background.contrast_ratio("#000000", "#ffffff") == 21.0


def test_contrast_ratio_is_symmetric() -> None:
    a = brand_eval_background.contrast_ratio("#D32F2F", "#ffffff")
    b = brand_eval_background.contrast_ratio("#ffffff", "#D32F2F")
    assert a == b


def test_contrast_ratio_accepts_short_hex() -> None:
    assert brand_eval_background.contrast_ratio("#000", "#fff") == 21.0


def test_background_findings_flags_missing_background() -> None:
    out = brand_eval_background.background_findings(None)
    assert [f.rule_id for f in out] == ["BG-ALLOWED"]


def test_background_findings_accepts_neutral_background() -> None:
    assert brand_eval_background.background_findings("#ffffff") == []


def test_background_findings_flags_off_palette_background() -> None:
    out = brand_eval_background.background_findings("#123456")
    assert [f.rule_id for f in out] == ["BG-ALLOWED"]


def test_background_findings_flags_low_contrast_text() -> None:
    out = brand_eval_background.background_findings("#ffffff", text_color="#eeeeee")
    assert [f.rule_id for f in out] == ["BG-CONTRAST"]


def test_background_rule_is_reexported_from_brand_eval() -> None:
    assert brand_eval.background_findings is brand_eval_background.background_findings
    assert brand_eval.contrast_ratio is brand_eval_background.contrast_ratio


def test_is_neutral_detects_achromatic_colors() -> None:
    assert brand_audit_math.is_neutral("#000000") is True
    assert brand_audit_math.is_neutral("#4A4A4A") is True
    assert brand_audit_math.is_neutral("#D32F2F") is False


def test_is_neutral_accepts_hex_without_hash() -> None:
    assert brand_audit_math.is_neutral("4a4a4a") is True


def test_luminance_orders_black_below_white() -> None:
    assert brand_audit_math.luminance("#000000") < brand_audit_math.luminance("#ffffff")


def test_luminance_white_is_one() -> None:
    assert brand_audit_math.luminance("#ffffff") == pytest.approx(1.0, abs=1e-9)


def test_contrast_black_white() -> None:
    assert brand_audit_math.contrast("#000", "#fff") == 21.0


def test_font_weight_detects_longest_token() -> None:
    assert brand_audit_math.font_weight("Brand Sans ExtraBold") == "extrabold"


def test_font_weight_unknown_returns_empty() -> None:
    assert brand_audit_math.font_weight("plain family") == ""


# --------------------------------------------------------------------------
# engine_layout_query / engine_layout_visual
# --------------------------------------------------------------------------


def _cfg(kind: str, **kw) -> dict:
    from agentic_bi.engine_layout_visual import Visual, _visual_config

    return _visual_config(Visual(kind=kind, table="T", **kw))


def test_visual_rejects_unknown_kind() -> None:
    from agentic_bi.engine_layout_visual import Visual

    with pytest.raises(ValueError):
        Visual(kind="nope", table="T")


@pytest.mark.parametrize(
    ("kind", "kw", "roles"),
    [
        ("table", {"columns": ["a", "b"]}, {"Values"}),
        ("card", {"value": "b"}, {"Values"}),
        ("gauge", {"value": "b"}, {"Y"}),
        ("kpi", {"value": "b", "trend": "a"}, {"Indicator", "TrendLine"}),
        ("slicer", {"axis": "a"}, {"Values"}),
        ("matrix", {"columns": ["a"], "value": "b"}, {"Rows", "Values"}),
        ("treemap", {"axis": "a", "value": "b"}, {"Group", "Values"}),
        ("scatter", {"x": "a", "y": "b"}, {"X", "Y"}),
        ("column", {"axis": "a", "value": "b"}, {"Category", "Y"}),
        (
            "stackedBar",
            {"axis": "a", "value": "b", "series": "c"},
            {"Category", "Y", "Series"},
        ),
    ],
)
def test_projection_roles_per_kind(kind: str, kw: dict, roles: set[str]) -> None:
    sv = _cfg(kind, **kw)["singleVisual"]
    assert set(sv["projections"]) == roles


def test_optional_series_only_for_stacked_charts() -> None:
    sv = _cfg("column", axis="a", value="b", series="c")["singleVisual"]
    assert "Series" not in sv["projections"]


def test_measure_replaces_value_aggregation() -> None:
    sv = _cfg("card", measure="m")["singleVisual"]
    ref = sv["projections"]["Values"][0]["queryRef"]
    assert ref == "T.m"
    assert any("Measure" in item for item in sv["prototypeQuery"]["Select"])


def test_aggregation_queryref_uses_label() -> None:
    sv = _cfg("card", value="b", agg="avg")["singleVisual"]
    assert sv["projections"]["Values"][0]["queryRef"] == "Avg(T.b)"


def test_data_query_built_from_prototype() -> None:
    from agentic_bi.engine_layout_query import _data_query

    sv = _cfg("card", value="b")["singleVisual"]
    cmd = json.loads(_data_query(sv))
    assert "Commands" in cmd
    assert (
        cmd["Commands"][0]["SemanticQueryDataShapeCommand"]["Query"]
        == sv["prototypeQuery"]
    )


def test_data_query_returns_none_without_prototype() -> None:
    from agentic_bi.engine_layout_query import _data_query

    assert _data_query({}) is None


def test_container_carries_query_and_geometry() -> None:
    from agentic_bi.engine_layout_visual import Visual, _container

    c = _container(Visual(kind="card", table="T", value="b"), 10, 20, 30, 40)
    assert (c["x"], c["y"], c["width"], c["height"]) == (10, 20, 30, 40)
    assert "query" in c and "dataTransforms" in c
    pos = json.loads(c["config"])["layouts"][0]["position"]
    assert (pos["x"], pos["y"], pos["width"], pos["height"]) == (10, 20, 30, 40)


def test_engine_layout_via_old_path_is_the_new_module() -> None:
    from agentic_bi import engine_layout
    from agentic_bi.engine import layout_visual

    assert engine_layout.Visual.__module__ == "agentic_bi.engine.layout_visual"
    assert engine_layout.Visual is layout_visual.Visual


# --------------------------------------------------------------------------
# Stage 4: every old flat path is an alias, not a copy
# --------------------------------------------------------------------------


#: Old flat module name -> new canonical dotted path.
MOVED_MODULES = {
    "engine_cli": "agentic_bi.engine.cli",
    "engine_container": "agentic_bi.engine.container",
    "engine_host": "agentic_bi.engine.host",
    "engine_layout": "agentic_bi.engine.layout",
    "engine_layout_query": "agentic_bi.engine.layout_query",
    "engine_layout_visual": "agentic_bi.engine.layout_visual",
    "engine_types": "agentic_bi.engine.types",
    "engine_verify": "agentic_bi.engine.verify",
    "engine_verify_brand": "agentic_bi.engine.verify_brand",
    "engine_verify_checks": "agentic_bi.engine.verify_checks",
    "engine_verify_core": "agentic_bi.engine.verify_core",
    "brand_audit": "agentic_bi.brand.audit",
    "brand_audit_eval": "agentic_bi.brand.audit_eval",
    "brand_audit_extract": "agentic_bi.brand.audit_extract",
    "brand_audit_math": "agentic_bi.brand.audit_math",
    "brand_audit_types": "agentic_bi.brand.audit_types",
    "brand_audit_typography": "agentic_bi.brand.audit_typography",
    "brand_config": "agentic_bi.brand.config",
    "brand_eval": "agentic_bi.brand.eval",
    "brand_eval_background": "agentic_bi.brand.eval_background",
    "brand_eval_common": "agentic_bi.brand.eval_common",
    "brand_fonts": "agentic_bi.brand.fonts",
    "brand_palette": "agentic_bi.brand.palette",
    "brand_rules": "agentic_bi.brand.rules",
    "skeleton_assembly": "agentic_bi.skeleton.assembly",
    "skeleton_container": "agentic_bi.skeleton.container",
    "skeleton_visuals": "agentic_bi.skeleton.visuals",
    "skeleton_visuals_extra": "agentic_bi.skeleton.visuals_extra",
}


@pytest.mark.parametrize(("old", "new"), sorted(MOVED_MODULES.items()))
def test_old_path_aliases_the_new_module(old: str, new: str) -> None:
    """Importing the old path yields the same module object, not a copy."""
    import importlib

    old_module = importlib.import_module(f"agentic_bi.{old}")
    new_module = importlib.import_module(new)
    assert old_module is new_module


@pytest.mark.parametrize("old", sorted(MOVED_MODULES))
def test_shim_exposes_the_public_api(old: str) -> None:
    """A shim must not hide the names the old module exported."""
    import importlib

    module = importlib.import_module(f"agentic_bi.{old}")
    assert getattr(module, "__all__", None) is not None or any(
        not name.startswith("_") for name in vars(module)
    )


def test_moved_names_kept_their_home_in_the_new_package() -> None:
    from agentic_bi.brand import palette
    from agentic_bi.engine import layout
    from agentic_bi.skeleton import visuals

    assert palette.ColorSpec.__module__ == "agentic_bi.brand.palette"
    assert layout.Visual.__module__ == "agentic_bi.engine.layout_visual"
    assert visuals.card_visual.__module__ == "agentic_bi.skeleton.visuals"


# --------------------------------------------------------------------------
# lineage_export_data
# --------------------------------------------------------------------------


@pytest.mark.parametrize("include_plantuml", [True, False])
def test_to_json_matches_export_data(
    template_pbix: Path, include_plantuml: bool
) -> None:
    from agentic_bi.lineage.lineage_export_data import build_lineage_data
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    lin = PbiLineage(str(template_pbix))
    a = lin.to_json(include_plantuml=include_plantuml)
    b = build_lineage_data(lin, include_plantuml=include_plantuml)
    del a["meta"], a["summary"], b["meta"], b["summary"]  # timestamps
    assert a == b


def test_lineage_data_structure(template_pbix: Path) -> None:
    from agentic_bi.lineage.lineage_export_data import build_lineage_data
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    data = build_lineage_data(PbiLineage(str(template_pbix)), include_plantuml=False)
    assert set(data) >= {
        "meta",
        "summary",
        "sources",
        "origin",
        "tables",
        "semantics",
        "pages",
        "brand",
        "unresolved_table_refs",
    }
    assert data["pages"] and data["summary"]["pages"] == len(data["pages"])
    assert data["tables"] and data["sources"]["by_table"]


def test_lineage_data_embeds_plantuml(template_pbix: Path) -> None:
    from agentic_bi.lineage.lineage_export_data import build_lineage_data
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    data = build_lineage_data(PbiLineage(str(template_pbix)), include_plantuml=True)
    assert data["plantuml"]["lineage"].startswith("@startuml")


def test_export_json_writes_valid_json(tmp_path: Path, template_pbix: Path) -> None:
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    out = PbiLineage(str(template_pbix)).export_json(tmp_path / "o.json")
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["pages"] > 0
