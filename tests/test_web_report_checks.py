"""Per-element check tests for the dashboard web clone (`web_report`).

These build layouts in memory (no `.pbix` needed) and assert on the typed issues
produced per element.
"""

from __future__ import annotations

import json

from tests.web_report_fixtures import make_container, make_layout, raw_container

from agentic_bi.web_report import inspect_layout
from agentic_bi.web_report.web_checks import has_in_filter as _has_in_filter


def test_inspect_counts_pages_and_elements():
    layout = make_layout(
        [
            make_container(
                "card",
                {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
                ["Sum(Sales.amount)"],
                title="Total",
            ),
            make_container(
                "columnChart",
                {
                    "Category": [{"queryRef": "Sales.region"}],
                    "Y": [{"queryRef": "Sum(Sales.amount)"}],
                },
                ["Sales.region", "Sum(Sales.amount)"],
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    assert len(model.pages) == 1
    assert len(model.elements) == 2
    card = model.elements[0]
    assert card.visual_type == "card"
    assert card.title == "Total"
    assert card.fields == ["Sum(Sales.amount)"]
    assert card.roles == ["Values"]


def test_clean_visual_has_no_issues():
    layout = make_layout(
        [
            make_container(
                "card",
                {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
                ["Sum(Sales.amount)"],
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    assert model.errors == 0
    assert model.elements[0].issues == []


def test_missing_projection_is_error():
    layout = make_layout(
        [
            raw_container({"singleVisual": {"visualType": "card", "projections": {}}}),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    codes = {i.check_id for i in model.elements[0].issues}
    assert "STRUCT-NO-PROJECTIONS" in codes
    assert model.errors >= 1


def test_missing_required_role_is_error():
    layout = make_layout(
        [
            make_container(
                "columnChart",
                {"Category": [{"queryRef": "Sales.region"}]},
                ["Sales.region"],
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    codes = {i.check_id for i in model.elements[0].issues}
    assert "STRUCT-MISSING-ROLE" in codes


def test_disallowed_role_is_error():
    layout = make_layout(
        [
            make_container(
                "card", {"Bogus": [{"queryRef": "Sales.region"}]}, ["Sales.region"]
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    codes = {i.check_id for i in model.elements[0].issues}
    assert "STRUCT-ROLE-NOT-ALLOWED" in codes


def test_queryref_without_select_is_error():
    layout = make_layout(
        [
            make_container("card", {"Values": [{"queryRef": "Sales.amount"}]}, []),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    codes = {i.check_id for i in model.elements[0].issues}
    assert "BIND-NO-SELECT" in codes


def test_registry_membership_flags_missing_column():
    layout = make_layout(
        [
            make_container(
                "card",
                {"Values": [{"queryRef": "Sum(Sales.missing)"}]},
                ["Sum(Sales.missing)"],
            ),
        ]
    )
    registry = {"Sales": {"columns": ["amount", "region"], "measures": []}}
    model = inspect_layout(layout, registry=registry, source="l.pbix")
    codes = {i.check_id for i in model.elements[0].issues}
    assert "BIND-FIELD-MISSING" in codes


def test_registry_membership_flags_missing_table():
    cfg = {
        "singleVisual": {
            "visualType": "card",
            "projections": {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
            "prototypeQuery": {
                "From": [{"Name": "t", "Entity": "Sales", "Type": 0}],
                "Select": [
                    {
                        "Name": "Sum(Sales.amount)",
                        "Aggregation": {
                            "Function": 0,
                            "Expression": {
                                "Column": {  # 'z' is not in From -> no entity
                                    "Expression": {"SourceRef": {"Source": "z"}},
                                    "Property": "amount",
                                }
                            },
                        },
                    }
                ],
            },
        },
    }
    model = inspect_layout(
        make_layout([raw_container(cfg)]),
        registry={"Sales": {"columns": ["amount"], "measures": []}},
        source="l.pbix",
    )
    codes = {i.check_id for i in model.elements[0].issues}
    assert "BIND-TABLE-MISSING" in codes


def test_static_visual_is_info_not_error():
    layout = make_layout(
        [
            raw_container(
                {
                    "singleVisual": {
                        "visualType": "textbox",
                        "projections": {},
                        "prototypeQuery": {},
                    }
                }
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    severities = {i.severity for i in model.elements[0].issues}
    assert severities == {"info"}
    assert model.errors == 0


def test_unsafe_in_filter_is_error():
    bad = json.dumps(
        [
            {
                "filter": {
                    "Where": [
                        {"Condition": {"In": {"Values": [{"Literal": {"Value": "1"}}]}}}
                    ]
                }
            }
        ]
    )
    container = make_container(
        "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
    )
    container["filters"] = bad
    model = inspect_layout(make_layout([container]), source="l.pbix")
    codes = {i.check_id for i in model.elements[0].issues}
    assert "FILTER-UNSAFE-IN" in codes


def test_has_in_filter_helper():
    assert _has_in_filter("[]") is False
    assert _has_in_filter("") is False
    assert (
        _has_in_filter(json.dumps([{"filter": {"Where": [{"Condition": {"In": {}}}]}}]))
        is True
    )


def test_element_metrics_count_colors_fonts_filters():
    container = make_container(
        "card",
        {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
        ["Sum(Sales.amount)"],
        title="Total",
    )
    cfg = json.loads(container["config"])
    cfg["singleVisual"]["objects"]["color"] = [
        {
            "properties": {
                "solid": {"color": {"expr": {"Literal": {"Value": "'#D32F2F'"}}}}
            }
        },
    ]
    cfg["singleVisual"]["objects"]["font"] = [
        {
            "properties": {
                "fontFamily": {"expr": {"Literal": {"Value": "'Brand Sans'"}}}
            }
        },
    ]
    container["config"] = json.dumps(cfg)
    container["filters"] = json.dumps([{"name": "f1"}, {"name": "f2"}])
    model = inspect_layout(make_layout([container]), source="l.pbix")
    m = model.elements[0].metrics
    assert m.colors == 1
    assert m.fonts == 1
    assert m.filters == 2
    # usage counts are metrics, not issues
    assert all(i.category != "brand" for i in model.elements[0].issues)


def test_summary_counts_by_severity():
    layout = make_layout(
        [
            make_container(
                "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
            ),
            make_container(
                "columnChart",
                {"Category": [{"queryRef": "Sales.region"}]},
                ["Sales.region"],
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    summary = model.summary()
    assert summary["elements"] == 2
    assert summary["issues"] == model.issues
    assert summary["error"] == model.errors
    assert summary["pages"] == 1
