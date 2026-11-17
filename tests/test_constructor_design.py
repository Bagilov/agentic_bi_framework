"""Design parsing: the untrusted JSON/YAML surface of the constructor.

A design arrives as a file, so every field is a boundary: a bad type, a duplicate
name or a string where a list belongs must be a `ValueError` that names the page
and the block. The tests pin the accepted shorthand forms too, because a spec
that compiles only in one of them would silently reject half of real input.
"""

from __future__ import annotations

import json

import pytest

from agentic_bi.constructor.design import Design, PageDesign, VisualDesign
from agentic_bi.constructor.model import norm_type, pbixray_type
from agentic_bi.constructor.model_context import ModelContext


def _design(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "Board",
        "pages": [
            {
                "name": "p1",
                "title": "Overview",
                "visuals": [{"kind": "card", "table": "Sales", "value": "amount"}],
            }
        ],
    }
    base.update(overrides)
    return base


class TestColumnTypes:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("INT", "int64"),
            ("integer", "int64"),
            ("bool", "int64"),
            ("float", "double"),
            ("number", "double"),
            ("datetime", "date"),
            ("text", "string"),
            (None, "string"),
        ],
    )
    def test_aliases_normalize_to_the_four_model_types(
        self, raw: object, expected: str
    ) -> None:
        assert norm_type(raw) == expected

    @pytest.mark.parametrize(
        ("dtype", "expected"),
        [
            ("datetime64[ns]", "date"),
            ("Int64", "int64"),
            ("boolean", "int64"),
            ("float64", "double"),
            ("object", "string"),
            ("unknown", "string"),
        ],
    )
    def test_a_pandas_dtype_maps_to_a_model_type(
        self, dtype: str, expected: str
    ) -> None:
        """A model read back from a `.pbix` arrives with pandas dtypes."""
        assert pbixray_type(dtype) == expected

    def test_an_unknown_type_lists_the_allowed_ones(self) -> None:
        with pytest.raises(ValueError) as exc:
            norm_type("money")
        assert "unsupported column type" in str(exc.value)
        assert "int64" in str(exc.value)


class TestModelContext:
    def test_tables_as_an_object_keep_their_column_types(self) -> None:
        model = ModelContext.from_dict(
            {
                "tables": {
                    "Sales": {
                        "columns": {"region": "string", "amount": "double"},
                        "measures": {"Total": "SUM(Sales[amount])"},
                    }
                }
            }
        )
        assert model.tables["Sales"].columns == {"region": "string", "amount": "double"}
        assert model.tables["Sales"].measures["Total"].startswith("SUM")

    def test_tables_as_a_list_accept_every_column_shorthand(self) -> None:
        model = ModelContext.from_dict(
            {
                "tables": [
                    {
                        "name": "Sales",
                        "columns": [
                            "region",
                            {"name": "qty", "type": "int"},
                            ["d", "date"],
                        ],
                    }
                ]
            }
        )
        assert model.tables["Sales"].columns == {
            "region": "string",
            "qty": "int64",
            "d": "date",
        }

    def test_a_duplicate_column_names_the_culprit(self) -> None:
        with pytest.raises(ValueError) as exc:
            ModelContext.from_dict({"tables": {"Sales": {"columns": ["a", "a"]}}})
        assert "duplicate column name 'a'" in str(exc.value)

    def test_a_non_object_model_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            ModelContext.from_dict(["Sales"])
        assert "model must be an object" in str(exc.value)

    def test_registry_lists_columns_and_measures_per_table(self) -> None:
        model = ModelContext.from_dict(
            {"tables": {"Sales": {"columns": ["a"], "measures": ["m"]}}}
        )
        assert model.registry() == {"Sales": {"columns": ["a"], "measures": ["m"]}}

    def test_spec_carries_types_values_and_measures(self) -> None:
        model = ModelContext.from_dict(
            {"tables": {"Sales": {"columns": {"a": "int64"}, "measures": {"m": "1"}}}}
        )
        spec = model.to_spec({"Sales": [{"a": "3"}]})
        table = spec["tables"][0]
        assert table["name"] == "Sales"
        assert table["columns"][0] == {"name": "a", "type": "int64", "values": ["3"]}
        assert spec["measures"] == [{"table": "Sales", "name": "m", "expression": "1"}]

    def test_unknown_tables_in_values_are_rejected(self) -> None:
        model = ModelContext.from_dict({"tables": {"Sales": {"columns": ["a"]}}})
        with pytest.raises(ValueError) as exc:
            model.to_spec({"Other": []})
        assert "unknown tables" in str(exc.value)


