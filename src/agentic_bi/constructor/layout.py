"""Deterministic placement of blocks and compilation of `Report/Layout`.

Nothing here is creative: blocks keep the design order, an explicit `pos` is
honoured, and every other block takes the first free cell of a fixed grid. The
same design therefore always yields the same layout, which is what makes a
preview or a diff between two builds meaningful.

Public API:
    MARGIN, GUTTER, ROW_H
    CompiledLayout(design, pages, layout, positions)
    compile_design(design) -> CompiledLayout
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentic_bi.constructor.blocks import BLOCKS, make_visual
from agentic_bi.constructor.design import Design, PageDesign, VisualDesign
from agentic_bi.engine.layout import build_report_dict
from agentic_bi.engine.layout_visual import Visual

if TYPE_CHECKING:
    from collections.abc import Iterable

MARGIN = 20
GUTTER = 20
ROW_H = 300
_MAX_ROWS = 500


@dataclass
class CompiledLayout:
    """The result of compiling a design: layout JSON, pages and positions."""

    design: Design
    pages: list[tuple[str, list[Visual]]]
    layout: dict
    positions: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)

    def layout_bytes(self) -> bytes:
        """Return `Report/Layout` encoded as the `.pbix` container expects it."""
        return json.dumps(self.layout, ensure_ascii=False).encode("utf-16-le")

    def page_counts(self) -> dict[str, int]:
        """Return the number of visuals per page title."""
        return {name: len(visuals) for name, visuals in self.pages}


def _span(block: VisualDesign, cols: int) -> int:
    default = BLOCKS[block.kind].default_span
    return max(1, min(int(block.span or default), cols))


def _cols(page: PageDesign) -> int:
    return 2 if page.width >= 800 else 1


def _mark(
    occupied: set[tuple[int, int]],
    x: int,
    y: int,
    w: int,
    h: int,
    cell_w: int,
    cell_h: int,
    cols: int,
) -> None:
    """Mark every grid cell covered by a box, clamped to the page grid."""
    c0 = min(cols - 1, max(0, (x - MARGIN) // (cell_w + GUTTER)))
    c1 = min(cols - 1, max(c0, (x + max(w, 1) - MARGIN) // (cell_w + GUTTER)))
    r0 = max(0, (y - MARGIN) // (cell_h + GUTTER))
    r1 = max(r0, (y + max(h, 1) - MARGIN) // (cell_h + GUTTER))
    for row in range(r0, r1 + 1):
        for col in range(c0, c1 + 1):
            occupied.add((row, col))


def _place(page: PageDesign) -> list[tuple[int, int, int, int]]:
    """Return one position per block: explicit positions first, then the grid.

    Raises:
        ValueError: the page grid has no free slot (an explicit layout covers
            the whole canvas), instead of placing a block outside the page.
    """
    cols = _cols(page)
    cell_w = (page.width - 2 * MARGIN - (cols - 1) * GUTTER) // cols
    if cell_w <= 0:
        raise ValueError(f"page {page.name!r}: {page.width}px is too narrow")
    occupied: set[tuple[int, int]] = set()
    result: list[tuple[int, int, int, int] | None] = [None] * len(page.visuals)

    for index, block in enumerate(page.visuals):
        if block.pos is None:
            continue
        result[index] = block.pos
        _mark(occupied, *block.pos, cell_w, ROW_H, cols)

    for index, block in enumerate(page.visuals):
        if result[index] is not None:
            continue
        span = _span(block, cols)
        width = span * cell_w + (span - 1) * GUTTER
        row = 0
        slot: int | None = None
        while slot is None:
            slot = next(
                (
                    col
                    for col in range(cols - span + 1)
                    if all((row, col + k) not in occupied for k in range(span))
                ),
                None,
            )
            if slot is not None:
                break
            row += 1
            if row > _MAX_ROWS:
                raise ValueError(f"page {page.name!r}: no free slot")
        x = MARGIN + slot * (cell_w + GUTTER)
        y = MARGIN + row * (ROW_H + GUTTER)
        result[index] = (x, y, width, ROW_H)
        _mark(occupied, x, y, width, ROW_H, cell_w, ROW_H, cols)

    if any(position is None for position in result):
        raise ValueError(f"page {page.name!r}: layout left a visual unplaced")
    return [position for position in result if position is not None]


def _canvas(design: Design) -> tuple[int, int]:
    widths: Iterable[int] = (page.width for page in design.pages)
    heights: Iterable[int] = (page.height for page in design.pages)
    return (max(widths, default=1280), max(heights, default=800))


def compile_design(design: Design) -> CompiledLayout:
    """Compile a design into `Report/Layout` without touching a `.pbix`.

    Raises:
        ValueError: a page cannot be laid out (no free slot, too narrow) or a
            block cannot become a visual (unknown field combination).
    """
    pages: list[tuple[str, list[Visual]]] = []
    positions: dict[str, tuple[int, int, int, int]] = {}
    for page in design.pages:
        placed = _place(page)
        visuals: list[Visual] = []
        for block, position in zip(page.visuals, placed, strict=True):
            visuals.append(make_visual({**block.to_block(), "pos": position}))
            positions[block.block_id] = position
        pages.append((page.title, visuals))

    layout = build_report_dict(
        pages, canvas=_canvas(design), margin=MARGIN, gutter=GUTTER
    )
    for section, page in zip(layout["sections"], design.pages, strict=True):
        # The page size declared by the design is a minimum: auto-placement may
        # grow the sheet so blocks never leave the canvas.
        section["width"] = max(int(section.get("width", 0)), page.width)
        section["height"] = max(int(section.get("height", 0)), page.height)
    return CompiledLayout(
        design=design, pages=pages, layout=layout, positions=positions
    )


__all__ = ["GUTTER", "MARGIN", "ROW_H", "CompiledLayout", "compile_design"]
