"""Mock glyphs for Power BI visuals, used to draw the board layout clone.

The clone must *look like the original report*, not like an analysis page. Each
`visualType` is mapped to a category and then to an inline SVG glyph that stands
in for the real visual (which cannot be rendered without the engine). The SVG
uses ``viewBox`` + ``preserveAspectRatio="none"`` so it stretches to fill the
element's true box from `Report/Layout` (position and size are preserved).

Public API:
    category(visual_type) -> str
    mock_body(visual_type) -> str   (an HTML fragment with one inline <svg>)
"""

from __future__ import annotations

# visualType -> mock category
_CATEGORY: dict[str, str] = {
    "card": "card",
    "cardVisual": "card",
    "multiRowCard": "card",
    "kpi": "kpi",
    "gauge": "gauge",
    "slicer": "slicer",
    "tableEx": "table",
    "pivotTable": "matrix",
    "matrix": "matrix",
    "columnChart": "column",
    "clusteredColumnChart": "column",
    "stackedColumnChart": "column",
    "barChart": "bar",
    "stackedBarChart": "bar",
    "lineChart": "line",
    "areaChart": "area",
    "pieChart": "pie",
    "donutChart": "donut",
    "treemap": "treemap",
    "funnel": "funnel",
    "waterfallChart": "waterfall",
    "scatterChart": "scatter",
    "textbox": "text",
    "image": "image",
    "shape": "shape",
    "basicShape": "shape",
    "rectangle": "shape",
    "actionButton": "button",
    "pageNavigator": "nav",
    "bookmarkNavigator": "nav",
}

_A = 'fill="currentColor"'
_S = 'fill="none" stroke="currentColor" stroke-width="1.5"'

