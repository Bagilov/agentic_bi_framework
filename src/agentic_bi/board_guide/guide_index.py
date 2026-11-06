"""Render the guide index: one link per page, skips and warnings explained.

The index is the entry point of a guide directory. It must never be a blank
document: a guide with no usable screenshot says which `page_<stem>.png` files
it expected, and a page whose screenshot can shift the hotspots carries a
warning instead of disappearing silently.

Public API:
    render_index_html(rows, source, ...) -> str
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from agentic_bi.board_guide.guide_assets import INDEX_CSS


def _e(value: object) -> str:
    """Escape text for an HTML text node or a quoted attribute."""
    return html.escape(str(value if value is not None else ""), quote=True)


def render_index_html(
    rows: list[tuple[str, str, int]],
    source: str,
    *,
    title: str = "Board guide",
    skipped: Sequence[tuple[str, str]] = (),
    warnings: Sequence[tuple[str, str]] = (),
) -> str:
    """Render the index: one link per generated page, skips explained.

    Args:
        rows: `(page name, href, visual count)` for every written page.
        source: the `.pbix` the geometry came from.
        title: the index title.
        skipped: `(page name, reason)` for pages that had no usable screenshot.
        warnings: `(page name, message)` for usable pages whose screenshot can
            shift the hotspots (an aspect-ratio mismatch); the page is still
            written, so this is a warning rather than a skip.

    A guide with no usable page is not a blank document: it says so and lists
    exactly which `page_<stem>.png` files it expected.
    """
    items = "".join(
        f'<li><a href="{_e(href)}">{_e(name)}</a>'
        f'<span class="meta">визуалов: {count}</span></li>'
        for name, href, count in rows
    )
    if rows:
        body = f"<ol>{items}</ol>"
    else:
        body = (
            '<p class="empty">В гайде нет ни одного листа с '
            "изображением. Положите скриншоты рядом с гайдом как "
            "<code>page_&lt;stem&gt;.png</code> (stem — из списка ниже) и "
            "пересоберите гайд.</p>"
        )
    skipped_html = ""
    if skipped:
        lines = "".join(
            f"<li><b>{_e(name)}</b> — {_e(reason)}</li>" for name, reason in skipped
        )
        skipped_html = (
            f'<section class="skipped"><h2>Пропущено листов: {len(skipped)}</h2>'
            f"<ul>{lines}</ul></section>"
        )
    warnings_html = ""
    if warnings:
        lines = "".join(
            f"<li><b>{_e(name)}</b> — {_e(message)}</li>" for name, message in warnings
        )
        warnings_html = (
            f'<section class="skipped"><h2>Предупреждения: {len(warnings)}</h2>'
            f"<ul>{lines}</ul></section>"
        )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(title)}</title>
<style>{INDEX_CSS}</style></head>
<body>
<h1>{_e(title)}</h1>
<div class="sub">{_e(source)} · листов: {len(rows)}</div>
{body}
{skipped_html}
{warnings_html}
</body></html>
"""


__all__ = ["render_index_html"]
