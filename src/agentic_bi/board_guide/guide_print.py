"""Printed companion list for a board guide page (stdlib only).

On screen a hotspot carries its help in the side panel on hover. On paper there
is no hover, the hover label is hidden and the panel becomes one block after the
image, so the numbered boxes on the screenshot would lead nowhere. This module
renders a plain list `#N -> type/fields/measures` that is hidden on screen and
shown only by the print stylesheet.

Public API:
    print_list_html(page, indices) -> str
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from agentic_bi.board_guide.guide_geometry import GuidePage


def _e(value: object) -> str:
    """Escape text for an HTML text node or a quoted attribute."""
    return html.escape(str(value if value is not None else ""), quote=True)


def _details(index: int, page: GuidePage) -> str:
    """One visual's printed line: type, projected fields, measures, filters."""
    visual = page.visuals[index]
    parts: list[str] = []
    if visual.fields:
        parts.append("поля: " + ", ".join(visual.fields[:12]))
    if visual.measures:
        parts.append("меры: " + ", ".join(visual.measures))
    if visual.filters:
        parts.append("фильтры: " + "; ".join(visual.filters))
    body = "; ".join(parts) if parts else "статический элемент"
    return f"<li><b>#{index + 1} {_e(visual.visual_type)}</b> — {_e(body)}</li>"


def print_list_html(page: GuidePage, indices: Sequence[int]) -> str:
    """The printed legend for every visible hotspot, or an empty string.

    Args:
        page: the page whose visuals are annotated.
        indices: visual indices that actually have a rendered hotspot, in the
            same order the hotspot labels use.

    Returns:
        A `<section class="printlist">` hidden on screen; `""` when no hotspot
        is rendered (there is then nothing for a printed number to point at).
    """
    if not indices:
        return ""
    items = "".join(_details(index, page) for index in indices)
    return (
        '<section class="printlist"><h2>Визуалы на листе</h2>'
        f"<ol>{items}</ol></section>"
    )


__all__ = ["print_list_html"]
