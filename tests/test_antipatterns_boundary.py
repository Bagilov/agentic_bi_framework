"""Boundary validation of the pbixray model consumed by the antipattern analysis.

`analyze_board_objects` accepts an arbitrary object (`object`), so the snapshot
layer validates its shape once. A missing member or row column must raise a
path-qualified `ValueError`, not an `AttributeError`/`KeyError` halfway through
the report — and a foreign object must never be silently treated as empty.
"""

from __future__ import annotations

import pytest

from agentic_bi.antipatterns.model_snapshot import snapshot_model
from agentic_bi.antipatterns.pbi_antipatterns import analyze_board_objects


class _Series:
    """A pandas-Series-like row: read a cell by column name."""

    def __init__(self, cells: dict[str, object]) -> None:
        self._cells = cells

    def __getitem__(self, key: str) -> object:
        return self._cells[key]


class _Frame:
    """A pandas-DataFrame-like frame with `iterrows()`."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def iterrows(self) -> list[tuple[int, object]]:
        return list(enumerate(self._rows))


class _Model:
    """A duck-typed pbixray model: only the members under test."""

    def __init__(self, **members: object) -> None:
        for name, value in members.items():
            setattr(self, name, value)


def _measure(name: str, expr: str, table: str = "T") -> _Series:
    return _Series({"TableName": table, "Name": name, "Expression": expr})


def _model(**overrides: object) -> _Model:
    members: dict[str, object] = {
        "power_query": {"T": "let Source = 1 in Source"},
        "dax_measures": _Frame([_measure("M1", "SUM([A])")]),
        "dax_columns": _Frame(
            [_Series({"TableName": "T", "ColumnName": "C", "Expression": "1"})]
        ),
        "schema": _Frame([_Series({"TableName": "T", "ColumnName": "A"})]),
        "tables": ["T"],
    }
    members.update(overrides)
    return _Model(**members)


class TestSnapshot:
    def test_a_valid_model_is_snapshotted(self) -> None:
        snap = snapshot_model(_model())
        assert [s.table for s in snap.sources] == ["T"]
        assert [m.name for m in snap.measures] == ["M1"]
        assert [c.column for c in snap.columns] == ["C"]
        assert snap.schema_tables == ["T"]
        assert snap.tables == ["T"]

    def test_a_frame_power_query_is_read_row_by_row(self) -> None:
        frame = _Frame(
            [
                _Series({"TableName": "A", "Expression": "x"}),
                _Series({"TableName": "B", "Expression": "y"}),
            ]
        )
        snap = snapshot_model(_model(power_query=frame))
        assert [(s.table, s.expression) for s in snap.sources] == [
            ("A", "x"),
            ("B", "y"),
        ]

    def test_an_empty_model_snapshots_to_empty_lists(self) -> None:
        snap = snapshot_model(
            _model(
                power_query={},
                dax_measures=_Frame([]),
                dax_columns=_Frame([]),
                schema=_Frame([]),
                tables=[],
            )
        )
        assert (snap.sources, snap.measures, snap.columns, snap.tables) == (
            [],
            [],
            [],
            [],
        )


class TestSnapshotErrors:
    def test_a_missing_member_is_named(self) -> None:
        model = _model()
        del model.schema
        with pytest.raises(ValueError, match="model has no 'schema'"):
            snapshot_model(model)

    def test_a_missing_row_column_names_the_row(self) -> None:
        model = _model(dax_measures=_Frame([_Series({"Name": "M"})]))
        with pytest.raises(
            ValueError, match=r"dax_measures\[0\]\.TableName' is missing"
        ):
            snapshot_model(model)

    def test_a_non_string_table_name_is_rejected(self) -> None:
        model = _model(
            dax_columns=_Frame(
                [_Series({"TableName": 7, "ColumnName": "C", "Expression": ""})]
            )
        )
        with pytest.raises(ValueError, match=r"TableName': expected string, got int"):
            snapshot_model(model)

    def test_a_power_query_of_an_unknown_shape_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"power_query': expected"):
            snapshot_model(_model(power_query=42))

    def test_tables_must_be_a_list_of_names(self) -> None:
        with pytest.raises(ValueError, match="tables': expected a list of names"):
            snapshot_model(_model(tables="T"))

    def test_a_non_string_table_entry_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"tables\[1\]': expected string"):
            snapshot_model(_model(tables=["T", 3]))

    def test_a_non_frame_measures_table_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"dax_measures': expected a frame"):
            snapshot_model(_model(dax_measures=[_measure("M", "1")]))


class TestAnalyzeBoardObjects:
    def test_findings_are_grouped_by_level(self) -> None:
        data = analyze_board_objects(
            _model(
                power_query={"T": "SELECT * FROM T"},
                dax_measures=_Frame([_measure("M1", "CALCULATE(SUM([A]))", table="T")]),
            )
        )
        assert data["summary"]["counts"] == {
            "sources": 1,
            "measures": 1,
            "calc_columns": 1,
            "tables": 1,
        }
        ids = {f["id"] for f in data["findings"]["measure"]}
        assert "dax.calculate_no_filter" in ids
        assert data["findings"]["source"][0]["scope"] == "T"

    def test_a_non_string_expression_is_not_code_not_an_error(self) -> None:
        model = _model(
            power_query={"T": 42},
            dax_measures=_Frame([_measure("M", 42)]),
            dax_columns=_Frame(
                [_Series({"TableName": "T", "ColumnName": "C", "Expression": 42})]
            ),
        )
        data = analyze_board_objects(model)
        assert data["summary"]["total_findings"] == 0

    def test_an_empty_model_reports_zeroes(self) -> None:
        data = analyze_board_objects(
            _model(
                power_query={},
                dax_measures=_Frame([]),
                dax_columns=_Frame([]),
                schema=_Frame([]),
                tables=[],
            )
        )
        assert data["summary"]["total_findings"] == 0
        assert data["summary"]["by_level"] == {}

    def test_pages_add_board_findings(self) -> None:
        pages = [
            {
                "name": "p1",
                "n_visuals": 20,
                "elements": {},
                "colors": [],
                "tables": ["T"],
            }
        ]
        data = analyze_board_objects(_model(), pages=pages)
        assert {f["id"] for f in data["findings"]["board"]} == {"board.page_overload"}

    def test_many_measures_are_all_counted(self) -> None:
        measures = [_measure(f"M{i}", "SUM([A])", table="T") for i in range(50)]
        data = analyze_board_objects(
            _model(
                power_query={},
                dax_measures=_Frame(measures),
                dax_columns=_Frame([]),
                schema=_Frame([]),
                tables=["T"],
            )
        )
        assert data["summary"]["counts"]["measures"] == 50
