"""Flowable builders for the lineage PDF report.

Builds the report body as reportlab flowables: the brand-book scorecard, the
flat lineage matrix (paginated automatically) and the list of elements
deviating from the brand book.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from agentic_bi.report.lineage_brand_cols import (
    BRAND_LEVEL_LABEL,
    as_list,
    as_mapping,
    as_rows,
)
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
    """Brand-book summary: aggregate line + per-page table.

    Every block comes from the untrusted lineage document, so a list-typed
    `brand`, `summary` or `pages` degrades to "no scorecard" instead of raising,
    and each value is escaped before it is interpolated into reportlab markup.
    """
    data = as_mapping(data)
    brand = as_mapping(data.get("brand"))
    summary = as_mapping(brand.get("summary"))
    pages = as_mapping(brand.get("pages"))
    if not summary and not pages:
        return []

    story: list = [
        Spacer(1, 6 * mm),
        Paragraph("Brand-book compliance", styles["Heading2"]),
    ]
    if summary:
        story.append(
            Paragraph(
                f"Pages: <b>{_esc(summary.get('pages', ''))}</b> - "
                f"compliant: {_esc(summary.get('ok', 0))}, "
                f"warnings: {_esc(summary.get('warnings', 0))}, "
                f"violations: {_esc(summary.get('errors', 0))}, "
                f"no data: {_esc(summary.get('unknown', 0))}. "
                f"Averages: fonts <b>{_pct_or_na(summary.get('fonts_compliance'))}</b>, "
                f"colors <b>{_pct_or_na(summary.get('colors_compliance'))}</b>.",
                styles["Body"],
            )
        )
        story.append(Spacer(1, 3 * mm))

    if pages:
        head = ["Page", "Fonts, %", "Colors, %", "Red", "Status"]
        body = [[_cell(h, styles["CellHead"]) for h in head]]
        for name, m in pages.items():
            m = as_mapping(m)
            fnt = as_mapping(m.get("fonts"))
            col = as_mapping(m.get("colors"))
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
    for p in as_rows(data.get("pages")):
        pname = p.get("name", "?")
        for v in as_rows(p.get("visuals")):
            b = as_mapping(v.get("brand"))
            if b.get("level") in ("warning", "error"):
                off = "; ".join(str(item) for item in as_list(b.get("off"))) or b.get(
                    "level", ""
                )
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


def _matrix_table(
    cols: list[str], weights: list[float], rows: list[dict], styles, content_w: float
) -> Table:
    """One matrix page set for a fixed column layout."""
    total_w = sum(weights)
    widths = [content_w * w / total_w for w in weights]
    body = [[_cell(c, styles["CellHead"]) for c in cols]]
    level_fill: list[tuple] = []
    for i, r in enumerate(rows, start=1):
        body.append([_cell(r.get(c, ""), styles["Cell"]) for c in cols])
        fill = LEVEL_FILL.get(f"L{r['Level']}")
        if fill:
            level_fill.append(("BACKGROUND", (0, i), (0, i), colors.HexColor(fill)))
            level_fill.append(("BACKGROUND", (1, i), (1, i), colors.HexColor(fill)))
    table = Table(body, colWidths=widths, repeatRows=1, splitByRow=1)
    table.setStyle(TableStyle(_base_style() + level_fill))
    return table


def _pct_or_na(value: object) -> str:
    """A percentage for the summary line, or `n/a` when nothing was measured.

    `fonts_compliance`/`colors_compliance` are `None` when no page carries the
    data (a theme-only board has no readable colours yet), and interpolating the
    `None` printed "Averages: fonts None%" in the shipped PDF.
    """
    if value is None or value == "":
        return "n/a"
    return f"{_esc(value)}%"


def lineage_matrix(
    rows: list[dict], styles, content_w: float, max_level: int, include_visuals: bool
) -> list:
    """The flat level matrix, one table per column layout.

    `SUMMARY_COLS` names the L1-L6 identity columns (origin, source, table,
    semantics); `L7_COLS` names the visual's own columns. The previous version
    picked **one** layout for the whole matrix (`include_visuals or max_level >=
    7`, true for every default CLI run), so every L1-L5 row was printed through
    `L7_COLS`: the origin/source/table/semantics cells vanished and the summary
    layout was unreachable dead code. Splitting by level keeps both: the identity
    rows keep their columns and the visual rows keep theirs.
    """
    visible = [
        r
        for r in rows
        if r["Level"] <= max_level and (include_visuals or r["Level"] < 7)
    ]
    if not visible:
        return []
    identity = [r for r in visible if r["Level"] < 7]
    visuals = [r for r in visible if r["Level"] == 7]
    levels = sorted({r["Level"] for r in visible})
    level_names = ", ".join(LEVEL.get(lv, str(lv)) for lv in levels)
    story: list = [
        Spacer(1, 6 * mm),
        Paragraph("Flat lineage level matrix", styles["Heading2"]),
        Paragraph(
            f"Levels: {_esc(level_names)} | rows: {len(visible)}. "
            f"Generated automatically from the lineage JSON.",
            styles["Body"],
        ),
        Spacer(1, 3 * mm),
    ]
    if identity:
        story.append(
            _matrix_table(SUMMARY_COLS, _SUMMARY_W, identity, styles, content_w)
        )
    if visuals:
        if identity:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Visuals (level 7)", styles["Heading2"]))
        story.append(_matrix_table(L7_COLS, _L7_W, visuals, styles, content_w))
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
