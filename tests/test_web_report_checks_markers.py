"""Independent oracle for `HTML_REQUIRED_MARKUP`.

`test_rendered_document_satisfies_its_own_html_checks` iterates over the same
marker table it validates, so deleting a marker also deletes its assertion. Here
the expected check ids are a literal set, and each marker is proven twice: it is
detected in the real rendered document, and its removal is reported.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.web_report import HTML_REQUIRED_MARKUP, inspect_layout, render_html
from agentic_bi.web_report.web_checks import html_issues

EXPECTED_CHECKS = frozenset(
    {
        "HTML-A11Y-LANG",
        "HTML-A11Y-FOCUS",
        "HTML-A11Y-TABS",
        "HTML-A11Y-TAB-STATE",
        "HTML-A11Y-CONTROLS",
        "HTML-A11Y-INTERACTIVE",
        "HTML-A11Y-DETAIL-TARGET",
        "HTML-A11Y-DETAIL-CLOSE",
        "HTML-A11Y-MODAL",
        "HTML-A11Y-INERT",
        "HTML-MEDIA-DARK",
        "HTML-MEDIA-MOTION",
        "HTML-MEDIA-NARROW",
        "HTML-MEDIA-PRINT",
    }
)

REMOVERS: dict[str, Callable[[str], str]] = {
    "HTML-A11Y-LANG": lambda m: m.replace('<html lang="ru">', "<html>"),
    "HTML-A11Y-FOCUS": lambda m: m.replace(":focus-visible", ":focus"),
    "HTML-A11Y-TABS": lambda m: m.replace('role="tablist"', ""),
    "HTML-A11Y-TAB-STATE": lambda m: m.replace('aria-selected="', 'aria-sel="'),
    "HTML-A11Y-CONTROLS": lambda m: m.replace("aria-label=", "aria-lab="),
    "HTML-A11Y-INTERACTIVE": lambda m: m.replace(
        'role="button" tabindex="0"', 'role="button"'
    ),
    "HTML-A11Y-DETAIL-TARGET": lambda m: m.replace('aria-controls="detailCard"', ""),
    "HTML-A11Y-DETAIL-CLOSE": lambda m: m.replace('id="detailClose"', ""),
    "HTML-A11Y-MODAL": lambda m: m.replace('aria-modal="', 'aria-mod="'),
    "HTML-A11Y-INERT": lambda m: m.replace(
        ' aria-hidden="true" inert=""', ' aria-hidden="true"'
    ),
    "HTML-MEDIA-DARK": lambda m: m.replace("@media (prefers-color-scheme: dark)", ""),
    "HTML-MEDIA-MOTION": lambda m: m.replace(
        "@media (prefers-reduced-motion: reduce)", ""
    ),
    "HTML-MEDIA-NARROW": lambda m: m.replace("@media (max-width: 720px)", ""),
    "HTML-MEDIA-PRINT": lambda m: m.replace("@media print", ""),
}


def _rendered() -> str:
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


def _codes(markup: str) -> set[str]:
    return {i.check_id for i in html_issues(markup)}


def test_marker_table_covers_exactly_the_expected_checks():
    assert {check_id for check_id, _ in HTML_REQUIRED_MARKUP} == EXPECTED_CHECKS


@pytest.mark.parametrize("check_id", sorted(EXPECTED_CHECKS))
def test_each_required_marker_is_detected_and_reported(check_id: str):
    markup = _rendered()
    assert check_id not in _codes(markup), f"{check_id} false positive"
    broken = REMOVERS[check_id](markup)
    assert broken != markup, f"remover for {check_id} changed nothing"
    assert check_id in _codes(broken), f"{check_id} not reported after removal"


def test_modality_marker_requires_the_non_modal_value():
    """The popover is not modal; `aria-modal="true"` would trap-screen-reader users."""
    markup = _rendered()
    assert "HTML-A11Y-MODAL" not in _codes(markup)
    broken = markup.replace('aria-modal="false"', 'aria-modal="true"')
    assert broken != markup
    assert "HTML-A11Y-MODAL" in _codes(broken)


def test_missing_popover_markup_is_reported():
    markup = _rendered()
    broken = re.sub(
        r'\s(?:id="detailClose"|aria-controls="detailCard"|aria-modal="[^"]*")',
        "",
        markup,
    )
    broken = broken.replace(' tabindex="-1"', "").replace(' inert=""', "")
    codes = _codes(broken)
    assert {
        "HTML-A11Y-DETAIL-CLOSE",
        "HTML-A11Y-DETAIL-TARGET",
        "HTML-A11Y-MODAL",
        "HTML-A11Y-INERT",
    } <= codes


@pytest.mark.parametrize(
    "needle",
    [
        ' aria-label="Закрыть детали элемента"',
        ' aria-label="Открыть панель фильтров"',
    ],
)
def test_every_labelled_control_needs_its_own_aria_label(needle: str):
    markup = _rendered()
    assert "HTML-A11Y-CONTROLS" not in _codes(markup)
    assert "HTML-A11Y-CONTROLS" in _codes(markup.replace(needle, ""))


def test_element_box_needs_its_own_aria_label():
    markup = _rendered()
    broken = re.sub(r'(<div class="el [^>]*?) aria-label="[^"]*"', r"\1", markup)
    assert broken != markup
    assert "HTML-A11Y-CONTROLS" in _codes(broken)
