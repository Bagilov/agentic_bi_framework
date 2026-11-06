"""`verify_safe_filters` must flag only structurally unresolvable `Condition.In`.

The check used to look for the key `In` under `filter.Where[].Condition` in every
page/visual filter blob, which rejected every Desktop-written `IN` filter:
`verify_safe_filters` returned 7 entries (pages `Overview`, `Industries
Overview`, `Pipeline Trends`, `Days Key Influencers`, `Decomposition`) on
`templates/template.pbix`. "Unsafe" now means the source alias is absent from
the filter's own `From`, or the `In` has neither `Values` nor `Table`.

The unsafe fixtures are nested under `Condition.And` on purpose: that is a real
filter shape, and the old scanner never looked below the top-level `Condition`,
so each of these tests fails when the fix is reverted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.engine.verify import load_layout, verify_safe_filters

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "template.pbix"
DECLARED = [{"Name": "o", "Entity": "Opportunities", "Type": 0}]


def _column(source: str) -> dict:
    return {
        "Column": {
            "Expression": {"SourceRef": {"Source": source}},
            "Property": "Status",
        }
    }


def _in_operand(source: str, *, values: bool = True) -> dict:
    operand: dict = {"Expressions": [_column(source)]}
    if values:
        operand["Values"] = [[{"Literal": {"Value": "'Open'"}}]]
    return operand


def _subquery_in(source: str = "i") -> dict:
    return {
        "Expressions": [_column(source)],
        "Table": {"SourceRef": {"Source": "subquery"}},
    }


def _filter(condition: dict, from_items: list[dict]) -> dict:
    body = {"Version": 2, "From": from_items, "Where": [{"Condition": condition}]}
    return {"name": "Filter", "filter": body}


def _nested(in_operand: dict) -> dict:
    return {"And": {"Left": _column("o"), "Right": {"Condition": {"In": in_operand}}}}


def _blob(*filters: dict) -> str:
    return json.dumps(list(filters))


def _layout(*, page_filters: object = "[]", visual_filters: object = "[]") -> dict:
    return {
        "sections": [
            {
                "displayName": "Overview",
                "filters": page_filters,
                "visualContainers": [{"filters": visual_filters}],
            }
        ]
    }


@pytest.mark.skipif(not TEMPLATE.exists(), reason="donor template is absent")
def test_donor_template_has_no_unsafe_in_filters() -> None:
    # Desktop's inline `Values` and Top-N `Table` filters resolve through their
    # own `From`; reporting them was the 7-entry false positive this fixes.
    results = verify_safe_filters(load_layout(TEMPLATE))
    assert [(c.name, c.ok) for c in results] == [("no unsafe IN filters", True)]
    assert results[0].detail == "[]"


def test_undeclared_alias_is_reported_once() -> None:
    # `x` is not in `From`, so Desktop cannot resolve the IN filter.
    filt = _filter(_nested(_in_operand("x")), DECLARED)
    results = verify_safe_filters(_layout(visual_filters=_blob(filt)))
    assert results[0].ok is False
    assert results[0].detail.count("visual in 'Overview'") == 1


def test_in_without_values_or_table_is_reported() -> None:
    # The alias resolves but there is nothing to compare against.
    filt = _filter(_nested(_in_operand("o", values=False)), DECLARED)
    results = verify_safe_filters(_layout(visual_filters=_blob(filt)))
    assert results[0].ok is False
    assert results[0].detail.count("visual in 'Overview'") == 1


def test_inline_values_filter_is_accepted() -> None:
    filt = _filter({"In": _in_operand("o")}, DECLARED)
    results = verify_safe_filters(_layout(visual_filters=_blob(filt)))
    assert [c.ok for c in results] == [True]


def test_top_n_subquery_filter_is_accepted() -> None:
    from_items = [{"Name": "subquery", "Type": 2}, *DECLARED]
    filt = _filter({"In": _subquery_in()}, from_items)
    results = verify_safe_filters(_layout(visual_filters=_blob(filt)))
    assert [c.ok for c in results] == [True]


def test_already_parsed_filter_list_is_accepted() -> None:
    # A layout decoded from JSON may carry a list instead of a JSON string.
    filt = _filter({"In": _in_operand("o")}, DECLARED)
    results = verify_safe_filters(_layout(visual_filters=[filt]))
    assert [c.ok for c in results] == [True]


def test_page_level_undeclared_alias_is_reported() -> None:
    filt = _filter(_nested(_in_operand("x")), DECLARED)
    results = verify_safe_filters(_layout(page_filters=_blob(filt)))
    assert results[0].ok is False
    assert results[0].detail.count("page 'Overview'") == 1


def test_malformed_filters_json_is_a_diagnostic_entry() -> None:
    results = verify_safe_filters(_layout(visual_filters="{not json"))
    assert results[0].ok is True
    diagnostics = [c for c in results if not c.critical]
    assert [c.name for c in diagnostics] == ["filters payload readable"]
    assert "filters JSON invalid" in diagnostics[0].detail
    assert "Traceback" not in diagnostics[0].detail
