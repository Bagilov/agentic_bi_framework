"""Hotspots under each other: paint order, overlap marking, readable labels.

Two visuals can share canvas area (a KPI on a background shape, a legend over a
chart). The later hotspot wins the hover, so a small nested visual must be
painted last; and when two boxes really overlap the panel has to say so, because
only one of them can be hovered at a time.
"""

from __future__ import annotations

import json
import re

from agentic_bi.board_guide import GuidePage, GuideVisual, render_page_html
from agentic_bi.board_guide.guide_render import hotspot_layout


def _page(*visuals: GuideVisual) -> GuidePage:
    page = GuidePage(name="P", width=1000, height=1000)
    page.visuals.extend(visuals)
    return page


def _position(html: str, index: int) -> int:
    """Offset of the exact `data-i="<index>"` attribute, not a prefix match."""
    match = re.search(rf'data-i="{index}"(?!\d)', html)
    assert match is not None, f"hotspot {index} is missing"
    return match.start()


def test_small_nested_hotspot_is_painted_after_the_large_one() -> None:
    page = _page(
        GuideVisual(visual_type="shape", x=0, y=0, width=400, height=400),
        GuideVisual(visual_type="card", title="KPI", x=100, y=100, width=50, height=50),
    )
    html = render_page_html(page, "p.png")
    assert _position(html, 0) < _position(html, 1)


def test_exact_hotspot_index_is_not_matched_inside_a_larger_index() -> None:
    """`data-i="1"` also prefixes `data-i="10"`; paint order must still be exact."""
    visuals = [
        GuideVisual(visual_type="card", x=0, y=0, width=40, height=40)
        for _ in range(10)
    ]
    visuals.append(GuideVisual(visual_type="shape", x=0, y=0, width=900, height=900))
    visuals.append(GuideVisual(visual_type="card", x=950, y=950, width=40, height=40))
    html = render_page_html(_page(*visuals), "p.png")
    assert html.count('data-i="10"') == 1
    assert html.count('data-i="1"') == 1
    assert _position(html, 10) < _position(html, 1)
    assert _position(html, 0) < _position(html, 1)


def test_overlapping_hotspots_are_marked_and_explained() -> None:
    page = _page(
        GuideVisual(
            visual_type="shape", title="frame", x=0, y=0, width=400, height=400
        ),
        GuideVisual(visual_type="card", title="KPI", x=100, y=100, width=50, height=50),
    )
    layout = hotspot_layout(page)
    assert layout.overlaps == {0: (1,), 1: (0,)}
    html = render_page_html(page, "p.png")
    assert "hot overlap" in html
    refs = html.split("window.__GUIDE_REFS__ = ", 1)[1].split(";</script>", 1)[0]
    payload = json.loads(refs)
    assert "Перекрывается с визуалом #2" in payload[0]
    assert "Перекрывается с визуалом #1" in payload[1]


def test_disjoint_hotspots_are_not_marked_as_overlapping() -> None:
    page = _page(
        GuideVisual(visual_type="card", x=0, y=0, width=100, height=100),
        GuideVisual(visual_type="card", x=500, y=500, width=100, height=100),
    )
    assert hotspot_layout(page).overlaps == {}
    assert "hot overlap" not in render_page_html(page, "p.png")


def test_a_tiny_hotspot_puts_its_label_outside() -> None:
    """A two-pixel target cannot hold its own label, so the label sits above."""
    page = _page(
        GuideVisual(visual_type="card", title="dot", x=100, y=100, width=1, height=1)
    )
    html = render_page_html(page, "p.png")
    assert 'class="hot label-above"' in html


def test_a_tiny_hotspot_at_the_top_puts_its_label_below() -> None:
    page = _page(
        GuideVisual(visual_type="card", title="dot", x=100, y=0, width=1, height=1)
    )
    html = render_page_html(page, "p.png")
    assert 'class="hot label-below"' in html


def test_a_large_hotspot_keeps_its_label_inside() -> None:
    page = _page(
        GuideVisual(
            visual_type="card", title="big", x=100, y=100, width=400, height=300
        )
    )
    html = render_page_html(page, "p.png")
    assert 'class="hot label-above"' not in html
    assert 'class="hot label-below"' not in html
    assert '<span class="hotlabel">#1 big</span>' in html
