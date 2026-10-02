"""Multi-page PDF report of a lineage page (diagram + matrix + brand audit).

Assembles the full lineage page into a single multi-page PDF:

    1. title + headline counters
    2. the PlantUML lineage diagram (tiled across pages when tall)
    3. the flat level matrix (automatically paginated)
    4. elements deviating from the brand book

Requires the ``report`` optional extra: ``reportlab`` (and ``Pillow`` for the
diagram, ``pandas``/``openpyxl`` for the Excel export).
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
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
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
        "Title": ParagraphStyle("TitleX", parent=normal, fontName=bold,
                                fontSize=20, leading=24, spaceAfter=4 * mm),
        "Heading2": ParagraphStyle("Heading2X", parent=normal, fontName=bold,
                                   fontSize=13, leading=16, spaceAfter=2 * mm),
        "Body": ParagraphStyle("BodyX", parent=normal, fontName=regular,
                               fontSize=9, leading=12),
        "Cell": ParagraphStyle("CellX", parent=normal, fontName=regular,
                               fontSize=6.5, leading=8),
        "CellHead": ParagraphStyle("CellHeadX", parent=normal, fontName=bold,
                                   fontSize=6.5, leading=8, textColor="#FFFFFF"),
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
    story.append(Paragraph(
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}. "
        f"Pages: {summary.get('pages', len(data.get('pages', [])) or 0)}, "
        f"visuals: {summary.get('visuals', '')}, "
        f"tables: {summary.get('tables', '')}, "
        f"measures: {summary.get('measures', '')}.",
        styles["Body"]))

    if with_diagram and plantuml.strip():
        story.append(PageBreak())
        story.extend(diagram_story(plantuml, content_w, content_h, styles))

    if summary.get("plantuml_available") is False:
        story.append(Paragraph("plantuml.jar not found; diagram omitted.",
                               styles["Body"]))

    story.extend(brand_scorecard(data, styles, content_w))

    rows = lineage_to_table(data)
    if rows:
        story.append(PageBreak())
        story.extend(lineage_matrix(rows, styles, content_w, max_level, include_visuals))

    issues = brand_issues(data, styles, content_w)
    if issues:
        story.append(PageBreak())
        story.extend(issues)

    doc = SimpleDocTemplate(
        str(out), pagesize=pagesize,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=14 * mm,
        title=title, author="agentic-bi-framework",
    )
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    logger.info("PDF report written: %s", out)
    return out


def _safe(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a multi-page PDF lineage report from JSON/.pbix.")
    parser.add_argument("input", help="path to lineage.json or .pbix")
    parser.add_argument("-o", "--output", default=None, help="output .pdf path")
    parser.add_argument("--title", default="Data lineage report")
    parser.add_argument("--page-size", default="A4", choices=["A4", "A3"])
    parser.add_argument("--orientation", default="landscape",
                        choices=["landscape", "portrait"])
    parser.add_argument("--font", default=None, help="Unicode TTF font path")
    parser.add_argument("--max-level", type=int, default=7)
    parser.add_argument("--no-visuals", action="store_true",
                        help="exclude level 7 (visuals)")
    parser.add_argument("--no-diagram", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s: %(message)s")

    from agentic_bi.report.lineage_table import load_json

    data = load_json(args.input)
    plantuml = ""
    if not args.no_diagram and find_plantuml_jar():
        try:
            plantuml = _plantuml_for(Path(args.input), data)
        except Exception as exc:  # noqa: BLE001 - diagram is best-effort
            logger.warning("could not build PlantUML: %s", exc)

    out = args.output or str(Path(args.input).with_suffix(".pdf"))
    build_report(
        data, out, plantuml=plantuml, title=args.title,
        source_name=Path(args.input).name,
        page_size=args.page_size, orientation=args.orientation,
        font_ttf=args.font, max_level=args.max_level,
        include_visuals=not args.no_visuals, with_diagram=not args.no_diagram,
    )
    print(f"PDF report saved: {out}")


if __name__ == "__main__":
    main()
