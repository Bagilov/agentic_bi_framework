"""Injection regression tests for the dashboard web clone (`web_report`).

Two defects were found and reproduced in a browser before these tests existed:

1. the client model was embedded as `json.dumps(...)` inside `<script>`, and
   `json.dumps` does not escape `<`/`>`, so a `</script>` in any string taken
   from the `.pbix` closed the element and injected script;
2. an element's key was interpolated into a single-quoted JS string inside
   `onclick`; `html.escape` is the wrong escape for that nested context because
   the browser un-escapes the attribute before parsing the JS.

Both strings come from the report itself, so both are attacker-controlled when
the `.pbix` is. These tests pin the fixes: they are one-line changes that a later
refactor could silently undo.
"""

from __future__ import annotations

import json
import re

from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.web_report import inspect_layout, render_html

BREAKOUT = "</script><script>document.title='PWNED'</script>"
JS_BREAKOUT = "P');document.title='PWNED';//"


def _payload_from_html(html: str) -> dict:
    """Extract and parse the embedded client model from the rendered document."""
    marker = "window.__REPORT_MODEL__ = "
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end].rstrip().rstrip(";"))


def _card(title: str = "") -> dict:
    return make_container(
        "card",
        {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
        ["Sum(Sales.amount)"],
        title=title,
    )


def test_visual_title_cannot_close_the_script_element():
    """A `</script>` in a visual title must not break out of the model script."""
    model = inspect_layout(make_layout([_card(title=BREAKOUT)]))
    html = render_html(model)

    assert "</script><script>" not in html
    assert BREAKOUT not in html


def test_visual_title_round_trips_through_the_embedded_model():
    """Escaping the payload must not corrupt the data the client receives."""
    model = inspect_layout(make_layout([_card(title=BREAKOUT)]))
    payload = _payload_from_html(render_html(model))

    assert payload["pages"][0]["elements"][0]["label"] == BREAKOUT


def test_entity_name_in_issue_message_cannot_close_the_script_element():
    """The payload sink has several sources; an issue message is one of them.

    An invalid entity name ends up in a `BIND-TABLE-MISSING` message, so a fix
    applied only to labels would leave this route open.
    """
    container = make_container(
        "tableEx",
        {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
        ["Sum(Sales.amount)"],
        title="ok",
    )
    container["config"] = json.dumps(
        {
            "singleVisual": {
                "visualType": "tableEx",
                "projections": {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
                "prototypeQuery": {
                    "From": [{"Name": "t", "Entity": BREAKOUT, "Type": 0}],
                    "Select": [
                        {
                            "Name": "Sum(Sales.amount)",
                            "Aggregation": {
                                "Function": 0,
                                "Expression": {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Source": "t"}},
                                        "Property": "amount",
                                    }
                                },
                            },
                        }
                    ],
                },
            }
        }
    )
    model = inspect_layout(
        make_layout([container]),
        registry={"Sales": {"columns": ["amount"], "measures": []}},
    )
    html = render_html(model)

    assert any(
        "BIND-TABLE-MISSING" == i.check_id for e in model.elements for i in e.issues
    )
    assert "</script><script>" not in html


def test_page_name_cannot_break_out_of_inline_javascript():
    """The element key (page name + index) must not become executable JS.

    The renderer used to emit ``onclick="showDetails('<key>')"``; a quote in the
    page name ended the JS string after the browser decoded the attribute.
    """
    model = inspect_layout(make_layout([_card()], page=JS_BREAKOUT))
    html = render_html(model)

    for handler in re.findall(r'onclick="([^"]*)"', html):
        assert JS_BREAKOUT not in handler, handler
        assert "document.title" not in handler


def test_element_key_is_carried_in_a_data_attribute():
    """The key reaches the handler through a `data-` attribute, not inline JS."""
    model = inspect_layout(make_layout([_card()], page="Overview"))
    html = render_html(model)

    assert 'data-key="Overview#0"' in html


def test_page_tabs_are_escaped_in_the_document():
    """A page name is also rendered as visible text in the tab strip."""
    model = inspect_layout(make_layout([_card()], page=BREAKOUT))
    html = render_html(model)

    assert BREAKOUT not in html
    assert "&lt;/script&gt;" in html
