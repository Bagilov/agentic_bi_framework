"""Role/type consistency across the engine, skeleton extras and the gallery.

Covers the fall-out of collapsing the invented `stackedColumnChart`/
`stackedBarChart` names onto Desktop's real types:

  - every kind maps to its own visualType: `column` is the *clustered* column,
    `bar` the clustered bar, and the stacked variants keep `columnChart`/
    `barChart` plus their Series role; a shared value would make one kind
    unreachable and render it under the wrong shape;
  - every kind the engine can build satisfies the validator's REQUIRED roles;
  - `series` is never dropped silently: either the kind supports it or
    `Visual(...)` rejects it;
  - the gallery must not contain two visuals with the same visualType *and* the
    same projections, and the whole page must pass `check_layout`;
  - the gallery must not put one column into both Category and Series;
  - `barChart` role names must match a real Power BI sample (it has "Rows");
  - web_mock knows only real visualTypes (`pivotTable`, never `matrix`).
"""

from __future__ import annotations

import json

import pytest

from agentic_bi import visual_check
from agentic_bi.engine.layout import gallery_visuals
from agentic_bi.engine.layout_visual import _VISUAL_TYPES, Visual, _container

COLUMNS = [
    {"name": "region", "type": "string"},
    {"name": "product", "type": "string"},
    {"name": "sale_date", "type": "date"},
    {"name": "amount", "type": "double"},
    {"name": "qty", "type": "int64"},
]
REGISTRY = {
    "Sales": {
        "columns": [c["name"] for c in COLUMNS],
        "measures": [],
    }
}

CATEGORY_KINDS = (
    "column",
    "bar",
    "line",
    "area",
    "pie",
    "donut",
    "funnel",
    "waterfall",
)


def _single(container: dict) -> dict:
    return json.loads(container["config"])["singleVisual"]


def _layout_errors(container: dict) -> list[str]:
    layout = {"sections": [{"displayName": "P", "visualContainers": [container]}]}
    return visual_check.check_layout(layout, REGISTRY)


def _kind_args(kind: str) -> dict:
    """Minimal inputs that satisfy `Visual._REQUIRED` for every supported kind."""
    if kind == "table":
        return {"columns": ["region"]}
    if kind == "matrix":
        return {"columns": ["region"], "value": "amount"}
    if kind in ("card", "gauge"):
        return {"value": "amount"}
    if kind == "kpi":
        return {"value": "amount", "trend": "sale_date"}
    if kind == "slicer":
        return {"axis": "region"}
    if kind == "scatter":
        return {"x": "amount", "y": "qty"}
    if kind == "treemap":
        return {"axis": "region", "value": "amount"}
    if kind in CATEGORY_KINDS or kind in ("stackedColumn", "stackedBar"):
        args = {"axis": "region", "value": "amount"}
        if kind in ("stackedColumn", "stackedBar"):
            args["series"] = "product"
        return args
    raise AssertionError(f"no test inputs for kind {kind!r}")


@pytest.mark.parametrize("kind", sorted(_VISUAL_TYPES))
def test_every_engine_kind_passes_check_layout(kind: str) -> None:
    visual = Visual(kind, "Sales", **_kind_args(kind))
    errors = _layout_errors(_container(visual, 0, 0, 100, 100))
    assert errors == [], f"{kind} -> {errors}"


def test_every_kind_maps_to_a_distinct_visual_type() -> None:
    # Two kinds sharing a type is how `bar` silently rendered as stacked: only
    # one of them is reachable from the emitted visualType. Table-like kinds
    # would be allowed to share, but no such pair exists, so keep the invariant
    # strict - it also catches a *new* kind colliding with an existing one.
    by_type: dict[str, str] = {}
    for kind, visual_type in _VISUAL_TYPES.items():
        assert visual_type not in by_type, (
            f"{kind} and {by_type[visual_type]} both emit {visual_type}"
        )
        by_type[visual_type] = kind


def test_kind_column_emits_the_clustered_type() -> None:
    assert _VISUAL_TYPES["column"] == "clusteredColumnChart"
    visual = Visual("column", "Sales", axis="region", value="amount")
    assert _single(_container(visual, 0, 0, 100, 100))["visualType"] == (
        "clusteredColumnChart"
    )


def test_kind_bar_emits_the_clustered_type_not_the_stacked_one() -> None:
    assert _VISUAL_TYPES["bar"] == "clusteredBarChart"
    visual = Visual("bar", "Sales", axis="region", value="amount")
    assert _single(_container(visual, 0, 0, 100, 100))["visualType"] == (
        "clusteredBarChart"
    )
    assert _VISUAL_TYPES["stackedBar"] == "barChart"


@pytest.mark.parametrize("kind", ["stackedColumn", "stackedBar"])
def test_stacked_kinds_keep_the_series_role(kind: str) -> None:
    visual = Visual(kind, "Sales", axis="region", value="amount", series="product")
    projections = _single(_container(visual, 0, 0, 100, 100))["projections"]
    assert "Series" in projections
    assert projections["Category"][0]["queryRef"] == "Sales.region"


