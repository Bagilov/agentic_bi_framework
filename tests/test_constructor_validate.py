"""Design validation: the gate that runs before any artifact is written.

Each rule exists because the alternative is a defect that only shows up in
Desktop: a missing value would become `Sum(table.None)`, an unknown column would
render blank, a `sum` over a date is rejected by the engine, and two blocks at
the same position hide each other. The tests assert the code and the location,
because that is what a caller (and an agent) acts on.
"""

from __future__ import annotations

import pytest

from agentic_bi.constructor.design import Design
from agentic_bi.constructor.issues import DesignError, has_errors, raise_for_errors
from agentic_bi.constructor.validate import validate_design

MODEL = {
    "tables": {
        "Sales": {
            "columns": {"region": "string", "amount": "double", "day": "date"},
            "measures": {"Total": "SUM(Sales[amount])"},
        },
        "Date": {"columns": {"day": "date"}},
    }
}


def _check(visuals: list[dict], **page: object) -> list:
    body = {"kind": "card", "table": "Sales", "value": "amount"}
    design = Design.from_dict(
        {
            "model": MODEL,
            "pages": [
                {
                    "name": "p",
                    "visuals": [dict(body, **visual) for visual in visuals],
                    **page,
                }
            ],
        }
    )
    return validate_design(design)


def _codes(issues: list) -> set[str]:
    return {issue.code for issue in issues}


class TestFieldRules:
    def test_a_complete_design_has_no_issues(self) -> None:
        assert _check([{}]) == []

    def test_a_card_without_a_value_or_measure_is_an_error(self) -> None:
        assert "missing_field" in _codes(_check([{"value": None}]))

    def test_a_table_without_columns_is_an_error(self) -> None:
        codes = _codes(_check([{"kind": "table", "columns": []}]))
        assert "empty_columns" in codes

    def test_a_chart_without_a_category_is_an_error(self) -> None:
        codes = _codes(_check([{"kind": "column", "axis": None}]))
        assert "missing_field" in codes

    def test_measure_and_value_together_conflict(self) -> None:
        codes = _codes(_check([{"measure": "Total"}]))
        assert "measure_value_conflict" in codes

    def test_aggregation_on_a_measure_is_rejected(self) -> None:
        codes = _codes(_check([{"measure": "Total", "value": None, "agg": "avg"}]))
        assert "measure_agg_conflict" in codes

    def test_a_field_the_kind_ignores_is_a_warning(self) -> None:
        issues = _check([{"kind": "card", "columns": ["region"]}])
        assert any(i.code == "unused_field" and i.severity == "warning" for i in issues)
        assert not has_errors(issues)

    def test_an_unknown_aggregation_is_an_error(self) -> None:
        assert "bad_agg" in _codes(_check([{"agg": "mode"}]))

    def test_a_zero_span_is_an_error(self) -> None:
        assert "bad_span" in _codes(_check([{"span": 0}]))

    def test_a_visual_filter_is_rejected_with_a_way_out(self) -> None:
        issues = _check([{"filters": [{"field": "region"}]}])
        message = next(i.message for i in issues if i.code == "unsupported_filters")
        assert "slicer" in message


class TestModelReferences:
    def test_an_unknown_table_is_reported(self) -> None:
        assert "unknown_table" in _codes(_check([{"table": "Missing"}]))

    def test_an_unknown_column_is_reported_with_its_qualified_name(self) -> None:
        issues = _check([{"value": "nope"}])
        message = next(i.message for i in issues if i.code == "unknown_column")
        assert "Sales.nope" in message

    def test_an_unknown_measure_is_reported(self) -> None:
        issues = _check([{"measure": "Nope", "value": None}])
        assert "unknown_measure" in _codes(issues)

    def test_a_slicer_by_measure_is_rejected(self) -> None:
        codes = _codes(_check([{"kind": "slicer", "axis": "Total"}]))
        assert "slicer_by_measure" in codes

    def test_a_numeric_aggregation_over_a_date_is_rejected(self) -> None:
        codes = _codes(_check([{"value": "day", "agg": "sum"}]))
        assert "bad_agg_type" in codes

    def test_an_extra_value_is_checked_like_the_main_value(self) -> None:
        codes = _codes(
            _check(
                [
                    {
                        "kind": "line",
                        "axis": "region",
                        "extra_values": ["nope"],
                    }
                ]
            )
        )
        assert "unknown_column" in codes

    def test_an_empty_model_only_warns(self) -> None:
        design = Design.from_dict(
            {
                "pages": [
                    {
                        "name": "p",
                        "visuals": [{"kind": "card", "table": "t", "value": "a"}],
                    }
                ]
            }
        )
        issues = validate_design(design)
        assert {i.code for i in issues} == {"no_model"}
        assert not has_errors(issues)


