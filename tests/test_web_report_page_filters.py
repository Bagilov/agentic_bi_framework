"""Page-level filter diagnostics for the web clone.

`Report/Layout` carries filters on both levels: `visualContainers[].filters` and
`sections[].filters`. Only the first was inspected, so an unsafe `Condition.In`
on a page was invisible to `web_report` while `engine.verify_filters` reported
it. The page-level findings must be counted *and* rendered: a number in the
summary with no place in the document is not a usable diagnostic.
"""

from __future__ import annotations

import json
import re

from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.web_report import inspect_layout, render_html
from agentic_bi.web_report.web_filter_checks import has_in_filter, unsafe_in_filter

_SALES = [{"Name": "t", "Entity": "Sales", "Type": 0}]


def _page_with_filters(filters: str) -> dict:
    container = make_container(
        "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
    )
    layout = make_layout([container])
    layout["sections"][0]["filters"] = filters
    return layout


def _unsafe_in() -> str:
    """An `In` on an alias the filter's own `From` does not declare."""
    return json.dumps(
        [
            {
                "type": "Categorical",
                "filter": {
                    "Version": 2,
                    "From": _SALES,
                    "Where": [
                        {
                            "Condition": {
                                "In": {
                                    "Expressions": [
                                        {
                                            "Column": {
                                                "Expression": {
                                                    "SourceRef": {"Source": "ghost"}
                                                },
                                                "Property": "amount",
                                            }
                                        }
                                    ],
                                    "Values": [[{"Literal": {"Value": "'1'"}}]],
                                }
                            }
                        }
                    ],
                },
            }
        ]
    )


def test_page_level_unsafe_in_is_reported_and_rendered():
    model = inspect_layout(_page_with_filters(_unsafe_in()), source="p.pbix")
    page = model.pages[0]
    assert [i.check_id for i in page.filter_issues] == ["FILTER-UNSAFE-IN"]
    assert page.issues == 1
    assert model.errors == 1
    markup = render_html(model)
    assert "Замечания страницы" in markup
    assert "FILTER-UNSAFE-IN" in markup
    assert 'class="badge error"' in markup


def test_page_level_issues_show_up_on_an_empty_page_too():
    layout = make_layout([], page="Empty")
    layout["sections"][0]["filters"] = _unsafe_in()
    model = inspect_layout(layout, source="p.pbix")
    markup = render_html(model)
    assert "Замечания страницы" in markup
    assert "Страница без визуалов" in markup
    # the page tab badge counts the filter finding as well
    assert 'aria-label="Empty, замечаний: 1"' in markup


def test_page_level_unreadable_payload_is_a_filter_issue():
    model = inspect_layout(_page_with_filters("{not json"), source="p.pbix")
    codes = [i.check_id for i in model.pages[0].filter_issues]
    assert codes == ["FILTER-UNREADABLE"]
    assert model.errors == 1


def test_clean_page_filters_add_nothing():
    layout = make_layout(
        [make_container("card", {"Values": [{"queryRef": "Sales.amount"}]}, ["a"])]
    )
    layout["sections"][0]["filters"] = "[]"
    model = inspect_layout(layout, source="p.pbix")
    assert model.pages[0].filter_issues == []
    assert "Замечания страницы" not in render_html(model)


def test_tri_state_keeps_unsafe_and_unreadable_apart():
    assert unsafe_in_filter(_unsafe_in()) is True
    assert unsafe_in_filter("[]") is False
    assert unsafe_in_filter("{not json") is None
    # the boolean view stays fail-closed for anything unreadable
    assert has_in_filter("{not json") is True
    assert has_in_filter("[]") is False


def test_page_level_findings_are_selectable_in_the_filter_panel():
    """A finding the panel cannot name cannot be isolated.

    Measured before: the `#filter-check` options were built from element issues
    only, so `FILTER-UNSAFE-IN` (a page-level filter check) was missing.
    """
    model = inspect_layout(_page_with_filters(_unsafe_in()), source="p.pbix")
    markup = render_html(model)
    assert '<option value="FILTER-UNSAFE-IN">FILTER-UNSAFE-IN</option>' in markup