class TestDesignParsing:
    def test_a_minimal_design_gets_defaults(self) -> None:
        design = Design.from_dict(
            {"pages": [{"visuals": [{"kind": "card", "table": "t", "value": "a"}]}]}
        )
        page = design.pages[0]
        assert design.name == "dashboard"
        assert page.name == "page_1"
        assert page.title == "page_1"
        assert (page.width, page.height) == (1280, 800)
        assert page.visuals[0].block_id == "page_1_1"

    def test_an_explicit_block_id_wins_over_the_generated_one(self) -> None:
        design = Design.from_dict(
            {
                "pages": [
                    {
                        "name": "p",
                        "visuals": [
                            {"id": "first", "kind": "card", "table": "t", "value": "a"}
                        ],
                    }
                ]
            }
        )
        assert design.pages[0].visuals[0].block_id == "first"

    def test_expected_pages_counts_visuals_per_title(self) -> None:
        design = Design.from_dict(
            {
                "pages": [
                    {
                        "name": "p1",
                        "title": "One",
                        "visuals": [
                            {"kind": "card", "table": "t", "value": "a"},
                            {"kind": "table", "table": "t", "columns": ["a"]},
                        ],
                    },
                    {
                        "name": "p2",
                        "title": "Two",
                        "visuals": [{"kind": "card", "table": "t", "value": "a"}],
                    },
                ]
            }
        )
        assert design.expected_pages() == {"One": 2, "Two": 1}
        assert design.visual_count() == 3
        assert design.kinds() == {"card", "table"}

    def test_load_reads_json_from_disk(self, tmp_path) -> None:
        path = tmp_path / "design.json"
        path.write_text(json.dumps(_design()), encoding="utf-8")
        design = Design.load(path)
        assert design.pages[0].title == "Overview"

    def test_invalid_json_names_the_file(self, tmp_path) -> None:
        path = tmp_path / "design.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            Design.load(path)
        assert "design.json" in str(exc.value)
        assert "invalid JSON" in str(exc.value)

    def test_a_non_object_design_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            Design.from_dict(["pages"])
        assert "design must be an object" in str(exc.value)

    def test_pages_must_be_a_list(self) -> None:
        with pytest.raises(ValueError) as exc:
            Design.from_dict({"pages": {"name": "p"}})
        assert "design.pages must be a list" in str(exc.value)


class TestVisualFields:
    def test_span_must_be_an_integer(self) -> None:
        with pytest.raises(ValueError) as exc:
            VisualDesign.from_dict({"kind": "card", "span": "wide"})
        assert "span must be an integer" in str(exc.value)

    def test_filters_are_parsed_as_objects(self) -> None:
        visual = VisualDesign.from_dict({"kind": "card", "filters": [{"field": "a"}]})
        assert visual.filters == [{"field": "a"}]

    def test_a_scalar_filter_list_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            VisualDesign.from_dict({"kind": "card", "filters": ["a"]})
        assert "must be an object" in str(exc.value)

    def test_a_non_object_page_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            PageDesign.from_dict(["visuals"])
        assert "page[0] must be an object" in str(exc.value)

    def test_visuals_must_be_a_list(self) -> None:
        with pytest.raises(ValueError) as exc:
            PageDesign.from_dict({"name": "p", "visuals": "card"})
        assert "visuals must be a list" in str(exc.value)
