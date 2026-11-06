"""Document-level (HTML) check tests for the dashboard web clone.

`html_issues` inspects an already-built document (public API), so it must not be
fooled by text that only looks like markup: a `<style>` inside a comment or a JS
string, a commented-out heading, or a hidden `<p>` carrying a stylesheet marker.
"""

from __future__ import annotations

import re

from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.web_report import inspect_layout, render_html
from agentic_bi.web_report.web_checks import html_issues


def _codes(markup: str) -> set[str]:
    return {i.check_id for i in html_issues(markup)}


def _rendered_document() -> str:
    layout = make_layout(
        [
            make_container(
                "card",
                {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
                ["Sum(Sales.amount)"],
                title="Total",
            )
        ]
    )
    return render_html(inspect_layout(layout, source="l.pbix"))


def _style_of(markup: str) -> str:
    start = markup.index("<style>") + len("<style>")
    return markup[start : markup.index("</style>", start)]


def test_stylesheet_markers_cannot_be_satisfied_by_report_text():
    """A page named `@media print` must not hide a removed print block.

    The old check searched the whole document, so report data (which is embedded
    in the page) could satisfy a stylesheet-marker check.
    """
    markup = _rendered_document()
    style = _style_of(markup)
    broken = markup.replace(
        style,
        style.replace("@media print", "@media screen").replace(
            ":focus-visible", ":focus"
        ),
    )
    broken = broken.replace(
        "</header>",
        '</header><p style="display:none">@media print :focus-visible</p>',
        1,
    )
    codes = _codes(broken)
    assert "HTML-MEDIA-PRINT" in codes
    assert "HTML-A11Y-FOCUS" in codes


def test_aria_label_is_required_on_every_interactive_control():
    """The detail popover's own label used to satisfy the check for all controls."""
    markup = _rendered_document()
    assert "HTML-A11Y-CONTROLS" not in _codes(markup)

    stripped = re.sub(r'(<div class="el [^>]*?) aria-label="[^"]*"', r"\1", markup)
    assert 'aria-label="Детали' not in stripped
    assert "HTML-A11Y-CONTROLS" in _codes(stripped)

    no_toggle = re.sub(
        r'(<button[^>]*id="filterToggle"[^>]*?) aria-label="[^"]*"', r"\1", markup
    )
    assert "HTML-A11Y-CONTROLS" in _codes(no_toggle)


def test_heading_check_ignores_script_templates():
    markup = (
        '<html lang="ru"><body><h1>T</h1>'
        '<script>const tpl = "<h4>fake</h4>";</script></body></html>'
    )
    heading = [i for i in html_issues(markup) if i.check_id.startswith("HTML-HEADING")]
    assert heading == []


def test_heading_check_ignores_stylesheet_bodies():
    markup = '<html lang="ru"><body><h1>T</h1><style>h2{} h3{}</style></body></html>'
    heading = [i for i in html_issues(markup) if i.check_id.startswith("HTML-HEADING")]
    assert heading == []


def test_document_without_headings_is_reported():
    markup = (
        '<html lang="ru"><head><style>@media print{}</style></head>'
        "<body><p>plain text</p></body></html>"
    )
    assert "HTML-HEADING-MISSING" in _codes(markup)


def test_style_marker_inside_a_comment_does_not_count():
    markup = (
        '<html lang="ru"><body><h1>a</h1>'
        "<!-- <style>@media print</style> --></body></html>"
    )
    assert "HTML-MEDIA-PRINT" in _codes(markup)


def test_style_marker_inside_a_script_string_does_not_count():
    markup = (
        '<html lang="ru"><body><h1>a</h1>'
        '<script>const s = "<style>@media print</style>";</script></body></html>'
    )
    assert "HTML-MEDIA-PRINT" in _codes(markup)


def test_style_marker_inside_a_real_style_element_still_counts():
    markup = (
        '<html lang="ru"><head><style>@media print{}</style></head>'
        "<body><h1>a</h1></body></html>"
    )
    assert "HTML-MEDIA-PRINT" not in _codes(markup)


def test_each_stylesheet_marker_is_detected_when_present():
    style = (
        "@media (prefers-color-scheme: dark){} "
        "@media (prefers-reduced-motion: reduce){} "
        "@media (max-width: 720px){} @media print{} :focus-visible{}"
    )
    markup = (
        f'<html lang="ru"><head><style>{style}</style></head>'
        "<body><h1>a</h1></body></html>"
    )
    stylesheet = {
        "HTML-A11Y-FOCUS",
        "HTML-MEDIA-DARK",
        "HTML-MEDIA-MOTION",
        "HTML-MEDIA-NARROW",
        "HTML-MEDIA-PRINT",
    }
    assert not (_codes(markup) & stylesheet)


def test_commented_heading_does_not_fake_a_level_skip():
    markup = '<html lang="ru"><body><!-- <h1>x</h1> --><h3>y</h3></body></html>'
    codes = _codes(markup)
    assert "HTML-HEADING-SKIP" not in codes
    assert "HTML-HEADING-START" in codes


def test_commented_heading_does_not_hide_a_missing_heading():
    markup = '<html lang="ru"><body><!-- <h1>x</h1> --><p>t</p></body></html>'
    assert "HTML-HEADING-MISSING" in _codes(markup)
