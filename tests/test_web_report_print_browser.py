"""Browser-measured print pagination for the web clone (headless Chrome).

A CSS-substring check cannot see whether a canvas really fits the sheet: the
caption's line box, the page-level findings and the paper box are layout facts.
These tests print a real document to PDF and count the sheets. They are skipped
when no Chromium binary is installed, since the pagination itself is a browser
result.

Measured before the fix: 1280x1050, 700x720, 1080x1920, 1x1920 and 4000x3000
canvases each produced **two** sheets, and a page with one filter finding did so
even with `line-height:1`. After: every canvas is one sheet, with or without
findings.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.board_guide.guide_capture import find_browser_executable
from agentic_bi.web_report import inspect_layout, render_html
from agentic_bi.web_report.web_model import (
    ElementReport,
    Issue,
    PageReport,
    WebReportModel,
)

_CHROME = find_browser_executable()

pytestmark = pytest.mark.skipif(
    _CHROME is None, reason="no headless Chromium binary on this machine"
)

_HIDE_CHROME = (
    "<style>@media print{header,.stats-grid,#detailsSection,.page-tabs,"
    ".footer{display:none !important}}</style>"
)

_UNSAFE_FILTER = (
    '[{"name":"x","filter":{"Where":[{"Condition":{"In":'
    '{"Expressions":[],"Values":[]}}}]}}]'
)

_CANVASES = [
    (1920, 1080),
    (1280, 720),
    (700, 720),
    (1280, 1050),
    (1080, 1920),
    (700, 400),
    (1, 1920),
    (4000, 3000),
]


def _card(title: str, x: int) -> dict:
    return make_container(
        "card",
        {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
        ["Sum(Sales.amount)"],
        title=title,
        x=x,
    )


def _pages_of(html: str, work: Path) -> int:
    """Print `html` to PDF and count `/Type /Page` objects.

    The interactive chrome is hidden so only the canvases are paginated; that is
    the part the fit calculation controls. Chrome writes uncompressed page
    objects, so the count is read from the PDF bytes without a PDF library
    (`pypdf` is not a declared dependency).
    """
    page = work / "doc.html"
    page.write_text(html.replace("</head>", _HIDE_CHROME + "</head>"), encoding="utf-8")
    pdf = work / "doc.pdf"
    subprocess.run(
        [
            str(_CHROME),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            f"--print-to-pdf={pdf}",
            "--no-pdf-header-footer",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert pdf.is_file(), "Chrome produced no PDF"
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes()))


def _layout(width: int, height: int, *, filter_notice: bool = False) -> dict:
    layout = make_layout([_card("LEFT", 20), _card("RIGHT", max(width // 2, 20))])
    layout["sections"][0]["width"] = width
    layout["sections"][0]["height"] = height
    if filter_notice:
        layout["sections"][0]["filters"] = _UNSAFE_FILTER
    return layout


@pytest.mark.parametrize(("width", "height"), _CANVASES)
def test_every_canvas_prints_on_one_sheet(
    width: int, height: int, tmp_path: Path
) -> None:
    markup = render_html(inspect_layout(_layout(width, height), source="w.pbix"))
    assert _pages_of(markup, tmp_path) == 1


@pytest.mark.parametrize(("width", "height"), _CANVASES)
def test_page_findings_do_not_push_the_canvas_onto_a_second_sheet(
    width: int, height: int, tmp_path: Path
) -> None:
    layout = _layout(width, height, filter_notice=True)
    model = inspect_layout(layout, source="w.pbix")
    assert model.pages[0].filter_issues, "the fixture must produce a finding"
    assert _pages_of(render_html(model), tmp_path) == 1


def test_a_long_finding_is_reserved_as_extra_lines(tmp_path: Path) -> None:
    page = PageReport(
        "P",
        width=1280,
        height=1050,
        elements=[ElementReport(page="P", index=0, visual_type="card")],
        filter_issues=[Issue("FILTER-UNSAFE-IN", "error", "длинное " * 90)],
    )
    model = WebReportModel(source="w.pbix", pages=[page])
    assert _pages_of(render_html(model), tmp_path) == 1


def test_two_pages_print_two_sheets(tmp_path: Path) -> None:
    first = _layout(1280, 720)["sections"][0]
    second = _layout(1280, 720)["sections"][0]
    model = inspect_layout({"sections": [first, second]}, source="w.pbix")
    assert len(model.pages) == 2
    assert _pages_of(render_html(model), tmp_path) == 2


def test_an_empty_page_prints_exactly_one_sheet(tmp_path: Path) -> None:
    """The empty page's caption must not spill the placeholder onto a second sheet.

    The placeholder is a standalone block with its own heading; the caption added
    in R7 is one more line box above it, and the sheet budget has to absorb it.
    """
    first = _layout(1280, 720)["sections"][0]
    empty = {
        "displayName": "Пустая страница",
        "width": 1280,
        "height": 720,
        "visualContainers": [],
    }
    model = inspect_layout({"sections": [first, empty]}, source="w.pbix")
    assert len(model.pages) == 2
    assert model.pages[1].elements == []
    assert _pages_of(render_html(model), tmp_path) == 2


def test_the_real_document_keeps_the_canvas_on_its_first_sheet(tmp_path: Path) -> None:
    """The header and the summary are not printed, so the canvas starts the sheet.

    Measured before: the real document (no test harness) printed a one-page
    1280x720 report as two sheets — the opening one carried only the title and
    the counters, and `break-inside:avoid` pushed the canvas over.
    """
    markup = render_html(inspect_layout(_layout(1280, 720), source="w.pbix"))
    # The metrics table follows the canvas on purpose; only the chrome is removed
    # here so the canvas alone is measured against the sheet.
    only_canvas = markup.replace(
        "</head>",
        "<style>@media print{#detailsSection{display:none}}</style></head>",
    )
    assert _pages_of(only_canvas, tmp_path) == 1
