"""The PDF lineage matrix, its page budget and its summary line.

Two defects from the round table:

* `use_l7 = include_visuals or max_level >= 7` was true for every default run, so
  all L1-L6 rows printed through `L7_COLS` and lost their origin/source/table/
  semantics cells (the summary layout was unreachable);
* a `None` average was interpolated verbatim ("Averages: fonts None%").
"""

from __future__ import annotations

import pytest

from agentic_bi.report.pdf_style import _styles
from agentic_bi.report.pdf_tables import SUMMARY_COLS, lineage_matrix


def _styles_or_skip():
    pytest.importorskip("reportlab")
    return _styles("Helvetica", "Helvetica-Bold")


def _row(level: int) -> dict:
    row = {col: "" for col in SUMMARY_COLS}
    row.update(
        {
            "Level": level,
            "Layer": f"L{level}",
            "L1 · Origin": "sales.csv",
            "L2 · Source": "Sales",
            "L4 · Table": "Sales",
            "L5 · Semantics": "3 measures",
            "Detail / Source": "detail",
            "Refs": 1,
            "Brand · fonts, %": 90,
            "Brand · colors, %": 80,
            "Brand · status": "ok",
        }
    )
    row["L7 · Visual"] = f"card #{level}"
    return row


def _tables(story: list) -> list:
    from reportlab.platypus import Table

    return [f for f in story if isinstance(f, Table)]


def test_identity_rows_keep_the_summary_layout() -> None:
    styles = _styles_or_skip()
    story = lineage_matrix(
        [_row(1), _row(4), _row(7)], styles, 700.0, max_level=7, include_visuals=True
    )
    tables = _tables(story)
    assert len(tables) == 2, "one table for levels 1-6, one for level 7"
    headers = [
        [cell.text for cell in table._cellvalues[0]]  # type: ignore[attr-defined]
        for table in tables
    ]
    assert "L1 · Origin" in headers[0]
    assert "L4 · Table" in headers[0]
    assert "L7 · Visual" in headers[1]


def test_without_visuals_only_the_summary_layout_is_used() -> None:
    styles = _styles_or_skip()
    story = lineage_matrix(
        [_row(1), _row(4)], styles, 700.0, max_level=6, include_visuals=False
    )
    headers = [cell.text for cell in _tables(story)[0]._cellvalues[0]]  # type: ignore[attr-defined]
    assert "L1 · Origin" in headers
    assert "L7 · Visual" not in headers


def test_the_identity_row_carries_its_origin_text() -> None:
    """The old L7 layout dropped the `L1 · Origin` cell entirely."""
    styles = _styles_or_skip()
    story = lineage_matrix([_row(1)], styles, 700.0, max_level=7, include_visuals=True)
    table = _tables(story)[0]
    flat = [
        cell.text  # type: ignore[attr-defined]
        for row in table._cellvalues  # type: ignore[attr-defined]
        for cell in row
    ]
    assert "sales.csv" in flat


def test_a_missing_average_prints_as_not_available() -> None:
    """`None%` came from interpolating an unmeasured average."""
    from agentic_bi.report.pdf_tables import brand_scorecard

    styles = _styles_or_skip()
    story = brand_scorecard(
        {
            "brand": {
                "summary": {
                    "pages": 2,
                    "fonts_compliance": None,
                    "colors_compliance": None,
                }
            }
        },
        styles,
        700.0,
    )
    text = " ".join(getattr(flowable, "text", "") for flowable in story)
    assert "None%" not in text
    assert "n/a" in text
