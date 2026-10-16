"""Flowable builders for the lineage PDF report.

Builds the report body as reportlab flowables: the brand-book scorecard, the
flat lineage matrix (paginated automatically) and the list of elements
deviating from the brand book.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from agentic_bi.report.lineage_brand_cols import BRAND_LEVEL_LABEL
from agentic_bi.report.lineage_matrix import LEVEL

LEVEL_FILL = {
    "L1": "#D5E8D4",
    "L2": "#FFF9C4",
    "L3": "#C8E6C9",
    "L4": "#B3E5FC",
    "L5": "#D1C4E9",
    "L6": "#FFE0B2",
    "L7": "#F8BBD0",
}
_HEADER_BG = "#2C3E50"
_GRID = "#9AA5B1"

SUMMARY_COLS = [
    "Level",
    "Layer",
    "L1 · Origin",
    "L2 · Source",
    "L3 · Power Query",
    "L4 · Table",
    "L5 · Semantics",
    "L6 · Page",
    "Refs",
    "Brand · fonts, %",
    "Brand · colors, %",
    "Brand · status",
]
L7_COLS = [
    "Level",
    "Layer",
    "L7 · Visual",
    "L6 · Page",
    "Detail / Source",
    "Refs",
    "Brand · fonts, %",
    "Brand · colors, %",
    "Brand · status",
]

# Relative column widths (normalized to the printable width).
_SUMMARY_W = [1.0, 1.8, 2.6, 1.8, 1.8, 1.8, 1.8, 2.0, 1.0, 1.4, 1.4, 1.4]
_L7_W = [1.0, 1.8, 3.0, 2.0, 3.0, 1.0, 1.4, 1.4, 1.4]


def _esc(value) -> str:
    """Escape text for reportlab's mini-HTML paragraph parser."""
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cell(text, style, align="LEFT"):
    return Paragraph(_esc(text), style)


def brand_scorecard(data: dict, styles, content_w: float) -> list:
    """Brand-book summary: aggregate line + per-page table."""
    brand = data.get("brand") or {}
    summary = brand.get("summary") or {}
    pages = brand.get("pages") or {}
    if not summary and not pages:
        return []

    story: list = [
        Spacer(1, 6 * mm),
        Paragraph("Brand-book compliance", styles["Heading2"]),
    ]
    if summary:
        story.append(
            Paragraph(
                f"Pages: <b>{summary.get('pages', '')}</b> - "
                f"compliant: {summary.get('ok', 0)}, "
                f"warnings: {summary.get('warnings', 0)}, "
                f"violations: {summary.get('errors', 0)}, "
                f"no data: {summary.get('unknown', 0)}. "
                f"Averages: fonts <b>{summary.get('fonts_compliance')}%</b>, "
                f"colors <b>{summary.get('colors_compliance')}%</b>.",
                styles["Body"],
            )
        )
        story.append(Spacer(1, 3 * mm))

    if pages:
        head = ["Page", "Fonts, %", "Colors, %", "Red", "Status"]
        body = [[_cell(h, styles["CellHead"]) for h in head]]
        for name, m in pages.items():
            m = m or {}
            fnt = m.get("fonts", {}) or {}
            col = m.get("colors", {}) or {}
            fc, cc = fnt.get("compliance"), col.get("compliance")
            body.append(
                [
                    _cell(name, styles["Cell"]),
                    _cell(fc if fc is not None else "-", styles["Cell"], "CENTER"),
                    _cell(cc if cc is not None else "-", styles["Cell"], "CENTER"),
                    _cell(
                        "yes" if col.get("has_red") else "no", styles["Cell"], "CENTER"
                    ),
                    _cell(
                        BRAND_LEVEL_LABEL.get(m.get("level", ""), ""), styles["Cell"]
                    ),
                ]
            )
        widths = [
            content_w * 0.45,
            content_w * 0.13,
            content_w * 0.13,
            content_w * 0.10,
            content_w * 0.19,
        ]
        story.append(_styled_table(body, widths))
    return story


def brand_issues(data: dict, styles, content_w: float, limit: int = 60) -> list:
    """List visuals deviating from the brand book (localizes the violation)."""
    problems = []
    for p in data.get("pages", []) or []:
        pname = p.get("name", "?")
        for v in p.get("visuals", []) or []:
            b = v.get("brand") or {}
            if b.get("level") in ("warning", "error"):
                off = "; ".join(b.get("off", []) or []) or b.get("level", "")
                problems.append(
                    (pname, f"{v.get('type', '?')} z={v.get('z', '')}", off)
                )
    if not problems:
        return []

    story: list = [
        Spacer(1, 6 * mm),
        Paragraph(
            f"Elements deviating from the brand book ({len(problems)})",
            styles["Heading2"],
        ),
    ]
    body = [
        [_cell(h, styles["CellHead"]) for h in ("Page", "Element (visual)", "Notes")]
    ]
    for row in problems[:limit]:
        body.append(
            [
                _cell(row[0], styles["Cell"]),
                _cell(row[1], styles["Cell"]),
                _cell(row[2], styles["Cell"]),
            ]
        )
    widths = [content_w * 0.28, content_w * 0.30, content_w * 0.42]
    story.append(_styled_table(body, widths))
    if len(problems) > limit:
        story.append(
            Paragraph(
                f"... {len(problems) - limit} more elements (total {len(problems)})",
                styles["Body"],
            )
        )
    return story


def lineage_matrix(
    rows: list[dict], styles, content_w: float, max_level: int, include_visuals: bool
) -> list:
    """The flat level matrix as a paginating reportlab table."""
    visible = [
        r
        for r in rows
        if r["Level"] <= max_level and (include_visuals or r["Level"] < 7)
    ]
    use_l7 = include_visuals or max_level >= 7
    cols = L7_COLS if use_l7 else SUMMARY_COLS
    weights = _L7_W if use_l7 else _SUMMARY_W
    total_w = sum(weights)
    widths = [content_w * w / total_w for w in weights]

    body = [[_cell(c, styles["CellHead"]) for c in cols]]
    level_fill: list[tuple] = []
    for i, r in enumerate(visible, start=1):
        body.append([_cell(r.get(c, ""), styles["Cell"]) for c in cols])
        lvl_key = f"L{r['Level']}"
        fill = LEVEL_FILL.get(lvl_key)
        if fill:
            level_fill.append(("BACKGROUND", (0, i), (0, i), colors.HexColor(fill)))
            level_fill.append(("BACKGROUND", (1, i), (1, i), colors.HexColor(fill)))

    table = Table(body, colWidths=widths, repeatRows=1, splitByRow=1)
    style = _base_style() + level_fill
    table.setStyle(TableStyle(style))

    levels = sorted({r["Level"] for r in visible})
    level_names = ", ".join(LEVEL.get(lv, str(lv)) for lv in levels)
    story = [
        Spacer(1, 6 * mm),
        Paragraph("Flat lineage level matrix", styles["Heading2"]),
        Paragraph(
            f"Levels: {_esc(level_names)} | rows: {len(visible)}. "
            f"Generated automatically from the lineage JSON.",
            styles["Body"],
        ),
        Spacer(1, 3 * mm),
        table,
    ]
    return story


def _base_style() -> list[tuple]:
    return [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_HEADER_BG)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(_GRID)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]


def _styled_table(body: list, widths: list) -> Table:
    table = Table(body, colWidths=widths, repeatRows=1, splitByRow=1)
    table.setStyle(TableStyle(_base_style()))
    return table
