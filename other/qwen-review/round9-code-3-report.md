# Bundle 3: report

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/report/__init__.py ====================

"""Multi-page PDF lineage report: diagram + flat matrix + brand audit.

The subpackage turns a ``PbiLineage.to_json()`` dict into a printable PDF. It is
environment-agnostic and consumes the lineage model already shipped in
``agentic_bi.lineage``.

Public API:
    - :func:`lineage_to_table` - flat level matrix rows
    - :class:`LineageTable` - dataframe + Excel export of the matrix
    - :func:`build_report` - assemble and write the multi-page PDF
    - :func:`validate_text`, :func:`render_png` - PlantUML validation/rendering

The PDF builder needs the ``report`` optional extra (reportlab, Pillow); the
matrix and PlantUML helpers only need the standard library (Excel needs pandas).
"""

from agentic_bi.report.lineage_brand_cols import BRAND_LEVEL_LABEL
from agentic_bi.report.lineage_matrix import COLUMNS, LEVEL, lineage_to_table
from agentic_bi.report.lineage_table import LineageTable, load_json
from agentic_bi.report.plantuml_tools import (
    find_plantuml_jar,
    render_png,
    validate_file,
    validate_text,
)


def build_report(*args, **kwargs):
    """Build the multi-page PDF report (lazy: needs the ``report`` extra)."""
    from agentic_bi.report.pdf_report import build_report as _build

    return _build(*args, **kwargs)


__all__ = [
    "BRAND_LEVEL_LABEL",
    "COLUMNS",
    "LEVEL",
    "LineageTable",
    "build_report",
    "find_plantuml_jar",
    "lineage_to_table",
    "load_json",
    "render_png",
    "validate_file",
    "validate_text",
]

==================== FILE: src/agentic_bi/report/lineage_matrix.py ====================

"""Flat level matrix of data lineage built from ``PbiLineage.to_json()``.

Every row is a single node of one of the seven lineage levels:

    1 · Origin -> 2 · Source -> 3 · Power Query -> 4 · Table
    -> 5 · Semantics -> 6 · Page -> 7 · Visual

Levels are unfolded into dedicated columns (``L1..L7``), so they stay visible
and can be filtered/sorted. Links between levels are exposed through the
``Parent`` / ``Came from`` / ``Goes to`` columns.

The output is a plain ``list[dict]`` and is intentionally renderer-agnostic:
the PDF report and the Excel export both consume it.
"""

from __future__ import annotations

from agentic_bi.lineage.lineage_origins import ORIGIN_STAGE_LABEL
from agentic_bi.report.lineage_brand_cols import (
    brand_row,
    page_brand_index,
    visual_brand_row,
)

LEVEL = {
    1: "1 · Origin",
    2: "2 · Source",
    3: "3 · Power Query",
    4: "4 · Table",
    5: "5 · Semantics",
    6: "6 · Page",
    7: "7 · Visual",
}

COLUMNS = [
    "Level",
    "Layer",
    "L1 · Origin",
    "L2 · Source",
    "L3 · Power Query",
    "L4 · Table",
    "L5 · Semantics",
    "L6 · Page",
    "L7 · Visual",
    "Parent",
    "Type",
    "Detail / Source",
    "Refs",
    "Came from",
    "Goes to",
    "Brand · fonts, %",
    "Brand · colors, %",
    "Brand · status",
    "Brand · notes",
]


def _blank_row(level: int) -> dict:
    """A row skeleton for a given level with all level columns empty."""
    row = {c: "" for c in COLUMNS}
    row["Level"] = level
    row["Layer"] = LEVEL[level]
    return row


