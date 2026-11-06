"""Geometry tests for the annotated board guide (`board_guide`).

The geometry is pure `Report/Layout` parsing, so these tests use in-memory
layouts and never touch the engine or a real capture. Name/stem sanitizing lives
in `test_board_guide_names.py`; robustness against malformed layout nodes lives
in `test_board_guide_robustness.py`.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.board_guide import extract_page_geometry
from agentic_bi.board_guide.guide_layout import (
    filter_refs,
    is_hidden,
    position,
    projections,
    visual_title,
)


def _write_pbix(path: Path, layout: dict, encoding: str = "utf-16-le") -> Path:
    payload = json.dumps(layout, ensure_ascii=False).encode(encoding)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Report/Layout", payload)
    return path


def test_extract_geometry_reads_pages_and_boxes(tmp_path: Path) -> None:
    layout = make_layout(
        [
            make_container(
                "card",
                {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
                ["Sum(Sales.amount)"],
                title="Total",
            ),
        ],
        page="Overview",
    )
    pbix = _write_pbix(tmp_path / "b.pbix", layout)
    geom = extract_page_geometry(pbix)
    assert len(geom.pages) == 1
    page = geom.pages[0]
    assert page.name == "Overview"
    assert page.stem == "Overview"
    assert geom.visual_count == 1
    visual = page.visuals[0]
    assert (visual.x, visual.y, visual.width, visual.height) == (20, 20, 400, 300)
    assert visual.label == "Total"


def test_geometry_uses_config_position_over_container(tmp_path: Path) -> None:
    """`layouts[0].position` wins: that is the design box a screenshot shows."""
    layout = make_layout(
        [
            make_container(
                "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
            )
        ]
    )
    cfg = json.loads(layout["sections"][0]["visualContainers"][0]["config"])
    cfg["layouts"] = [{"position": {"x": 55, "y": 66, "width": 77, "height": 88}}]
    layout["sections"][0]["visualContainers"][0]["config"] = json.dumps(cfg)
    geom = extract_page_geometry(_write_pbix(tmp_path / "b.pbix", layout))
    visual = geom.pages[0].visuals[0]
    assert (visual.x, visual.y, visual.width, visual.height) == (55, 66, 77, 88)


def test_bad_config_position_falls_back_to_container_box() -> None:
    """A malformed config coordinate must not silently become a 0 origin."""
    vc = {"x": 11, "y": 22, "width": 33, "height": 44}
    cfg = {"layouts": [{"position": {"x": "abc", "y": 66}}]}
    assert position(vc, cfg) == (11.0, 22.0, 33.0, 44.0, 0.0)


def test_position_accepts_string_coordinates() -> None:
    """String coordinates are common in some writers and must be honoured."""
    cfg = {
        "layouts": [{"position": {"x": "55", "y": "66", "width": "77", "height": "88"}}]
    }
    assert position({}, cfg) == (55.0, 66.0, 77.0, 88.0, 0.0)


def test_position_rejects_non_finite_coordinates() -> None:
    """`nan`/`inf` are not coordinates: they must fall back, not leak as `nan%`."""
    cfg = {"layouts": [{"position": {"x": "nan", "y": "nan"}}]}
    assert position({}, cfg) == (0.0, 0.0, 0.0, 0.0, 0.0)
    cfg = {"layouts": [{"position": {"x": "inf", "y": 1}}]}
    assert position({}, cfg) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_literal_ignores_non_string_values() -> None:
    """A `null`/number DAX literal must not leak `"None"`/`"5"` as text."""
    from agentic_bi.board_guide.guide_layout import _literal

    assert _literal(None) == ""
    assert _literal(5) == ""
    assert _literal("'KPI'") == "KPI"
    assert _literal(42) == ""


def test_page_hidden_in_reading_view_is_skipped(tmp_path: Path) -> None:
    layout = make_layout(
        [
            make_container(
                "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
            )
        ]
    )
    layout["sections"].append(
        {"displayName": "Tooltip", "hideInReadingView": True, "visualContainers": []}
    )
    geom = extract_page_geometry(_write_pbix(tmp_path / "b.pbix", layout))
    assert [p.name for p in geom.pages] == ["P"]
    assert is_hidden({"hideInReadingView": True}) is True
    assert is_hidden({}) is False


def test_display_option_is_not_a_hide_marker() -> None:
    """Measured: Desktop writes 1 and our own engine writes 3 for visible pages.

    An earlier implementation treated `displayOption == 3` as "hidden" and
    silently dropped every page of a framework-built board.
    """
    assert is_hidden({"displayOption": 3}) is False
    assert is_hidden({"displayOption": 1}) is False


def test_visuals_are_sorted_top_left(tmp_path: Path) -> None:
    first = make_container(
        "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"], x=900
    )
    first["y"] = 10
    second = make_container(
        "card", {"Values": [{"queryRef": "Sales.qty"}]}, ["Sales.qty"], x=20
    )
    second["y"] = 500
    layout = make_layout([first, second])
    geom = extract_page_geometry(_write_pbix(tmp_path / "b.pbix", layout))
    ys = [v.y for v in geom.pages[0].visuals]
    assert ys == sorted(ys)


def test_unreadable_container_is_skipped_not_fatal(tmp_path: Path) -> None:
    layout = make_layout(
        [
            {"x": 0, "y": 0, "width": 10, "height": 10},  # no config
            {"config": "{not json", "x": 0, "y": 0, "width": 10, "height": 10},
            42,  # not a dict
            make_container(
                "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
            ),
        ]
    )
    geom = extract_page_geometry(_write_pbix(tmp_path / "b.pbix", layout))
    assert geom.visual_count == 1


def test_measures_are_separated_from_columns() -> None:
    sv = {
        "prototypeQuery": {
            "Select": [
                {"Measure": {"Property": "Revenue"}, "NativeReferenceName": "Rev"},
                {
                    "Column": {"Property": "region"},
                    "NativeReferenceName": "Sales.region",
                },
            ]
        }
    }
    fields, measures = projections(sv)
    assert fields == ["Sales.region"]
    assert measures == ["Rev"]


def test_projections_tolerate_string_or_missing_query() -> None:
    assert projections({"prototypeQuery": "not json"}) == ([], [])
    assert projections({}) == ([], [])
    assert projections({"prototypeQuery": {"Select": [None, "x", {}]}}) == ([], [])


def test_visual_title_reads_nested_literal() -> None:
    cfg = {
        "singleVisual": {
            "vcObjects": {
                "title": [
                    {"properties": {"text": {"expr": {"Literal": {"Value": "'KPI'"}}}}}
                ]
            }
        }
    }
    assert visual_title(cfg) == "KPI"
    assert visual_title({"singleVisual": {}}) == ""


def test_filter_refs_describe_comparisons() -> None:
    flt = {
        "expression": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": "Sales"}},
                "Property": "region",
            }
        },
        "filter": {
            "Where": [
                {
                    "Condition": {
                        "Comparison": {
                            "ComparisonKind": 0,
                            "Left": {"Column": {"Property": "region"}},
                            "Right": {"Literal": {"Value": "'EU'"}},
                        }
                    }
                }
            ]
        },
    }
    refs = filter_refs(json.dumps([flt]))
    assert refs == ["Sales[region]: region = EU"]
    assert filter_refs("[]") == []
    assert filter_refs("not json") == []
