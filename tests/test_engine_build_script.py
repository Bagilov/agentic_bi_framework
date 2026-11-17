"""Contract of the PowerShell engine build script (ported R9 model builder).

The script runs only on a Windows host, so its text is the only thing a macOS CI
can assert. Each expectation below is a defect measured on the guest:

* `DATATABLE` rejects a `BLANK()`/`DATEVALUE()` literal whose type does not match
  the declared column, so rows are built with `Table.FromRows` +
  `Table.TransformColumnTypes`;
* non-invariant number formatting turned `1.5` into `1,5` on a comma locale;
* a `\\r\\n` inside a string value ended the M string literal;
* TOM rejects a measure whose name collides with a column, and a relationship
  needs the tables persisted first (columns have server IDs only after a save).
"""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "src" / "agentic_bi" / "_engine_build.ps1"
)


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


class TestEngineModes:
    def test_the_mode_is_a_documented_parameter(self, script: str) -> None:
        assert "[ValidateSet('dax', 'm')]" in script
        assert "$engineMode" in script

    def test_a_spec_may_override_the_mode(self, script: str) -> None:
        assert "PSObject.Properties['mode']" in script
        assert "unknown mode" in script

    def test_a_custom_query_forces_the_m_path(self, script: str) -> None:
        assert "$useM = ($engineMode -eq 'm') -or" in script


class TestDaxMode:
    def test_rows_are_built_with_datatable(self, script: str) -> None:
        assert "$daxExpr = 'DATATABLE('" in script

    def test_null_is_the_null_literal(self, script: str) -> None:
        assert "$vals += 'null'" in script
        code = "\n".join(
            line for line in script.splitlines() if not line.lstrip().startswith("#")
        )
        assert "BLANK()" not in code

    def test_a_date_is_date_plus_time(self, script: str) -> None:
        assert "+TIME('" in script

    def test_the_declared_types_match_the_literals(self, script: str) -> None:
        for dax_type in ("INTEGER", "DOUBLE", "DATETIME", "STRING"):
            assert dax_type in script

    def test_numbers_are_formatted_with_the_invariant_culture(
        self, script: str
    ) -> None:
        assert "string]::Format([Globalization.CultureInfo]::InvariantCulture" in script

    def test_string_values_strip_carriage_returns_and_newlines(
        self, script: str
    ) -> None:
        assert ".Replace(\"`r\",' ')" in script
        assert ".Replace(\"`n\",' ')" in script


class TestMMode:
    def test_rows_are_built_with_table_from_rows(self, script: str) -> None:
        assert "Table.FromRows(" in script
        assert "Table.TransformColumnTypes(" in script

    def test_type_parts_are_nested_pairs(self, script: str) -> None:
        # A flat list ({"a", type text}) is not the M signature.
        assert "$typeParts += ('{\"' + $cd.name + '\", ' + $ty + '}')" in script

    def test_dates_become_datetime_literals(self, script: str) -> None:
        assert "#datetime(" in script

    def test_column_types_map_to_m_types(self, script: str) -> None:
        for m_type in ("Int64.Type", "type number", "type datetime", "type text"):
            assert m_type in script


class TestPartitionSourceTypes:
    def test_an_import_partition_uses_an_m_source(self, script: str) -> None:
        # A calculated (DAX) source here built a model that opened but held no
        # rows: the M expression became the DAX of a calculated table.
        assert "'Microsoft.AnalysisServices.Tabular.MPartitionSource'" in script

    def test_a_calculated_table_uses_a_calculated_source(self, script: str) -> None:
        assert (
            "'Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource'" in script
        )
        code = "\n".join(
            line for line in script.splitlines() if not line.lstrip().startswith("#")
        )
        assert "CalculationExpression" not in code


class TestModelFeatures:
    def test_a_table_may_supply_a_custom_m_query(self, script: str) -> None:
        assert "PSObject.Properties['query']" in script
        assert "uses custom M query" in script

    def test_a_calculated_dax_table_skips_the_partition(self, script: str) -> None:
        assert "CalculationExpression" in script

    def test_a_measure_name_colliding_with_a_column_is_skipped(
        self, script: str
    ) -> None:
        assert "name collides with column" in script

    def test_the_model_culture_is_optional(self, script: str) -> None:
        assert "$specObj.culture" in script
        assert "culture skipped" in script

    def test_relationships_are_many_to_one_with_cross_filtering(
        self, script: str
    ) -> None:
        assert "SingleColumnRelationship" in script
        assert "RelationshipEndCardinality]::Many" in script
        assert "RelationshipEndCardinality]::One" in script
        assert "BothDirections" in script

    def test_relationships_are_added_after_the_first_save(self, script: str) -> None:
        first_save = script.index("Write-Output 'model saved'")
        relationships = script.index("SingleColumnRelationship")
        assert first_save < relationships

    def test_missing_relationship_parts_are_reported_not_fatal(
        self, script: str
    ) -> None:
        assert "relationship skipped: table missing" in script
        assert "relationship skipped: column missing" in script

    def test_a_failed_refresh_fails_the_build(self, script: str) -> None:
        # An ImageSave with unloaded segments produces a model whose visuals are
        # all blank, so a refresh error must not be swallowed.
        assert 'throw ("refresh failed' in script

    def test_an_unprocessed_model_is_reported(self, script: str) -> None:
        assert "model stayed " in script
        assert "$state -ne 'Ready'" in script

    def test_the_hard_check_is_opt_in(self, script: str) -> None:
        # This VM's Desktop refused to process a TOM-created database at all, so
        # failing hard by default would break every build there.
        assert "$RequireProcessed" in script
        assert "WARNING: " in script

    def test_refresh_runs_on_the_build_connection(self, script: str) -> None:
        # A second connection left the database Unprocessed on the guest, so the
        # refresh stays on the connection that created the model.
        assert "$srv3" not in script
        assert "$tb.RequestRefresh" in script


class TestHostContract:
    def test_the_binary_directory_is_configurable(self, script: str) -> None:
        assert "$env:PBI_RS_BIN" in script

    def test_the_workspace_root_is_configurable(self, script: str) -> None:
        assert "$env:PBI_RS_WS_ROOT" in script

    def test_a_live_port_is_honoured_over_a_stale_workspace(self, script: str) -> None:
        assert "$Port -gt 0" in script
        assert "no live engine port found" in script
