"""Render + integration tests for the dashboard web clone (`web_report`).

The render tests use in-memory layouts; the integration tests use the shipped
donor template and a board built from scratch.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.web_report import (
    build_model,
    inspect_layout,
    render_html,
    write_html,
)
from agentic_bi.web_report.web_render import _model_payload


def test_render_html_draws_layout_with_tools():
    layout = make_layout(
        [
            make_container(
                "card",
                {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
                ["Sum(Sales.amount)"],
                title="Total",
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    html = render_html(model, title="T")
    # layout canvas with geometry and a mock SVG glyph
    assert 'class="canvas"' in html
    assert 'class="el ' in html
    assert "<svg" in html
    # tooltips + filters + detail popover
    assert "title=" in html and "нарушений нет" in html
    assert 'id="filter-check"' in html
    assert 'id="detailCard"' in html
    assert 'onclick="showPage(0)"' in html
    # the model payload is valid JSON and carries geometry
    start = html.index("window.__REPORT_MODEL__ = ")
    end = html.index("};", start) + 1
    payload = json.loads(html[start + len("window.__REPORT_MODEL__ = ") : end])
    el = payload["pages"][0]["elements"][0]
    assert el["label"] == "Total"
    assert "width" in el and "height" in el


def test_render_marks_problem_elements():
    layout = make_layout(
        [
            make_container(
                "columnChart",
                {"Category": [{"queryRef": "Sales.region"}]},
                ["Sales.region"],
                title="By region",
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    html = render_html(model)
    # the missing required role is an error -> the box is outlined as error
    assert 'class="el error"' in html
    assert "STRUCT-MISSING-ROLE" in html


def test_model_payload_round_trips_issues():
    layout = make_layout(
        [
            make_container(
                "columnChart",
                {"Category": [{"queryRef": "Sales.region"}]},
                ["Sales.region"],
                title="By region",
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    payload = _model_payload(model)
    codes = [i["check_id"] for i in payload["pages"][0]["elements"][0]["issues"]]
    assert "STRUCT-MISSING-ROLE" in codes


def test_write_html_creates_file(tmp_path: Path):
    layout = make_layout(
        [
            make_container(
                "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
            ),
        ]
    )
    model = inspect_layout(layout, source="l.pbix")
    out = write_html(model, tmp_path / "clone.html")
    assert out.exists() and out.stat().st_size > 0


def test_cli_writes_clone(template_pbix: Path, tmp_path: Path):
    from agentic_bi.web_report.web_cli import main

    out = tmp_path / "cli_clone.html"
    rc = main(["--pbix", str(template_pbix), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "window.__REPORT_MODEL__" in body


def test_build_model_on_donor_template(template_pbix: Path):
    model = build_model(template_pbix)
    assert len(model.pages) >= 1
    assert len(model.elements) >= 1
    assert model.summary()["pages"] == len(model.pages)


def _build_board(template: Path, out: Path) -> Path:
    from agentic_bi import engine_container, engine_layout
    from agentic_bi.engine_layout import Visual

    with zipfile.ZipFile(template) as z:
        names = set(z.namelist())
        datamodel = z.read("DataModel")
    copy_members = [
        m
        for m in engine_container.COPY_MEMBERS
        if m in names and m not in ("Report/Layout", "DataModel")
    ]
    page = [
        Visual(
            "card",
            "Opportunities",
            value="Probability",
            agg="avg",
            title="Avg probability",
        ),
        Visual(
            "column",
            "Opportunities",
            axis="Sales Stage",
            value="Value",
            agg="sum",
            title="Value by stage",
        ),
    ]
    layout = engine_layout.build_report([("Overview", page)])
    engine_container.build_container(
        template, layout, datamodel, out, copy_members=copy_members
    )
    return out


def test_build_model_on_built_board(template_pbix: Path, tmp_path: Path):
    """End-to-end: build a board, clone it, and expect a clean element set."""
    board = _build_board(template_pbix, tmp_path / "board.pbix")
    model = build_model(board)
    assert model.summary()["pages"] == 1
    assert model.summary()["elements"] == 2
    assert model.errors == 0
    assert "Overview" in render_html(model)


def test_clean_element_badge_is_ok(template_pbix: Path, tmp_path: Path):
    """A visual with no issues renders an OK badge and 'ok' severity."""
    board = _build_board(template_pbix, tmp_path / "board.pbix")
    html = render_html(build_model(board))
    assert 'class="el ok"' in html
    assert '<span class="badge ok">OK</span>' in html
