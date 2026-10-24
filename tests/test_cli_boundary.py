"""Tests for the CLI boundary contract and default output locations.

Every console entry point must return a documented code on a bad input instead of
leaking a traceback (BR-7), and no default output may be written inside the
installed package. These pin both: a missing input is exit 2, and the resolved
default paths are CWD-relative.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi import cli_support
from agentic_bi.cli_support import EXIT_BAD_INPUT, EXIT_FAILED, EXIT_OK, run_boundary


class TestRunBoundary:
    def test_passes_the_body_code_through(self) -> None:
        assert run_boundary(lambda: 0, prog="p") == EXIT_OK
        assert run_boundary(lambda: 1, prog="p") == EXIT_FAILED

    def test_maps_a_missing_file_to_bad_input(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def body() -> int:
            raise FileNotFoundError("no such board")

        assert run_boundary(body, prog="agentic-bi-x") == EXIT_BAD_INPUT
        assert "agentic-bi-x: error:" in capsys.readouterr().err

    def test_maps_a_value_error_to_bad_input(self) -> None:
        def body() -> int:
            raise ValueError("bad spec")

        assert run_boundary(body, prog="p") == EXIT_BAD_INPUT

    def test_does_not_swallow_an_unexpected_error(self) -> None:
        def body() -> int:
            raise KeyError("a bug, not a user mistake")

        with pytest.raises(KeyError):
            run_boundary(body, prog="p")

    def test_fail_returns_the_requested_code(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli_support.fail("prog", "nope") == EXIT_BAD_INPUT
        assert "prog: error: nope" in capsys.readouterr().err


class TestEntryPointBadInputIsCodeTwo:
    """A missing input file must be exit 2, not an unhandled exception."""

    def test_visual_check(self, tmp_path: Path) -> None:
        from agentic_bi.visual_check import main

        code = main([str(tmp_path / "missing.pbix"), str(tmp_path / "missing.json")])
        assert code == EXIT_BAD_INPUT

    def test_brand_audit_on_an_unreadable_config(self, tmp_path: Path) -> None:
        from agentic_bi.brand_audit import main

        doc = tmp_path / "deck.pptx"
        doc.write_bytes(b"not a real pptx")
        code = main([str(doc), "--config", str(tmp_path / "missing.yaml")])
        assert code == EXIT_BAD_INPUT

    def test_antipatterns(self, tmp_path: Path) -> None:
        from agentic_bi.antipatterns.pbi_antipatterns import main

        assert main([str(tmp_path / "missing.pbix")]) == EXIT_BAD_INPUT

    def test_pbix_patch_on_a_missing_file(self, tmp_path: Path) -> None:
        from agentic_bi.pbix_binary.patch_cli import main

        code = main(["members", "--pbix", str(tmp_path / "missing.pbix")])
        assert code == EXIT_BAD_INPUT

    def test_pbix_patch_on_a_malformed_spec(self, tmp_path: Path) -> None:
        from agentic_bi.pbix_binary.patch_cli import main

        spec = tmp_path / "bad.json"
        spec.write_text("{ not json", encoding="utf-8")
        pbix = tmp_path / "board.pbix"
        pbix.write_bytes(b"not a zip")
        code = main(
            [
                "apply",
                "--pbix",
                str(pbix),
                "--spec",
                str(spec),
                "--out",
                str(tmp_path / "out.pbix"),
            ]
        )
        assert code == EXIT_BAD_INPUT

    def test_test_build_without_a_datamodel_on_macos(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi import test_build

        monkeypatch.setattr(test_build.sys, "platform", "darwin")
        csv = tmp_path / "s.csv"
        csv.write_text("region,amount\nA,1\nB,2\n", encoding="utf-8")
        code = test_build.main(
            ["--data", str(csv), "--table", "T", "--out", str(tmp_path / "o.pbix")]
        )
        assert code == EXIT_BAD_INPUT


class TestDefaultOutputsAreCwdRelative:
    """No default output may resolve inside the installed package."""

    def test_antipatterns_default_out_is_relative(self, monkeypatch, tmp_path) -> None:

        from agentic_bi.antipatterns import pbi_antipatterns as mod

        captured: dict[str, Path] = {}

        def fake_analyze(_pbix: str) -> dict:
            return {
                "summary": {"total_findings": 0, "critical": 0, "by_level": {}},
                "findings": {},
                "by_id": {},
            }

        def fake_write(_data: dict, out: Path) -> Path:
            captured["out"] = out
            return out

        monkeypatch.setattr(mod, "analyze_pbix", fake_analyze)
        monkeypatch.setattr(mod, "_write", fake_write)
        monkeypatch.chdir(tmp_path)
        pbix = tmp_path / "board.pbix"
        pbix.write_bytes(b"x")
        assert mod.main([str(pbix)]) == 0
        assert captured["out"].is_relative_to(Path("output_files"))
        assert (
            Path(mod.__file__).resolve().parent not in captured["out"].resolve().parents
        )


def test_cli_support_exports_the_documented_codes() -> None:
    assert (EXIT_OK, EXIT_FAILED, EXIT_BAD_INPUT) == (0, 1, 2)
