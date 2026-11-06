"""Boundary validation of the declarative dashboard spec.

A spec arrives as JSON/YAML, so every field is checked before it becomes a typed
record: a bad value must name the exact path and raise `ValueError` (the CLI maps
it to exit code 2), never a bare `KeyError`/`AttributeError` deep in the builder.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.spec import (
    DashboardSpec,
    ElementSpec,
    PageSpec,
    from_dict,
    load,
    spec_to_board,
    validate_spec,
)


def _doc(**dashboard: object) -> dict[str, object]:
    dash: dict[str, object] = {
        "name": "Board",
        "table": "Data",
        "pages": [{"name": "p1"}],
    }
    dash.update(dashboard)
    return {"dashboard": dash}


def _elements(*elements: object) -> dict[str, object]:
    return _doc(pages=[{"name": "p1", "elements": list(elements)}])


class TestHappyPath:
    def test_minimal_document_is_accepted(self) -> None:
        spec = from_dict(_doc())
        assert spec.name == "Board"
        assert spec.table == "Data"
        assert [p.name for p in spec.pages] == ["p1"]
        assert validate_spec(spec) == []

    def test_flat_document_without_the_dashboard_wrapper(self) -> None:
        spec = from_dict({"name": "D", "table": "T", "pages": [{"name": "P"}]})
        assert spec.name == "D"
        assert spec.pages[0].name == "P"

    def test_every_element_type_is_parsed(self) -> None:
        spec = from_dict(
            _elements(
                {"type": "kpi", "field": {"kind": "measure", "property": "m"}},
                {
                    "type": "chart",
                    "axis": {"kind": "column", "property": "c"},
                    "value": {"kind": "measure", "property": "m"},
                },
                {"type": "table", "fields": [{"property": "c"}]},
            )
        )
        assert [e.type for e in spec.pages[0].elements] == ["kpi", "chart", "table"]

    def test_position_is_normalized_to_four_integers(self) -> None:
        spec = from_dict(
            _elements(
                {"type": "table", "fields": [{"property": "c"}], "pos": [1, 2, 3, 4]}
            )
        )
        assert spec.pages[0].elements[0].pos == [1, 2, 3, 4]

    def test_load_reads_a_json_document(self, tmp_path: Path) -> None:
        path = tmp_path / "board.json"
        path.write_text(json.dumps(_doc()), encoding="utf-8")
        assert load(path).name == "Board"

    def test_load_reads_a_yaml_document(self, tmp_path: Path) -> None:
        pytest.importorskip("yaml")
        path = tmp_path / "board.yaml"
        path.write_text("dashboard:\n  name: Y\n  table: T\n", encoding="utf-8")
        assert load(path).name == "Y"


class TestEmptyAndMaximum:
    def test_an_empty_document_keeps_the_old_problem_report(self) -> None:
        spec = from_dict({})
        problems = validate_spec(spec)
        assert "Missing dashboard.name" in problems
        assert any("No pages" in p for p in problems)

    def test_zero_pages_parse_and_are_reported(self) -> None:
        spec = from_dict(_doc(pages=[]))
        assert spec.pages == []
        assert any("No pages" in p for p in validate_spec(spec))

    def test_many_pages_and_elements_are_accepted(self) -> None:
        pages = [
            {"name": f"p{i}", "elements": [{"type": "kpi", "field": {"property": "m"}}]}
            for i in range(200)
        ]
        spec = from_dict(_doc(pages=pages))
        assert len(spec.pages) == 200
        assert validate_spec(spec) == []


class TestDocumentShape:
    def test_root_must_be_a_mapping(self) -> None:
        with pytest.raises(ValueError, match=r"document': expected mapping, got list"):
            from_dict([])

    def test_dashboard_must_be_a_mapping(self) -> None:
        with pytest.raises(ValueError, match=r"dashboard': expected mapping, got str"):
            from_dict({"dashboard": "nope"})

    def test_page_index_is_named_in_the_error(self) -> None:
        with pytest.raises(ValueError, match=r"pages\[1\]': expected mapping"):
            from_dict(_doc(pages=[{"name": "p1"}, "p2"]))

    def test_page_name_must_be_a_string(self) -> None:
        with pytest.raises(
            ValueError, match=r"pages\[0\]\.name': expected string, got int"
        ):
            from_dict(_doc(pages=[{"name": 5}]))

    def test_quality_must_be_a_mapping(self) -> None:
        with pytest.raises(ValueError, match=r"quality': expected mapping, got list"):
            from_dict({**_doc(), "quality": []})


class TestElementShape:
    def test_unknown_element_type_keeps_the_old_message(self) -> None:
        with pytest.raises(ValueError, match="Unknown element type 'gauge'"):
            from_dict(_elements({"type": "gauge"}))

    def test_element_type_must_be_a_string(self) -> None:
        with pytest.raises(
            ValueError,
            match=r"pages\[0\]\.elements\[0\]\.type': expected string, got int",
        ):
            from_dict(_elements({"type": 2}))

    def test_visual_type_must_be_a_string(self) -> None:
        with pytest.raises(ValueError, match=r"elements\[0\]\.visual_type"):
            from_dict(_elements({"type": "chart", "visual_type": 1}))

    def test_field_kind_must_be_a_string(self) -> None:
        # Mirrors `spec: field 'visuals[2].kind': expected string, got int`; the
        # exact path includes the element and the field mapping.
        with pytest.raises(
            ValueError,
            match=r"elements\[0\]\.field\.kind': expected string, got int",
        ):
            from_dict(_elements({"type": "kpi", "field": {"kind": 3}}))

    def test_field_property_must_be_a_string(self) -> None:
        with pytest.raises(ValueError, match=r"elements\[0\]\.field\.property"):
            from_dict(_elements({"type": "kpi", "field": {"property": ["a"]}}))

    def test_a_null_field_entry_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"fields\[0\]': expected mapping"):
            from_dict(_elements({"type": "table", "fields": [None]}))

    def test_pos_must_have_four_values(self) -> None:
        with pytest.raises(ValueError, match=r"elements\[0\]\.pos': expected"):
            from_dict(_elements({"type": "table", "pos": [1, 2]}))

    def test_pos_values_must_be_integers(self) -> None:
        with pytest.raises(ValueError, match=r"elements\[0\]\.pos\[3\]"):
            from_dict(_elements({"type": "table", "pos": [1, 2, 3, "4"]}))

    def test_bool_is_not_an_integer_position(self) -> None:
        with pytest.raises(ValueError, match=r"pos\[0\]': expected integer, got bool"):
            from_dict(_elements({"type": "table", "pos": [True, 0, 1, 1]}))

    def test_filters_must_be_strings(self) -> None:
        with pytest.raises(ValueError, match=r"filters\[0\]': expected string"):
            from_dict(_doc(pages=[{"name": "p1", "filters": [1]}]))


class TestSpecToBoardGuards:
    def test_a_valid_hand_built_spec_builds(self) -> None:
        spec = DashboardSpec(
            name="D",
            table="T",
            pages=[
                PageSpec(
                    name="P",
                    elements=[
                        ElementSpec(
                            type="kpi",
                            field={"kind": "measure", "property": "m"},
                        )
                    ],
                )
            ],
        )
        assert spec_to_board(spec).visuals()

    def test_missing_kpi_field_names_the_path(self) -> None:
        spec = DashboardSpec(
            name="D",
            table="T",
            pages=[PageSpec(name="P", elements=[ElementSpec("kpi")])],
        )
        with pytest.raises(ValueError, match=r"pages\[0\]\.elements\[0\]\.field"):
            spec_to_board(spec)

    def test_field_without_property_is_rejected(self) -> None:
        el = ElementSpec(type="kpi", field={"kind": "measure"})
        spec = DashboardSpec(name="D", table="T", pages=[PageSpec("P", elements=[el])])
        with pytest.raises(ValueError, match=r"\.field\.property"):
            spec_to_board(spec)

    def test_unknown_field_kind_is_rejected(self) -> None:
        el = ElementSpec(type="kpi", field={"property": "m", "kind": "mesure"})
        spec = DashboardSpec(name="D", table="T", pages=[PageSpec("P", elements=[el])])
        with pytest.raises(ValueError, match="expected one of"):
            spec_to_board(spec)

    def test_table_without_fields_is_rejected(self) -> None:
        spec = DashboardSpec(
            name="D", table="T", pages=[PageSpec("P", elements=[ElementSpec("table")])]
        )
        with pytest.raises(ValueError, match=r"\.fields': expected list"):
            spec_to_board(spec)

    def test_chart_without_axis_is_rejected(self) -> None:
        el = ElementSpec(
            type="chart", axis=None, value={"kind": "measure", "property": "m"}
        )
        spec = DashboardSpec(name="D", table="T", pages=[PageSpec("P", elements=[el])])
        with pytest.raises(ValueError, match=r"\.axis"):
            spec_to_board(spec)

    def test_a_short_position_is_rejected(self) -> None:
        el = ElementSpec(type="kpi", field={"property": "m"}, pos=[1, 2])
        spec = DashboardSpec(name="D", table="T", pages=[PageSpec("P", elements=[el])])
        with pytest.raises(ValueError, match=r"\.pos': expected \[x, y, w, h\]"):
            spec_to_board(spec)
