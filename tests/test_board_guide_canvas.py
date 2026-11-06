"""Canvas defaults and hotspot percentages shared by geometry and rendering.

A hotspot is a canvas percentage, so the page canvas used by `place()` and the
one printed in the header (and dumped to `--geometry-json`) must be one value.
A negative canvas from an untrusted layout is not a canvas and must fall back to
the same default the renderer uses.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from agentic_bi.board_guide import (
    GuideGeometry,
    GuidePage,
    GuideVisual,
    extract_page_geometry,
    render_page_html,
)
from agentic_bi.board_guide.guide_hotspots import (
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
)


def _write_pbix(path: Path, layout: dict) -> Path:
    payload = json.dumps(layout, ensure_ascii=False).encode("utf-16-le")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Report/Layout", payload)
    return path


def test_hotspot_is_percentage_of_canvas() -> None:
    visual = GuideVisual(visual_type="card", x=130, y=105, width=260, height=210)
    box = visual.hotspot(1300, 1050)
    assert box == {"left": 10.0, "top": 10.0, "width": 20.0, "height": 20.0}
    page = GuidePage(name="P", width=1300, height=1050)
    page.visuals.append(visual)
    html = render_page_html(page, "p.png")
    assert "left:10.00%;top:10.00%;width:20.00%;height:20.00%" in html, (
        "rendered hotspot must use the same percentages as the geometry"
    )


def test_hotspot_falls_back_to_default_canvas() -> None:
    visual = GuideVisual(visual_type="card", x=128, y=72, width=128, height=72)
    box = visual.hotspot(0, 0)
    assert box["left"] == 10.0
    assert box["width"] == 10.0


def test_negative_page_canvas_falls_back_to_the_default(tmp_path: Path) -> None:
    """`width: -100` must not survive into `--geometry-json` or the renderer."""
    layout = {
        "sections": [
            {
                "displayName": "P",
                "width": -100,
                "height": -50,
                "visualContainers": [],
            }
        ]
    }
    geom = extract_page_geometry(_write_pbix(tmp_path / "b.pbix", layout))
    page = geom.pages[0]
    assert (page.width, page.height) == (DEFAULT_CANVAS_WIDTH, DEFAULT_CANVAS_HEIGHT)


def test_page_and_hotspot_share_one_default_canvas() -> None:
    page = GuidePage(name="P")
    assert page.width == DEFAULT_CANVAS_WIDTH
    assert page.height == DEFAULT_CANVAS_HEIGHT
    visual = GuideVisual(visual_type="card", x=128, y=72, width=128, height=72)
    box = visual.hotspot(DEFAULT_CANVAS_WIDTH, DEFAULT_CANVAS_HEIGHT)
    assert box["left"] == 10.0
    assert box["width"] == 10.0


def test_label_falls_back_to_type() -> None:
    assert GuideVisual(visual_type="textbox", title="").label == "textbox"
    assert GuideVisual(visual_type="card", title="", measures=["Rev"]).label == "Rev"
    assert (
        GuideVisual(visual_type="card", title="", fields=["Sales.region"]).label
        == "Sales.region"
    )
    assert (
        GuideVisual(visual_type="textbox", title="", fields=[], measures=[]).has_data
        is False
    )


def test_geometry_to_dict_round_trips() -> None:
    page = GuidePage(name="P", width=1300, height=1050)
    page.visuals.append(GuideVisual(visual_type="card", title="T", x=1, y=2))
    payload = GuideGeometry(source="b.pbix", pages=[page]).to_dict()
    assert payload["pbix"] == "b.pbix"
    assert payload["pages"][0]["visuals"][0]["title"] == "T"