def lineage_to_table(data: dict) -> list[dict]:
    """Unfold lineage JSON into flat rows (one node per row), levels 1 -> 7.

    Args:
        data: a dict in the ``PbiLineage.to_json()`` structure.

    Returns:
        List of row dicts keyed by :data:`COLUMNS`.
    """
    rows: list[dict] = []
    tables = data.get("tables", {})
    pages = data.get("pages", [])
    sources = data.get("sources", {})
    semantics = data.get("semantics", {})
    origin = data.get("origin", {})
    src_by_table = sources.get("by_table", {})

    # map "source table -> origin label" (level 1 -> level 2)
    src_to_origin: dict[str, str] = {}
    for it in origin.get("items", []):
        olabel = it.get("label") or it.get("key") or "?"
        for tbl in it.get("tables", []) or []:
            src_to_origin[tbl] = olabel

    def _sem_label(tbl: str) -> str:
        sem = semantics.get(tbl)
        if not sem:
            return tbl
        parts = []
        nm = len(sem.get("measures", []))
        nc = len(sem.get("calc_columns", []))
        if nm:
            parts.append(f"{nm} measures")
        if nc:
            parts.append(f"{nc} cols")
        return f"{tbl}: {', '.join(parts)}" if parts else tbl

    # === LEVEL 1: ORIGIN ===
    for it in origin.get("items", []):
        okey = it.get("key", "")
        olabel = it.get("label") or okey
        cat = it.get("category", "origin-unknown")
        otables = it.get("tables", []) or []
        stages = it.get("stages", []) or []
        chain = " -> ".join(
            f"{ORIGIN_STAGE_LABEL.get(s.get('stage'), s.get('stage'))}: {s.get('label')}"
            for s in stages
        )
        n_targets = sum(1 for t in otables if t in src_by_table)
        detail = it.get("detail") or ""
        if chain:
            detail = f"{chain}\n{detail}" if detail else chain
        row = _blank_row(1)
        row.update(
            {
                "L1 · Origin": olabel,
                "Type": cat,
                "Detail / Source": detail,
                "Refs": n_targets,
                "Goes to": ", ".join(t for t in otables if t in src_by_table),
            }
        )
        rows.append(row)

    # === LEVEL 2: SOURCES ===
    for tbl, s in src_by_table.items():
        refs = tables.get(tbl, {}).get("refs", 0)
        row = _blank_row(2)
        row.update(
            {
                "L1 · Origin": src_to_origin.get(tbl, ""),
                "L2 · Source": tbl,
                "Parent": src_to_origin.get(tbl, ""),
                "Type": s.get("type", ""),
                "Detail / Source": s.get("detail", ""),
                "Refs": refs,
                "Came from": src_to_origin.get(tbl, ""),
                "Goes to": (
                    f"M-query {tbl}"
                    if tables.get(tbl, {}).get("has_power_query")
                    else f"Table {tbl}"
                ),
            }
        )
        rows.append(row)

    # === LEVEL 3: POWER QUERY ===
    for tbl in sorted(t for t, tv in tables.items() if tv.get("has_power_query")):
        refs = tables.get(tbl, {}).get("refs", 0)
        row = _blank_row(3)
        row.update(
            {
                "L2 · Source": tbl,
                "L3 · Power Query": f"M-query {tbl}",
                "Parent": tbl,
                "Type": "Power Query",
                "Refs": refs,
                "Came from": f"Source {tbl}",
                "Goes to": f"Table {tbl}",
            }
        )
        rows.append(row)

    # === LEVEL 4: MODEL TABLES ===
    for tbl, tv in tables.items():
        if tv.get("technical"):
            continue
        src = tv.get("source", {})
        detail_parts = []
        cols = tv.get("columns_count", 0)
        meas = tv.get("measures_count", 0)
        ncalc = tv.get("calc_columns_count", 0)
        if cols:
            detail_parts.append(f"{cols} cols")
        if meas:
            detail_parts.append(f"{meas} measures")
        if ncalc:
            detail_parts.append(f"{ncalc} calc")
        row = _blank_row(4)
        row.update(
            {
                "L2 · Source": tbl,
                "L3 · Power Query": f"M-query {tbl}"
                if tv.get("has_power_query")
                else "",
                "L4 · Table": tbl,
                "Parent": f"M-query {tbl}" if tv.get("has_power_query") else "",
                "Type": src.get("type") or "business",
                "Detail / Source": src.get("detail") or ", ".join(detail_parts),
                "Refs": tv.get("refs", 0),
                "Came from": (
                    f"M-query {tbl}" if tv.get("has_power_query") else f"Source {tbl}"
                ),
                "Goes to": _sem_label(tbl) if semantics.get(tbl) else "",
            }
        )
        rows.append(row)

    # === LEVEL 5: SEMANTICS ===
    for tbl, sem in semantics.items():
        nm = len(sem.get("measures", []))
        nc = len(sem.get("calc_columns", []))
        using_pages = [p["name"] for p in pages if tbl in p.get("tables", [])]
        row = _blank_row(5)
        row.update(
            {
                "L2 · Source": tbl,
                "L4 · Table": tbl,
                "L5 · Semantics": _sem_label(tbl),
                "Parent": tbl,
                "Type": f"{nm} measures / {nc} calc" if (nm or nc) else "semantics",
                "Refs": sem.get("table_refs", 0),
                "Came from": f"Table {tbl}",
                "Goes to": ", ".join(using_pages) if using_pages else "",
            }
        )
        rows.append(row)

    # === LEVEL 6: PAGES ===
    for p in pages:
        name = p["name"]
        tables_on_page = p.get("tables", [])
        n_vis = p.get("n_visuals", 0)
        from_label = (
            ", ".join(_sem_label(t) for t in tables_on_page) if tables_on_page else ""
        )
        row = _blank_row(6)
        row.update(
            {
                "L6 · Page": name,
                "Parent": from_label,
                "Type": f"{n_vis} visuals" if n_vis else "page",
                "Detail / Source": ", ".join(tables_on_page),
                "Refs": p.get("refs", 0),
                "Came from": from_label,
                "Goes to": f"visuals ({n_vis})" if n_vis else "",
            }
        )
        rows.append(row)

    # === LEVEL 7: VISUALS ===
    for p in pages:
        for vis in p.get("visuals", []):
            vtype = vis.get("type", "?")
            z = vis.get("z", "")
            bindings = "; ".join(
                f"{b.get('role')}={b.get('queryRef')}" for b in vis.get("bindings", [])
            )
            colors = len(vis.get("colors", []))
            row = _blank_row(7)
            row.update(
                {
                    "L6 · Page": p["name"],
                    "L7 · Visual": f"{p['name']} · {vtype} z={z}",
                    "Parent": p["name"] if p.get("visuals") else "",
                    "Type": vtype,
                    "Detail / Source": bindings,
                    "Refs": vis.get("n_bindings", 0),
                    "Came from": ", ".join(p.get("tables", [])),
                    "Goes to": f"{colors} colors" if colors else "",
                }
            )
            if vis.get("brand"):
                row.update(visual_brand_row(vis))
            rows.append(row)

    # === RIGHT SIDE: brand compliance metrics ===
    brand_index = page_brand_index(data)
    if brand_index:
        empty = brand_row(None)
        for r in rows:
            if r.get("Level") == 7 and r.get("L7 · Visual"):
                continue  # keep element metrics, do not overwrite with page metrics
            metrics = brand_index.get(r.get("L6 · Page", ""))
            r.update(brand_row(metrics) if metrics else empty)
        summary = (data.get("brand") or {}).get("summary", {})
        if summary and rows:
            base = rows[0]
            fc, cc = summary.get("fonts_compliance"), summary.get("colors_compliance")
            base["Brand · fonts, %"] = fc if fc is not None else ""
            base["Brand · colors, %"] = cc if cc is not None else ""
            base["Brand · status"] = (
                "violations"
                if summary.get("errors")
                else ("warnings" if summary.get("warnings") else "compliant")
            )
            base["Brand · notes"] = (
                f"pages with deviations: {len(summary.get('off_brand_pages', []))}"
            )

    return rows

