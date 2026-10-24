"""Tests for the declarative spec path: boundary validation and thresholds.

The spec is untrusted input, so a malformed spec must be reported as a problem
(not raise a bare `KeyError`/`IndexError` deep in the builder), and a threshold
override must either take effect or be rejected — never silently weaken a gate.
"""

from __future__ import annotations

import pytest

from agentic_bi.engine_layout import build_report
from agentic_bi.spec import (
    DashboardSpec,
    ElementSpec,
    PageSpec,
    from_dict,
    spec_to_board,
    validate_spec,
)
from agentic_bi.thresholds import (
    get_threshold,
    resolve_thresholds,
    validate_override,
)


class TestSpecBoundaryValidation:
    def test_missing_name_does_not_raise_and_is_reported(self) -> None:
        spec = from_dict({"table": "T", "pages": [{"name": "P"}]})
        assert spec.name == ""
        assert "Missing dashboard.name" in validate_spec(spec)

    def test_field_without_property_is_a_problem_not_a_keyerror(self) -> None:
        spec = from_dict(
            {
                "name": "D",
                "table": "T",
                "pages": [
                    {
                        "name": "P",
                        "elements": [{"type": "kpi", "field": {"display": "X"}}],
                    }
                ],
            }
        )
        problems = validate_spec(spec)
        assert any("missing 'property'" in p for p in problems)

    def test_non_mapping_field_is_rejected_with_a_message(self) -> None:
        spec = from_dict(
            {
                "name": "D",
                "table": "T",
                "pages": [
                    {"name": "P", "elements": [{"type": "table", "fields": ["colA"]}]}
                ],
            }
        )
        problems = validate_spec(spec)
        assert any("must be a mapping" in p for p in problems)

    def test_duplicate_page_names_are_reported(self) -> None:
        spec = DashboardSpec(
            name="D",
            table="T",
            pages=[PageSpec(name="P"), PageSpec(name="P")],
        )
        assert "Duplicate page name 'P'" in validate_spec(spec)

    def test_bad_pos_is_reported(self) -> None:
        spec = DashboardSpec(
            name="D",
            table="T",
            pages=[
                PageSpec(
                    name="P",
                    elements=[
                        ElementSpec(
                            type="kpi",
                            field={"property": "m", "kind": "measure"},
                            pos=[1, 2],
                        )
                    ],
                )
            ],
        )
        assert any("pos must be [x, y, w, h]" in p for p in validate_spec(spec))

    def test_unknown_field_kind_is_reported(self) -> None:
        spec = DashboardSpec(
            name="D",
            table="T",
            pages=[
                PageSpec(
                    name="P",
                    elements=[
                        ElementSpec(
                            type="kpi",
                            field={"property": "m", "kind": "mesure"},
                        )
                    ],
                )
            ],
        )
        assert any("unknown field kind" in p for p in validate_spec(spec))

    def test_element_must_be_a_mapping(self) -> None:
        with pytest.raises(ValueError, match="element must be a mapping"):
            from_dict({"name": "D", "pages": [{"name": "P", "elements": ["kpi"]}]})

    def test_non_list_elements_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="elements must be a list"):
            from_dict({"name": "D", "pages": [{"name": "P", "elements": "kpi"}]})

    def test_a_valid_spec_passes_validation(self) -> None:
        spec = from_dict(
            {
                "name": "D",
                "table": "T",
                "pages": [
                    {
                        "name": "P",
                        "elements": [
                            {
                                "type": "chart",
                                "axis": {"kind": "column", "property": "c"},
                                "value": {"kind": "measure", "property": "m"},
                            }
                        ],
                    }
                ],
            }
        )
        assert validate_spec(spec) == []
        board = spec_to_board(spec)
        assert board is not None


class TestThresholds:
    def test_nested_container_is_flattened(self) -> None:
        # documented shape: quality: {thresholds: {...}}
        resolved = resolve_thresholds(
            {"quality": {"thresholds": {"max_layout_problems": 5}}}
        )
        assert resolved["quality.max_layout_problems"] == 5

    def test_deploy_guardrails_container_is_flattened(self) -> None:
        resolved = resolve_thresholds(
            {"deploy": {"guardrails": {"max_deletion_pct": 10}}}
        )
        assert resolved["deploy.max_deletion_pct"] == 10

    def test_flat_override_still_works(self) -> None:
        assert (
            resolve_thresholds({"quality.max_layout_problems": 3})[
                "quality.max_layout_problems"
            ]
            == 3
        )

    def test_wrong_type_keeps_the_default(self) -> None:
        resolved = resolve_thresholds({"quality": {"max_layout_problems": "0"}})
        assert resolved["quality.max_layout_problems"] == 0

    def test_bool_is_rejected_for_an_int_threshold(self) -> None:
        assert validate_override("quality.max_layout_problems", True) is False
        assert validate_override("quality.max_layout_problems", 2) is True

    def test_bool_accepted_for_a_bool_threshold(self) -> None:
        assert validate_override("build.donor_required", False) is True

    def test_unknown_key_is_passed_through(self) -> None:
        resolved = resolve_thresholds({"project.custom_limit": 7})
        assert resolved["project.custom_limit"] == 7

    def test_default_is_used_without_overrides(self) -> None:
        assert get_threshold("quality.max_layout_problems") == 0


class TestBuildReportGuard:
    def test_empty_pages_raise_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one page"):
            build_report([])


class TestPrototypeQueryTolerance:
    """`prototypeQuery` may arrive as a JSON string; that must not raise."""

    def test_web_checks_tolerates_a_string_prototype_query(self) -> None:
        from agentic_bi.web_report.web_checks import element_issues

        registry = {"T": {"columns": ["c"], "measures": ["m"]}}
        sv = {"visualType": "lineChart", "prototypeQuery": '{"Select": []}'}
        issues = element_issues(sv, {}, ["Category"], registry)
        assert isinstance(issues, list)

    def test_validate_layout_tolerates_a_string_prototype_query(self) -> None:
        from agentic_bi.validate_pbix import validate_layout

        layout = {
            "sections": [
                {
                    "visualContainers": [
                        {
                            "config": {
                                "singleVisual": {"prototypeQuery": '{"Select": []}'}
                            }
                        }
                    ]
                }
            ]
        }
        assert validate_layout(layout, {}) == []


class TestGalleryGuard:
    def test_empty_tables_raise_a_value_error(self) -> None:
        from agentic_bi.engine_layout import build_gallery

        with pytest.raises(ValueError, match="at least one table"):
            build_gallery({"tables": []})


class TestGetThresholdTypo:
    def test_unknown_key_returns_none_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="agentic_bi.thresholds"):
            assert get_threshold("quality.max_layout_problemm") is None
        assert "unknown threshold key" in caplog.text
