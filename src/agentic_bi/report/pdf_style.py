"""Page geometry, text styles and font registration for the PDF report.

Owns the printable page sizes, the Unicode TTF lookup (with the Helvetica
fallback), the paragraph styles, the page footer and the markup escaping used
by :mod:`agentic_bi.report.pdf_report` when it composes the report story.
"""

from __future__ import annotations

import logging
from pathlib import Path

from reportlab.lib.pagesizes import A3, A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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


def _safe(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
