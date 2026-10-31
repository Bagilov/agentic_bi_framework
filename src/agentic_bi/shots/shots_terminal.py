"""Wrap captured console text into a terminal-style HTML card.

The wrapping and sizing happen in Python, not in the browser, so the output is
deterministic: the card is exactly as tall as its content and no line is ever
clipped, on any machine and any font available. A card shorter than Chromium's
minimum window height is padded to that floor (see `card_size`), because the
browser would otherwise clamp its layout viewport and drop the body.

`build_terminal_html` is pure (text in, HTML string out), so it is unit-testable
without a browser; `render_terminal_png` is the thin browser step and lives with
the rest of the rendering in `shots_render`.

Public API:
    BAR_HEIGHT, MAX_COLUMNS
    highlight_markers(text) -> str
    wrap(text, columns) -> list[str]
    build_terminal_html(text, ...) -> str
"""

from __future__ import annotations

import html
import re
import unicodedata

from agentic_bi.shots.shots_types import MIN_WINDOW_HEIGHT

BAR_HEIGHT = 44
PAD_X = 20
PAD_Y = 18
LINE_HEIGHT = 1.5
MAX_COLUMNS = 96
# Monospace advance width as a fraction of the font point size.
ADVANCE = 0.6
# A tab is expanded to this many cells when measuring display width.
_TAB_CELLS = 4

# Lines worth emphasising in a captured run: a passing gate, a verdict, a
# headline count. Kept as a constant so a new command's result line is added in
# one place instead of in every figure script.
DEFAULT_HIGHLIGHTS: tuple[str, ...] = (
    "All checks passed!",
    "already formatted",
    "passed",
    "pages=",
    "Total findings:",
    "ERRORS:",
    "exit code: 0",
    "EXITCODE=0",
)

_CSS = """* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #11161f;
       font-family: -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif; }}
.win {{ width: {width}px; background: #11161f; border-radius: 12px; overflow: hidden; }}
.bar {{ display: flex; align-items: center; gap: 8px; height: {bar}px; padding: 0 16px;
        background: #1b2230; border-bottom: 1px solid #263041; }}
.dot {{ width: 12px; height: 12px; border-radius: 50%; }}
.r {{ background: #ff5f57; }} .y {{ background: #febc2e; }} .g {{ background: #28c840; }}
.title {{ margin-left: 10px; color: #8b97ab; font: 500 13px/1 -apple-system, sans-serif;
          letter-spacing: .2px; }}
pre {{ margin: 0; padding: {pad_y}px {pad_x}px; color: #d6deeb;
       font: 400 {point}px/{lh} "SF Mono", "Menlo", "Monaco", monospace;
       tab-size: {tab}; -moz-tab-size: {tab}; white-space: pre; }}
.ok {{ color: #7ee787; font-weight: 600; }}
"""

_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<style>{css}</style>
<div class="win">
  <div class="bar">
    <span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
    <span class="title">{title}</span>
  </div>
  <pre>{body}</pre>