==================== FILE: src/agentic_bi/report/lineage_table.py ====================

"""Excel view of the flat lineage matrix.

Consumes the rows produced by :func:`agentic_bi.report.lineage_matrix.lineage_to_table`
and renders an xlsx workbook with three sheets:

    Lineage  - the full matrix (autofilter, per-level cell palette)
    Summary  - node counters per level/type + brand-book summary
    Columns  - static documentation of the matrix format

Requires ``pandas`` and ``openpyxl`` (the ``report`` optional extra).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_bi.report.lineage_matrix import COLUMNS, lineage_to_table

# Light fill per level, used for the Excel line palette.
LEVEL_COLORS = {
    "L1": "D5E8D4",
    "L2": "FFF9C4",
    "L3": "C8E6C9",
    "L4": "B3E5FC",
    "L5": "D1C4E9",
    "L6": "FFE0B2",
    "L7": "F8BBD0",
}

_COLUMN_WIDTH = {
    "Level": 6,
    "Layer": 18,
    "L1 · Origin": 30,
    "L2 · Source": 20,
    "L3 · Power Query": 22,
    "L4 · Table": 20,
    "L5 · Semantics": 22,
    "L6 · Page": 26,
    "L7 · Visual": 30,
    "Parent": 26,
    "Type": 20,
    "Detail / Source": 40,
    "Refs": 14,
    "Came from": 26,
    "Goes to": 26,
    "Brand · fonts, %": 18,
    "Brand · colors, %": 17,
    "Brand · status": 18,
    "Brand · notes": 36,
}


class LineageTable:
    """Flat lineage matrix from a ``PbiLineage.to_json()`` dict.

    Args:
        data: dict in the ``PbiLineage.to_json()`` structure.
    """

    def __init__(self, data: dict):
        self.data = data
        self.rows = lineage_to_table(data)

    @property
    def dataframe(self):
        """The matrix as a pandas DataFrame (lazy import)."""
        import pandas as pd

        return pd.DataFrame(self.rows, columns=COLUMNS).fillna("")

    @property
    def summary(self) -> dict:
        """Node counters per level/type plus the brand-book summary."""
        df = self.dataframe
        return {
            "nodes": len(df),
            "by_level": df.groupby("Layer").size().to_dict(),
            "by_type": df["Type"].value_counts().to_dict(),
            "with_refs": int((df["Refs"] > 0).sum()),
            "orphans": [
                r for r in self.rows if not r.get("Came from") and r.get("Level", 0) > 1
            ],
            "brand": (self.data.get("brand") or {}).get("summary", {}),
        }

    def to_excel(self, out_path: str | Path) -> Path:
        """Save the matrix to xlsx (Lineage + Summary + Columns)."""
        import pandas as pd
        from openpyxl.styles import Font, PatternFill

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df = self.dataframe

        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Lineage", index=False)
            wb = writer.book
            ws = wb["Lineage"]

            for cell in ws[1]:
                cell.fill = PatternFill(
                    start_color="2C3E50", end_color="2C3E50", fill_type="solid"
                )
                cell.font = Font(color="FFFFFF", bold=True)
            for col in ws.columns:
                header = col[0].value
                ws.column_dimensions[col[0].column_letter].width = _COLUMN_WIDTH.get(
                    header, 14
                )
            ws.auto_filter.ref = ws.dimensions

            header_to_col = {h: i for i, h in enumerate(COLUMNS, start=1)}
            fill_by_col = {
                "L1 · Origin": "L1",
                "L2 · Source": "L2",
                "L3 · Power Query": "L3",
                "L4 · Table": "L4",
                "L5 · Semantics": "L5",
                "L6 · Page": "L6",
                "L7 · Visual": "L7",
            }
            for row in ws.iter_rows(min_row=2):
                for header, key in fill_by_col.items():
                    cell = row[header_to_col[header] - 1]
                    if cell.value:
                        cell.fill = PatternFill(
                            start_color=LEVEL_COLORS[key],
                            end_color=LEVEL_COLORS[key],
                            fill_type="solid",
                        )

            self._write_summary_sheet(wb, self.summary)
            self._write_columns_sheet(wb)
        return out

    @staticmethod
    def _write_columns_sheet(wb) -> None:
        """Document the matrix format (Column / Description / Source)."""
        rows = [
            ["Lineage matrix format"],
            [],
            ["Column", "Description", "Source"],
            ["Level", "Lineage layer number (1-7)", "computed"],
            [
                "Layer",
                "Layer name (Origin/Source/Power Query/Table/Semantics/Page/Visual)",
                "LEVEL",
            ],
            ["L1..L7", "Node of the matching layer (one per row)", "lineage JSON"],
            ["Parent", "Node one layer above", "layer links"],
            ["Type", "Node type (origin category/source/visual type)", "lineage JSON"],
            [
                "Detail / Source",
                "Path/DSN/columns/measures or bindings",
                "lineage JSON",
            ],
            ["Refs", "How many times the node is used in visuals", "lineage JSON refs"],
            ["Came from", "Input node (layer N-1)", "layer links"],
            ["Goes to", "Output node (layer N+1)", "layer links"],
            [
                "Brand · fonts, %",
                "Brand-font compliance of the page/visual",
                "brand block",
            ],
            ["Brand · colors, %", "Brand-palette color compliance", "brand block"],
            [
                "Brand · status",
                "compliant / warnings / violation / no data",
                "brand block",
            ],
            [
                "Brand · notes",
                "Deviations: off-brand fonts/colors, missing brand red",
                "brand block",
            ],
            [],
            [
                "Note: level 7 rows carry element metrics, level 6 page metrics, "
                "level 1 the dashboard summary."
            ],
        ]
        ws = wb.create_sheet("Columns")
        for row in rows:
            ws.append(row)

    @staticmethod
    def _write_summary_sheet(wb, summ: dict) -> None:
        s = wb.create_sheet("Summary")
        s.append(["Lineage matrix statistics"])
        s.append([])
        s.append(["Total nodes", summ["nodes"]])
        s.append(["Nodes with refs>0", summ["with_refs"]])
        s.append([])
        s.append(["By level"])
        for lvl, cnt in summ["by_level"].items():
            s.append([lvl, cnt])
        s.append([])
        s.append(["By type"])
        for t, cnt in sorted(summ["by_type"].items(), key=lambda kv: -kv[1]):
            s.append([t, cnt])
        if summ["orphans"]:
            s.append([])
            s.append(["Orphan nodes (no source)"])
            for o in summ["orphans"]:
                s.append([o.get("Level"), o.get("Layer"), o.get("Detail / Source")])
        b = summ.get("brand") or {}
        if b:
            s.append([])
            s.append(["Brand-book compliance (page elements)"])
            s.append(["Pages", b.get("pages", 0)])
            s.append(["Compliant", b.get("ok", 0)])
            s.append(["Warnings", b.get("warnings", 0)])
            s.append(["Violations", b.get("errors", 0)])
            s.append(["No data", b.get("unknown", 0)])
            s.append(["Fonts, %", b.get("fonts_compliance")])
            s.append(["Colors, %", b.get("colors_compliance")])
            if b.get("error_pages"):
                s.append(["Pages with violations", ", ".join(b["error_pages"])])


def load_json(path: str | Path) -> dict:
    """Load a lineage JSON file, or generate it from a ``.pbix`` path."""
    path = Path(path)
    if path.suffix.lower() == ".pbix":
        from agentic_bi.lineage.pbi_lineage import PbiLineage

        with PbiLineage(path) as lg:
            return lg.to_json()
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Flat level matrix of data lineage (JSON/.pbix -> xlsx)."
    )
    parser.add_argument("input", help="path to lineage.json or .pbix")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="output xlsx (default: '<name>_table.xlsx' next to input)",
    )
    args = parser.parse_args()

    data = load_json(args.input)
    inp = Path(args.input)
    out = Path(args.output) if args.output else inp.with_name(inp.stem + "_table.xlsx")

    table = LineageTable(data)
    table.to_excel(out)
    print(f"Lineage matrix saved: {out}")
    print(f"Total nodes: {len(table.rows)}")


if __name__ == "__main__":
    main()

==================== FILE: src/agentic_bi/report/lineage_brand_cols.py ====================

"""Brand-book columns for the flat lineage matrix.

