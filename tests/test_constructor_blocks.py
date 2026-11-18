"""Block catalogue and block -> `Visual` conversion.

A block is the constructor's unit of input, so its contract is a public API: the
catalogue must describe every kind (an agent reads it instead of the sources),
Power BI visual-type aliases must resolve, and a malformed field must be a
`ValueError` naming the block rather than a visual that silently ignores it.
"""

from __future__ import annotations

import pytest

from agentic_bi.constructor.blocks import (
    AGGREGATIONS,
    ALIASES,
    BLOCKS,
    catalog,
    make_visual,
    resolve_kind,
)


class TestResolveKind:
    @pytest.mark.parametrize("kind", sorted(BLOCKS))
    def test_every_catalogued_kind_resolves_to_itself(self, kind: str) -> None:
        assert resolve_kind(kind) == kind

    @pytest.mark.parametrize(("alias", "canonical"), sorted(ALIASES.items()))
    def test_power_bi_aliases_map_to_the_canonical_kind(
        self, alias: str, canonical: str
    ) -> None:
        assert resolve_kind(alias) == canonical

    def test_unknown_kind_lists_the_available_ones(self) -> None:
        with pytest.raises(ValueError) as exc:
            resolve_kind("treemap")
        assert "unknown block kind" in str(exc.value)
        assert "card" in str(exc.value)


class TestCatalog:
    def test_catalog_is_json_ready_and_covers_every_block(self) -> None:
        entries = catalog()
        assert {entry["kind"] for entry in entries} == set(BLOCKS)
        for entry in entries:
            assert isinstance(entry["required"], list)
            assert isinstance(entry["optional"], list)
            assert isinstance(entry["default_span"], int)

    def test_required_fields_do_not_overlap_optional_ones(self) -> None:
        for spec in BLOCKS.values():
            assert not set(spec.required) & set(spec.optional), spec.kind

    def test_the_visual_type_is_the_engine_catalogue_value(self) -> None:
        """A duplicated type table would let the catalogue advertise a name the
        engine does not emit (the verify step then calls it unknown)."""
        from agentic_bi.engine.layout_catalog import _VISUAL_TYPES

        for kind, spec in BLOCKS.items():
            assert spec.visual_type == _VISUAL_TYPES[kind]

    def test_every_declared_field_is_understood_by_the_visual(self) -> None:
        """A field the catalogue advertises but `make_visual` drops is a lie."""
        handled = {
            "table",
            "columns",
            "axis",
            "value",
            "measure",
            "agg",
            "extra_values",
            "title",
            "description",
            "tooltip",
            "pos",
            "span",
        }
        for spec in BLOCKS.values():
            assert (set(spec.required) | set(spec.optional)) <= handled, spec.kind


class TestMakeVisual:
    def test_card_with_a_measure_carries_the_measure_not_a_value(self) -> None:
        visual = make_visual({"kind": "card", "table": "Sales", "measure": "Total"})
        assert visual.measure == "Total"
        assert visual.value is None

    def test_extra_values_survive_for_a_line_chart(self) -> None:
        visual = make_visual(
            {
                "kind": "line",
                "table": "Sales",
                "axis": "day",
                "value": "done",
                "extra_values": ["failed"],
            }
        )
        assert visual.extra_values == ["failed"]

    def test_title_and_tooltip_are_carried_as_text(self) -> None:
        visual = make_visual(
            {
                "kind": "table",
                "table": "Sales",
                "columns": ["region"],
                "title": "Regions",
                "description": "one row per region",
                "tooltip": "source: sales",
            }
        )
        assert visual.title == "Regions"
        assert visual.description == "one row per region"
        assert visual.tooltip == "source: sales"

    def test_pos_is_normalized_to_four_ints(self) -> None:
        visual = make_visual(
            {"kind": "table", "table": "t", "columns": ["a"], "pos": ["10", 20, 30, 40]}
        )
        assert visual.pos == (10, 20, 30, 40)

    @pytest.mark.parametrize("bad_pos", [[1, 2, 3], "0,0,10,10", [1, 2, 3, "x"]])
    def test_a_malformed_pos_names_the_candidate(self, bad_pos: object) -> None:
        with pytest.raises(ValueError) as exc:
            make_visual(
                {"kind": "table", "table": "t", "columns": ["a"], "pos": bad_pos}
            )
        assert "pos" in str(exc.value)

    @pytest.mark.parametrize(
        "bad_pos", [[True, 2, 3, 4], [1.5, 2, 3, 4], [1, 2, 3, 4.25]]
    )
    def test_a_bool_or_fractional_pos_is_rejected(self, bad_pos: object) -> None:
        with pytest.raises(ValueError) as exc:
            make_visual(
                {"kind": "table", "table": "t", "columns": ["a"], "pos": bad_pos}
            )
        assert "pos" in str(exc.value)

    def test_an_integral_float_pos_is_accepted(self) -> None:
        visual = make_visual(
            {"kind": "table", "table": "t", "columns": ["a"], "pos": [10.0, 20, 30, 40]}
        )
        assert visual.pos == (10, 20, 30, 40)

    @pytest.mark.parametrize("bad_pos", [["1_0", 2, 3, 4], ["١٢٣", 2, 3, 4]])
    def test_python_only_integer_syntax_in_pos_is_rejected(
        self, bad_pos: object
    ) -> None:
        with pytest.raises(ValueError):
            make_visual(
                {"kind": "table", "table": "t", "columns": ["a"], "pos": bad_pos}
            )

    def test_an_unsupported_aggregation_names_the_block(self) -> None:
        with pytest.raises(ValueError) as exc:
            make_visual({"kind": "card", "table": "t", "value": "a", "agg": "mode"})
        assert "card: unsupported agg" in str(exc.value)

    @pytest.mark.parametrize("agg", AGGREGATIONS)
    def test_every_documented_aggregation_is_accepted(self, agg: str) -> None:
        visual = make_visual({"kind": "card", "table": "t", "value": "a", "agg": agg})
        assert visual.agg == agg

    def test_columns_as_a_string_is_rejected_instead_of_splitting(self) -> None:
        with pytest.raises(ValueError) as exc:
            make_visual({"kind": "table", "table": "t", "columns": "region"})
        assert "must be a list of names" in str(exc.value)
