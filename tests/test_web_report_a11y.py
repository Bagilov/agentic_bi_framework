"""Accessibility / theme / responsive / print regression tests for `web_report`.

The renderer emits a single HTML document; these tests pin the contract that a
later refactor could silently drop: landmarks and heading order, keyboard and
ARIA semantics, empty states, theme/media-query blocks, and the matching
`web_checks.html_issues` guard.

Each test is written so the mutation it guards against actually fails it (for
example: a one-page fixture used to make the tab-state assertion tautological).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.web_report_fixtures import make_container, make_layout, raw_container

from agentic_bi.web_report import (
    HTML_REQUIRED_MARKUP,
    inspect_layout,
    render_html,
)
from agentic_bi.web_report.web_checks import html_issues

_TOKEN_RE = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;]+);")


def _card(title: str = "Total") -> dict:
    return make_container(
        "card",
        {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
        ["Sum(Sales.amount)"],
        title=title,
    )


def _rendered() -> str:
    return render_html(inspect_layout(make_layout([_card()]), source="l.pbix"))


def _two_pages() -> str:
    layout = make_layout([_card("A")], page="Overview")
    layout["sections"].append(
        {
            "displayName": "Sales",
            "width": 1280,
            "height": 720,
            "visualContainers": [_card("B")],
        }
    )
    return render_html(inspect_layout(layout, source="l.pbix"))


def _script(markup: str) -> str:
    return markup[markup.index("const MODEL") :]


def _css_block(markup: str, header: str) -> str:
    """Return the body of the first CSS block whose header is `header`."""
    if header not in markup:
        raise AssertionError(f"CSS block {header!r} is missing from the document")
    start = markup.index(header)
    opening = markup.index("{", start)
    depth = 0
    for pos in range(opening, len(markup)):
        if markup[pos] == "{":
            depth += 1
        elif markup[pos] == "}":
            depth -= 1
            if depth == 0:
                return markup[opening + 1 : pos]
    raise AssertionError(f"unbalanced block for {header!r}")


def _tokens(block: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in _TOKEN_RE.finditer(block)}


def _tag(markup: str, needle: str) -> str:
    """The single opening tag carrying `needle`."""
    tags = re.findall(r"<[A-Za-z][^>]*" + re.escape(needle) + r"[^>]*>", markup)
    assert tags, needle
    return tags[0]


def test_rendered_document_satisfies_its_own_html_checks():
    markup = _rendered()
    assert html_issues(markup) == []
    for check_id, needle in HTML_REQUIRED_MARKUP:
        assert needle in markup, check_id


def test_tabs_expose_state_and_only_the_active_tab_is_focusable():
    markup = _two_pages()
    assert markup.count('role="tab"') == 2
    assert 'aria-selected="true" tabindex="0"' in markup
    # a one-page fixture made this tautological before; two pages force the
    # inactive branch to exist and to be asserted.
    assert 'aria-selected="false" tabindex="-1"' in markup
    assert 'aria-controls="pagePanel0"' in markup
    assert 'role="tabpanel"' in markup
    assert 'aria-labelledby="pageTab0"' in markup


def test_tab_label_does_not_leak_the_badge_count():
    markup = _two_pages()
    assert 'aria-label="Overview, замечаний: 0"' in markup
    assert 'aria-label="Sales, замечаний: 0"' in markup
    assert '<span class="tab-badge" aria-hidden="true">' in markup


def test_show_page_synchronises_selected_state_and_tabindex():
    show = _script(_rendered())
    body = show[show.index("function showPage") : show.index("function onTabKey")]
    assert "setAttribute('aria-selected'" in body
    assert "setAttribute('tabindex'" in body


def test_interactive_element_is_keyboard_reachable_and_labelled():
    markup = _rendered()
    assert 'role="button" tabindex="0"' in markup
    assert 'aria-haspopup="dialog"' in markup
    assert 'aria-controls="detailCard"' in markup
    assert 'aria-label="Total, card,' in markup


def test_element_keyboard_handler_cancels_default_scrolling():
    script = _script(_rendered())
    start = script.index("document.addEventListener('DOMContentLoaded'")
    block = script[start : script.index("document.getElementById('pageTabs')")]
    assert "addEventListener('keydown'" in block
    assert "ev.preventDefault()" in block


def test_filter_controls_have_labels_and_a_status_region():
    markup = _rendered()
    toggle = _tag(markup, 'id="filterToggle"')
    assert 'aria-expanded="false"' in toggle
    assert 'aria-label="Открыть панель фильтров"' in toggle
    assert 'aria-controls="filterPanel"' in toggle
    assert 'aria-label="Закрыть панель фильтров"' in markup
    # the counter announces politely but is not a second role=status region:
    # both assertions have to describe the same tag, not unrelated substrings.
    count = _tag(markup, 'id="filter-count"')
    assert 'aria-live="polite"' in count
    assert "role=" not in count
    live = _tag(markup, 'role="status"')
    assert 'id="detailLive"' in live


def test_closed_filter_panel_is_hidden_inert_and_returns_focus():
    markup = _rendered()
    panel = _tag(markup, 'id="filterPanel"')
    assert 'aria-hidden="true"' in panel
    assert "inert" in panel
    script = _script(markup)
    body = script[
        script.index("function toggleFilterPanel") : script.index(
            "function resetFilters"
        )
    ]
    assert "panel.inert = !open" in body
    assert "setAttribute('aria-hidden'" in body
    assert "toggle.focus()" in body
    # the toggle's accessible name follows the expanded state: assert the
    # conditional itself, not just that both strings exist somewhere.
    label = script[
        script.index("function setFilterToggleLabel") : script.index(
            "function toggleFilterPanel"
        )
    ]
    assert "open ? 'Закрыть панель фильтров' : 'Открыть панель фильтров'" in label


def test_detail_dialog_is_focusable_and_closable_by_a_visible_button():
    markup = _rendered()
    card = _tag(markup, 'id="detailCard"')
    assert 'role="dialog"' in card
    assert 'tabindex="-1"' in card
    assert "aria-live" not in card
    close = _tag(markup, 'id="detailClose"')
    assert 'aria-label="Закрыть детали элемента"' in close
    # the live region is a separate node that is always rendered
    live = _tag(markup, 'id="detailLive"')
    assert 'aria-live="polite"' in live
    assert 'role="status"' in live
    script = _script(markup)
    show = script[
        script.index("function showDetails") : script.index("function hideDetails")
    ]
    assert "card.focus()" in show


def test_empty_state_is_not_a_live_region():
    markup = render_html(inspect_layout({"sections": []}, source="empty.pbix"))
    empty = _tag(markup, 'class="empty-state"')
    assert "role=" not in empty
    # the only live region left is the persistent detail announcement
    assert markup.count('role="status"') == 1
    assert 'id="detailLive"' in _tag(markup, 'role="status"')


def test_heading_order_starts_at_h1_without_skips():
    markup = _rendered()
    issues = [i for i in html_issues(markup) if i.check_id.startswith("HTML-HEADING")]
    assert issues == []
    assert markup.index("<h1") < markup.index("<h2")


def test_printed_canvas_has_a_page_heading():
    markup = _rendered()
    assert '<h2 class="canvas-title">P</h2>' in markup


def test_focus_is_visible_and_colors_are_not_hardcoded_white():
    markup = _rendered()
    assert ":focus-visible" in markup
    assert "outline:3px solid var(--focus)" in markup
    normalised = re.sub(r"\s+", "", markup.lower())
    # case-normalised; "#fff" also catches its "#ffffff" prefix form
    assert "color:#fff" not in normalised
    assert "color:white" not in normalised
    assert "color:rgb(255,255,255)" not in normalised


def test_dark_theme_uses_its_own_token_values():
    dark = _tokens(_css_block(_rendered(), "@media (prefers-color-scheme: dark)"))
    assert dark["text"] == "#e6ecf3"
    assert dark["muted"] == "#9aa7b8"
    assert dark["surface"] == "#141a2f"
    assert dark["accent"] == "#00d4ff"
    assert dark["body-ink"] == "#9fd8ff"


def test_print_block_overrides_every_dark_token_and_keeps_ink_dark():
    markup = _rendered()
    dark = _tokens(_css_block(markup, "@media (prefers-color-scheme: dark)"))
    printed = _tokens(_css_block(markup, "@media print"))
    assert set(printed) == set(dark), "print must redefine the dark theme tokens"
    assert printed["text"] == "#000"
    assert printed["muted"] != dark["muted"]
    assert printed["accent"] != dark["accent"]
    assert printed["body-ink"] != dark["body-ink"]


def test_print_block_keeps_severity_fills_and_expands_details():
    block = _css_block(_rendered(), "@media print")
    assert "print-color-adjust:exact" in block
    assert "details:not([open]) > *:not(summary)" in block
    assert "#metrics-table" in block
    assert ".canvas-title" in block
    assert "a[href]::after" not in block


def test_theme_motion_responsive_and_print_blocks_are_present():
    markup = _rendered()
    assert "@media (prefers-color-scheme: dark)" in markup
    assert "@media print" in markup
    assert "@media (max-width: 720px)" in markup
    # the print chrome is hidden by display:none, however the selectors are split
    block = _css_block(markup, "@media print")
    hidden = [
        selector
        for rule in block.split("}")
        if "display:none !important" in rule
        for selector in [rule.split("{")[0]]
    ]
    joined = " ".join(hidden)
    for selector in (".filter-panel", "#detailCard", ".page-tabs"):
        assert selector in joined, selector


def test_narrow_tables_scroll_horizontally():
    block = _css_block(_rendered(), ".table-scroll")
    assert "overflow-x:auto" in block


def test_reduced_motion_block_disables_transitions_and_animations():
    block = _css_block(_rendered(), "@media (prefers-reduced-motion: reduce)")
    assert "transition:none !important" in block
    assert "animation:none !important" in block
    assert "*::before" in block


def test_active_tab_has_a_border_and_forced_colors_rule():
    markup = _rendered()
    active = _css_block(markup, ".tab.active")
    assert "border-bottom:3px solid var(--accent)" in active
    forced = _css_block(markup, "@media (forced-colors: active)")
    assert ".tab.active" in forced


def test_empty_report_renders_an_explicit_empty_state():
    markup = render_html(inspect_layout({"sections": []}, source="empty.pbix"))
    assert "В отчёте нет визуалов" in markup
    assert 'class="empty-state"' in markup
    assert 'id="pageTabs"' not in markup
    assert 'id="filterPanel"' not in markup
    assert html_issues(markup) == []


def test_page_without_visuals_gets_a_page_empty_state():
    markup = render_html(inspect_layout(make_layout([], page="Empty"), source="l"))
    assert "Страница без визуалов" in markup
    assert "«Empty»" in markup


def test_visual_without_data_gets_a_placeholder():
    container = raw_container(
        {"singleVisual": {"visualType": "card", "projections": {}}}
    )
    markup = render_html(inspect_layout(make_layout([container]), source="l"))
    assert "Нет данных для этого визуала" in markup
    # the empty state is presentational under role="button": the accessible name
    # has to carry the state instead.
    assert "без данных" in _tag(markup, 'data-el="1"')


def test_decorative_visual_is_labelled_static_not_empty():
    container = raw_container(
        {
            "singleVisual": {
                "visualType": "textbox",
                "projections": {},
                "prototypeQuery": {},
            }
        }
    )
    markup = render_html(inspect_layout(make_layout([container]), source="l"))
    assert "Статический элемент" in markup
    # the state must be in the accessible name, not only in visible body text
    assert "статический элемент" in _tag(markup, 'data-el="1"')


def test_html_checks_flag_missing_markers():
    markup = _rendered()
    broken = markup.replace('<html lang="ru">', "<html>")
    style = markup[markup.index("<style>") + 7 : markup.index("</style>")]
    broken = broken.replace(style, style.replace("@media print", "@media screen"))
    broken = broken.replace('role="button" tabindex="0"', 'role="button"')
    codes = {i.check_id for i in html_issues(broken)}
    assert "HTML-A11Y-LANG" in codes
    assert "HTML-MEDIA-PRINT" in codes
    assert "HTML-A11Y-INTERACTIVE" in codes


def test_html_checks_flag_heading_skip():
    codes = {i.check_id for i in html_issues("<h1>a</h1><h3>b</h3>")}
    assert "HTML-HEADING-SKIP" in codes


def test_cli_missing_pbix_is_a_clean_input_error(capsys):
    from agentic_bi.web_report.web_cli import main

    rc = main(["--pbix", "/nope/missing.pbix", "--out", "/tmp/x.html"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "agentic-bi-web-clone: error:" in err
    assert "Traceback" not in err


def test_cli_bad_registry_is_a_clean_input_error(
    template_pbix: Path, tmp_path: Path, capsys
):
    from agentic_bi.web_report.web_cli import main

    reg = tmp_path / "reg.json"
    reg.write_text("{not json", encoding="utf-8")
    rc = main(
        [
            "--pbix",
            str(template_pbix),
            "--out",
            str(tmp_path / "o.html"),
            "--registry",
            str(reg),
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "некорректный JSON" in err
    assert "Traceback" not in err


def test_model_payload_still_round_trips_after_markup_changes():
    markup = _rendered()
    start = markup.index("window.__REPORT_MODEL__ = ")
    end = markup.index("};", start) + 1
    payload = json.loads(markup[start + len("window.__REPORT_MODEL__ = ") : end])
    assert payload["pages"][0]["elements"][0]["label"] == "Total"