Unfolds the ``brand`` blocks of ``PbiLineage.to_json()`` into the right-hand
matrix columns (fonts %, colors %, status, notes) for both page-level and
visual-level rows.
"""

from __future__ import annotations

BRAND_LEVEL_LABEL = {
    "ok": "compliant",
    "warning": "warnings",
    "error": "violation",
    "unknown": "no data",
}

_EMPTY = {
    "Brand · fonts, %": "",
    "Brand · colors, %": "",
    "Brand · status": "",
    "Brand · notes": "",
}


def page_brand_index(data: dict) -> dict[str, dict]:
    """Map "page name -> brand metrics" from the lineage JSON."""
    index: dict[str, dict] = {}
    for p in data.get("pages", []) or []:
        if p.get("brand"):
            index[p.get("name", "?")] = p["brand"]
    brand_block = data.get("brand") or {}
    for name, m in (brand_block.get("pages") or {}).items():
        index.setdefault(name, m)
    return index


def brand_row(metrics: dict | None) -> dict:
    """Unfold page-level brand metrics into matrix columns."""
    m = metrics or {}
    fonts = m.get("fonts", {}) or {}
    colors = m.get("colors", {}) or {}
    fc, cc = fonts.get("compliance"), colors.get("compliance")
    notes: list[str] = []
    for f in fonts.get("off", []) or []:
        notes.append(f"font: {f}")
    for c in colors.get("off", []) or []:
        notes.append(f"color: {c}")
    if colors and not colors.get("has_red") and colors.get("total"):
        notes.append("no brand red")
    return {
        "Brand · fonts, %": fc if fc is not None else "",
        "Brand · colors, %": cc if cc is not None else "",
        "Brand · status": BRAND_LEVEL_LABEL.get(m.get("level", ""), ""),
        "Brand · notes": "; ".join(notes[:6]),
    }


def visual_brand_row(visual: dict) -> dict:
    """Unfold visual-level brand metrics (level 7 rows) into matrix columns."""
    m = visual.get("brand") or {}
    if not m:
        return dict(_EMPTY)
    f, c = m.get("fonts", {}) or {}, m.get("colors", {}) or {}
    return {
        "Brand · fonts, %": f.get("compliance")
        if f.get("compliance") is not None
        else "",
        "Brand · colors, %": c.get("compliance")
        if c.get("compliance") is not None
        else "",
        "Brand · status": BRAND_LEVEL_LABEL.get(m.get("level", ""), ""),
        "Brand · notes": "; ".join(m.get("off", []) or [])[:200],
    }

==================== FILE: src/agentic_bi/report/pdf_report.py ====================

"""Multi-page PDF report of a lineage page (diagram + matrix + brand audit).

