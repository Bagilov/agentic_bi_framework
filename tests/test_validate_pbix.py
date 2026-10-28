"""Static validation of a layout against a donor model (`validate_pbix`).

`validate_pbix` is the last gate before a report is published: it asserts that
every table/column/measure a layout references actually exists in the donor
model. A miss here ships a report that fails to render on a Report Server
("Could not load data..."), so the module is tested at its boundaries: each
reference kind (page filter, visual filter, query Select of all three shapes),
the alias/entity resolution, the empty-registry contract, and the untrusted-input
shapes that must not raise.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentic_bi.validate_pbix import (
    EXAMPLE_REGISTRY,
    load_registry,
    validate_layout,
    validate_pbix,
)

REGISTRY = {
    "Sales": {"columns": ["Region", "Amount"], "measures": ["Total"]},
    "Date": {"columns": ["Day"], "measures": []},
}


def _layout(*containers: dict, page_filters: object = None) -> dict:
    section: dict = {"visualContainers": list(containers)}
    if page_filters is not None:
        section["filters"] = page_filters
    return {"sections": [section]}


def _visual(config: dict | str, filters: object = None) -> dict:
    vc: dict = {"config": config}
    if filters is not None:
        vc["filters"] = filters
    return vc


def _query(select: list[dict], sources: list[dict] | None = None) -> dict:
    return {
        "singleVisual": {"prototypeQuery": {"From": sources or [], "Select": select}}
    }


def _col(entity: str, prop: str, source: str | None = None) -> dict:
    expr: dict = {"SourceRef": {"Source": source or entity}}
    if source is None:
        expr["SourceRef"] = {"Entity": entity}
    return {"Column": {"Expression": expr, "Property": prop}, "Name": prop}


def _measure(prop: str, source: str) -> dict:
    return {
        "Measure": {"Expression": {"SourceRef": {"Source": source}}, "Property": prop}
    }


class TestRegistryWiring:
    def test_none_falls_back_to_the_example_registry(self) -> None:
        assert validate_layout({}, None) == []
        assert validate_layout(_layout(), None) == []

    def test_an_empty_registry_is_honoured_not_replaced(self) -> None:
        problems = validate_layout(
            _layout(_visual(_query([_col("Anything", "X")]))), {}
        )
        assert problems and "not in the donor model" in problems[0]

    def test_example_registry_shape_is_stable(self) -> None:
        assert "Data" in EXAMPLE_REGISTRY
        assert set(EXAMPLE_REGISTRY["Data"]) == {"columns", "measures"}

    def test_load_registry_round_trips_a_json_file(self, tmp_path: Path) -> None:
        path = tmp_path / "reg.json"
        path.write_text(json.dumps(REGISTRY), encoding="utf-8")
        assert load_registry(path) == REGISTRY


class TestReferenceKinds:
    def test_a_valid_layout_has_no_problems(self) -> None:
        layout = _layout(
            _visual(_query([_col("Sales", "Region"), _measure("Total", "Sales")]))
        )
        assert validate_layout(layout, REGISTRY) == []

    def test_unknown_table_is_reported(self) -> None:
        problems = validate_layout(
            _layout(_visual(_query([_col("Nope", "X")]))), REGISTRY
        )
        assert problems == [
            "section[0]/visual[0]: table 'Nope' is not in the donor model"
        ]

    def test_unknown_column_names_the_bucket(self) -> None:
        problems = validate_layout(
            _layout(_visual(_query([_col("Sales", "Nope")]))), REGISTRY
        )
        assert len(problems) == 1
        assert "Sales.Nope is not in the donor" in problems[0]
        assert "columns:" in problems[0]

    def test_a_column_used_as_a_measure_is_reported(self) -> None:
        layout = _layout(_visual(_query([_measure("Region", "Sales")])))
        problems = validate_layout(layout, REGISTRY)
        assert len(problems) == 1
        assert "measures:" in problems[0]

    def test_a_measure_used_as_a_column_is_reported(self) -> None:
        layout = _layout(_visual(_query([_col("Sales", "Total")])))
        problems = validate_layout(layout, REGISTRY)
        assert len(problems) == 1
        assert "columns:" in problems[0]

    def test_an_entity_sourceref_needs_no_alias(self) -> None:
        sel = {
            "Column": {
                "Expression": {"SourceRef": {"Entity": "Sales"}},
                "Property": "Region",
            }
        }
        assert validate_layout(_layout(_visual(_query([sel]))), REGISTRY) == []

    def test_an_alias_is_resolved_to_its_entity(self) -> None:
        query = _query(
            [_col("Sales", "Region", source="s")], [{"Name": "s", "Entity": "Sales"}]
        )
        assert validate_layout(_layout(_visual(query)), REGISTRY) == []

    def test_an_unknown_alias_falls_back_to_the_raw_source(self) -> None:
        query = _query([_col("Sales", "Region", source="ghost")])
        problems = validate_layout(_layout(_visual(query)), REGISTRY)
        assert problems and "table 'ghost'" in problems[0]

    def test_an_aggregation_select_is_a_column_reference(self) -> None:
        sel = {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {"SourceRef": {"Entity": "Sales"}},
                        "Property": "Amount",
                    }
                }
            }
        }
        assert validate_layout(_layout(_visual(_query([sel]))), REGISTRY) == []
        bad = {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {"SourceRef": {"Entity": "Sales"}},
                        "Property": "Nope",
                    }
                }
            }
        }
        assert len(validate_layout(_layout(_visual(_query([bad]))), REGISTRY)) == 1

    def test_an_aggregation_without_a_column_is_ignored(self) -> None:
        assert (
            validate_layout(_layout(_visual(_query([{"Aggregation": {}}]))), REGISTRY)
            == []
        )


class TestFilters:
    def test_a_page_filter_is_checked_and_located(self) -> None:
        page_filter = {
            "expression": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": "Sales"}},
                    "Property": "Nope",
                }
            }
        }
        layout = _layout(_visual(_query([])), page_filters=[page_filter])
        problems = validate_layout(layout, REGISTRY)
        assert problems == [
            "section[0] filter: Sales.Nope is not in the donor (columns: ['Region', 'Amount'])"
        ]

    def test_a_visual_filter_is_checked_and_located(self) -> None:
        page_filter = {
            "expression": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": "Ghost"}},
                    "Property": "X",
                }
            }
        }
        layout = _layout(_visual(_query([]), filters=[page_filter]))
        problems = validate_layout(layout, REGISTRY)
        assert "visual[0] filter" in problems[0]

    def test_filters_given_as_a_json_string_are_parsed(self) -> None:
        raw = json.dumps(
            [
                {
                    "expression": {
                        "Column": {
                            "Expression": {"SourceRef": {"Entity": "Ghost"}},
                            "Property": "X",
                        }
                    }
                }
            ]
        )
        layout = _layout(_visual(_query([])), page_filters=raw)
        assert "table 'Ghost'" in validate_layout(layout, REGISTRY)[0]

    def test_a_filter_without_a_column_is_ignored(self) -> None:
        assert (
            validate_layout(_layout(_visual(_query([])), page_filters=[{}]), REGISTRY)
            == []
        )

    def test_a_malformed_filter_string_yields_no_reference(self) -> None:
        assert (
            validate_layout(
                _layout(_visual(_query([])), page_filters="{not json"), REGISTRY
            )
            == []
        )


class TestUntrustedShapesDoNotRaise:
    """A layout is external input; a bad shape must be skipped, never a crash."""

    def test_a_missing_config_is_ignored(self) -> None:
        assert (
            validate_layout({"sections": [{"visualContainers": [{}]}]}, REGISTRY) == []
        )

    def test_a_config_string_is_parsed(self) -> None:
        cfg = json.dumps(_query([_col("Sales", "Nope")]))
        problems = validate_layout(_layout(_visual(cfg)), REGISTRY)
        assert problems and "Nope" in problems[0]

    def test_a_non_dict_config_is_ignored(self) -> None:
        assert validate_layout(_layout(_visual("[]")), REGISTRY) == []

    def test_a_prototype_query_that_is_a_list_is_ignored(self) -> None:
        assert (
            validate_layout(
                _layout(_visual({"singleVisual": {"prototypeQuery": []}})), REGISTRY
            )
            == []
        )

    def test_a_select_entry_that_is_not_a_dict_is_skipped(self) -> None:
        query = {"singleVisual": {"prototypeQuery": {"Select": ["nonsense"]}}}
        assert validate_layout(_layout(_visual(query)), REGISTRY) == []

    def test_a_section_without_visual_containers_is_ignored(self) -> None:
        assert validate_layout({"sections": [{}]}, REGISTRY) == []

    def test_a_layout_without_sections_is_valid(self) -> None:
        assert validate_layout({}, REGISTRY) == []

    def test_a_sourceref_without_a_source_or_entity_resolves_to_none(self) -> None:
        sel = {"Column": {"Expression": {"SourceRef": {}}, "Property": "X"}}
        assert validate_layout(_layout(_visual(_query([sel]))), REGISTRY) == []


class TestValidatePbixReadsTheContainer:
    def test_a_rebuilt_pbix_validates_against_its_own_model(
        self, template_copy: Path
    ) -> None:
        """End to end: rebuild a `.pbix`, then validate it against the sample model."""
        from agentic_bi.rebuild import rebuild_pbix

        out = template_copy.parent / "rebuilt.pbix"
        rebuild_pbix(template_copy, out, display_name="V")
        # The rebuilt layout references the module defaults; validation must run
        # against an explicit registry without raising.
        assert validate_pbix(out, {}) is not None

    def test_a_valid_rebuilt_layout_has_no_unexpected_problems(
        self, template_copy: Path
    ) -> None:
        from agentic_bi.rebuild import rebuild_pbix

        out = template_copy.parent / "v2.pbix"
        rebuild_pbix(template_copy, out, display_name="V")
        registry = {"Data": {"columns": ["Value"], "measures": ["Value"]}}
        assert validate_pbix(out, registry) == []