@pytest.mark.parametrize("kind", ["column", "bar", "line", "area"])
def test_clustered_and_line_kinds_honour_their_series(kind: str) -> None:
    # A legend is valid on clustered/line charts; dropping `series` would build
    # a chart that looks fine but is missing the requested breakdown.
    visual = Visual(kind, "Sales", axis="region", value="amount", series="product")
    projections = _single(_container(visual, 0, 0, 100, 100))["projections"]
    assert projections["Series"][0]["queryRef"] == "Sales.product"
    assert _layout_errors(_container(visual, 0, 0, 100, 100)) == []


@pytest.mark.parametrize("kind", ["table", "card", "slicer", "treemap", "scatter"])
def test_series_on_a_kind_without_a_series_role_is_rejected(kind: str) -> None:
    kwargs = _kind_args(kind) | {"series": "product", "table": "Sales"}
    with pytest.raises(ValueError, match="no Series role"):
        Visual(kind, **kwargs)


def test_gallery_has_no_duplicate_type_and_projection_pair() -> None:
    seen: dict[tuple[str, str], str] = {}
    for visual in gallery_visuals("Sales", COLUMNS):
        single = _single(_container(visual, 0, 0, 100, 100))
        key = (
            single["visualType"],
            json.dumps(single["projections"], sort_keys=True),
        )
        assert key not in seen, (
            f"{visual.kind} duplicates {seen[key]}: same visualType and projections"
        )
        seen[key] = visual.kind


def test_every_gallery_visual_satisfies_allowed_and_required_roles() -> None:
    visuals = gallery_visuals("Sales", COLUMNS)
    assert {v.kind for v in visuals} >= {"column", "bar", "stackedColumn", "stackedBar"}
    for visual in visuals:
        single = _single(_container(visual, 0, 0, 100, 100))
        visual_type = single["visualType"]
        assert visual_type in visual_check.ALLOWED, f"{visual.kind} -> {visual_type}"
        allowed = visual_check.ALLOWED[visual_type]
        projections = single["projections"]
        assert set(projections) <= allowed, f"{visual.kind} -> {set(projections)}"
        for role in visual_check.REQUIRED.get(visual_type, []):
            assert role in projections, f"{visual.kind} lost required role {role}"


def test_the_whole_gallery_page_passes_check_layout() -> None:
    visuals = gallery_visuals("Sales", COLUMNS)
    layout = {
        "sections": [
            {
                "displayName": "Gallery",
                "visualContainers": [
                    _container(v, i * 10, 0, 100, 100) for i, v in enumerate(visuals)
                ],
            }
        ]
    }
    assert visual_check.check_layout(layout, REGISTRY) == []


def test_gallery_stacked_visuals_carry_a_series() -> None:
    stacked = [
        v
        for v in gallery_visuals("Sales", COLUMNS)
        if v.kind in ("stackedColumn", "stackedBar")
    ]
    assert stacked
    for visual in stacked:
        assert visual.series, f"{visual.kind} lost its Series breakdown"
        projections = _single(_container(visual, 0, 0, 100, 100))["projections"]
        assert "Series" in projections


def test_single_category_column_never_becomes_its_own_series() -> None:
    columns = [
        {"name": "region", "type": "string"},
        {"name": "amount", "type": "double"},
    ]
    visuals = gallery_visuals("Sales", columns)
    for visual in visuals:
        if visual.kind in ("stackedColumn", "stackedBar"):
            assert visual.series != visual.axis
        projections = _single(_container(visual, 0, 0, 100, 100))["projections"]
        if "Series" in projections:
            series_ref = projections["Series"][0]["queryRef"]
            assert series_ref != projections["Category"][0]["queryRef"], visual.kind


def test_bar_chart_roles_match_real_power_bi_samples() -> None:
    # templates/template.pbix sec4/vis1 (page "Pipeline Trends") carries Rows.
    allowed = visual_check.ALLOWED["barChart"]
    assert {"Category", "Y", "Rows"} <= allowed
    assert visual_check.REQUIRED["barChart"] == ["Category", "Y"]


def test_matrix_is_not_a_power_bi_visual_type() -> None:
    assert "matrix" not in visual_check.ALLOWED
    assert "pivotTable" in visual_check.ALLOWED


def test_web_mock_category_is_predictable_for_unknown_types() -> None:
    from agentic_bi.web_report import web_mock

    assert web_mock.category("definitelyNotAVisual") == "unknown"
    assert web_mock.category("") == "unknown"
    assert "<svg" in web_mock.mock_body("definitelyNotAVisual")
    assert web_mock.category("matrix") == "unknown"
    assert web_mock.category("pivotTable") == "matrix"
    assert web_mock.category("clusteredBarChart") == "bar"


def test_skeleton_extra_visuals_pass_check_layout() -> None:
    from agentic_bi.skeleton import visuals_extra

    axis = {"kind": "column", "property": "region", "display": "Region"}
    value = {"kind": "column", "property": "amount", "display": "Amount", "agg": True}
    series = {"kind": "column", "property": "product", "display": "Product"}
    qty = {"kind": "column", "property": "qty", "display": "Qty", "agg": True}
    containers = {
        "stacked": visuals_extra.stacked_visual(axis, value, series, "Sales"),
        "treemap": visuals_extra.treemap_visual(axis, value, "Sales"),
        "scatter": visuals_extra.scatter_visual(value, qty, None, "Sales"),
    }
    for name, container in containers.items():
        errors = _layout_errors(container)
        assert errors == [], f"{name} -> {errors}"