Assembles the full lineage page into a single multi-page PDF:

    1. title + headline counters
    2. the PlantUML lineage diagram (tiled across pages when tall)
    3. the flat level matrix (automatically paginated)
    4. elements deviating from the brand book

Requires the ``report`` optional extra: ``reportlab`` (and ``Pillow`` for the
diagram, ``pandas``/``openpyxl`` for the Excel export).

CLI exit codes: 0 on success, 2 on a bad input (missing/unreadable JSON/.pbix).
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A3, A4, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

from agentic_bi.report.lineage_matrix import lineage_to_table
from agentic_bi.report.pdf_diagram import diagram_story
from agentic_bi.report.pdf_tables import brand_issues, brand_scorecard, lineage_matrix
from agentic_bi.report.plantuml_tools import find_plantuml_jar

logger = logging.getLogger(__name__)

_PAGE_SIZES = {"A4": A4, "A3": A3}

# Common Unicode font locations, tried when REPORT_PDF_FONT is not set.
_FONT_CANDIDATES = [
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/DejaVuSans.ttf", "C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
]


def _resolve_fonts(font_ttf: str | None = None) -> tuple[str, str]:
    """Register a Unicode TTF when available; fall back to Helvetica."""
    import os

    regular = font_ttf or os.getenv("REPORT_PDF_FONT")
    candidates = []
    if regular:
        candidates.append((regular, regular))
    candidates.extend(_FONT_CANDIDATES)
    for reg, bold in candidates:
        if reg and Path(reg).exists():
            try:
                pdfmetrics.registerFont(TTFont("ReportFont", reg))
                if bold and Path(bold).exists():
                    pdfmetrics.registerFont(TTFont("ReportFont-Bold", bold))
                    return "ReportFont", "ReportFont-Bold"
                return "ReportFont", "ReportFont"
            except Exception as exc:  # noqa: BLE001 - fall back on any font error
                logger.warning("font %s rejected: %s", reg, exc)
    return "Helvetica", "Helvetica-Bold"


