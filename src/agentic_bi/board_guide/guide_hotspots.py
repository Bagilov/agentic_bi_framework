"""Hotspot placement and paint order for the annotated board guide (stdlib only).

A visual's design box is not a hotspot yet. In `Report/Layout` a box may be
unset, negative, partly or wholly outside the canvas, degenerate (zero width or
height), or it may sit under a larger neighbour so that its hover label is
unreachable. This module turns the typed box into a usable percentage rectangle:

* intersect with the canvas — nothing outside the image is drawn;
* grow an intersecting box to a minimum visible size, so a two-pixel decorative
  visual still has a hoverable, labelled target;
* keep a fully outside box invisible instead of pinning an artifact to the edge.

`overlap_pairs` reports which hotspots share area, so the renderer can mark them
and the panel can say so; `paint_order` sorts large boxes first so a small visual
nested in a large one is painted last and keeps its hover.

Public API:
    Box                  - left/top/width/height in canvas percent
    DEFAULT_CANVAS_WIDTH - fallback canvas width, in design pixels
    DEFAULT_CANVAS_HEIGHT- fallback canvas height, in design pixels
    MIN_HOTSPOT_PX       - smallest visible side, in design pixels
    place(visual, w, h)  - one visual's hotspot
    is_visible(box)      - the box has a usable area
    overlap_pairs(boxes) - index pairs whose boxes intersect
    paint_order(boxes)   - indices, large first, small (nested) last
"""

from __future__ import annotations

import math
from typing import Protocol, TypedDict

DEFAULT_CANVAS_WIDTH = 1280.0
DEFAULT_CANVAS_HEIGHT = 720.0
# A hotspot thinner than this is still a target, so it is grown to it. Eight
# design pixels is above the ~6 px a pointer needs and below any real visual, so
# the growth never hides the true geometry of a meaningful box.
MIN_HOTSPOT_PX = 8.0
# Growth is capped so a legacy 1x1 visual on a small canvas cannot eat the page.
MAX_MIN_PERCENT = 4.0


class Box(TypedDict):
    """A hotspot rectangle, in percent of the canvas (0..100)."""

    left: float
    top: float
    width: float
    height: float


class BoxedVisual(Protocol):
    """Anything with a design box (a `GuideVisual`)."""

    x: float
    y: float
    width: float
    height: float


def _finite(value: object) -> float | None:
    """`value` as a finite float, or None when it is not a number."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canvas(value: float, fallback: float) -> float:
    """A usable canvas side: finite and positive, else the default."""
    number = _finite(value)
    return number if number and number > 0 else fallback


def _percent(px: float, side: float) -> float:
    """A design pixel coordinate as a canvas percentage, clipped to 0..100."""
    return min(max(px / side * 100.0, 0.0), 100.0)


def _empty() -> Box:
    return {"left": 0.0, "top": 0.0, "width": 0.0, "height": 0.0}


def is_visible(box: Box) -> bool:
    """Whether the hotspot has a non-zero area (and so can be hovered)."""
    return box["width"] > 0.0 and box["height"] > 0.0


def _area(box: Box) -> float:
    return box["width"] * box["height"]


def _grow(box: Box, page_width: float, page_height: float) -> Box:
    """Raise a visible box to the minimum hover size, kept inside the canvas."""
    min_w = min(MAX_MIN_PERCENT, MIN_HOTSPOT_PX / page_width * 100.0)
    min_h = min(MAX_MIN_PERCENT, MIN_HOTSPOT_PX / page_height * 100.0)
    width = min(max(box["width"], min_w), 100.0)
    height = min(max(box["height"], min_h), 100.0)
    left = min(max(box["left"], 0.0), 100.0 - width)
    top = min(max(box["top"], 0.0), 100.0 - height)
    return {"left": left, "top": top, "width": width, "height": height}


def place(visual: BoxedVisual, page_width: float, page_height: float) -> Box:
    """One visual's hotspot as canvas percentages.

    The box is intersected with the canvas, not merely shifted: a visual that is
    entirely left of or below the page has nothing to annotate and stays
    invisible, while a visual that hangs over an edge keeps only its visible
    part. A `nan`/`inf` coordinate or a negative size is treated like an unset
    one instead of leaking `nan%` into CSS.
    """
    w = _canvas(page_width, DEFAULT_CANVAS_WIDTH)
    h = _canvas(page_height, DEFAULT_CANVAS_HEIGHT)
    x = _finite(visual.x) or 0.0
    y = _finite(visual.y) or 0.0
    raw_w = max(_finite(visual.width) or 0.0, 0.0)
    raw_h = max(_finite(visual.height) or 0.0, 0.0)

    left = _percent(x, w)
    right = _percent(x + raw_w, w)
    top = _percent(y, h)
    bottom = _percent(y + raw_h, h)
    box: Box = {
        "left": left,
        "top": top,
        "width": right - left,
        "height": bottom - top,
    }
    if not is_visible(box):
        return _empty()
    return _grow(box, w, h)


def overlap_pairs(boxes: list[Box]) -> list[tuple[int, int]]:
    """Index pairs of hotspots whose areas intersect (touching edges do not)."""
    pairs: list[tuple[int, int]] = []
    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            dx = min(a["left"] + a["width"], b["left"] + b["width"]) - max(
                a["left"], b["left"]
            )
            dy = min(a["top"] + a["height"], b["top"] + b["height"]) - max(
                a["top"], b["top"]
            )
            if dx > 0.01 and dy > 0.01:
                pairs.append((i, j))
    return pairs


def paint_order(boxes: list[Box]) -> list[int]:
    """Indices ordered large-area first, so a nested small hotspot paints last.

    Later siblings win the hover in CSS, so a small visual inside a large one
    must come last; otherwise the large hotspot swallows the small one's label.
    Ties keep the input order, which `extract_page_geometry` already sorts
    top-left first.
    """
    return sorted(range(len(boxes)), key=lambda i: (-_area(boxes[i]), i))


__all__ = [
    "DEFAULT_CANVAS_HEIGHT",
    "DEFAULT_CANVAS_WIDTH",
    "MIN_HOTSPOT_PX",
    "Box",
    "is_visible",
    "overlap_pairs",
    "paint_order",
    "place",
]
