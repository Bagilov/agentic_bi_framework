"""Tests for `agentic_bi.settings`: the one place donor object names live.

The framework builds layouts that reference model objects (tables, columns,
measures) which must already exist in the donor DataModel. Those names used to be
baked into each entry point's signature as `fact_table`/`kpi_measures`; they now
resolve through `settings` (explicit argument > environment > neutral default),
so the shipped code describes no particular model. These tests pin the resolution
order and that the callers actually honour it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi import settings

_ENV_VARS = (
    "PBI_MODEL_TABLE",
    "PBI_MODEL_MEASURE_TABLE",
    "PBI_MODEL_COLUMN",
    "PBI_MODEL_MEASURE",
)


@pytest.fixture(autouse=True)
def _clean_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from a developer's ambient model-name environment."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class TestDefaults:
    def test_defaults_are_neutral_not_donor_specific(self) -> None:
        assert settings.DEFAULT_TABLE == "Data"
        assert settings.DEFAULT_COLUMN == "Value"
        assert settings.DEFAULT_MEASURE == "Value"

    def test_no_donor_name_survives_in_the_defaults(self) -> None:
        blob = f"{settings.DEFAULTS}".lower()
        assert "fact_table" not in blob
        assert "kpi_measures" not in blob

    def test_default_model_matches_the_module_defaults(self) -> None:
        assert settings.default_model() == settings.DEFAULTS

    def test_measure_table_defaults_to_none(self) -> None:
        assert settings.DEFAULTS.measure_table is None


class TestEnvironmentResolution:
    @pytest.mark.parametrize(
        ("var", "value", "field"),
        [
            ("PBI_MODEL_TABLE", "Sales", "table"),
            ("PBI_MODEL_MEASURE_TABLE", "KPI", "measure_table"),
            ("PBI_MODEL_COLUMN", "Region", "column"),
            ("PBI_MODEL_MEASURE", "Total", "measure"),
        ],
    )
    def test_each_variable_overrides_its_field(
        self, monkeypatch: pytest.MonkeyPatch, var: str, value: str, field: str
    ) -> None:
        monkeypatch.setenv(var, value)
        assert getattr(settings.default_model(), field) == value

    def test_a_blank_variable_is_treated_as_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PBI_MODEL_TABLE", "")
        assert settings.default_model().table == settings.DEFAULT_TABLE

    def test_environment_does_not_mutate_the_module_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PBI_MODEL_TABLE", "Sales")
        settings.default_model()
        assert settings.DEFAULTS.table == settings.DEFAULT_TABLE


class TestResolveModel:
    def test_explicit_argument_beats_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PBI_MODEL_TABLE", "FromEnv")
        assert settings.resolve_model(table="FromArg").table == "FromArg"

    def test_none_falls_through_to_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PBI_MODEL_COLUMN", "Region")
        assert settings.resolve_model(column=None).column == "Region"

    def test_an_explicit_measure_table_is_kept(self) -> None:
        assert settings.resolve_model(measure_table="KPI").measure_table == "KPI"

    def test_resolve_model_is_frozen(self) -> None:
        import dataclasses

        names = settings.resolve_model()
        with pytest.raises(dataclasses.FrozenInstanceError):
            names.table = "changed"  # type: ignore[misc]


class TestCallersHonourSettings:
    def test_board_resolves_a_none_table_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi.board import Board

        monkeypatch.setenv("PBI_MODEL_TABLE", "Sales")
        assert Board().table == "Sales"

    def test_board_explicit_table_beats_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi.board import Board

        monkeypatch.setenv("PBI_MODEL_TABLE", "Sales")
        assert Board(table="Explicit").table == "Explicit"

    def test_board_measure_alias_needs_a_measure_table(self) -> None:
        from agentic_bi.board import Board

        assert Board().measure_alias is None
        assert Board(measure_table="KPI").measure_alias == "s"

    def test_spec_from_dict_uses_the_resolved_default_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi.spec import from_dict

        monkeypatch.setenv("PBI_MODEL_TABLE", "Sales")
        assert from_dict({"name": "D", "pages": []}).table == "Sales"

    def test_spec_from_dict_keeps_an_explicit_table(self) -> None:
        from agentic_bi.spec import from_dict

        assert from_dict({"name": "D", "table": "T", "pages": []}).table == "T"

    def test_rebuild_defaults_are_not_donor_names(self) -> None:
        import inspect

        from agentic_bi.rebuild import rebuild_pbix

        sig = inspect.signature(rebuild_pbix)
        for name in ("table", "col", "measure"):
            assert sig.parameters[name].default is None, name

    def test_example_registry_matches_the_neutral_defaults(self) -> None:
        from agentic_bi.validate_pbix import EXAMPLE_REGISTRY

        assert settings.DEFAULT_TABLE in EXAMPLE_REGISTRY


class TestNoDonorNamesRemainInSource:
    """The done-criterion from the plan: no donor name outside `settings`/fixtures."""

    #: Names of one particular donor model that must not be compiled into `src/`.
    DONOR = ("fact_table", "kpi_measures", "dim_registry")

    def test_src_has_no_donor_object_names(self) -> None:
        src = Path(__file__).resolve().parents[1] / "src" / "agentic_bi"
        offenders: list[str] = []
        for path in src.rglob("*.py"):
            if path.name == "settings.py":
                continue
            text = path.read_text(encoding="utf-8")
            for name in self.DONOR:
                if name in text:
                    offenders.append(f"{path.relative_to(src)}: {name}")
        assert not offenders, f"donor object names remain in src/: {offenders}"