# body: a single inline <svg>; `o` = opacity variants keep glyphs light.
_BODY: dict[str, str] = {
    "card": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="10" y="20" width="46" height="12" rx="2" {_A} opacity="0.85"/>'
        f'<rect x="10" y="38" width="28" height="4" rx="2" {_A} opacity="0.35"/>'
        "</svg>"
    ),
    "kpi": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="10" y="16" width="40" height="12" rx="2" {_A} opacity="0.85"/>'
        f'<path d="M12 46 l8 -8 l6 5 l10 -12" {_S}/>'
        f'<path d="M36 31 l4 0 l0 4" {_S}/>'
        "</svg>"
    ),
    "gauge": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<path d="M15 50 A35 35 0 0 1 85 50" {_S}/>'
        f'<path d="M50 50 L74 30" stroke="currentColor" stroke-width="2"/>'
        f'<circle cx="50" cy="50" r="4" {_A}/>'
        "</svg>"
    ),
    "slicer": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="12" y="20" width="76" height="20" rx="3" {_S}/>'
        f'<rect x="18" y="28" width="34" height="4" rx="2" {_A} opacity="0.5"/>'
        f'<path d="M74 27 l5 6 l5 -6" {_S}/>'
        "</svg>"
    ),
    "table": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="8" y="10" width="84" height="10" {_A} opacity="0.22"/>'
        + "".join(
            f'<rect x="8" y="{24 + i * 8}" width="{84 - i * 6}" height="4" rx="2" '
            f'{_A} opacity="0.32"/>'
            for i in range(4)
        )
        + "</svg>"
    ),
    "matrix": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="8" y="10" width="84" height="8" {_A} opacity="0.28"/>'
        + "".join(
            f'<line x1="{8 + i * 17}" y1="10" x2="{8 + i * 17}" y2="52" {_S} '
            'opacity="0.5"/>'
            for i in range(1, 5)
        )
        + "".join(
            f'<line x1="8" y1="{18 + i * 8}" x2="92" y2="{18 + i * 8}" {_S} '
            'opacity="0.4"/>'
            for i in range(1, 5)
        )
        + "</svg>"
    ),
    "column": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<line x1="8" y1="52" x2="92" y2="52" {_S} opacity="0.5"/>'
        + "".join(
            f'<rect x="{14 + i * 17}" y="{52 - h}" width="11" height="{h}" '
            f'{_A} opacity="0.75"/>'
            for i, h in enumerate((26, 14, 34, 20))
        )
        + "</svg>"
    ),
    "bar": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        + "".join(
            f'<rect x="8" y="{8 + i * 11}" width="{w}" height="7" rx="2" '
            f'{_A} opacity="0.75"/>'
            for i, w in enumerate((70, 48, 84, 36))
        )
        + "</svg>"
    ),
    "line": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<line x1="8" y1="52" x2="92" y2="52" {_S} opacity="0.5"/>'
        f'<polyline points="10,44 26,30 42,38 58,18 74,26 90,12" {_S}'
        ' stroke-width="2"/>'
        "</svg>"
    ),
    "area": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<polygon points="10,44 26,30 42,38 58,18 74,26 90,12 90,52 10,52" '
        f'{_A} opacity="0.3"/>'
        f'<polyline points="10,44 26,30 42,38 58,18 74,26 90,12" {_S}'
        ' stroke-width="2"/>'
        "</svg>"
    ),
    "pie": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<circle cx="50" cy="30" r="22" {_A} opacity="0.75"/>'
        f'<path d="M50 30 L50 8 A22 22 0 0 1 70 40 Z" {_A} opacity="0.45"/>'
        "</svg>"
    ),
    "donut": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<circle cx="50" cy="30" r="22" {_A} opacity="0.55"/>'
        f'<circle cx="50" cy="30" r="11" fill="#0f1526"/>'
        "</svg>"
    ),
    "treemap": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="8" y="10" width="46" height="40" {_A} opacity="0.5"/>'
        f'<rect x="56" y="10" width="36" height="22" {_A} opacity="0.35"/>'
        f'<rect x="56" y="34" width="17" height="16" {_A} opacity="0.6"/>'
        f'<rect x="75" y="34" width="17" height="16" {_A} opacity="0.28"/>'
        "</svg>"
    ),
    "funnel": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="14" y="10" width="72" height="9" {_A} opacity="0.6"/>'
        f'<rect x="24" y="22" width="52" height="9" {_A} opacity="0.5"/>'
        f'<rect x="34" y="34" width="32" height="9" {_A} opacity="0.4"/>'
        f'<rect x="42" y="46" width="16" height="8" {_A} opacity="0.3"/>'
        "</svg>"
    ),
    "waterfall": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<line x1="8" y1="52" x2="92" y2="52" {_S} opacity="0.5"/>'
        f'<rect x="14" y="30" width="12" height="22" {_A} opacity="0.7"/>'
        f'<rect x="28" y="20" width="12" height="10" {_A} opacity="0.45"/>'
        f'<rect x="42" y="26" width="12" height="6" {_A} opacity="0.45"/>'
        f'<rect x="56" y="12" width="12" height="14" {_A} opacity="0.45"/>'
        f'<rect x="70" y="12" width="12" height="40" {_A} opacity="0.7"/>'
        "</svg>"
    ),
    "scatter": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<line x1="8" y1="52" x2="92" y2="52" {_S} opacity="0.5"/>'
        f'<line x1="8" y1="8" x2="8" y2="52" {_S} opacity="0.5"/>'
        + "".join(
            f'<circle cx="{x}" cy="{y}" r="3" {_A} opacity="0.7"/>'
            for x, y in ((22, 40), (34, 28), (46, 34), (58, 18), (70, 26), (82, 14))
        )
        + "</svg>"
    ),
    "text": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        + "".join(
            f'<rect x="10" y="{12 + i * 9}" width="{80 - (i % 2) * 30}" height="5" '
            f'rx="2" {_A} opacity="0.4"/>'
            for i in range(4)
        )
        + "</svg>"
    ),
    "image": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="8" y="10" width="84" height="40" rx="3" {_S} opacity="0.5"/>'
        f'<circle cx="30" cy="24" r="5" {_A} opacity="0.6"/>'
        f'<path d="M14 46 l20 -18 l14 12 l12 -10 l26 16 Z" {_A} opacity="0.5"/>'
        "</svg>"
    ),
    "shape": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="14" y="12" width="72" height="36" rx="4" {_A} opacity="0.18"/>'
        "</svg>"
    ),
    "button": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="18" y="18" width="64" height="24" rx="12" {_S} opacity="0.7"/>'
        f'<rect x="40" y="28" width="20" height="4" rx="2" {_A} opacity="0.5"/>'
        "</svg>"
    ),
    "nav": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        + "".join(
            f'<rect x="{10 + i * 22}" y="24" width="16" height="12" rx="3" {_A} '
            f'opacity="0.45"/>'
            for i in range(4)
        )
        + "</svg>"
    ),
    "unknown": (
        '<svg viewBox="0 0 100 60" preserveAspectRatio="none">'
        f'<rect x="10" y="12" width="80" height="36" rx="4" stroke-dasharray="4 3" '
        f'{_S} opacity="0.6"/>'
        f'<text x="50" y="38" text-anchor="middle" fill="currentColor" '
        'font-size="20" opacity="0.6">?</text>'
        "</svg>"
    ),
}


def category(visual_type: str) -> str:
    """Return the mock category for a `visualType` (or ``unknown``)."""
    return _CATEGORY.get(visual_type, "unknown")


def mock_body(visual_type: str) -> str:
    """Return the inline-SVG mock for a `visualType`."""
    return _BODY.get(category(visual_type), _BODY["unknown"])
