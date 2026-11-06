"""Hostile lineage documents must not abort the PDF report.

`lineage.json` is untrusted: it can be hand-edited, produced by an older tool, or
truncated. Before this, a list-typed `summary`/`meta` raised `AttributeError`, a
scalar `pages` raised `TypeError`, a scalar entry in `tables`/`semantics`/`visuals`
raised on `.get`, and an unclosed `<b>` in a header counter raised inside
reportlab's parser — all as tracebacks from a console script that promises exit 2
for a bad input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi.report.lineage_matrix import lineage_to_table
from agentic_bi.report.pdf_report import build_report
from agentic_bi.report.pdf_style import _styles
from agentic_bi.report.pdf_tables import brand_scorecard

HOSTILE_DOCUMENTS: dict[str, object] = {
    "top-level list": [1, 2],
    "top-level string": "not a document",
    "summary list": {"summary": [1, 2]},
    "meta string": {"meta": "abc"},
    "pages int": {"pages": 5},
    "pages string": {"pages": "abc"},
    "pages mixed": {
        "pages": [1, "x", {"name": [1], "visuals": "y", "tables": {"a": 1}}]
    },
    "tables scalar entries": {"tables": {"T": 5, "U": {"source": []}}},
    "sources list": {"sources": []},
    "origin scalar items": {"origin": {"items": [1, {"tables": "x", "stages": [2]}]}},
    "semantics list": {"semantics": []},
    "brand list": {"brand": []},
    "brand pages list": {"brand": {"pages": [1]}},
    "brand summary list": {"brand": {"summary": []}},
    "unclosed markup": {"summary": {"visuals": "<b>"}},
    "unknown markup": {"summary": {"visuals": "<foo>x</foo>"}},
    "markup in brand": {
        "brand": {"summary": {"pages": "<b>", "fonts_compliance": {"x": 1}}}
    },
    "visual brand off items": {
        "pages": [
            {
                "name": "P",
                "visuals": [1, {"brand": {"level": "error", "off": [1, "x"]}}],
            }
        ]
    },
}


@pytest.mark.parametrize(
    "data", HOSTILE_DOCUMENTS.values(), ids=HOSTILE_DOCUMENTS.keys()
)
def test_a_hostile_document_still_produces_a_pdf(data: object, tmp_path: Path) -> None:
    out = build_report(data, tmp_path / "report.pdf")  # type: ignore[arg-type]
    payload = out.read_bytes()
    assert payload.startswith(b"%PDF-")
    assert payload.rstrip().endswith(b"%%EOF")


def test_empty_lineage_renders_no_matrix_rows() -> None:
    assert lineage_to_table([]) == []  # type: ignore[arg-type]
    assert lineage_to_table({"pages": 5}) == []
    assert lineage_to_table({"pages": [1, "x"]}) == []
    # an object page is a page, even when its fields are missing
    assert [row["L6 · Page"] for row in lineage_to_table({"pages": [{}]})] == ["?"]


def test_page_count_is_read_from_the_page_list_when_summary_is_silent() -> None:
    rows = lineage_to_table({"pages": [{"name": "P"}]})
    assert [row["L6 · Page"] for row in rows] == ["P"]


def test_brand_scorecard_ignores_non_object_blocks() -> None:
    styles = _styles("Helvetica", "Helvetica-Bold")
    for data in (
        [],
        {"brand": []},
        {"brand": {"pages": [1]}},
        {"brand": {"summary": [1]}},
    ):
        assert brand_scorecard(data, styles, 500.0) == []  # type: ignore[arg-type]
