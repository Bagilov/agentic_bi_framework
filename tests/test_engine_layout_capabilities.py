"""Layout capability port from the internal dashboard API (R9).

Measured on a Windows guest: a visual title written to `objects` is ignored by
Desktop, which then draws an automatic title from the field name, so the title
belongs to the *container* (`vcObjects`) with `show=true`. The same change adds
an optional subtitle, a tooltip object, extra Y values and the dict-shaped
`build_report_dict` the constructor compiles through.
"""

from __future__ import annotations

import json

import pytest

from agentic_bi.engine.layout import build_report, build_report_dict
from agentic_bi.engine.layout_visual import Visual, _visual_config


def _single(visual: Visual) -> dict:
    return _visual_config(visual)["singleVisual"]


class TestTitleIsAContainerObject:
    def test_a_title_lands_in_vcobjects_not_in_objects(self) -> None:
        single = _single(Visual("card", table="t", measure="m", title="Sales"))
        assert "title" not in single["objects"]
        props = single["vcObjects"]["title"][0]["properties"]
        assert props["show"]["expr"]["Literal"]["Value"] == "true"
        assert props["text"]["expr"]["Literal"]["Value"] == "'Sales'"

    def test_a_description_becomes_the_subtitle(self) -> None:
        single = _single(
            Visual("card", table="t", measure="m", title="Sales", description="2026")
        )
        props = single["vcObjects"]["title"][0]["properties"]
        assert props["subTitle"]["expr"]["Literal"]["Value"] == "'2026'"

    def test_a_title_without_a_description_has_no_subtitle(self) -> None:
        single = _single(Visual("card", table="t", measure="m", title="Sales"))
        props = single["vcObjects"]["title"][0]["properties"]
        assert "subTitle" not in props

    def test_a_quote_in_a_description_is_escaped_once(self) -> None:
        single = _single(
            Visual(
                "card",
                table="t",
                measure="m",
                title="Sales",
                description="Q1 '26",
            )
        )
        props = single["vcObjects"]["title"][0]["properties"]
        assert props["subTitle"]["expr"]["Literal"]["Value"] == "'Q1 ''26'"

    def test_a_visual_without_a_title_keeps_vcobjects_empty(self) -> None:
        assert _single(Visual("card", table="t", measure="m"))["vcObjects"] == {}


class TestTooltipAndExtraValues:
    def test_a_tooltip_becomes_a_default_tooltip_object(self) -> None:
        single = _single(Visual("card", table="t", measure="m", tooltip="source: x"))
        tooltip = single["objects"]["visualTooltip"][0]["properties"]
        assert tooltip["type"]["expr"]["Literal"]["Value"] == "'Default'"
        assert tooltip["text"]["expr"]["Literal"]["Value"] == "'source: x'"

    def test_extra_values_extend_the_y_role_in_order(self) -> None:
        single = _single(
            Visual(
                "line",
                table="t",
                axis="day",
                value="done",
                extra_values=["failed", "retry"],
            )
        )
        refs = [item["queryRef"] for item in single["projections"]["Y"]]
        assert refs == ["Sum(t.done)", "Sum(t.failed)", "Sum(t.retry)"]

    def test_extra_values_respect_the_aggregation(self) -> None:
        single = _single(
            Visual(
                "column",
                table="t",
                axis="day",
                value="done",
                agg="avg",
                extra_values=["failed"],
            )
        )
        refs = [item["queryRef"] for item in single["projections"]["Y"]]
        assert refs[-1] == "Avg(t.failed)"

    @pytest.mark.parametrize("kind", ["pie", "donut", "card", "table", "gauge"])
    def test_a_kind_without_a_multi_value_y_role_is_rejected(self, kind: str) -> None:
        with pytest.raises(ValueError) as exc:
            Visual(
                kind=kind,
                table="t",
                axis="day",
                value="done",
                columns=["day"],
                extra_values=["failed"],
            )
        assert "multi-value Y role" in str(exc.value)


class TestBuildReportDict:
    def test_the_dict_and_the_bytes_describe_the_same_layout(self) -> None:
        pages = [("One", [Visual("card", table="t", measure="m")])]
        layout = build_report_dict(pages)
        raw = build_report(pages)
        assert (
            json.loads(raw.decode("utf-16-le"))["sections"][0]["displayName"]
            == (layout["sections"][0]["displayName"])
        )

    def test_canvas_margin_and_gutter_control_auto_placement(self) -> None:
        pages = [("P", [Visual("card", table="t", measure="m")])]
        layout = build_report_dict(pages, canvas=(900, 700), margin=10, gutter=5)
        section = layout["sections"][0]
        container = section["visualContainers"][0]
        assert (container["x"], container["y"]) == (10, 10)
        assert section["width"] >= 900 and section["height"] >= 700

    def test_an_empty_page_list_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            build_report_dict([])
        assert "at least one page" in str(exc.value)

    def test_an_unusable_canvas_is_rejected(self) -> None:
        pages = [("P", [Visual("card", table="t", measure="m")])]
        with pytest.raises(ValueError) as exc:
            build_report_dict(pages, canvas=(0, 600))
        assert "canvas must be positive" in str(exc.value)

    def test_a_negative_margin_is_rejected(self) -> None:
        pages = [("P", [Visual("card", table="t", measure="m")])]
        with pytest.raises(ValueError) as exc:
            build_report_dict(pages, margin=-1)
        assert "margin/gutter" in str(exc.value)

    def test_a_report_id_is_preserved(self) -> None:
        pages = [("P", [Visual("card", table="t", measure="m")])]
        assert build_report_dict(pages, report_id=42)["id"] == 42
