"""Hotspot placement tests (`board_guide.guide_hotspots`).

A hotspot is the only way a reader can reach a visual's metadata, so its box has
to be *usable*: inside the image, big enough to hover, and painted so a small
visual nested in a large one is not swallowed. These are pure geometry tests —
no browser, no screenshot.
"""

from __future__ import annotations

from agentic_bi.board_guide.guide_geometry import GuideVisual
from agentic_bi.board_guide.guide_hotspots import (
    MIN_HOTSPOT_PX,
    is_visible,
    overlap_pairs,
    paint_order,
    place,
)

_ZERO = {"left": 0.0, "top": 0.0, "width": 0.0, "height": 0.0}


def test_place_converts_design_pixels_to_canvas_percent() -> None:
    visual = GuideVisual(visual_type="card", x=130, y=105, width=260, height=210)
    assert place(visual, 1300, 1050) == {
        "left": 10.0,
        "top": 10.0,
        "width": 20.0,
        "height": 20.0,
    }


def test_place_drops_a_box_entirely_outside_the_canvas() -> None:
    """Nothing to annotate: the old behaviour pinned a fake box to the edge."""
    left = GuideVisual(visual_type="x", x=-500, y=10, width=50, height=50)
    below = GuideVisual(visual_type="x", x=10, y=900, width=50, height=50)
    assert place(left, 100, 100) == _ZERO
    assert place(below, 100, 100) == _ZERO


def test_place_clips_a_box_that_hangs_over_an_edge() -> None:
    partly = GuideVisual(visual_type="x", x=-5, y=95, width=10, height=10)
    box = place(partly, 100, 100)
    assert box == {"left": 0.0, "top": 95.0, "width": 5.0, "height": 5.0}
    assert is_visible(box)


def test_place_keeps_a_zero_size_box_invisible() -> None:
    """A degenerate box is not a target; growing it would invent geometry."""
    for width, height in ((0.0, 10.0), (10.0, 0.0), (-5.0, -5.0)):
        visual = GuideVisual(visual_type="x", x=10, y=10, width=width, height=height)
        assert place(visual, 100, 100) == _ZERO


def test_place_grows_a_tiny_visible_box_to_a_hoverable_minimum() -> None:
    tiny = GuideVisual(visual_type="x", x=10, y=10, width=0.5, height=0.5)
    box = place(tiny, 1280, 720)
    assert box["width"] >= MIN_HOTSPOT_PX / 1280 * 100
    assert box["height"] >= MIN_HOTSPOT_PX / 720 * 100


def test_place_keeps_a_grown_box_inside_the_canvas() -> None:
    """A dot at the bottom-right corner grows left/up, not past the image."""
    corner = GuideVisual(visual_type="x", x=1279.9, y=719.9, width=0.5, height=0.5)
    box = place(corner, 1280, 720)
    assert box["left"] + box["width"] <= 100.0
    assert box["top"] + box["height"] <= 100.0
    assert box["width"] > 0.0 and box["height"] > 0.0


def test_place_rejects_non_finite_coordinates() -> None:
    """`nan`/`inf` from a hand-edited box must not become `nan%` in CSS."""
    visual = GuideVisual(
        visual_type="x",
        x=float("nan"),
        y=float("inf"),
        width=float("nan"),
        height=10,
    )
    assert place(visual, 100, 100) == _ZERO


def test_place_falls_back_to_the_default_canvas() -> None:
    visual = GuideVisual(visual_type="card", x=128, y=72, width=128, height=72)
    box = place(visual, 0, float("nan"))
    assert box["left"] == 10.0
    assert box["width"] == 10.0


def test_overlap_pairs_finds_shared_area_only() -> None:
    boxes = [
        {"left": 0.0, "top": 0.0, "width": 10.0, "height": 10.0},
        {"left": 5.0, "top": 5.0, "width": 10.0, "height": 10.0},
        {"left": 20.0, "top": 20.0, "width": 5.0, "height": 5.0},
        # touches box 0 exactly on its right edge: no shared area
        {"left": 10.0, "top": 0.0, "width": 5.0, "height": 5.0},
    ]
    assert overlap_pairs(boxes) == [(0, 1)]


def test_paint_order_puts_a_nested_small_hotspot_last() -> None:
    """The last sibling wins the hover, so the small box must come last."""
    big = {"left": 0.0, "top": 0.0, "width": 40.0, "height": 40.0}
    small = {"left": 10.0, "top": 10.0, "width": 5.0, "height": 5.0}
    middle = {"left": 60.0, "top": 0.0, "width": 10.0, "height": 10.0}
    assert paint_order([big, small, middle]) == [0, 2, 1]


def test_is_visible_requires_both_sides() -> None:
    assert is_visible({"left": 0.0, "top": 0.0, "width": 1.0, "height": 0.0}) is False
    assert is_visible({"left": 0.0, "top": 0.0, "width": 1.0, "height": 1.0}) is True
