"""The first diagram tile must leave room for the heading above it.

`_tiles` cut every tile to the full `content_h`, but `diagram_story` already put a
heading and a 4 mm spacer on the first page. The first tile therefore overflowed
by the heading height and was pushed to its own page, leaving a page that carried
only "Data lineage diagram".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi.report.pdf_diagram import _tiles
from agentic_bi.report.pdf_style import _styles


def _png(path: Path, width: int, height: int) -> Path:
    PIL = pytest.importorskip("PIL.Image")
    PIL.new("RGB", (width, height), "white").save(path)
    return path


def _heights(flowables: list) -> list[float]:
    return [float(f.drawHeight) for f in flowables if hasattr(f, "drawHeight")]


def test_the_first_tile_fits_the_room_left_by_the_heading(tmp_path: Path) -> None:
    png = _png(tmp_path / "d.png", 200, 4000)
    styles = _styles("Helvetica", "Helvetica-Bold")
    full = _heights(_tiles(png, 500.0, 700.0, styles))
    with_heading = _heights(_tiles(png, 500.0, 700.0, styles, first_h=650.0))
    assert full and with_heading
    assert with_heading[0] <= 650.0
    assert with_heading[0] < full[0], "the heading must cost the first tile height"
    assert len(with_heading) >= len(full)


def test_a_short_diagram_that_only_fits_without_the_heading_is_tiled(
    tmp_path: Path,
) -> None:
    """A 690 px image fits 700 but not the 650 left after the heading."""
    png = _png(tmp_path / "d.png", 500, 690)
    styles = _styles("Helvetica", "Helvetica-Bold")
    assert len(_tiles(png, 500.0, 700.0, styles)) == 1
    tiled = _tiles(png, 500.0, 700.0, styles, first_h=650.0)
    assert len(tiled) > 1, "the image must be cut instead of overflowing the page"