</div>
"""


def display_width(ch: str) -> int:
    """Columns a character occupies in a monospace cell (1, 2, or 0).

    The card is a monospace grid, and the browser positions a wide glyph over two
    cells and a zero-width mark over none. Counting `len()` instead would let a
    line of 88 CJK characters overflow the card and be clipped, so wrapping
    counts display cells, not code points.
    """
    if ch == "\t":
        return _TAB_CELLS
    if unicodedata.combining(ch) or ch in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def _cells(text: str) -> int:
    """The display width of `text` in monospace cells."""
    return sum(display_width(ch) for ch in text)


def _split_cells(text: str, budget: int) -> tuple[str, str]:
    """Split `text` so the first part fits in `budget` display cells."""
    used = 0
    for i, ch in enumerate(text):
        width = display_width(ch)
        if used + width > budget:
            return text[:i], text[i:]
        used += width
    return text, ""


def _wrap_line(line: str, columns: int) -> list[str]:
    """Wrap one logical line to `columns` cells, preserving its leading indent.

    The first line uses the full `columns`; every continuation is prefixed with
    the indent plus four spaces, and that prefix is part of the cell budget, so a
    continuation cannot itself overflow the card.
    """
    if _cells(line) <= columns:
        return [line]
    indent = len(line) - len(line.lstrip(" "))
    prefix = " " * min(indent + 4, max(0, columns - 8))
    out: list[str] = []
    current = line
    first = True
    while True:
        budget = columns if first else columns - len(prefix)
        head, rest = _split_cells(current, max(1, budget))
        if not head:  # a single wide glyph wider than the budget: keep it whole
            head, rest = current[:1], current[1:]
        if not rest:
            out.append(head if first else prefix + head)
            break
        out.append(head if first else prefix + head)
        current = rest
        first = False
    return out


def wrap(text: str, columns: int) -> list[str]:
    """Wrap every line of `text` to `columns` (capped at `MAX_COLUMNS`)."""
    columns = max(20, min(columns, MAX_COLUMNS))
    wrapped: list[str] = []
    for line in text.splitlines():
        wrapped.extend(_wrap_line(line, columns))
    return wrapped


def highlight_markers(body: str, markers: tuple[str, ...] = DEFAULT_HIGHLIGHTS) -> str:
    """Wrap every `markers` occurrence in `body` with the highlight span.

    The body must already be HTML-escaped; matching happens on the escaped text
    so a marker containing `<`/`&` still matches. All markers are applied in one
    left-to-right pass, longest first, so an inner marker that is also a
    substring of a longer one (``passed`` inside ``All checks passed!``) does not
    nest a span inside a span.
    """
    escaped = sorted({html.escape(m) for m in markers if m}, key=len, reverse=True)
    if not escaped or not body:
        return body
    pattern = re.compile("|".join(re.escape(m) for m in escaped))
    return pattern.sub(lambda m: f'<span class="ok">{m.group(0)}</span>', body)


def card_size(lines: list[str], point: int, columns: int) -> tuple[int, int]:
    """The exact pixel size of a card holding `lines` at `point` size.

    The width follows `columns` (the wrap width actually used), so a narrow run
    yields a narrow card; it is not pinned to `MAX_COLUMNS`.

    The height never falls below `MIN_WINDOW_HEIGHT`: Chromium clamps its layout
    viewport below that (so a shorter card would lose its body), and a card that
    wants to be shorter is padded with its own background instead.
    """
    width = int(PAD_X * 2 + columns * point * ADVANCE) + 2
    height = int(BAR_HEIGHT + PAD_Y * 2 + len(lines) * point * LINE_HEIGHT) + 2
    return width, max(height, MIN_WINDOW_HEIGHT)


def build_terminal_html(
    text: str,
    *,
    title: str = "terminal",
    columns: int = 88,
    point: int = 13,
    markers: tuple[str, ...] = DEFAULT_HIGHLIGHTS,
) -> tuple[str, int, int]:
    """Build the terminal card HTML and its exact pixel size.

    Args:
        text: the captured console output.
        title: the card's title-bar label.
        columns: wrap width (capped at `MAX_COLUMNS`).
        point: font point size.
        markers: substrings to emphasise.

    Returns:
        `(html, width, height)` — window size in CSS pixels for the browser.
    """
    columns = max(20, min(columns, MAX_COLUMNS))
    lines = wrap(text.rstrip("\n"), columns)
    width, height = card_size(lines, point, columns)
    body = highlight_markers(html.escape("\n".join(lines)), markers)
    css = _CSS.format(
        width=width,
        bar=BAR_HEIGHT,
        pad_x=PAD_X,
        pad_y=PAD_Y,
        point=point,
        lh=LINE_HEIGHT,
        tab=_TAB_CELLS,
    )
    return _TEMPLATE.format(css=css, title=html.escape(title), body=body), width, height


__all__ = [
    "ADVANCE",
    "BAR_HEIGHT",
    "DEFAULT_HIGHLIGHTS",
    "MAX_COLUMNS",
    "build_terminal_html",
    "card_size",
    "display_width",
    "highlight_markers",
    "wrap",
]