class TestPageRules:
    def test_a_design_without_pages_is_an_error(self) -> None:
        assert "no_pages" in {i.code for i in validate_design(Design())}

    def test_a_page_without_visuals_is_an_error(self) -> None:
        design = Design.from_dict({"model": MODEL, "pages": [{"name": "p"}]})
        assert "empty_page" in {i.code for i in validate_design(design)}

    def test_duplicate_page_names_and_titles_are_reported(self) -> None:
        page = {"name": "p", "title": "Same", "visuals": []}
        design = Design.from_dict({"model": MODEL, "pages": [page, dict(page)]})
        codes = {i.code for i in validate_design(design)}
        assert {"duplicate_page", "duplicate_title"} <= codes

    def test_a_page_below_the_minimum_size_is_an_error(self) -> None:
        assert "small_page" in _codes(_check([], width=200, height=100))

    def test_page_filters_are_rejected(self) -> None:
        assert "unsupported_filters" in _codes(_check([], filters=[{"a": 1}]))


class TestGeometry:
    def test_a_position_outside_the_page_is_an_error(self) -> None:
        assert "pos_out_of_page" in _codes(_check([{"pos": [1200, 30, 400, 300]}]))

    def test_overlapping_positions_name_the_other_block(self) -> None:
        issues = _check(
            [
                {"pos": [20, 20, 300, 200]},
                {"pos": [100, 100, 300, 200]},
            ]
        )
        message = next(i.message for i in issues if i.code == "overlap")
        assert "visuals[0]" in message

    def test_a_span_wider_than_the_grid_warns(self) -> None:
        issues = _check([{"span": 3}])
        assert any(i.code == "span_clamped" and i.severity == "warning" for i in issues)

    def test_a_negative_position_is_an_error(self) -> None:
        assert "bad_pos" in _codes(_check([{"pos": [-5, 20, 300, 200]}]))


class TestRelationships:
    def _design(self, relationships: list[dict]) -> Design:
        return Design.from_dict(
            {
                "model": {**MODEL, "relationships": relationships},
                "pages": [
                    {
                        "name": "p",
                        "visuals": [
                            {"kind": "card", "table": "Sales", "value": "amount"}
                        ],
                    }
                ],
            }
        )

    def test_a_valid_relationship_produces_no_issue(self) -> None:
        issues = validate_design(
            self._design(
                [
                    {
                        "fromTable": "Sales",
                        "fromColumn": "day",
                        "toTable": "Date",
                        "toColumn": "day",
                    }
                ]
            )
        )
        assert issues == []

    def test_a_missing_key_is_reported(self) -> None:
        codes = {
            i.code for i in validate_design(self._design([{"fromTable": "Sales"}]))
        }
        assert "bad_relationship" in codes

    def test_an_unknown_column_is_reported(self) -> None:
        issues = validate_design(
            self._design(
                [
                    {
                        "fromTable": "Sales",
                        "fromColumn": "nope",
                        "toTable": "Date",
                        "toColumn": "day",
                    }
                ]
            )
        )
        assert any("Sales.nope" in i.message for i in issues)

    def test_two_active_links_between_the_same_tables_are_rejected(self) -> None:
        link = {
            "fromTable": "Sales",
            "fromColumn": "day",
            "toTable": "Date",
            "toColumn": "day",
        }
        codes = {i.code for i in validate_design(self._design([link, dict(link)]))}
        assert "duplicate_active_relationship" in codes

    def test_an_inactive_link_is_not_counted_as_active(self) -> None:
        link = {
            "fromTable": "Sales",
            "fromColumn": "day",
            "toTable": "Date",
            "toColumn": "day",
            "isActive": False,
        }
        codes = {i.code for i in validate_design(self._design([link, dict(link)]))}
        assert "duplicate_active_relationship" not in codes

    def test_a_non_boolean_is_active_is_rejected(self) -> None:
        issues = validate_design(
            self._design(
                [
                    {
                        "fromTable": "Sales",
                        "fromColumn": "day",
                        "toTable": "Date",
                        "toColumn": "day",
                        "isActive": "sometimes",
                    }
                ]
            )
        )
        assert any("isActive must be boolean" in i.message for i in issues)


class TestIssuesApi:
    def test_raise_for_errors_only_raises_on_errors(self) -> None:
        design = Design.from_dict(
            {"pages": [{"name": "p", "visuals": [{"kind": "card", "value": "a"}]}]}
        )
        issues = validate_design(design)
        with pytest.raises(DesignError) as exc:
            raise_for_errors(issues)
        assert exc.value.issues

    def test_issue_serializes_to_its_location(self) -> None:
        issue = _check([{"table": "Missing"}])[0]
        assert issue.as_dict()["path"].startswith("pages[p]")
        assert issue.as_dict()["severity"] == "error"
