"""Render a board guide: an index plus one annotated page per screenshot.

Geometry comes from `guide_geometry`; the picture is an external file (`page_<stem>.png`
next to the HTML, or any `src` prefix). Each visual becomes an absolutely
positioned hotspot expressed in canvas percentages, so the overlay is correct at
any screenshot scale — the layout canvas is scaled to fit the image, which keeps
its aspect ratio.

Public API:
    render_page_html(page, image, ...) -> str
    render_index_html(rows, source)   -> str
    build_guide(geometry, out_dir, screenshots=None) -> list[Path]
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

from agentic_bi.board_guide.guide_assets import INDEX_CSS, PAGE_CSS, PAGE_JS
from agentic_bi.board_guide.guide_geometry import (
    GuideGeometry,
    GuidePage,
    GuideVisual,
    unique_stems,
)

# Characters json.dumps leaves alone that are unsafe inside a `<script>` element
# or a JavaScript string literal: the HTML script-terminator pair, `&`, and the
# JS line terminators U+2028/U+2029 (valid JSON, a syntax error in older JS).
_SCRIPT_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _canvas_px(value: float, fallback: float) -> float:
    """A finite, positive canvas dimension for display (guards `nan`/`inf`)."""
    return value if math.isfinite(value) and value > 0 else fallback


def _json_for_script(payload: object) -> str:
    """Serialize `payload` for embedding inside a `<script>` element."""
    text = json.dumps(payload, ensure_ascii=False)
    for char, escaped in _SCRIPT_ESCAPES.items():
        text = text.replace(char, escaped)
    return text


def visual_ref_html(visual: GuideVisual) -> str:
    """The side-panel help block for one visual (type, fields, DAX, filters)."""
    parts = [f'<div class="vtype">{_e(visual.visual_type)}</div>']
    if not visual.has_data:
        parts.append('<div class="tagrow">статический элемент</div>')
    if visual.fields:
        tags = "".join(f'<span class="tag">{_e(x)}</span>' for x in visual.fields[:12])
        parts.append(f'<div class="tagrow">{tags}</div>')
    if visual.measures:
        names = "<br/>".join(_e(m) for m in visual.measures)
        parts.append(f'<div class="vmeasure">{names}</div>')
    if visual.filters:
        joined = " · ".join(_e(f) for f in visual.filters)
        parts.append(f'<div class="vfilter">Фильтры: {joined}</div>')
    if visual.dax:
        lines = "".join(f"<code>{_e(x)}</code>" for x in list(visual.dax.values())[:4])
        parts.append(
            f'<details class="vdax"><summary>DAX ({len(visual.dax)})</summary>'
            f"{lines}</details>"
        )
    return "".join(parts)


def _hotspots(page: GuidePage) -> str:
    boxes = []
    for i, visual in enumerate(page.visuals):
        box = visual.hotspot(page.width, page.height)
        style = (
            f"left:{box['left']:.2f}%;top:{box['top']:.2f}%;"
            f"width:{box['width']:.2f}%;height:{box['height']:.2f}%"
        )
        boxes.append(
            f'<div class="hot" data-i="{i}" title="{_e(visual.label)}" '
            f'style="{style}"></div>'
        )
    return "".join(boxes)


def render_page_html(
    page: GuidePage,
    image: str,
    *,
    title: str | None = None,
    index_href: str = "index.html",
) -> str:
    """Render one annotated page.

    Args:
        page: the page geometry (canvas size + visuals).
        image: the `src` of the screenshot (a bare filename or a URL prefix).
        title: the heading; defaults to the page name.
        index_href: the "back to index" link target.

    Returns:
        A self-contained HTML document string.
    """
    refs = _json_for_script(
        [
            f"<b>Визуал #{i + 1}: {_e(v.label)}</b><hr>{visual_ref_html(v)}"
            for i, v in enumerate(page.visuals)
        ]
    )
    heading = title or page.name
    canvas_w = _canvas_px(page.width, 1280.0)
    canvas_h = _canvas_px(page.height, 720.0)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(heading)} · board guide</title>
<style>{PAGE_CSS}</style></head>
<body>
<header>
  <a class="back" href="{_e(index_href)}">← индекс</a>
  <h1>{_e(heading)}</h1>
  <span class="meta">канвас {canvas_w:.0f}×{canvas_h:.0f} ·
    визуалов {len(page.visuals)} · наведите/кликните на визуал</span>
</header>
<div class="stage">
  <div class="imgwrap">
    <img src="{_e(image)}" alt="{_e(heading)}">
    {_hotspots(page)}
  </div>
</div>
<div class="panel" id="panel">
  <span class="hint">Наведите курсор на визуал — появится справка.</span>
</div>
<script>window.__GUIDE_REFS__ = {refs};</script>
<script>{PAGE_JS}</script>
</body></html>
"""


def render_index_html(
    rows: list[tuple[str, str, int]], source: str, *, title: str = "Board guide"
) -> str:
    """Render the index listing every generated page."""
    items = "".join(
        f'<li><a href="{_e(href)}">{_e(name)}</a>'
        f'<span class="meta">визуалов: {count}</span></li>'
        for name, href, count in rows
    )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>{_e(title)}</title>
<style>{INDEX_CSS}</style></head>
<body>
<h1>{_e(title)}</h1>
<div class="sub">{_e(source)} · листов: {len(rows)}</div>
<ol>{items}</ol>
</body></html>
"""


def _resolve_image(stem: str, screenshots: Path | str | None) -> str | None:
    """The `src` for a page stem: an explicit `src_prefix`, else a found PNG."""
    if screenshots is None:
        return None
    if isinstance(screenshots, str) and "://" in screenshots:
        return f"{screenshots.rstrip('/')}/page_{stem}.png"
    root = Path(screenshots)
    candidate = root / f"page_{stem}.png"
    if candidate.exists():
        return str(candidate)
    return None


def build_guide(
    geometry: GuideGeometry,
    out_dir: str | Path,
    screenshots: str | Path | None = None,
    *,
    src_prefix: str | None = None,
    title: str = "Board guide",
) -> list[Path]:
    """Write the index and one HTML per page that has a screenshot.

    Args:
        geometry: the extracted page/visual geometry.
        out_dir: the output directory (HTML is written here).
        screenshots: a local directory to discover `page_<stem>.png` in. Pages
            without a matching screenshot are skipped, so a partial capture
            still produces a usable guide.
        src_prefix: overrides the `<img src>` prefix (e.g. an `http://` base or
            a relative directory); when given, every page is emitted.
        title: the index title.

    Returns:
        The list of written paths (page files first, then the index).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, int]] = []
    saved: list[Path] = []

    stems = unique_stems(geometry.pages)
    for page, stem in zip(geometry.pages, stems, strict=True):
        if src_prefix:
            image: str | None = f"{src_prefix.rstrip('/')}/page_{stem}.png"
        else:
            image = _resolve_image(stem, screenshots)
        if not image:
            continue
        page_file = out / f"guide_{stem}.html"
        page_file.write_text(
            render_page_html(page, image, title=page.name), encoding="utf-8"
        )
        saved.append(page_file)
        rows.append((page.name, page_file.name, len(page.visuals)))

    index = out / "index.html"
    index.write_text(
        render_index_html(rows, geometry.source, title=title), encoding="utf-8"
    )
    saved.append(index)
    return saved


__all__ = [
    "build_guide",
    "render_index_html",
    "render_page_html",
    "visual_ref_html",
]
