"""Geometry checks for explicit block positions (page bounds, overlaps, span).

Explicit positions are the only part of a design that can silently overlap: the
auto-placement always finds a free cell, but a hand-written `pos` can sit on top
of a neighbour or hang off the canvas. These checks run before the layout is
compiled, so the error names the page and the two blocks that collide.

Public API:
    check_page_geometry(page, issues) -> None
"""

from __future__ import annotations

from agentic_bi.constructor.design import PageDesign
from agentic_bi.constructor.issues import Issue


def _overlap(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> bool:
    """True when two boxes share at least one pixel."""
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def check_page_geometry(page: PageDesign, issues: list[Issue]) -> None:
    """Append page-bound, overlap and span findings for one page."""
    cols = 2 if page.width >= 800 else 1
    explicit: list[tuple[str, tuple[int, int, int, int]]] = []
    for index, block in enumerate(page.visuals):
        path = f"pages[{page.name}].visuals[{index}]"
        if block.span is not None and block.span > cols:
            issues.append(
                Issue(
                    "warning",
                    "span_clamped",
                    f"span {block.span} > {cols} columns; it will be clamped",
                    path,
                )
            )
        if block.pos is None:
            continue
        position = block.pos
        x, y, w, h = position
        if x + w > page.width or y + h > page.height:
            issues.append(
                Issue(
                    "error",
                    "pos_out_of_page",
                    f"pos {position} exceeds page {page.width}x{page.height}",
                    path,
                )
            )
        for other_path, other in explicit:
            if _overlap(position, other):
                issues.append(
                    Issue("error", "overlap", f"pos overlaps {other_path}", path)
                )
        explicit.append((path, position))


__all__ = ["check_page_geometry"]
