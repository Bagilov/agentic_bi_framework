"""`Condition.In` checks for the web clone, shared with `engine.verify_filters`.

Every decision here comes from `visual_check_filters`, not from a substring
search: Desktop's inline `Values` IN and its Top-N `Table`/`subquery` IN are
legitimate, and only a structurally unresolvable `In` is reported. The donor
template carries three legitimate IN filters, so the regression test below pins
"zero findings" on it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.web_report import build_model, inspect_layout
from agentic_bi.web_report.web_filter_checks import has_in_filter, unsafe_in_filter
from agentic_bi.web_report.web_model import Issue


def _card(filters: str) -> dict:
    """A clean card container carrying `filters` as its visual filter blob."""
    container = make_container(
        "card",
        {"Values": [{"queryRef": "Sales.amount"}]},
        ["Sales.amount"],
    )
    container["filters"] = filters
    return container


def _issues(filters: str) -> list[Issue]:
    """Issues of a single card whose visual filters are `filters`."""
    model = inspect_layout(make_layout([_card(filters)]), source="l.pbix")
    return model.elements[0].issues


def _codes(filters: str) -> list[str]:
    """Check ids of a single card whose visual filters are `filters`."""
    return [issue.check_id for issue in _issues(filters)]


def _wrapped(where: list[dict], from_items: list[dict]) -> str:
    """A serialized filter list with one `Categorical` filter."""
    return json.dumps(
        [
            {
                "name": "Filter",
                "type": "Categorical",
                "filter": {"Version": 2, "From": from_items, "Where": where},
            }
        ]
    )


def _in_under_and(operand: dict) -> list[dict]:
    """The `In` operand buried inside `Condition.And.Left`.

    A top-level-only scan never sees this `Condition` mapping, so only a real
    structural walk can report it.
    """
    return [
        {
            "Condition": {
                "And": {
                    "Left": {"Condition": {"In": operand}},
                    "Right": {
                        "Condition": {
                            "Comparison": {
                                "ComparisonKind": 0,
                                "Left": {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Source": "t"}},
                                        "Property": "region",
                                    }
                                },
                                "Right": {"Literal": {"Value": "'EU'"}},
                            }
                        }
                    },
                }
            }
        }
    ]


_SALES = [{"Name": "t", "Entity": "Sales", "Type": 0}]


def test_template_has_no_unsafe_in_findings(template_pbix: Path) -> None:
    """The donor template's three legitimate IN filters are not reported."""
    model = build_model(template_pbix)
    found = [
        f"{element.page}#{element.index}"
        for page in model.pages
        for element in page.elements
        for issue in element.issues
        if issue.check_id == "FILTER-UNSAFE-IN"
    ]
    assert found == []


def test_nested_unresolvable_alias_reported_exactly_once() -> None:
    """An `In` on an aliased source missing from `From` is one error, not two."""
    operand = {
        "Expressions": [
            {
                "Column": {
                    "Expression": {"SourceRef": {"Source": "ghost"}},
                    "Property": "amount",
                }
            }
        ],
        "Values": [[{"Literal": {"Value": "'1'"}}]],
    }
    codes = _codes(_wrapped(_in_under_and(operand), _SALES))
    assert codes.count("FILTER-UNSAFE-IN") == 1


def test_in_without_values_or_table_reported() -> None:
    """An `In` with neither `Values` nor `Table` cannot be resolved."""
    codes = _codes(_wrapped(_in_under_and({}), _SALES))
    assert codes.count("FILTER-UNSAFE-IN") == 1


def test_inline_values_in_filter_accepted() -> None:
    """`Opportunities.Status IN ('Open')` is a declared-alias inline `Values` IN."""
    where = [
        {
            "Condition": {
                "In": {
                    "Expressions": [
                        {
                            "Column": {
                                "Expression": {"SourceRef": {"Source": "o"}},
                                "Property": "Status",
                            }
                        }
                    ],
                    "Values": [[{"Literal": {"Value": "'Open'"}}]],
                }
            }
        }
    ]
    filters = _wrapped(where, [{"Name": "o", "Entity": "Opportunities", "Type": 0}])
    assert "FILTER-UNSAFE-IN" not in _codes(filters)


def test_in_table_subquery_accepted() -> None:
    """A Top-N `Table`/`subquery` IN is declared in the filter's own `From`."""
    where = [
        {
            "Condition": {
                "In": {
                    "Expressions": [
                        {
                            "Column": {
                                "Expression": {"SourceRef": {"Source": "i"}},
                                "Property": "Industry",
                            }
                        }
                    ],
                    "Table": {"SourceRef": {"Source": "subquery"}},
                }
            }
        }
    ]
    from_items = [
        {
            "Name": "subquery",
            "Expression": {
                "Subquery": {"Query": {"Version": 2, "Top": 5, "Select": []}}
            },
            "Type": 2,
        },
        {"Name": "i", "Entity": "Industries", "Type": 0},
    ]
    assert "FILTER-UNSAFE-IN" not in _codes(_wrapped(where, from_items))


def test_malformed_filters_payload_is_a_diagnostic() -> None:
    """An unreadable blob yields one `FILTER-UNREADABLE` entry, not a traceback."""
    codes = _codes("{not json")
    assert codes.count("FILTER-UNREADABLE") == 1
    assert "FILTER-UNSAFE-IN" not in codes


def test_an_unreadable_blob_shape_is_not_certified_as_safe():
    """Fail-closed: a payload that is not a list of objects is unreadable.

    Measured before: `json.dumps(bad_filter)` (a single object) parsed to "no
    filters" and `has_in_filter` returned False, i.e. an unreadable filter was
    certified as safe.
    """
    assert unsafe_in_filter(json.dumps({"a": 1})) is None
    assert has_in_filter(json.dumps({"a": 1})) is True
    assert "FILTER-UNREADABLE" in _codes(json.dumps({"a": 1}))


def test_a_double_encoded_filter_is_inspected_not_skipped():
    """A string entry that parses to a filter object is the same filter."""
    filt = {
        "name": "Filter",
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "o", "Entity": "Sales", "Type": 0}],
            "Where": [{"Condition": {"In": {"Expressions": [], "Values": []}}}],
        },
    }
    blob = json.dumps([json.dumps(filt)])
    assert unsafe_in_filter(blob) is True
    assert "FILTER-UNSAFE-IN" in _codes(blob)


@pytest.mark.parametrize("blob", [5, 5.5, True])
def test_a_non_sequence_blob_is_unreadable_not_a_crash(blob: object):
    """A scalar blob must be an error: iterating it raised `TypeError`."""
    assert unsafe_in_filter(blob) is None
    assert "FILTER-UNREADABLE" in _codes(blob)  # type: ignore[arg-type]


def test_a_non_object_entry_is_unreadable():
    blob = json.dumps(["text", 3, None, []])
    assert unsafe_in_filter(blob) is None
    assert "FILTER-UNREADABLE" in _codes(blob)


@pytest.mark.parametrize("blob", ["[]", "", None, "null"])
def test_an_absent_filter_list_is_still_clean(blob: object):
    assert unsafe_in_filter(blob) is False
    assert _codes(blob) == []
