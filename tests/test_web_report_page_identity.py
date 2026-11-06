"""Page identity: two pages may share a display name, so keys must not.

A Power BI report can hold two pages called "Overview"; the layout's
`section.name` GUID distinguishes them. The clone keyed elements as
`page#index`, so `BY_KEY` kept one entry per colliding key: clicking an element
on the second page opened the first page's details and label, and the filter
jumped to the wrong page. Page names are also coerced, because a numeric
`displayName` otherwise disagreed with the string `ElementReport.page`.
"""

from __future__ import annotations

import re

from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.web_report import inspect_layout, render_html
from agentic_bi.web_report.web_model import (
    ElementReport,
    Issue,
    PageReport,
    WebReportModel,
)


def _card(title: str) -> dict:
    return make_container(
        "card",
        {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
        ["Sum(Sales.amount)"],
        title=title,
    )


def _two_pages() -> dict:
    layout = make_layout([_card("FIRST")], page="Overview")
    second = make_layout([_card("SECOND")], page="Overview")["sections"][0]
    layout["sections"].append(second)
    return layout


def test_duplicate_page_names_keep_distinct_element_keys() -> None:
    model = inspect_layout(_two_pages(), source="d.pbix")
    keys = [e.key for e in model.elements]
    assert len(keys) == 2
    assert len(set(keys)) == 2
    assert model.pages[0].elements[0].page_ordinal == 0
    assert model.pages[1].elements[0].page_ordinal == 1


def test_the_client_model_keeps_both_pages_lookupable() -> None:
    html = render_html(inspect_layout(_two_pages(), source="d.pbix"))
    keys = re.findall(r'"key": "([^"]+)"', html)
    assert len(keys) == 2
    assert len(set(keys)) == 2
    assert 'data-key="0:Overview#0"' in html
    assert 'data-key="1:Overview#0"' in html


def test_a_numeric_page_name_matches_the_element_page() -> None:
    layout = make_layout([_card("A")])
    layout["sections"][0]["displayName"] = 7
    model = inspect_layout(layout, source="n.pbix")
    assert model.pages[0].name == "7"
    assert model.elements[0].page == "7"
    assert model.elements[0].key == "0:7#0"


def test_a_page_name_that_is_not_text_falls_back() -> None:
    page = PageReport(["name"])  # type: ignore[arg-type]
    assert page.name == "Page"
    assert PageReport("").name == "Page"


def test_each_element_carries_its_page_ordinal() -> None:
    """The filter must match by page index: names are not identifiers."""
    html = render_html(inspect_layout(_two_pages(), source="d.pbix"))
    assert 'data-page-idx="0"' in html
    assert 'data-page-idx="1"' in html
    script = html[html.index("const MODEL") :]
    assert "el.dataset.pageIdx !== page" in script


def test_non_issue_entries_in_a_public_model_are_dropped() -> None:
    """`PageReport`/`ElementReport` are public; a dict must not reach the renderer."""
    page = PageReport(
        "P",
        elements=[
            ElementReport(
                page="P",
                index=0,
                visual_type="card",
                issues=[{"severity": "error"}, "error", 5, Issue("X", "info", "m")],
            )
        ],
        filter_issues=[{"severity": "error"}, "error", None, Issue("Y", "error", "n")],
    )
    model = WebReportModel(source="m.pbix", pages=[page])
    html = render_html(model)
    assert "X: m" in html
    assert "Y: n" in html
    assert page.filter_issues and len(page.filter_issues) == 1
    assert len(page.elements[0].issues) == 1


def test_an_unknown_severity_does_not_raise() -> None:
    """A public `Issue` may carry a severity outside the literal vocabulary."""
    page = PageReport(
        "P",
        elements=[
            ElementReport(
                page="P",
                index=0,
                visual_type="card",
                issues=[Issue("X", "critical", "m")],
            )
        ],
        filter_issues=[Issue("Y", "critical", "n")],
    )
    html = render_html(WebReportModel(source="m.pbix", pages=[page]))
    assert "X: m" in html
    assert "Y: n" in html
