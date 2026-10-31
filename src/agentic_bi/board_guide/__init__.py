"""Annotated board guide: a report screenshot with interactive visual hotspots.

This is the *visual* companion of `web_report`:

* `web_report` renders a dependency-free **layout** clone — every element at its
  true position, drawn with a mock glyph, plus per-element checks;
* `board_guide` renders the **real screenshot** of a page with the same
  geometry as transparent hotspots on top: hovering a visual shows its type,
  projected fields, measures, measures' DAX and visual filters in a side panel.

Neither reads images: the picture is what a human sees, the hotspots and their
metadata come from `Report/Layout`, so an agent can drive or validate the guide
without vision.

Modules:
    guide_geometry - `.pbix` -> typed pages/visuals geometry (stdlib only)
    guide_layout   - tolerant helpers for untrusted `Report/Layout` nodes
    guide_names    - page names -> safe, unique file stems
    guide_assets   - CSS/HTML fragments for the page and the index
    guide_render   - geometry + screenshots -> self-contained HTML
    guide_capture  - optional Playwright capture of rendered pages (extra)
    guide_cli      - `agentic-bi-board-guide` command line

Typical use:

    from agentic_bi.board_guide import extract_page_geometry, build_guide
    geom = extract_page_geometry("board.pbix")
    build_guide(geom, "guide_dir", screenshots="shots_dir")

Environment-agnostic: no hosts, no shares, no personal paths. Capture is opt-in
and its selectors are parameters, so the module works against any portal or any
locally rendered screenshot set.
"""

from __future__ import annotations

from agentic_bi.board_guide.guide_geometry import (
    GuideGeometry,
    GuidePage,
    GuideVisual,
    extract_page_geometry,
    load_measure_expressions,
    safe_name,
    unique_stems,
)
from agentic_bi.board_guide.guide_render import build_guide, render_page_html

__all__ = [
    "GuideGeometry",
    "GuidePage",
    "GuideVisual",
    "build_guide",
    "extract_page_geometry",
    "load_measure_expressions",
    "render_page_html",
    "safe_name",
    "unique_stems",
]
