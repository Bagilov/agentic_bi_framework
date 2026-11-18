"""Build paths and the `Constructor` facade, including the row boundary.

The artifact tests use the shipped donor template, so they exercise the real
container code (zip rewrite, layout encoding) without Desktop or a network. The
row tests pin the type coercion that decides whether a value reaches the engine
as a number, a date or a NULL.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentic_bi.constructor import Constructor, Design
from agentic_bi.constructor.build_paths import (
    build_engine,
    engine_problems,
    merge_into_donor,
)
from agentic_bi.constructor.issues import DesignError
from agentic_bi.constructor.layout import compile_design
from agentic_bi.constructor.rows import coerce_value, normalize_rows

DESIGN = {
    "name": "Board",
    "model": {
        "tables": {
            "Sales": {
                "columns": {"region": "string", "amount": "double", "qty": "int64"},
                "measures": {"Rows": "COUNTROWS(Sales)"},
            }
        }
    },
    "pages": [
        {
            "name": "overview",
            "title": "Overview",
            "visuals": [
                {"kind": "card", "table": "Sales", "measure": "Rows"},
                {"kind": "table", "table": "Sales", "columns": ["region", "amount"]},
            ],
        }
    ],
}


def _design() -> Design:
    return Design.from_dict(DESIGN)


class TestCoerceValue:
    @pytest.mark.parametrize(
        ("raw", "typ", "expected"),
        [
            (None, "int64", None),
            (float("nan"), "double", None),
            ("", "int64", None),
            ("  ", "string", "  "),
            ("42", "int64", 42),
            (3.0, "int64", 3),
            (True, "int64", 1),
            (True, "string", "true"),
            ("2.5", "double", 2.5),
            (7, "string", "7"),
        ],
    )
    def test_values_coerce_to_the_column_type(
        self, raw: object, typ: str, expected: object
    ) -> None:
        assert coerce_value(raw, typ, "t[0].c") == expected

    def test_a_fractional_value_for_int64_names_the_cell(self) -> None:
        with pytest.raises(ValueError) as exc:
            coerce_value("2.5", "int64", "Sales[4].qty")
        assert "Sales[4].qty" in str(exc.value)

    def test_an_out_of_range_int64_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            coerce_value(2**63, "int64", "t[0].c")
        assert "out of range" in str(exc.value)

    def test_a_non_number_for_double_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            coerce_value("abc", "double", "t[0].c")
        assert "expected double" in str(exc.value)

    def test_a_large_integer_string_keeps_its_precision(self) -> None:
        # A float round-trip loses every integer above 2**53.
        assert coerce_value("9007199254740993", "int64", "t[0].c") == 9007199254740993

    def test_an_exponent_form_for_int64_is_accepted(self) -> None:
        assert coerce_value("1e3", "int64", "t[0].c") == 1000

    @pytest.mark.parametrize("raw", ["inf", "-inf", "nan", float("inf")])
    def test_a_non_finite_double_is_rejected(self, raw: object) -> None:
        with pytest.raises(ValueError) as exc:
            coerce_value(raw, "double", "Sales[0].amount")
        assert "Sales[0].amount" in str(exc.value)
        assert "finite" in str(exc.value)

    def test_a_ru_date_string_normalizes_to_iso(self) -> None:
        # Invariant-culture parsing on the guest would read this as May 6.
        assert coerce_value("05.06.2024", "date", "t[0].d") == "2024-06-05T00:00:00"

    def test_an_iso_date_string_normalizes_to_iso(self) -> None:
        assert coerce_value("2024-06-05", "date", "t[0].d") == "2024-06-05T00:00:00"

    def test_a_datetime_object_still_isoformats(self) -> None:
        assert (
            coerce_value(datetime(2024, 6, 5, 10, 30), "date", "t[0].d")
            == "2024-06-05T10:30:00"
        )

    def test_a_non_date_string_names_the_cell(self) -> None:
        with pytest.raises(ValueError) as exc:
            coerce_value("not-a-date", "date", "Sales[2].day")
        assert "Sales[2].day" in str(exc.value)
        assert "expected a date" in str(exc.value)

    def test_a_sub_resolution_fraction_for_int64_is_rejected(self) -> None:
        # float("0.99999999999999999") == 1.0; the value is not an integer.
        with pytest.raises(ValueError):
            coerce_value("0.99999999999999999", "int64", "t[0].c")

    def test_a_large_decimal_form_int64_keeps_precision(self) -> None:
        assert coerce_value("9007199254740993.0", "int64", "t[0].c") == 9007199254740993

    @pytest.mark.parametrize("raw", ["1_000", "١٢٣"])
    def test_python_only_integer_syntax_is_rejected(self, raw: str) -> None:
        with pytest.raises(ValueError):
            coerce_value(raw, "int64", "t[0].c")

    def test_datetime_microseconds_normalize_to_seconds(self) -> None:
        assert (
            coerce_value(datetime(2024, 6, 5, 10, 30, 0, 123456), "date", "t[0].d")
            == "2024-06-05T10:30:00"
        )

    def test_tz_aware_datetime_normalizes_like_the_string_channel(self) -> None:
        aware = datetime(2024, 6, 5, 10, 30, tzinfo=timezone.utc)
        assert coerce_value(aware, "date", "t[0].d") == coerce_value(
            "2024-06-05 10:30:00", "date", "t[0].d"
        )


class TestNormalizeRows:
    def test_rows_are_coerced_and_named_by_table(self) -> None:
        rows = normalize_rows(
            _design(), {"Sales": [{"region": "EU", "amount": "1.5", "qty": "2"}]}
        )
        assert rows == {"Sales": [{"region": "EU", "amount": 1.5, "qty": 2}]}

    def test_an_unknown_table_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            normalize_rows(_design(), {"Other": []})
        assert "not in model context" in str(exc.value)

    def test_an_unknown_column_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            normalize_rows(_design(), {"Sales": [{"other": 1}]})
        assert "data columns are not in model context" in str(exc.value)

    def test_a_row_that_is_not_an_object_is_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            normalize_rows(_design(), {"Sales": [[1, 2]]})
        assert "must be an object" in str(exc.value)

    def test_a_dataframe_like_input_needs_its_table_name(self) -> None:
        class Frame:
            def to_dict(self, *, orient: str) -> list[dict[str, object]]:
                assert orient == "records"
                return [{"region": "EU", "amount": 1.0, "qty": 1}]

        with pytest.raises(ValueError) as exc:
            normalize_rows(_design(), Frame())
        assert "table= is required" in str(exc.value)
        assert normalize_rows(_design(), Frame(), "Sales")["Sales"][0]["region"] == "EU"

    def test_date_rows_normalize_to_iso(self) -> None:
        design = Design.from_dict(
            {
                "model": {"tables": {"T": {"columns": {"d": "date"}}}},
                "pages": [
                    {
                        "name": "p",
                        "visuals": [{"kind": "table", "table": "T", "columns": ["d"]}],
                    }
                ],
            }
        )
        rows = normalize_rows(design, {"T": [{"d": "05.06.2024"}, {"d": None}]})
        assert rows == {"T": [{"d": "2024-06-05T00:00:00"}, {"d": None}]}


class TestEngineGate:
    def test_a_non_ascii_model_name_blocks_a_live_build(self) -> None:
        design = Design.from_dict(
            {
                "model": {"tables": {"Продажи": {"columns": ["a"]}}},
                "pages": [
                    {
                        "name": "p",
                        "visuals": [
                            {"kind": "table", "table": "Продажи", "columns": ["a"]}
                        ],
                    }
                ],
            }
        )
        assert any("non-ASCII" in problem for problem in engine_problems(design))

    def test_a_measure_without_dax_blocks_the_visual_that_uses_it(self) -> None:
        design = Design.from_dict(
            {
                "model": {"tables": {"Sales": {"columns": ["a"], "measures": ["M"]}}},
                "pages": [
                    {
                        "name": "p",
                        "visuals": [{"kind": "card", "table": "Sales", "measure": "M"}],
                    }
                ],
            }
        )
        problems = engine_problems(design)
        assert any("has no DAX" in problem for problem in problems)


class TestBuildPaths:
    def test_a_clean_build_replaces_the_layout(
        self, template_pbix: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "board.pbix"
        ctor = Constructor(_design())
        ctor.build_donor(template_pbix, out, skip_preflight=True)
        with zipfile.ZipFile(out) as archive:
            layout = json.loads(archive.read("Report/Layout").decode("utf-16-le"))
        assert [s["displayName"] for s in layout["sections"]] == ["Overview"]

    def test_keeping_donor_pages_appends_ours(
        self, template_pbix: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "merged.pbix"
        ctor = Constructor(_design())
        ctor.build_donor(template_pbix, out, keep_donor_pages=True, skip_preflight=True)
        with zipfile.ZipFile(out) as archive:
            layout = json.loads(archive.read("Report/Layout").decode("utf-16-le"))
        names = [s["displayName"] for s in layout["sections"]]
        assert names[-1] == "Overview"
        assert len(names) > 1

    def test_merge_numbers_appended_sections_and_binds_a_pod(self) -> None:
        donor = {
            "sections": [{"name": "a", "ordinal": 0, "displayName": "Donor"}],
            "pods": [{"name": "Pod", "boundSection": "a", "config": "{}"}],
            "config": json.dumps({"activeSectionIndex": 0}),
        }
        compiled = compile_design(_design())
        merged = merge_into_donor(_layout_file(donor), compiled.layout)
        assert merged["sections"][-1]["ordinal"] == 1
        assert merged["pods"][-1]["boundSection"] == merged["sections"][-1]["name"]
        assert json.loads(merged["config"])["activeSectionIndex"] == 1

    def test_a_donor_with_broken_config_is_rejected(self) -> None:
        donor = {"sections": [], "pods": [], "config": "{not json"}
        with pytest.raises(ValueError) as exc:
            merge_into_donor(_layout_file(donor), compile_design(_design()).layout)
        assert "not valid JSON" in str(exc.value)

    def test_merging_a_donor_without_layout_names_the_problem(self, tmp_path) -> None:
        donor = tmp_path / "nolayout.pbix"
        with zipfile.ZipFile(donor, "w") as z:
            z.writestr("Version", "1.28")
        with pytest.raises(ValueError) as exc:
            merge_into_donor(donor, compile_design(_design()).layout)
        assert "Report/Layout" in str(exc.value)

    def test_merging_the_same_design_twice_keeps_names_unique(self) -> None:
        compiled = compile_design(_design())
        empty = {"sections": [], "pods": [], "config": "{}"}
        first = merge_into_donor(_layout_file(empty), compiled.layout)
        second = merge_into_donor(_layout_file(first), compiled.layout)
        names = [section["name"] for section in second["sections"]]
        assert len(names) == len(set(names))
        assert {pod["boundSection"] for pod in second["pods"]} <= set(names)

    def test_a_donor_with_non_object_sections_is_rejected(self) -> None:
        donor = {"sections": ["x"], "pods": [], "config": "{}"}
        with pytest.raises(ValueError) as exc:
            merge_into_donor(_layout_file(donor), compile_design(_design()).layout)
        assert "sections[0]" in str(exc.value)

    def test_a_donor_with_a_bad_ordinal_is_rejected(self) -> None:
        donor = {
            "sections": [{"name": "a", "ordinal": "first"}],
            "pods": [],
            "config": "{}",
        }
        with pytest.raises(ValueError) as exc:
            merge_into_donor(_layout_file(donor), compile_design(_design()).layout)
        assert "ordinal" in str(exc.value)

    def test_engine_build_rejects_an_empty_datamodel(
        self, template_pbix: Path, tmp_path: Path
    ) -> None:
        compiled = compile_design(_design())
        with pytest.raises(ValueError) as exc:
            build_engine(compiled, template_pbix, b"", tmp_path / "x.pbix")
        assert "datamodel is empty" in str(exc.value)

    def test_engine_build_rejects_a_missing_template(self, tmp_path: Path) -> None:
        compiled = compile_design(_design())
        with pytest.raises(FileNotFoundError):
            build_engine(compiled, tmp_path / "missing.pbix", b"x", tmp_path / "x.pbix")

    def test_engine_build_writes_a_container_from_bytes(self, tmp_path: Path) -> None:
        """The OPC template supplies only the scaffolding members, not a model."""
        from agentic_bi.engine.container import COPY_MEMBERS

        template = tmp_path / "opc.pbix"
        with zipfile.ZipFile(template, "w") as archive:
            for member in COPY_MEMBERS:
                archive.writestr(member, b"scaffolding")
        out = build_engine(
            compile_design(_design()), template, b"MODEL", tmp_path / "e.pbix"
        )
        with zipfile.ZipFile(out) as archive:
            assert archive.read("DataModel") == b"MODEL"
            assert json.loads(archive.read("Report/Layout").decode("utf-16-le"))


def _layout_file(layout: dict) -> Path:
    """A `.pbix`-shaped zip whose only interesting member is `Report/Layout`."""
    import tempfile

    path = Path(tempfile.mkdtemp()) / "donor.pbix"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Report/Layout", json.dumps(layout).encode("utf-16-le"))
    return path


class TestConstructorFacade:
    def test_an_invalid_design_raises_unless_validation_is_deferred(self) -> None:
        broken = {"pages": [{"name": "p", "visuals": [{"kind": "card"}]}]}
        with pytest.raises(DesignError):
            Constructor(broken)
        assert Constructor(broken, validate=False).issues

    def test_a_context_argument_overrides_the_design_model(self) -> None:
        design = {
            "pages": [
                {"name": "p", "visuals": [{"kind": "card", "table": "T", "value": "a"}]}
            ]
        }
        ctor = Constructor(design, {"tables": {"T": {"columns": {"a": "int64"}}}})
        assert ctor.issues == []

    def test_preview_reports_every_block_with_its_position(self) -> None:
        preview = Constructor(_design()).preview()
        page = preview["pages"][0]
        assert page["title"] == "Overview"
        assert [v["id"] for v in page["visuals"]] == ["overview_1", "overview_2"]
        assert all(len(v["pos"]) == 4 for v in page["visuals"])

    def test_expected_types_come_from_the_catalogue(self) -> None:
        assert Constructor(_design()).expected_types() == {"card", "tableEx"}

    def test_layout_only_build_writes_json_and_a_passing_report(
        self, tmp_path: Path
    ) -> None:
        report = Constructor(_design()).build_and_test(tmp_path / "out")
        assert report.ok
        layout = json.loads((tmp_path / "out" / "layout.json").read_text())
        assert layout["sections"][0]["displayName"] == "Overview"
        assert report.meta["layout"].endswith("layout.json")

    def test_a_built_artifact_passes_its_own_checks(
        self, template_pbix: Path, tmp_path: Path
    ) -> None:
        ctor = Constructor(_design())
        out = tmp_path / "board.pbix"
        ctor.build_donor(template_pbix, out, skip_preflight=True)
        report = ctor.test(out)
        assert report.critical_ok, report.to_markdown()
        assert any(c.group == "registry" for c in report.checks)

    def test_a_missing_artifact_is_a_failed_check_not_an_exception(self) -> None:
        report = Constructor(_design()).test(Path("nope.pbix"))
        assert not report.critical_ok
        assert report.checks[-1].name == "layout readable"

    def test_a_corrupt_artifact_is_a_failed_check_not_an_exception(
        self, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.pbix"
        bad.write_bytes(b"not a zip")
        report = Constructor(_design()).test(bad)
        assert not report.critical_ok
        assert report.checks[-1].name == "layout readable"

    def test_an_artifact_without_layout_is_a_failed_check(self, tmp_path: Path) -> None:
        bad = tmp_path / "nolayout.pbix"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("Version", "1.28")
        report = Constructor(_design()).test(bad)
        assert not report.critical_ok
        assert report.checks[-1].name == "layout readable"


class TestBuildState:
    def test_a_live_build_tests_against_its_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import agentic_bi.constructor.build_paths as bp

        class StubPipeline:
            def __init__(self, **kwargs: object) -> None:
                pass

            def build_datamodel(self, spec: dict) -> bytes:
                return b"MODEL"

        monkeypatch.setattr(bp, "EnginePipeline", StubPipeline)
        monkeypatch.setattr(
            bp, "build_engine", lambda compiled, template, datamodel, out: Path(out)
        )
        ctor = Constructor(_design())
        report = ctor.build_and_test(
            tmp_path / "board.pbix",
            data={"Sales": [{"region": "EU", "amount": "1.5", "qty": "2"}]},
            template=tmp_path / "t.pbix",
        )
        assert report.meta["spec"] == "values"
        assert ctor._values == {"Sales": [{"region": "EU", "amount": 1.5, "qty": 2}]}
        spec = ctor.spec(ctor._values)
        amount = next(c for c in spec["tables"][0]["columns"] if c["name"] == "amount")
        assert amount["values"] == [1.5]

    def test_a_merged_build_without_preflight_reports_the_skipped_registry(
        self, template_pbix: Path, tmp_path: Path
    ) -> None:
        ctor = Constructor(_design())
        out = tmp_path / "merged.pbix"
        ctor.build_donor(template_pbix, out, keep_donor_pages=True, skip_preflight=True)
        report = ctor.test(out)
        skipped = [
            c for c in report.checks if c.group == "registry" and c.level == "warning"
        ]
        assert skipped, report.to_markdown()
        assert "skipped" in skipped[0].name

    def test_an_empty_registry_reports_the_skipped_check(
        self, template_pbix: Path, tmp_path: Path
    ) -> None:
        design = Design.from_dict(
            {
                "pages": [
                    {
                        "name": "p",
                        "visuals": [{"kind": "card", "table": "T", "value": "a"}],
                    }
                ]
            }
        )
        ctor = Constructor(design)
        out = tmp_path / "board.pbix"
        ctor.build_donor(template_pbix, out, skip_preflight=True)
        report = ctor.test(out)
        assert any(
            c.group == "registry" and c.level == "warning" for c in report.checks
        )

    def test_a_failed_preflight_does_not_leave_the_merged_flag(
        self, template_pbix: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi.constructor.model_context import ModelContext

        monkeypatch.setattr(
            ModelContext,
            "from_pbix",
            classmethod(
                lambda cls, pbix, **kw: cls.from_dict(
                    {"tables": {"Real": {"columns": {"a": "string"}}}}
                )
            ),
        )
        design = Design.from_dict(
            {
                "model": {"tables": {"Missing": {"columns": {"a": "string"}}}},
                "pages": [
                    {
                        "name": "p",
                        "visuals": [
                            {"kind": "table", "table": "Missing", "columns": ["a"]}
                        ],
                    }
                ],
            }
        )
        ctor = Constructor(design)
        with pytest.raises(DesignError):
            ctor.build_donor(template_pbix, tmp_path / "x.pbix", keep_donor_pages=True)
        assert ctor._merged is False
