"""Embed a PlantUML diagram into a PDF story, tiling it across pages.

A lineage diagram is often much taller than a single page. This module renders
the PlantUML source to PNG (via :mod:`agentic_bi.report.plantuml_tools`), scales
it to the printable width and cuts it into vertical tiles so every tile fits a
page. If the jar/Pillow is unavailable, the diagram is skipped and the report is
still produced.
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, Spacer

from agentic_bi.report.plantuml_tools import render_png

logger = logging.getLogger(__name__)


def _tiles(png_path: Path, content_w: float, content_h: float, styles) -> list:
    """Cut the PNG into page-height tiles scaled to the content width."""
    from PIL import Image as PILImage

    image = PILImage.open(png_path)
    width, height = image.size
    scale = content_w / float(width)
    scaled_h = height * scale
    if scaled_h <= content_h:
        buffer = io.BytesIO(png_path.read_bytes())
        image.close()
        return [Image(buffer, width=content_w, height=scaled_h,
                      hAlign="CENTER")]

    # slice the image into page-height tiles (pixels per page in source space)
    page_h_px = max(1, int(content_h / scale))
    flowables: list = []
    top = 0
    while top < height:
        bottom = min(height, top + page_h_px)
        tile = image.crop((0, top, width, bottom))
        buffer = io.BytesIO()
        tile.save(buffer, format="PNG")
        buffer.seek(0)
        tile_h = (bottom - top) * scale
        flowables.append(Image(buffer, width=content_w, height=tile_h,
                               hAlign="CENTER"))
        flowables.append(PageBreak())
        top = bottom
    image.close()
    if flowables and isinstance(flowables[-1], PageBreak):
        flowables.pop()
    return flowables


def diagram_story(plantuml: str, content_w: float, content_h: float,
                  styles, title: str = "Data lineage diagram") -> list:
    """Render ``plantuml`` and return flowables (one or more pages)."""
    story: list = [Paragraph(title, styles["Heading2"]), Spacer(1, 4 * mm)]
    if not plantuml.strip():
        story.append(Paragraph("No diagram provided.", styles["Body"]))
        return story

    with tempfile.TemporaryDirectory() as td:
        png = render_png(plantuml, td)
        if png is None:
            logger.warning("PlantUML rendering unavailable; diagram skipped")
            story.append(Paragraph(
                "Diagram not rendered (plantuml.jar / Pillow unavailable).",
                styles["Body"]))
            return story
        try:
            story.extend(_tiles(Path(png), content_w, content_h, styles))
        except ImportError:
            logger.warning("Pillow unavailable; diagram placed as a single image")
            story.append(Image(str(png), width=content_w, hAlign="CENTER"))
    return story
