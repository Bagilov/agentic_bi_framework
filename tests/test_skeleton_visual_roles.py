"""Every skeleton visual builder must pass the real Power BI role tables.

`chart_visual` used to emit the value projection under ``Values`` for
``lineChart``/``clusteredColumnChart``. Power BI's cartesian charts expose
``Category``/``Y``/``Series``, so `visual_check.check_layout` rejected every
board built through that helper ("role 'Values' not allowed", "missing required
role 'Y'"). These tests validate the produced containers with the real
validator (no mocks) and pin the role names for every public builder.
"""

from __future__ import annotations

import json

import pytest

from agentic_bi import visual_check
from agentic_bi.skeleton import visuals, visuals_extra

TABLE = "Sales"
MEASURE_TABLE = "Sales Measures"
COLUMNS = ["region", "product", "sale_date", "amount", "qty"]
MEASURES = ["Total Sales"]
REGISTRY = {
    TABLE: {"columns": COLUMNS, "measures": MEASURES},
    MEASURE_TABLE: {"columns": [], "measures": MEASURES},
}

AXIS = {"kind": "column", "property": "region", "display": "Region"}
SERIES = {"kind": "column", "property": "product", "display": "Product"}
AMOUNT_AGG = {"kind": "column", "property": "amount", "display": "Amount", "agg": True}
QTY_AGG = {"kind": "column", "property": "qty", "display": "Qty", "agg": True}
TOTAL_MEASURE = {"kind": "measure", "property": "Total Sales", "display": "Total"}

CHART_TYPES = ("lineChart", "clusteredColumnChart")
VALUE_FIELDS = (TOTAL_MEASURE, AMOUNT_AGG)


def _single(container: dict) -> dict:
    return json.loads(container["config"])["singleVisual"]


def _errors(container: dict) -> list[str]:
    layout = {"sections": [{"displayName": "P", "visualContainers": [container]}]}
    return visual_check.check_layout(layout, REGISTRY)


# ─── chart_visual ───────────────────────────────────────────


@pytest.mark.parametrize("visual_type", CHART_TYPES)
@pytest.mark.parametrize("value", VALUE_FIELDS)
def test_chart_visual_passes_the_validator(visual_type: str, value: dict) -> None:
    container = visuals.chart_visual(visual_type, AXIS, value, TABLE)
    assert _errors(container) == []


@pytest.mark.parametrize("visual_type", CHART_TYPES)
@pytest.mark.parametrize("value", VALUE_FIELDS)
def test_chart_visual_uses_category_and_y_roles(visual_type: str, value: dict) -> None:
    projections = _single(visuals.chart_visual(visual_type, AXIS, value, TABLE))[
        "projections"
    ]
    assert set(projections) == {"Category", "Y"}
    assert projections["Category"][0]["queryRef"] == "Sales.region"


def test_chart_visual_is_a_real_catalog_type() -> None:
    for visual_type in CHART_TYPES:
        assert visual_type in visual_check.ALLOWED
        assert {"Category", "Y"} <= visual_check.ALLOWED[visual_type]


@pytest.mark.parametrize("visual_type", CHART_TYPES)
def test_chart_visual_keeps_query_refs_and_flags(visual_type: str) -> None:
    single = _single(visuals.chart_visual(visual_type, AXIS, AMOUNT_AGG, TABLE))
    assert single["drillFilterOtherVisuals"] is True
    assert single["hasDefaultSort"] is True
    names = {s["Name"] for s in single["prototypeQuery"]["Select"]}
    for refs in single["projections"].values():
        for ref in refs:
            assert ref["queryRef"] in names


def test_chart_visual_with_a_separate_measure_table() -> None:
    container = visuals.chart_visual(
        "clusteredColumnChart",
        AXIS,
        TOTAL_MEASURE,
        TABLE,
        measure_table=MEASURE_TABLE,
        measure_alias="s",
    )
    assert _errors(container) == []
    single = _single(container)
    assert single["projections"]["Y"][0]["queryRef"] == "Sales Measures.Total Sales"
    sources = {f["Name"] for f in single["prototypeQuery"]["From"]}
    assert sources == {"m", "s"}


# ─── every public builder ───────────────────────────────────


def _builder_containers() -> dict[str, list[dict]]:
    return {
        "card_measure": [visuals.card_visual(TOTAL_MEASURE, TABLE)],
        "card_agg": [visuals.card_visual(AMOUNT_AGG, TABLE)],
        "chart_line": [visuals.chart_visual("lineChart", AXIS, AMOUNT_AGG, TABLE)],
        "chart_column": [
            visuals.chart_visual("clusteredColumnChart", AXIS, AMOUNT_AGG, TABLE)
        ],
        "table": [visuals.table_visual([AXIS, AMOUNT_AGG], TABLE)],
        "stacked_no_series": [
            visuals_extra.stacked_visual(AXIS, AMOUNT_AGG, None, TABLE)
        ],
        "stacked_series": [
            visuals_extra.stacked_visual(AXIS, AMOUNT_AGG, SERIES, TABLE)
        ],
        "treemap": [visuals_extra.treemap_visual(AXIS, AMOUNT_AGG, TABLE)],
        "scatter": [visuals_extra.scatter_visual(AMOUNT_AGG, QTY_AGG, None, TABLE)],
        "scatter_size": [
            visuals_extra.scatter_visual(AMOUNT_AGG, QTY_AGG, QTY_AGG, TABLE)
        ],
        "kpi_band": visuals_extra.kpi_band([TOTAL_MEASURE, AMOUNT_AGG], TABLE),
    }


@pytest.mark.parametrize("case", sorted(_builder_containers()))
def test_builder_passes_the_validator(case: str) -> None:
    containers = _builder_containers()[case]
    assert containers
    for container in containers:
        assert _errors(container) == []


def test_only_cartesian_roles_are_y_not_values() -> None:
    for case, containers in _builder_containers().items():
        for container in containers:
            single = _single(container)
            projections = single["projections"]
            if single["visualType"] in CHART_TYPES:
                assert "Values" not in projections, f"{case} still uses Values"
                assert "Y" in projections, f"{case} lost the Y role"


def _public_builders(module) -> set[str]:
    return {
        name
        for name, obj in vars(module).items()
        if not name.startswith("_")
        and callable(obj)
        and getattr(obj, "__module__", None) == module.__name__
        and name != "page_filter"
    }


def test_all_public_visual_builders_are_covered() -> None:
    assert _public_builders(visuals) == {"card_visual", "chart_visual", "table_visual"}
    assert _public_builders(visuals_extra) == {
        "stacked_visual",
        "treemap_visual",
        "scatter_visual",
        "kpi_band",
    }


def test_legacy_shims_export_the_fixed_builders() -> None:
    from agentic_bi import skeleton_visuals, skeleton_visuals_extra

    assert skeleton_visuals.chart_visual is visuals.chart_visual
    assert skeleton_visuals_extra.stacked_visual is visuals_extra.stacked_visual