def _styles(regular: str, bold: str) -> dict:
    normal = getSampleStyleSheet()["Normal"]
    return {
        "Title": ParagraphStyle(
            "TitleX",
            parent=normal,
            fontName=bold,
            fontSize=20,
            leading=24,
            spaceAfter=4 * mm,
        ),
        "Heading2": ParagraphStyle(
            "Heading2X",
            parent=normal,
            fontName=bold,
            fontSize=13,
            leading=16,
            spaceAfter=2 * mm,
        ),
        "Body": ParagraphStyle(
            "BodyX", parent=normal, fontName=regular, fontSize=9, leading=12
        ),
        "Cell": ParagraphStyle(
            "CellX", parent=normal, fontName=regular, fontSize=6.5, leading=8
        ),
        "CellHead": ParagraphStyle(
            "CellHeadX",
            parent=normal,
            fontName=bold,
            fontSize=6.5,
            leading=8,
            textColor="#FFFFFF",
        ),
    }


def _page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor("#666666")
    canvas.drawRightString(doc.pagesize[0] - 10 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_report(
    data: dict,
    out_path: str | Path,
    *,
    plantuml: str = "",
    title: str = "Data lineage report",
    source_name: str | None = None,
    page_size: str = "A4",
    orientation: str = "landscape",
    font_ttf: str | None = None,
    max_level: int = 7,
    include_visuals: bool = True,
    with_diagram: bool = True,
) -> Path:
    """Build a multi-page PDF report and return the output path.

    Args:
        data: dict in the ``PbiLineage.to_json()`` structure.
        out_path: destination ``.pdf`` path.
        plantuml: PlantUML source for the diagram (skipped when empty).
        title: report title.
        source_name: shown under the title (e.g. the source file name).
        page_size: ``"A4"`` (default) or ``"A3"``.
        orientation: ``"landscape"`` (default) or ``"portrait"``.
        font_ttf: explicit Unicode TTF path; otherwise resolved automatically.
        max_level: deepest lineage level included (1-7).
        include_visuals: include level 7 (visuals) in the matrix.
        with_diagram: render and embed the PlantUML diagram.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    size = _PAGE_SIZES.get(page_size.upper(), A4)
    pagesize = landscape(size) if orientation == "landscape" else portrait(size)

    margin = 12 * mm
    content_w = pagesize[0] - 2 * margin
    content_h = pagesize[1] - 2 * margin - 10 * mm

    regular, bold = _resolve_fonts(font_ttf)
    styles = _styles(regular, bold)

    summary = data.get("summary") or {}
    meta = data.get("meta") or {}
    story: list = [Paragraph(_safe(title), styles["Title"])]
    subtitle = source_name or meta.get("file") or ""
    if subtitle:
        story.append(Paragraph(_safe(subtitle), styles["Body"]))
    story.append(
        Paragraph(
            f"Generated: {datetime.now():%Y-%m-%d %H:%M}. "
            f"Pages: {summary.get('pages', len(data.get('pages', [])) or 0)}, "
            f"visuals: {summary.get('visuals', '')}, "
            f"tables: {summary.get('tables', '')}, "
            f"measures: {summary.get('measures', '')}.",
            styles["Body"],
        )
    )

    if with_diagram and plantuml.strip():
        story.append(PageBreak())
        story.extend(diagram_story(plantuml, content_w, content_h, styles))

    if summary.get("plantuml_available") is False:
        story.append(
            Paragraph("plantuml.jar not found; diagram omitted.", styles["Body"])
        )

    story.extend(brand_scorecard(data, styles, content_w))

    rows = lineage_to_table(data)
    if rows:
        story.append(PageBreak())
        story.extend(
            lineage_matrix(rows, styles, content_w, max_level, include_visuals)
        )

    issues = brand_issues(data, styles, content_w)
    if issues:
        story.append(PageBreak())
        story.extend(issues)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=pagesize,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=14 * mm,
        title=title,
        author="agentic-bi-framework",
    )
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    logger.info("PDF report written: %s", out)
    return out


def _safe(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _plantuml_for(src: Path, data: dict) -> str:
    """Resolve PlantUML source: from a .pbix, the JSON block, or a sibling .puml."""
    if src.suffix.lower() == ".pbix":
        from agentic_bi.lineage.pbi_lineage import PbiLineage

        with PbiLineage(src) as lg:
            return lg.to_plantuml()
    block = data.get("plantuml")
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        found = block.get("lineage") or block.get("source")
        if found:
            return found
    sibling = src.with_suffix(".puml")
    if sibling.exists():
        return sibling.read_text(encoding="utf-8")
    return ""


def main(argv: list[str] | None = None) -> int:
    from agentic_bi.cli_support import run_boundary

    parser = argparse.ArgumentParser(
        prog="agentic-bi-report",
        description="Build a multi-page PDF lineage report from JSON/.pbix.",
    )
    parser.add_argument("input", help="path to lineage.json or .pbix")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="output .pdf path (default: next to the input as "
        "'<name>_YYYYMMDD_HHMMSS.pdf')",
    )
    parser.add_argument("--title", default="Data lineage report")
    parser.add_argument("--page-size", default="A4", choices=["A4", "A3"])
    parser.add_argument(
        "--orientation", default="landscape", choices=["landscape", "portrait"]
    )
    parser.add_argument("--font", default=None, help="Unicode TTF font path")
    parser.add_argument("--max-level", type=int, default=7)
    parser.add_argument(
        "--no-visuals", action="store_true", help="exclude level 7 (visuals)"
    )
    parser.add_argument("--no-diagram", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    def body() -> int:
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(levelname)s: %(message)s",
        )

        from agentic_bi.report.lineage_table import load_json

        data = load_json(args.input)
        plantuml = ""
        if not args.no_diagram and find_plantuml_jar():
            try:
                plantuml = _plantuml_for(Path(args.input), data)
            except Exception as exc:  # noqa: BLE001 - diagram is best-effort
                logger.warning("could not build PlantUML: %s", exc)

        inp = Path(args.input)
        if args.output:
            out = args.output
        else:
            # Timestamped default so repeated runs never overwrite each other.
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = str(inp.with_name(f"{inp.stem}_{stamp}.pdf"))
        build_report(
            data,
            out,
            plantuml=plantuml,
            title=args.title,
            source_name=Path(args.input).name,
            page_size=args.page_size,
            orientation=args.orientation,
            font_ttf=args.font,
            max_level=args.max_level,
            include_visuals=not args.no_visuals,
            with_diagram=not args.no_diagram,
        )
        print(f"PDF report saved: {out}")
        return 0

    return run_boundary(body, prog="agentic-bi-report")


if __name__ == "__main__":
    raise SystemExit(main())

==================== FILE: src/agentic_bi/report/pdf_tables.py ====================

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

==================== FILE: src/agentic_bi/report/pdf_diagram.py ====================

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
        return [Image(buffer, width=content_w, height=scaled_h, hAlign="CENTER")]

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
        flowables.append(Image(buffer, width=content_w, height=tile_h, hAlign="CENTER"))
        flowables.append(PageBreak())
        top = bottom
    image.close()
    if flowables and isinstance(flowables[-1], PageBreak):
        flowables.pop()
    return flowables


def diagram_story(
    plantuml: str,
    content_w: float,
    content_h: float,
    styles,
    title: str = "Data lineage diagram",
) -> list:
    """Render ``plantuml`` and return flowables (one or more pages)."""
    story: list = [Paragraph(title, styles["Heading2"]), Spacer(1, 4 * mm)]
    if not plantuml.strip():
        story.append(Paragraph("No diagram provided.", styles["Body"]))
        return story

    with tempfile.TemporaryDirectory() as td:
        png = render_png(plantuml, td)
        if png is None:
            logger.warning("PlantUML rendering unavailable; diagram skipped")
            story.append(
                Paragraph(
                    "Diagram not rendered (plantuml.jar / Pillow unavailable).",
                    styles["Body"],
                )
            )
            return story
        try:
            story.extend(_tiles(Path(png), content_w, content_h, styles))
        except ImportError:
            logger.warning("Pillow unavailable; diagram placed as a single image")
            story.append(Image(str(png), width=content_w, hAlign="CENTER"))
    return story

==================== FILE: src/agentic_bi/report/plantuml_tools.py ====================

"""PlantUML helpers: local validation and rendering of ``.puml`` diagrams.

Rendering is needed before the diagram is embedded into the PDF report, and
validation catches syntax errors before a broken diagram reaches a reader.

The ``plantuml.jar`` location is resolved from configuration only:

    PLANTUML_JAR      explicit path to the jar
    PLANTUML_JAR_DIR  directory to glob for ``plantuml-*.jar`` (newest wins)

No environment-specific default path is shipped. Running the jar requires Java
on ``PATH``.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import tempfile
from pathlib import Path


def find_plantuml_jar() -> str | None:
    """Resolve the PlantUML jar from ``PLANTUML_JAR`` / ``PLANTUML_JAR_DIR``."""
    env = os.getenv("PLANTUML_JAR")
    if env and Path(env).exists():
        return env
    jar_dir = os.getenv("PLANTUML_JAR_DIR")
    if jar_dir:
        matches = sorted(glob.glob(str(Path(jar_dir, "plantuml-*.jar"))))
        if matches:
            return matches[-1]
    return None


def _run(
    jar: str, args: list[str], stdin_text: str | None = None
) -> subprocess.CompletedProcess:
    """Run the jar with a forced UTF-8 charset (Windows-safe for Unicode)."""
    cmd = [
        "java",
        "-Dfile.encoding=UTF-8",
        "-Dsun.jnu.encoding=UTF-8",
        "-jar",
        jar,
        "-charset",
        "UTF-8",
        *args,
    ]
    if stdin_text is not None:
        return subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return subprocess.run(cmd, capture_output=True, text=True)


def validate_text(puml_text: str, jar: str | None = None) -> tuple[bool, str]:
    """Validate PlantUML source text.

    Returns:
        ``(ok, message)``. ``ok`` is True when the diagram compiles.
    """
    jar = jar or find_plantuml_jar()
    if not jar:
        return False, "plantuml.jar not found; set PLANTUML_JAR"

    with tempfile.TemporaryDirectory() as td:
        src = Path(td, "input.puml")
        src.write_text(puml_text, encoding="utf-8")
        result = _run(jar, ["-checkonly", str(src)])
    merged = (result.stdout or "") + (result.stderr or "")
    if "error" in merged.lower():
        m = re.search(r"Error\s+line\s+(\d+)[^\n]*", merged, re.IGNORECASE)
        line = m.group(0).strip() if m else merged.strip()[-200:]
        return False, line
    if result.returncode != 0 and "some diagram" not in merged.lower():
        return False, merged.strip()[-300:]
    return True, "OK"


def validate_file(puml_path: str | Path, jar: str | None = None) -> tuple[bool, str]:
    """Validate a ``.puml`` file on disk."""
    text = Path(puml_path).read_text(encoding="utf-8")
    return validate_text(text, jar)


def render_png(
    puml_text: str, out_dir: str | Path, jar: str | None = None
) -> Path | None:
    """Render PlantUML to PNG. Returns the generated path or None."""
    jar = jar or find_plantuml_jar()
    if not jar:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td, "input.puml")
        src.write_text(puml_text, encoding="utf-8")
        result = _run(jar, ["-tpng", "-o", str(out_dir.resolve()), str(src)])
    merged = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 and "error" in merged.lower():
        return None
    pngs = sorted(out_dir.glob("*.png"))
    return pngs[0] if pngs else None

