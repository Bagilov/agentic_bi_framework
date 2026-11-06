"""Robustness tests for `web_inspect` on malformed `Report/Layout` input.

The layout is untrusted: page sizes and the `sections`/`visualContainers`
collections can hold objects, strings, `NaN`/`inf` or non-lists. The inspector
must degrade to defaults instead of raising `TypeError`/`OverflowError`.
"""

from __future__ import annotations

from agentic_bi.web_report import inspect_layout


def test_page_size_defaults_when_values_are_not_numeric():
    layout = {"sections": [{"width": {}, "height": "inf"}]}
    model = inspect_layout(layout, source="l.pbix")
    assert len(model.pages) == 1
    assert model.pages[0].width == 1280
    assert model.pages[0].height == 1050


def test_page_size_ignores_non_finite_values():
    layout = {"sections": [{"width": "inf", "height": float("nan")}]}
    page = inspect_layout(layout).pages[0]
    assert page.width == 1280
    assert page.height == 1050


def test_sections_must_be_a_list():
    assert inspect_layout({"sections": 5}).pages == []
    assert inspect_layout({"sections": None}).pages == []
    assert inspect_layout({}).pages == []


def test_non_dict_sections_and_containers_are_skipped():
    layout = {
        "sections": [
            None,
            "nope",
            {"displayName": "P", "visualContainers": ["bad", 7]},
        ]
    }
    model = inspect_layout(layout, source="l.pbix")
    assert [p.name for p in model.pages] == ["P"]
    assert model.pages[0].elements == []


def test_layout_that_is_not_a_mapping_yields_an_empty_model():
    model = inspect_layout([], source="l.pbix")  # type: ignore[arg-type]
    assert model.pages == []
