"""`visual_check` must flag a real `Condition.In`, never the substring "In".

The old check serialized each filter and searched for `"In"` inside the JSON
text. On `templates/template.pbix` that produced 69 false errors because
`Include`, `Income`, `Index`, table and column names all contain the substring.
These tests pin the structural walk: only `Condition.In` counts, and Desktop's
two legitimate shapes (inline `Values`, Top-N `Table` subquery) stay certifiable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.test_visual_types_are_real import _registry_from_layout

from agentic_bi import visual_check

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "template.pbix"


def _container(filters: object, visual_type: str = "card") -> dict:
    return {
        "sections": [
            {
                "visualContainers": [
                    {
                        "config": json.dumps(
                            {"singleVisual": {"visualType": visual_type}}
                        ),
                        "filters": filters,
                    }
                ]
            }
        ]
    }


def _in_errors(filters: object) -> list[str]:
    errs = visual_check.check_layout(_container(filters), {})
    return [e for e in errs if "unsafe Condition.In" in e]


def _filter(where: list[dict], from_items: list[dict] | None = None) -> str:
    body: dict[str, object] = {"Where": where}
    if from_items is not None:
        body["From"] = from_items
    return json.dumps([{"name": "Filter", "filter": body}])


def _in_where(source: str = "o", prop: str = "Status") -> list[dict]:
    return [
        {
            "Condition": {
                "In": {
                    "Expressions": [
                        {
                            "Column": {
                                "Expression": {"SourceRef": {"Source": source}},
                                "Property": prop,
                            }
                        }
                    ],
                    "Values": [[{"Literal": {"Value": "'Open'"}}]],
                }
            }
        }
    ]


@pytest.mark.skipif(not TEMPLATE.exists(), reason="donor template is absent")
def test_donor_template_has_no_unsafe_in_errors() -> None:
    # The donor carries two Desktop-written In shapes: inline `Values` and a
    # Top-N `Table` subquery. Both resolve through the filter's own `From`, so a
    # structural check must accept them (the textual check reported 69 errors).
    layout = visual_check.layout_from_pbix(TEMPLATE)
    errors = visual_check.check_layout(layout, {})
    assert [e for e in errors if "unsafe Condition.In" in e] == []


@pytest.mark.skipif(not TEMPLATE.exists(), reason="donor template is absent")
def test_donor_has_no_real_defects_with_a_layout_derived_registry() -> None:
    # Membership is tautological here (the registry comes from the layout), so
    # anything left is a structural claim about the board itself.
    layout = visual_check.layout_from_pbix(TEMPLATE)
    registry = _registry_from_layout(layout)
    assert visual_check.check_layout(layout, registry) == []


def test_dangling_condition_in_is_one_error() -> None:
    # `o` is never declared in `From`, so Desktop cannot resolve the IN filter.
    assert len(_in_errors(_filter(_in_where(source="o")))) == 1


def test_resolvable_condition_in_is_accepted() -> None:
    filters = _filter(_in_where(source="o"), [{"Name": "o", "Entity": "T", "Type": 0}])
    assert _in_errors(filters) == []


def test_subquery_in_is_accepted_when_the_alias_is_declared() -> None:
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
    filters = _filter(
        where,
        [
            {"Name": "subquery", "Type": 2},
            {"Name": "i", "Entity": "Industries", "Type": 0},
        ],
    )
    assert _in_errors(filters) == []


@pytest.mark.parametrize("name", ["Include", "Income", "Index", "Initial Inbox"])
def test_names_containing_in_are_not_filters(name: str) -> None:
    where = [
        {
            "Condition": {
                "Not": {
                    "Expression": {
                        "Column": {
                            "Expression": {"SourceRef": {"Source": "o"}},
                            "Property": name,
                        }
                    }
                }
            }
        }
    ]
    filters = _filter(where, [{"Name": "o", "Entity": name, "Type": 0}])
    assert _in_errors(filters) == []


@pytest.mark.parametrize("operator", ["Not", "And", "Comparison"])
def test_other_conditions_are_not_flagged(operator: str) -> None:
    where = [{"Condition": {operator: {"Left": {}, "Right": {}}}}]
    assert _in_errors(_filter(where)) == []


def test_in_nested_under_and_is_still_found() -> None:
    nested = {"And": {"Left": {"Condition": {"In": {"Values": [[1]]}}}}}
    assert len(_in_errors(_filter([{"Condition": nested}]))) == 1


@pytest.mark.parametrize("blob", ["[]", "", None, "{}", "null"])
def test_empty_or_non_list_filters_do_not_raise(blob: object) -> None:
    assert _in_errors(blob) == []


def test_broken_filters_json_is_a_readable_error() -> None:
    errs = visual_check.check_layout(_container("not json"), {})
    assert any("filters JSON invalid" in e for e in errs)
    assert all("Traceback" not in e for e in errs)


def test_non_dict_entries_in_filters_are_skipped() -> None:
    assert _in_errors(json.dumps(["text", 3, None, []])) == []


def test_an_unreadable_blob_shape_is_reported_not_silently_clean() -> None:
    """Parity with the web clone: the shared parser is fail-closed.

    `{}` parses to an object, and an entry that is not an object (including a
    double-encoded *list*) cannot be inspected — both must surface as an error
    instead of "no unsafe filter found".
    """
    for blob in ("{}", json.dumps(["text", 3]), json.dumps([json.dumps([{"a": 1}])])):
        errs = visual_check.check_layout(_container(blob), {})
        assert any("filters" in e for e in errs), (blob, errs)


@pytest.mark.parametrize("blob", [5, 3.5, True])
def test_a_scalar_blob_is_reported_not_a_traceback(blob: object) -> None:
    errs = visual_check.check_layout(_container(blob), {})
    assert any("filters" in e for e in errs), errs


def test_a_double_encoded_filter_object_is_inspected() -> None:
    filt = {"filter": {"From": [], "Where": [{"Condition": {"In": {"Values": []}}}]}}
    errs = visual_check.check_layout(_container(json.dumps([json.dumps(filt)])), {})
    assert any("unsafe Condition.In filter" in e for e in errs)


@pytest.mark.parametrize("blob", ["[]", "", None, "null"])
def test_an_absent_filter_list_is_clean(blob: object) -> None:
    errs = visual_check.check_layout(_container(blob), {})
    assert not any("filters" in e for e in errs), errs
