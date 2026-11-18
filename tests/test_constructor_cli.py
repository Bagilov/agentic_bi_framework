"""Console contract of `agentic-bi-constructor`.

The command is an agent-facing API: `--catalog` and `--schema` describe the
input format, `--check`/`--preview` are side-effect free, a build writes the
layout plus a report, and every usage mistake is exit 2 with one message instead
of a traceback. `--json` keeps the machine-readable path working on failure too.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from agentic_bi.cli_support import EXIT_BAD_INPUT, EXIT_OK
from agentic_bi.constructor.cli import main
from agentic_bi.constructor.schema import get_schema

DESIGN = {
    "name": "Board",
    "model": {
        "tables": {"Sales": {"columns": {"region": "string", "amount": "double"}}}
    },
    "pages": [
        {
            "name": "p",
            "title": "Overview",
            "visuals": [{"kind": "card", "table": "Sales", "value": "amount"}],
        }
    ],
}


def _write_design(tmp_path: Path, body: object = None) -> Path:
    path = tmp_path / "design.json"
    path.write_text(json.dumps(DESIGN if body is None else body), encoding="utf-8")
    return path


class TestDiscoveryOutput:
    def test_catalog_lists_every_block_as_json(self, capsys) -> None:
        assert main(["--catalog"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert {"card", "table", "matrix"} <= {entry["kind"] for entry in payload}

    @pytest.mark.parametrize("name", ["design", "context", "report"])
    def test_schema_is_printed_by_name(self, name: str, capsys) -> None:
        assert main(["--schema", name]) == EXIT_OK
        assert json.loads(capsys.readouterr().out)["$schema"].endswith("2020-12/schema")

    def test_an_unknown_schema_is_a_bad_input(self) -> None:
        with pytest.raises(SystemExit):
            main(["--schema", "pages"])

    def test_catalog_cannot_be_combined_with_a_design(self, tmp_path: Path) -> None:
        code = main(["--catalog", "--design", str(_write_design(tmp_path))])
        assert code == EXIT_BAD_INPUT

    def test_schema_cannot_be_combined_with_a_build(self, tmp_path: Path) -> None:
        code = main(["--schema", "design", "--out", str(tmp_path / "o")])
        assert code == EXIT_BAD_INPUT


class TestValidationModes:
    def test_check_passes_for_a_valid_design_without_writing(
        self, tmp_path: Path, capsys
    ) -> None:
        code = main(["--design", str(_write_design(tmp_path)), "--check"])
        assert code == EXIT_OK
        assert "1 passed" in capsys.readouterr().out
        assert not list(tmp_path.glob("**/*.json"))[1:]

    def test_check_reports_each_problem_with_its_location(
        self, tmp_path: Path, capsys
    ) -> None:
        broken = {"pages": [{"name": "p", "visuals": [{"kind": "card", "table": "T"}]}]}
        code = main(["--design", str(_write_design(tmp_path, broken)), "--check"])
        assert code == EXIT_BAD_INPUT
        captured = capsys.readouterr()
        assert "missing_field" in captured.out
        assert "validation failed" in captured.err

    def test_preview_shows_the_placement_table(self, tmp_path: Path, capsys) -> None:
        code = main(["--design", str(_write_design(tmp_path)), "--preview"])
        assert code == EXIT_OK
        assert "| page | id | kind | table |" in capsys.readouterr().out

    def test_preview_json_carries_positions(self, tmp_path: Path, capsys) -> None:
        code = main(["--design", str(_write_design(tmp_path)), "--preview", "--json"])
        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["pages"][0]["visuals"][0]["pos"]) == 4

    def test_a_missing_design_file_is_one_message(self, tmp_path: Path, capsys) -> None:
        code = main(["--design", str(tmp_path / "nope.json"), "--check"])
        assert code == EXIT_BAD_INPUT
        assert "cannot load design" in capsys.readouterr().err


class TestBuildModes:
    def test_a_layout_only_build_writes_json_and_a_report(
        self, tmp_path: Path, capsys
    ) -> None:
        out = tmp_path / "out"
        code = main(["--design", str(_write_design(tmp_path)), "--out", str(out)])
        assert code == EXIT_OK
        assert (out / "layout.json").exists()
        assert (out / "constructor_report.md").exists()
        summary = (out / "constructor_report.md").read_text()
        assert "| layout | 1 | 0 |" in summary
        assert "1 passed, 0 failed" in summary

    def test_a_json_report_goes_to_stdout(self, tmp_path: Path, capsys) -> None:
        out = tmp_path / "out"
        code = main(
            ["--design", str(_write_design(tmp_path)), "--out", str(out), "--json"]
        )
        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["schema"] == "constructor.report/1"
        assert payload["critical_ok"] is True

    def test_an_explicit_report_path_is_honoured(self, tmp_path: Path) -> None:
        report = tmp_path / "r.json"
        code = main(
            [
                "--design",
                str(_write_design(tmp_path)),
                "--out",
                str(tmp_path / "out"),
                "--report",
                str(report),
            ]
        )
        assert code == EXIT_OK
        assert json.loads(report.read_text())["ok"] is True

    def test_layout_can_be_written_to_an_explicit_path(self, tmp_path: Path) -> None:
        layout = tmp_path / "custom" / "layout.json"
        code = main(
            [
                "--design",
                str(_write_design(tmp_path)),
                "--out",
                str(tmp_path / "unused"),
                "--layout",
                str(layout),
            ]
        )
        assert code == EXIT_OK
        assert json.loads(layout.read_text())["sections"]


class TestUsageErrors:
    def test_a_build_without_out_is_a_bad_input(self, tmp_path: Path, capsys) -> None:
        code = main(["--design", str(_write_design(tmp_path))])
        assert code == EXIT_BAD_INPUT
        assert "--out is required" in capsys.readouterr().err

    def test_data_needs_a_template(self, tmp_path: Path) -> None:
        code = main(
            [
                "--design",
                str(_write_design(tmp_path)),
                "--out",
                str(tmp_path / "o.pbix"),
                "--data",
                "Sales=rows.csv",
            ]
        )
        assert code == EXIT_BAD_INPUT

    def test_two_sources_are_rejected(self, tmp_path: Path) -> None:
        code = main(
            [
                "--design",
                str(_write_design(tmp_path)),
                "--out",
                str(tmp_path / "o.pbix"),
                "--donor",
                "a.pbix",
                "--template",
                "t.pbix",
                "--datamodel",
                "m.abf",
            ]
        )
        assert code == EXIT_BAD_INPUT

    def test_keep_donor_pages_requires_a_donor(self, tmp_path: Path) -> None:
        code = main(
            [
                "--design",
                str(_write_design(tmp_path)),
                "--out",
                str(tmp_path / "o.pbix"),
                "--keep-donor-pages",
            ]
        )
        assert code == EXIT_BAD_INPUT

    def test_usage_errors_are_json_when_asked(self, tmp_path: Path, capsys) -> None:
        code = main(["--design", str(_write_design(tmp_path)), "--json"])
        assert code == EXIT_BAD_INPUT
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert payload["exit"] == EXIT_BAD_INPUT

    def test_check_and_preview_are_mutually_exclusive(self, tmp_path: Path) -> None:
        code = main(["--design", str(_write_design(tmp_path)), "--check", "--preview"])
        assert code == EXIT_BAD_INPUT


class TestMissingDonor:
    def test_a_missing_donor_is_a_failed_report_and_exit(
        self, tmp_path: Path, capsys
    ) -> None:
        code = main(
            [
                "--design",
                str(_write_design(tmp_path)),
                "--out",
                str(tmp_path / "o.pbix"),
                "--donor",
                str(tmp_path / "missing.pbix"),
            ]
        )
        assert code == EXIT_BAD_INPUT
        captured = capsys.readouterr()
        assert "assembly" in captured.out


class TestBadInputArtifacts:
    def test_a_malformed_yaml_design_is_one_message(
        self, tmp_path: Path, capsys
    ) -> None:
        pytest.importorskip("yaml")
        path = tmp_path / "design.yaml"
        path.write_text("pages: [unclosed", encoding="utf-8")
        code = main(["--design", str(path), "--check"])
        assert code == EXIT_BAD_INPUT
        assert "invalid YAML" in capsys.readouterr().err

    def test_a_donor_zip_without_layout_is_bad_input(
        self, tmp_path: Path, capsys
    ) -> None:
        donor = tmp_path / "donor.pbix"
        with zipfile.ZipFile(donor, "w") as z:
            z.writestr("Version", "1.28")
        code = main(
            [
                "--design",
                str(_write_design(tmp_path)),
                "--out",
                str(tmp_path / "o.pbix"),
                "--donor",
                str(donor),
                "--no-preflight",
            ]
        )
        assert code == EXIT_BAD_INPUT
        assert "assembly" in capsys.readouterr().out


class TestSchemaApi:
    def test_an_unknown_schema_lists_the_choices(self) -> None:
        with pytest.raises(ValueError) as exc:
            get_schema("nope")
        assert "available" in str(exc.value)

    def test_the_design_schema_embeds_the_block_catalogue(self) -> None:
        schema = get_schema("design")
        assert schema["x-blocks"]
        assert schema["required"] == ["pages"]
