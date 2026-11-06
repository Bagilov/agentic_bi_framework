"""Tests for the flat level matrix (`report.lineage_matrix`).

`lineage_to_table` is the single producer the PDF and Excel exports share, and
its rows mix text with numbers: `Level`/`Refs` are counts that stay integers so
a spreadsheet can sort/filter them, while the level columns stay text. These
tests pin that split and the origin -> source link the matrix exists for.
"""

from __future__ import annotations

from agentic_bi.report.lineage_matrix import (
    COLUMNS,
    LEVEL,
    _blank_row,
    lineage_to_table,
)


def test_blank_row_keeps_level_numeric_and_other_columns_text() -> None:
    row = _blank_row(4)
    assert row["Level"] == 4
    assert isinstance(row["Level"], int)
    assert row["Layer"] == LEVEL[4]
    assert all(row[c] == "" for c in COLUMNS if c not in ("Level", "Layer"))


def test_lineage_to_table_links_origin_to_source_with_numeric_refs() -> None:
    data = {
        "origin": {
            "items": [
                {
                    "key": "excel",
                    "label": "Excel file",
                    "category": "origin-file",
                    "tables": ["Sales"],
                }
            ]
        },
        "sources": {"by_table": {"Sales": {"type": "Excel", "detail": "book.xlsx"}}},
        "tables": {"Sales": {"refs": 3}},
    }
    rows = lineage_to_table(data)
    origin = next(r for r in rows if r["Level"] == 1)
    source = next(r for r in rows if r["Level"] == 2)
    assert origin["L1 · Origin"] == "Excel file"
    assert origin["Goes to"] == "Sales"
    assert origin["Refs"] == 1
    assert isinstance(origin["Refs"], int)
    assert source["L2 · Source"] == "Sales"
    assert source["Came from"] == "Excel file"
    assert source["Refs"] == 3
    assert isinstance(source["Refs"], int)


def test_lineage_to_table_of_empty_json_has_no_rows() -> None:
    assert lineage_to_table({}) == []
