"""A derived database name must be legal for TOM.

`EnginePipeline.run` and the example builder derive the model name from the
output file stem, and the guest chain builds a per-run name
`<stem>.<token>.pbix`. TOM rejects `.` in an object name, so every one of those
builds failed with "The 'Name' property cannot contain ..." (reproduced on the
guest). The sanitizer is the single place that knows the rule.
"""

from __future__ import annotations

import pytest

from agentic_bi.engine.core import EnginePipeline, database_name


class TestDatabaseName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Board", "Board"),
            ("board.4706163d", "board_4706163d"),
            ("Sales, Q1", "Sales_ Q1"),
            ("a/b\\c", "a_b_c"),
            ("[x]{y}<z>", "_x__y__z_"),
            ("  Board  ", "Board"),
            ("", "Board"),
        ],
    )
    def test_forbidden_punctuation_becomes_an_underscore(
        self, raw: str, expected: str
    ) -> None:
        assert database_name(raw) == expected

    @pytest.mark.parametrize("ch", list(".,;'`:/\\*|\"?&%$!+=()[]{}<>"))
    def test_no_forbidden_character_survives(self, ch: str) -> None:
        assert ch not in database_name(f"a{ch}b")

    def test_build_spec_sanitizes_the_database(self) -> None:
        spec = EnginePipeline.build_spec(
            [{"a": "1", "b": "x"}], table="Sales", database="board.4706163d"
        )
        assert spec["database"] == "board_4706163d"

    def test_the_table_name_is_left_to_the_model_context(self) -> None:
        """Only the database is derived from a path; tables are model objects."""
        spec = EnginePipeline.build_spec([{"a": "1"}], "Sales", "Board")
        assert spec["tables"][0]["name"] == "Sales"


class TestEngineMode:
    """The row encoding is a build-script contract, so it travels in the spec."""

    def test_the_mode_is_carried_into_the_spec(self) -> None:
        spec = EnginePipeline.build_spec([{"a": "1"}], "T", "Board", mode="m")
        assert spec["mode"] == "m"

    def test_no_mode_leaves_the_script_default(self) -> None:
        spec = EnginePipeline.build_spec([{"a": "1"}], "T", "Board")
        assert "mode" not in spec

    def test_an_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            EnginePipeline.build_spec([{"a": "1"}], "T", "Board", mode="pq")
        assert "use dax or m" in str(exc.value)
