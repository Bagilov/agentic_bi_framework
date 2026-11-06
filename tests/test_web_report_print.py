"""Print, overlay and live-region regressions for the web clone.

The browser-measured defects behind these tests: a 1920 px canvas was clipped at
the sheet edge because paged media has no horizontal pagination; a canvas taller
than the printable height was torn across sheets with the page name left behind
on the first one; a blanket print `color/background:#fff !important` erased
severity fills; the filter scrim never hid again after the first close; two
`role="status"` regions double-announced; and a public `ElementReport` geometry
value could add a second CSS declaration.
"""

from __future__ import annotations

import math
import re

import pytest
from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.web_report import inspect_layout, render_html
from agentic_bi.web_report.web_model import (
    ElementReport,
    Issue,
    PageReport,
    WebReportModel,
)
from agentic_bi.web_report.web_render import (
    _PRINT_CAPTION_PX,
    _PRINT_CONTENT_PX,
    _PRINT_NOTICE_GAP_PX,
    _PRINT_NOTICE_LINE_PX,
    _PRINT_SAFETY_PX,
    _PRINT_SHEET_PX_H,
    _notice_lines,
    _scale_text,
)
from agentic_bi.web_report.web_render import (
    _print_scale as _fit_scale,
)

# A4 landscape with 10 mm margins, in CSS px at 96 dpi.
_A4_LANDSCAPE_PX = (297 - 20) / 25.4 * 96, (210 - 20) / 25.4 * 96

_CANVASES = [
    (1920, 1080),
    (1280, 720),
    (700, 720),
    (1280, 1050),
    (1080, 1920),
    (700, 400),
    # degenerate canvases from a hostile layout: a 1 px side still printed
    (1920, 1),
    (1, 1920),
]


def _reserved(notices: int = 0) -> float:
    """The vertical space a printed page spends before its canvas."""
    reserve = _PRINT_CAPTION_PX + _PRINT_SAFETY_PX
    if notices:
        reserve += notices * _PRINT_NOTICE_LINE_PX + _PRINT_NOTICE_GAP_PX
    return reserve