def test_page_level_findings_are_marked_for_the_severity_filter():
    model = inspect_layout(_page_with_filters(_unsafe_in()), source="p.pbix")
    markup = render_html(model)
    item = re.search(r'<li data-severity="[^"]*" data-check="[^"]*">', markup)
    assert item, "the notice item must carry the filter keys"
    assert 'data-check="FILTER-UNSAFE-IN"' in item.group(0)
    assert 'data-severity="error"' in item.group(0)
    script = markup[markup.index("const MODEL") :]
    assert "querySelectorAll('.page-issues li')" in script
    assert "li.classList.toggle('dim'" in script


def test_page_findings_are_dimmed_on_screen_and_restored_for_print():
    """The filter toggles `.dim` on page notices; it needs a screen rule.

    Measured before: the only `.page-issues li.dim` declaration lived in the
    print block and set `opacity:1`, so isolating a finding on screen changed
    nothing and the user could not tell which notices were filtered out.
    """
    model = inspect_layout(_page_with_filters(_unsafe_in()), source="p.pbix")
    markup = render_html(model)
    css = markup[markup.index("<style>") : markup.index("</style>")]
    screen, print_block = css.split("@media print", 1)
    assert ".page-issues li.dim { opacity:0.25; }" in screen
    assert ".page-issues li.dim { opacity:1; }" in print_block


def test_a_page_only_match_is_not_reported_as_zero_elements():
    """A page-level finding belongs to no element, so it must still pick its page.

    Measured before (real `SCRIPT` in Chrome): selecting `FILTER-UNSAFE-IN`, whose
    only match is a page notice, switched no page, left the notice inside a
    `display:none` panel and printed "0 элементов показано".
    """
    markup = render_html(
        inspect_layout(_page_with_filters(_unsafe_in()), source="p.pbix")
    )
    body = markup[markup.index("function applyFilters") :]
    assert "notices.find(li => !li.classList.contains('dim'))" in body
    assert "Number(wrap.dataset.page)" in body
    assert "замечаний страницы" in body


def test_the_metrics_table_carries_the_same_filter_keys_as_the_elements():
    """The table honoured only severity, so page/kind/check isolation never dimmed it."""
    markup = render_html(
        inspect_layout(_page_with_filters(_unsafe_in()), source="p.pbix")
    )
    row = re.search(r"<tr data-detail=\"[^\"]*\"[^>]*>", markup)
    assert row, "the details table must have a row"
    for attr in ("data-severity=", "data-page-idx=", "data-kind=", "data-checks="):
        assert attr in row.group(0)
    body = markup[markup.index("function applyFilters") :]
    assert "!matches(tr, sev, page, kind, check)" in body


def test_a_carriage_return_in_a_page_name_survives_the_attribute_round_trip():
    """The HTML parser folds CR to LF, so a raw CR key never matched its JSON entry."""
    layout = _page_with_filters("[]")
    layout["sections"][0]["displayName"] = "A\rB"
    markup = render_html(inspect_layout(layout, source="p.pbix"))
    assert 'data-key="0:A&#13;B#0"' in markup


def test_a_nul_in_a_page_name_is_scrubbed_before_it_reaches_the_document():
    """A literal NUL becomes U+FFFD in an attribute, so the key could not round-trip."""
    layout = _page_with_filters("[]")
    layout["sections"][0]["displayName"] = "A\x00B"
    markup = render_html(inspect_layout(layout, source="p.pbix"))
    assert "\x00" not in markup
    assert "A\ufffdB" in markup


def test_the_printed_document_does_not_spend_a_sheet_on_the_header():
    """`header` and the summary grid are screen chrome and must not be printed.

    Measured before: a one-page 1280x720 report printed as **three** sheets, with
    the canvas pushed off the sheet that carried only the title and the counters.
    """
    markup = render_html(inspect_layout(_page_with_filters("[]"), source="p.pbix"))
    css = markup[markup.index("<style>") : markup.index("</style>")]
    print_block = css.split("@media print", 1)[1]
    hide = re.search(r"([^{}]*)\{ display:none !important; \}", print_block)
    assert hide, "the print block must still strip chrome"
    for selector in ("header", ".stats-grid", ".page-tabs"):
        assert selector in hide.group(1)
