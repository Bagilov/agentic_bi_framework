"""Render a board guide page: the screenshot plus annotated hotspots.

Geometry comes from `guide_geometry`; the picture is an external file (`page_<stem>.png`
next to the HTML, or any `src` prefix). Each visual becomes an absolutely
positioned hotspot expressed in canvas percentages, so the overlay is correct at
any screenshot scale — the layout canvas is scaled to fit the image, which keeps
its aspect ratio. `guide_build` decides which pages to write and where.

Public API:
    render_page_html(page, image, ...) -> str
    render_index_html(rows, source, ...) -> str
    visual_ref_html(visual, overlaps=()) -> str
"""

from __future__ import annotations

import html
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass

from agentic_bi.board_guide.guide_assets import PAGE_CSS, PAGE_JS
from agentic_bi.board_guide.guide_geometry import GuidePage, GuideVisual
from agentic_bi.board_guide.guide_hotspots import (
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    Box,
    is_visible,
    overlap_pairs,
    paint_order,
)
from agentic_bi.board_guide.guide_index import render_index_html
from agentic_bi.board_guide.guide_print import print_list_html

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

_HINT = "Наведите курсор на визуал — появится справка."
_EMPTY_HINT = "На этом листе нет визуалов, поэтому справки нет."


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


def visual_ref_html(visual: GuideVisual, *, overlaps: Sequence[int] = ()) -> str:
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
    if overlaps:
        who = ", ".join(f"#{i + 1}" for i in sorted(overlaps))
        parts.append(
            f'<div class="voverlap">Перекрывается с визуалом {who}: '
            "наведите его отдельно, подписи не совпадают.</div>"
        )
    return "".join(parts)


def _label_place(box: Box) -> str:
    """Where the hover label goes so it never sits on the hotspot's own text.

    A box with room inside keeps its label there; a thin or tiny hotspot puts
    the label outside — above when there is canvas above it, else below — so the
    label is readable instead of overflowing a two-pixel target.
    """
    if box["width"] >= 14.0 and box["height"] >= 10.0:
        return ""
    return " label-above" if box["top"] >= 8.0 else " label-below"


@dataclass(frozen=True)
class HotspotLayout:
    """Rendered hotspots plus what the panel needs to explain them."""

    html: str
    overlaps: dict[int, tuple[int, ...]]
    visible: int
    indices: tuple[int, ...] = ()
    dropped: int = 0


def hotspot_layout(page: GuidePage) -> HotspotLayout:
    """Place every visible hotspot and record which ones share area.

    Invisible boxes (off-canvas, zero-size) are dropped instead of being pinned
    to an edge; `dropped` counts them so the page can say how many visuals are
    missing instead of losing them silently. Visible ones are painted
    large-first, so a small visual nested in a large one stays on top and keeps
    its hover and label.
    """
    boxes = [visual.hotspot(page.width, page.height) for visual in page.visuals]
    visible = [i for i, box in enumerate(boxes) if is_visible(box)]
    if not visible:
        return HotspotLayout("", {}, 0, (), len(page.visuals))
    subset = [boxes[i] for i in visible]
    shared: dict[int, list[int]] = {i: [] for i in visible}
    for a, b in overlap_pairs(subset):
        shared[visible[a]].append(visible[b])
        shared[visible[b]].append(visible[a])
    parts: list[str] = []
    for position in paint_order(subset):
        index = visible[position]
        box = boxes[index]
        label = page.visuals[index].label
        flags = " overlap" if shared[index] else ""
        style = (
            f"left:{box['left']:.2f}%;top:{box['top']:.2f}%;"
            f"width:{box['width']:.2f}%;height:{box['height']:.2f}%"
        )
        parts.append(
            f'<div class="hot{flags}{_label_place(box)}" data-i="{index}" '
            f'role="button" tabindex="0" aria-label="#{index + 1} {_e(label)}" '
            f'title="{_e(label)}" style="{style}">'
            f'<span class="hotlabel">#{index + 1} {_e(label)}</span></div>'
        )
    overlaps = {key: tuple(value) for key, value in shared.items() if value}
    return HotspotLayout(
        "".join(parts),
        overlaps,
        len(visible),
        tuple(visible),
        len(page.visuals) - len(visible),
    )


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
            An empty value renders an explicit empty state, never `<img src="">`.
        title: the heading; defaults to the page name.
        index_href: the "back to index" link target.

    Returns:
        A self-contained HTML document string.
    """
    layout = hotspot_layout(page)
    refs = _json_for_script(
        [
            f"<b>Визуал #{i + 1}: {_e(v.label)}</b><hr>"
            f"{visual_ref_html(v, overlaps=layout.overlaps.get(i, ()))}"
            for i, v in enumerate(page.visuals)
        ]
    )
    heading = title or page.name
    canvas_w = _canvas_px(page.width, DEFAULT_CANVAS_WIDTH)
    canvas_h = _canvas_px(page.height, DEFAULT_CANVAS_HEIGHT)
    if image.strip():
        media = f'<img src="{_e(image)}" alt="{_e(heading)}">{layout.html}'
    else:
        media = (
            '<div class="noimg">Изображение страницы не найдено: '
            "скриншот не передан, поэтому hotspots не строятся.</div>"
        )
    note = ""
    if not page.visuals:
        note = (
            '<div class="empty">На этой странице нет визуалов: '
            "в Report/Layout для листа нет визуальных контейнеров.</div>"
        )
    elif layout.visible == 0:
        note = (
            '<div class="empty">Ни один визуал не попадает в '
            "границы канваса, поэтому показать нечего.</div>"
        )
    dropped = f" · вне канваса {layout.dropped}" if layout.dropped else ""
    hint = _HINT if page.visuals else _EMPTY_HINT
    action = "наведите/кликните на визуал" if page.visuals else "справки нет"
    printed = print_list_html(page, layout.indices)
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
    визуалов {len(page.visuals)}{dropped} · {action}</span>
</header>
<div class="stage">
  <div class="imgwrap">
    {media}
  </div>
  {note}
  {printed}
</div>
<div class="panel" id="panel" aria-live="polite">
  <span class="hint">{hint}</span>
</div>
<script>window.__GUIDE_REFS__ = {refs};</script>
<script>{PAGE_JS}</script>
</body></html>
"""


__all__ = [
    "HotspotLayout",
    "hotspot_layout",
    "render_index_html",
    "render_page_html",
    "visual_ref_html",
]