def _card(title: str, x: int) -> dict:
    return make_container(
        "card",
        {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
        ["Sum(Sales.amount)"],
        title=title,
        x=x,
    )


def _markup(width: int, height: int = 720) -> str:
    visuals = [
        _card("LEFTMARK", 20),
        _card("MIDMARK", max(width // 2, 20)),
        _card("RIGHTMARK", max(width - 420, 20)),
    ]
    layout = make_layout(visuals, width=width)
    layout["sections"][0]["height"] = height
    return render_html(inspect_layout(layout, source="w.pbix"))


def _script(markup: str) -> str:
    return markup[markup.index("const MODEL") :]


def _function(script: str, name: str, next_name: str) -> str:
    start = script.index(f"function {name}")
    return script[start : script.index(f"function {next_name}", start)]


def _print_block(markup: str) -> str:
    start = markup.index("@media print")
    opening = markup.index("{", start)
    depth = 0
    for pos in range(opening, len(markup)):
        if markup[pos] == "{":
            depth += 1
        elif markup[pos] == "}":
            depth -= 1
            if depth == 0:
                return markup[opening + 1 : pos]
    raise AssertionError("@media print block is unbalanced")


def _canvas_style(markup: str) -> str:
    match = re.search(r'<div class="canvas" style="([^"]*)"', markup)
    assert match, "the canvas element carries no inline style"
    return match.group(1)


def _print_scale(markup: str) -> float:
    match = re.search(r"--print-scale:([0-9.]+)", markup)
    assert match, "the renderer must supply a print scale"
    return float(match.group(1))


def _canvas_size(markup: str) -> tuple[float, float]:
    style = _canvas_style(markup)
    width = re.search(r"width:([0-9.]+)px", style)
    height = re.search(r"height:([0-9.]+)px", style)
    assert width and height
    return float(width.group(1)), float(height.group(1))


def test_print_budget_is_the_a4_landscape_printable_box():
    width, height = _A4_LANDSCAPE_PX
    assert _PRINT_CONTENT_PX == pytest.approx(width, abs=0.01)
    assert _PRINT_SHEET_PX_H == pytest.approx(height, abs=0.01)
    assert _reserved(1) < _PRINT_SHEET_PX_H


def test_print_caption_reserves_the_measured_line_box():
    """The caption's *line box* is what takes space, not its font size.

    Measured in Chrome: `.canvas-title` is 18.67 px font with a 23 px line box
    plus a 6 px margin, while the budget reserved only `14pt + 6` (24.67 px). A
    height-bound canvas therefore overflowed by 4.33 px and broke onto a second
    sheet. The print block now pins `line-height:1.2` (22.4 px), so reserving
    28.4 px covers the measured 29 px box.
    """
    # `line-height:1.2` makes the line box 22.4 px, so 28.4 px covers the
    # measured 29 px box (Chromium's `normal` is ~1.23 em, i.e. 23 px).
    assert _PRINT_CAPTION_PX >= 28.4
    assert _PRINT_CAPTION_PX == pytest.approx(14 * 96 / 72 * 1.2 + 6, abs=0.01)


def test_page_notices_are_reserved_on_the_sheet():
    """Page-level findings print above the caption and used to be free of charge."""
    assert _PRINT_NOTICE_LINE_PX >= 21
    assert _PRINT_NOTICE_GAP_PX >= 10
    assert _reserved(2) - _reserved(0) == pytest.approx(
        2 * _PRINT_NOTICE_LINE_PX + _PRINT_NOTICE_GAP_PX, abs=0.01
    )


def test_a_long_notice_is_reserved_as_more_than_one_line():
    short = PageReport("P", filter_issues=[Issue("FILTER-UNSAFE-IN", "error", "x")])
    long = PageReport(
        "P",
        filter_issues=[Issue("FILTER-UNSAFE-IN", "error", "y" * 400)],
    )
    assert _notice_lines(short) == 1
    assert _notice_lines(long) >= 3


@pytest.mark.parametrize(("width", "height"), _CANVASES)
def test_print_scale_fits_the_canvas_on_one_sheet(width: int, height: int):
    markup = _markup(width, height)
    scale = _print_scale(markup)
    assert 0 < scale <= 1.0
    assert width * scale <= _PRINT_CONTENT_PX + 0.5, "torn horizontally"
    assert height * scale + _reserved() <= _PRINT_SHEET_PX_H + 0.5, (
        "torn vertically: the caption does not fit with the canvas"
    )
    # the scale is the largest one that fits: either a dimension uses the whole
    # budget or the canvas is already at its natural size. A scale smaller than
    # necessary silently wastes sheet space and this bound catches it.
    uses_width = abs(width * scale - _PRINT_CONTENT_PX) <= 1.0
    uses_height = abs(height * scale - (_PRINT_SHEET_PX_H - _reserved())) <= 1.0
    assert scale == 1.0 or uses_width or uses_height, f"{width}x{height} shrunk"


def test_a_page_with_findings_gets_a_smaller_scale_than_a_clean_one():
    """The renderer feeds the notice count into the fit, not just the canvas size."""
    clean = _fit_scale(1280, 1050)
    with_notice = _fit_scale(1280, 1050, notices=2)
    assert with_notice < clean
    markup = _markup(1280, 1050)

    def page(issues: list[Issue]) -> PageReport:
        element = ElementReport(page="P", index=0, visual_type="card")
        return PageReport(
            "P", width=1280, height=1050, elements=[element], filter_issues=issues
        )

    clean = WebReportModel(source="c.pbix", pages=[page([])])
    noisy = WebReportModel(
        source="c.pbix", pages=[page([Issue("FILTER-UNSAFE-IN", "error", "x")])]
    )
    assert _print_scale(render_html(noisy)) < _print_scale(render_html(clean))
    assert "--print-scale" in markup


@pytest.mark.parametrize(("width", "height"), _CANVASES)
def test_printed_cardinals_stay_inside_the_sheet(width: int, height: int):
    """Real print geometry: the scaled canvas plus the sheet chrome fits.

    The previous version only checked that the inline size was unscaled, so it
    stayed green when the vertical fit was removed entirely.
    """
    markup = _markup(width, height)
    printed_width, printed_height = _canvas_size(markup)
    scale = _print_scale(markup)
    assert (printed_width, printed_height) == (width, height)
    assert printed_width * scale <= _PRINT_CONTENT_PX + 0.5
    assert printed_height * scale + _reserved() <= _PRINT_SHEET_PX_H + 0.5
    assert markup.count('data-el="1"') == 3
    assert "LEFTMARK" in markup and "RIGHTMARK" in markup


def test_a_narrow_canvas_keeps_its_natural_size():
    markup = _markup(700, 400)
    assert _print_scale(markup) == 1.0
    assert "width:700px" in _canvas_style(markup)


@pytest.mark.parametrize(("width", "height"), [(700, 720), (1234, 777)])
def test_print_scale_is_rounded_down_and_never_exceeds_the_budget(
    width: int, height: int
):
    """`floor`, not `round`: these sizes have a 7th decimal >= 5.

    1920x1080 (the previous case) has a 0 there, so `round()` survived the test.
    """
    scale = _fit_scale(width, height)
    text = _scale_text(scale)
    assert len(text.split(".")[1]) == 6
    assert float(text) == math.floor(scale * 1_000_000) / 1_000_000
    assert float(text) != round(scale, 6), "this size must distinguish floor/round"
    assert width * float(text) <= _PRINT_CONTENT_PX


def test_every_printed_page_starts_on_a_new_sheet_after_its_caption():
    block = _print_block(_markup(1280, 720))
    assert "@page { size:A4 landscape; margin:10mm; }" in block
    assert ".canvas-wrap ~ .canvas-wrap { break-before:page" in block
    assert "page-break-before:always" in block
    # the caption's line box is pinned so the reserved space is real everywhere
    assert "font-size:14pt; line-height:1.2" in block


def test_print_block_applies_the_scale_and_keeps_severity_fills():
    block = _print_block(_markup(1280))
    assert "zoom:var(--print-scale,1)" in block
    # severity fills and text colors come from the print token block now
    assert "background:none !important" not in block
    start = block.index(".el {")
    rule = block[start : block.index("}", start)]
    assert "background" not in rule and "color" not in rule
    assert "h1, .subtitle, .el-title" not in block
    assert "details::details-content" in block


def test_filter_scrim_is_rendered_and_wired_to_close_the_panel():
    markup = _markup(1280)
    scrim = re.findall(r"<div[^>]*id=\"filterScrim\"[^>]*>", markup)
    assert scrim, "the filter panel needs a real click-away scrim"
    assert 'aria-hidden="true"' in scrim[0]
    assert "toggleFilterPanel(false)" in scrim[0]
    css = markup[: markup.index("</style>")]
    assert ".filter-scrim.open { display:block; }" in css
    print_block = _print_block(markup)
    assert ".filter-scrim" in print_block
    body = _function(_script(markup), "toggleFilterPanel", "resetFilters")
    assert "getElementById('filterScrim')" in body
    # unconditional: the scrim must also be *hidden* when the panel closes.
    # Gating the call on `open` leaves a full-page backdrop over the report.
    assert re.search(r"(?m)^  scrim\.classList\.toggle\('open', open\);$", body)
    assert "if (scrim &&" not in body
    # focus still returns from the panel, the scrim or the document body
    assert "document.activeElement === document.body" in body


def test_filter_counter_counts_only_the_active_canvas():
    body = _function(_script(_markup(1280)), "applyFilters", "escapeHtml")
    assert "active.querySelectorAll('.el:not(.dim)').length" in body
    # a document-wide count reports elements hidden on other pages
    assert "document.querySelectorAll('.el:not(.dim)')" not in body
    assert "BY_KEY[first.dataset.key]._pi" in body


def test_filter_counter_is_seeded_before_the_first_filter_change():
    """The seed must not jump pages: `applyFilters(true)` only fills the counter.

    Measured before: the seed called the full `applyFilters()`, which — with no
    filter set — jumped to the page of the first element, so a report whose first
    page is empty opened on page 2 and the first tab was skipped.
    """
    script = _script(_markup(1280))
    init = script[script.index("document.addEventListener('DOMContentLoaded'") :]
    assert "applyFilters(true)" in init
    body = _function(script, "applyFilters", "escapeHtml")
    assert "if (seed !== true && target !== null) showPage(target);" in body


def test_filter_toggle_animates_with_the_panel():
    css = _markup(1280)
    start = css.index(".filter-toggle {")
    block = css[start : css.index("}", start)]
    assert "transition:left .25s ease" in block


def test_closing_details_changes_the_live_region_text():
    script = _script(_markup(1280))
    start = script.index("function hideDetails")
    body = script[
        start : script.index("document.addEventListener('DOMContentLoaded'", start)
    ]
    assert "getElementById('detailLive')" in body
    assert "Детали элемента закрыты" in body


def test_opening_details_announces_the_page_and_the_issue_count():
    body = _function(_script(_markup(1280)), "showDetails", "hideDetails")
    assert "el._page" in body.split("detailLive")[1]
    assert ", замечаний: " in body
    assert "el.label" in body


def test_closing_details_returns_focus_to_a_visible_control():
    script = _script(_markup(1280))
    body = script[
        script.index("function hideDetails") : script.index(
            "document.addEventListener('DOMContentLoaded'"
        )
    ]
    # focusing an element on a now-hidden page is a no-op that drops focus to
    # <body>; the toggle is the visible fallback.
    assert "previous.offsetParent" in body
    assert "getElementById('filterToggle')" in body


def test_escape_does_not_announce_a_close_for_a_card_that_was_never_open():
    script = _script(_markup(1280))
    init = script[script.index("document.addEventListener('DOMContentLoaded'") :]
    assert "detailOpen" in init
    assert "card.style.display !== 'none'" not in init


def test_switching_pages_closes_a_card_that_belongs_to_another_page():
    body = _function(_script(_markup(1280)), "showPage", "onTabKey")
    assert "detailOpen" in body
    assert "BY_KEY[detailKey]._pi !== idx" in body
    assert "hideDetails()" in body


def test_only_the_detail_region_is_a_status_region():
    markup = _markup(1280)
    assert markup.count('role="status"') == 1
    live = re.search(r"<[^>]*role=\"status\"[^>]*>", markup)
    assert live and 'id="detailLive"' in live.group(0)
    count = re.search(r"<[^>]*id=\"filter-count\"[^>]*>", markup)
    assert count and "role=" not in count.group(0)


def _hostile_model() -> WebReportModel:
    hostile = "0;background:url(https://evil.example/x)"
    element = ElementReport(page="P", index=0, visual_type="card", title="H")
    element.x = hostile
    element.y = "1;position:fixed;inset:0"
    element.width = "2;background:red"
    element.height = "3;color:red"
    return WebReportModel(
        source="h.pbix", pages=[PageReport("P", width=1280, elements=[element])]
    )


def test_geometry_style_cannot_add_a_css_declaration():
    markup = render_html(_hostile_model())
    style = re.search(r'<div class="el [^"]*"[^>]*style="([^"]*)"', markup)
    assert style, "element box missing its inline style"
    value = style.group(1)
    assert "background" not in value and "position" not in value
    assert "url(" not in value
    declarations = [part.strip() for part in value.split(";") if part.strip()]
    assert len(declarations) == 4
    assert value.startswith("left:0px;top:0px;width:0px;height:0px;")


def test_the_page_tab_badge_counts_findings_not_elements():
    """The badge and its accessible name announce findings, like the header.

    Counting elements with issues made the tab say "замечаний: 1" for an element
    carrying three errors, contradicting the "Ошибок 3" summary card.
    """
    element = ElementReport(
        page="P",
        index=0,
        visual_type="card",
        issues=[Issue("A", "error", "x"), Issue("B", "error", "y")],
    )
    model = WebReportModel(source="s.pbix", pages=[PageReport("P", elements=[element])])
    markup = render_html(model)
    assert 'aria-label="P, замечаний: 2"' in markup
    assert '<span class="tab-badge" aria-hidden="true">2</span>' in markup


def test_closing_the_card_only_restores_focus_it_owned():
    """A side-effect close must not steal focus from the tab or the panel.

    Measured: a tab switch closed the card and moved focus to #filterToggle, so
    the next arrow key went nowhere (the listener is on #pageTabs) and a filter
    change ejected focus from the panel. The close still restores focus when the
    card itself had it, and only then.
    """
    script = _script(_markup(1280))
    body = script[script.index("function hideDetails") :]
    assert "card === document.activeElement" in body
    assert "card.contains(document.activeElement)" in body
    owns = body.index("ownsFocus")
    guard = body.index("if (!ownsFocus) return;")
    focus = body.index("previous.focus()")
    assert owns < guard < focus


def test_the_scale_never_becomes_zero_or_negative():
    """A hostile notice count must not emit an invalid `zoom` declaration."""
    assert _fit_scale(1280, 1050, notices=10_000) == pytest.approx(0.02, abs=1e-9)
    assert _fit_scale(1e9, 1e9) > 0
