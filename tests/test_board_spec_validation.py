"""Regression tests for the Qwen-confirmed board/spec fixes (round 11, part 2).

The initial round-11 audit was local (chat.qwen.ai was WAF-blocked); when the
exchange finally completed, Qwen confirmed five further defects, each
re-measured here before the fix:

- `Visual` never checked that a visual's required inputs are present, so a
  value-less card/gauge/kpi became `Sum(table.None)` (an unbound visual);
- `_visual_config` interpolated a title into a DAX literal unescaped, so a
  title with a single quote corrupted the config;
- `validate_spec` accepted an unknown chart `visual_type` and a non-string
  page filter (both crashed `spec_to_board`/shipped a dead visual);
- `skeleton_visuals._query_item` raised a bare `KeyError` on a missing
  `property`;
- a narrow page emitted a negative width into the layout.
"""

from __future__ import annotations

import json

import pytest


class TestVisualRequiredInputs:
    """A half-built visual used to become `Sum(table.None)` and render blank."""

    @pytest.mark.parametrize(
        "kind",
        ["card", "gauge", "kpi"],
    )
    def test_value_less_value_visual_is_rejected(self, kind: str) -> None:
        from agentic_bi.engine_layout_visual import Visual

        with pytest.raises(ValueError, match="requires one of"):
            Visual(kind=kind, table="t")

    def test_table_without_columns_is_rejected(self) -> None:
        from agentic_bi.engine_layout_visual import Visual

        with pytest.raises(ValueError, match="requires one of"):
            Visual(kind="table", table="t", columns=[])

    def test_chart_without_value_is_rejected(self) -> None:
        from agentic_bi.engine_layout_visual import Visual

        with pytest.raises(ValueError, match="requires one of"):
            Visual(kind="line", table="t", axis="a")

    def test_scatter_needs_both_axes(self) -> None:
        from agentic_bi.engine_layout_visual import Visual

        with pytest.raises(ValueError, match="requires one of"):
            Visual(kind="scatter", table="t", x="a")

    def test_measure_satisfies_the_value_requirement(self) -> None:
        from agentic_bi.engine_layout_visual import Visual, _visual_config

        sv = _visual_config(Visual(kind="card", table="t", measure="m"))["singleVisual"]
        assert sv["projections"]["Values"][0]["queryRef"] == "t.m"

    def test_valid_visuals_still_build(self) -> None:
        from agentic_bi.engine_layout_visual import Visual, _visual_config

        for kw in (
            {"kind": "card", "table": "t", "value": "b"},
            {"kind": "table", "table": "t", "columns": ["a"]},
            {"kind": "scatter", "table": "t", "x": "a", "y": "b"},
            {"kind": "slicer", "table": "t", "axis": "a"},
        ):
            assert _visual_config(Visual(**kw))["singleVisual"]["projections"]


class TestVisualTitleDaxLiteral:
    def test_single_quote_in_title_is_doubled(self) -> None:
        from agentic_bi.engine_layout_query import dax_literal

        assert dax_literal("Sales '23") == "'Sales ''23'"

    def test_title_survives_a_quote_in_the_config(self) -> None:
        from agentic_bi.engine_layout_visual import Visual, _visual_config

        cfg = _visual_config(Visual("card", table="t", measure="m", title="Sales '23"))
        value = cfg["singleVisual"]["objects"]["title"][0]["properties"]["text"][
            "expr"
        ]["Literal"]["Value"]
        assert value == "'Sales ''23'"
        # the literal opens and closes exactly once around the escaped text
        assert value.count("'") - value.count("''") * 2 == 2


class TestSpecValidationOfChartTypeAndFilters:
    def _spec(self, element: dict, filters: list | None = None):
        from agentic_bi.spec import from_dict

        return from_dict(
            {
                "dashboard": {
                    "name": "B",
                    "table": "t",
                    "pages": [
                        {
                            "name": "p1",
                            "filters": filters or [],
                            "elements": [element],
                        }
                    ],
                }
            }
        )

    def test_unknown_chart_type_is_reported(self) -> None:
        from agentic_bi.spec import validate_spec

        spec = self._spec(
            {
                "type": "chart",
                "visual_type": "myCustomChart",
                "axis": {"kind": "column", "property": "a"},
                "value": {"kind": "column", "property": "v", "agg": True},
            }
        )
        assert any("unknown visual_type" in p for p in validate_spec(spec))

    def test_supported_chart_types_are_clean(self) -> None:
        from agentic_bi.spec import validate_spec

        for vt in ("lineChart", "clusteredColumnChart"):
            spec = self._spec(
                {
                    "type": "chart",
                    "visual_type": vt,
                    "axis": {"kind": "column", "property": "a"},
                    "value": {"kind": "column", "property": "v", "agg": True},
                }
            )
            assert validate_spec(spec) == []

    @pytest.mark.parametrize("bad", [123, None, {"a": 1}, "", "  "])
    def test_non_string_filter_is_reported(self, bad) -> None:
        from agentic_bi.spec import validate_spec

        spec = self._spec({"type": "table", "fields": [{"property": "c"}]}, [bad])
        assert any("must be a non-empty string" in p for p in validate_spec(spec))

    def test_string_filter_is_clean(self) -> None:
        from agentic_bi.spec import validate_spec

        spec = self._spec(
            {"type": "table", "fields": [{"property": "c"}]}, ["category"]
        )
        assert validate_spec(spec) == []


class TestSkeletonQueryItemGuard:
    def test_missing_property_raises_a_clear_error(self) -> None:
        from agentic_bi.skeleton_visuals import _query_item

        with pytest.raises(ValueError, match="property"):
            _query_item({"kind": "column"}, "t", "m")

    def test_empty_property_is_rejected(self) -> None:
        from agentic_bi.skeleton_visuals import _query_item

        with pytest.raises(ValueError, match="property"):
            _query_item({"kind": "column", "property": ""}, "t", "m")


class TestBoardPositionIsNeverNegative:
    def test_narrow_page_clamps_to_a_positive_size(self) -> None:
        from agentic_bi.board import Board

        for width in (30, 10, 0):
            board = Board(table="t")
            page = board.add_page("p1", width=width, cols=2)
            for container in (
                page.table([{"kind": "column", "property": "x", "display": "X"}]),
                page.header("H"),
            ):
                pos = json.loads(container["config"])["layouts"][0]["position"]
                assert pos["width"] > 0 and pos["height"] > 0
                assert pos["x"] >= 0 and pos["y"] >= 0
