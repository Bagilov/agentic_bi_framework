"""Unified console UX for the zone-H entry points.

Every command in this zone must honour the same contract
(:mod:`agentic_bi.cli_support`): `0` success, `1` the work ran and its own result
was negative, `2` bad input/configuration — and never a traceback for a bad
input. These tests pin that, plus `--help` completeness, the summary line, and
that no message leaks an absolute path or dies on a non-UTF-8 console.

No network and no real external service is used: commands that download or parse
a real artifact are driven through their in-process seam.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from agentic_bi.cli_support import EXIT_BAD_INPUT, EXIT_FAILED, EXIT_OK

PROG_VALIDATE = "agentic_bi.validate_pbix"


def _help(main: Any, capsys: pytest.CaptureFixture[str]) -> str:
    """Run `--help` and return its stdout; assert it exits 0."""
    with pytest.raises(SystemExit) as info:
        main(["--help"])
    assert info.value.code == EXIT_OK
    return capsys.readouterr().out


class TestValidatePbixCli:
    def test_help_lists_every_flag_and_the_default(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentic_bi.validate_pbix import main

        out = _help(main, capsys)
        assert "--registry" in out
        assert "output_files/sample.pbix" in out

    def test_a_clean_layout_is_exit_zero(
        self,
        template_copy: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi import settings
        from agentic_bi.rebuild import rebuild_pbix
        from agentic_bi.validate_pbix import main

        monkeypatch.chdir(tmp_path)
        model = settings.resolve_model()
        out = rebuild_pbix(template_copy, Path("board.pbix"), display_name="V")
        registry = {
            model.table: {
                "columns": [model.column],
                "measures": [model.measure],
            }
        }
        Path("reg.json").write_text(json.dumps(registry), encoding="utf-8")

        assert main([str(out), "--registry", "reg.json"]) == EXIT_OK
        stdout = capsys.readouterr().out
        assert "-> OK" in stdout
        assert str(tmp_path) not in stdout
        assert re.search(r"(?m)^\S*/(Users|home|private|var)/", stdout) is None

    def test_layout_problems_are_exit_one(
        self, template_copy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi.rebuild import rebuild_pbix
        from agentic_bi.validate_pbix import main

        monkeypatch.chdir(tmp_path)
        out = rebuild_pbix(template_copy, Path("board.pbix"), display_name="V")
        Path("empty.json").write_text("{}", encoding="utf-8")
        assert main([str(out), "--registry", "empty.json"]) == EXIT_FAILED

    def test_a_missing_pbix_is_bad_input(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi.validate_pbix import main

        monkeypatch.chdir(tmp_path)
        assert main(["missing.pbix"]) == EXIT_BAD_INPUT
        err = capsys.readouterr().err
        assert f"{PROG_VALIDATE}: error:" in err
        assert "missing.pbix" in err

    def test_a_malformed_registry_is_bad_input(
        self,
        template_copy: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi.validate_pbix import main

        monkeypatch.chdir(tmp_path)
        Path("bad.json").write_text("{ not json", encoding="utf-8")
        code = main([str(template_copy), "--registry", "bad.json"])
        assert code == EXIT_BAD_INPUT
        err = capsys.readouterr().err
        assert f"{PROG_VALIDATE}: error:" in err
        assert "bad.json" in err

    def test_a_missing_registry_is_bad_input(
        self, template_copy: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi.validate_pbix import main

        code = main([str(template_copy), "--registry", "no-such.json"])
        assert code == EXIT_BAD_INPUT

    def test_a_container_without_a_layout_is_bad_input(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi.validate_pbix import main

        monkeypatch.chdir(tmp_path)
        with zipfile.ZipFile("nolayout.pbix", "w") as archive:
            archive.writestr("Version", "1.28")
        assert main(["nolayout.pbix"]) == EXIT_BAD_INPUT
        assert "Report/Layout" in capsys.readouterr().err


class TestInspectBoardCli:
    THESIS = {
        "summary": {"pages": 2, "visuals": 5, "tables": 3, "measures": 4},
        "pages": [],
        "sources": {},
    }

    def test_help_lists_every_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        from agentic_bi.inspect_board import main

        out = _help(main, capsys)
        assert "--path" in out
        assert "--keep-pbix" in out
        assert "output_files/inspect" in out

    def test_a_missing_required_flag_is_a_usage_error(self) -> None:
        from agentic_bi.inspect_board import main

        with pytest.raises(SystemExit) as info:
            main([])
        assert info.value.code == EXIT_BAD_INPUT

    def test_success_writes_the_report(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi import inspect_board as mod

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(mod, "inspect_board", lambda *_a, **_k: self.THESIS)

        assert mod.main(["--path", "/Team/Sales"]) == EXIT_OK
        saved = Path("output_files/inspect/Sales.json")
        assert saved.is_file()
        stdout = capsys.readouterr().out
        assert "-> OK" in stdout
        assert "Saved: output_files/inspect/Sales.json" in stdout
        assert re.search(r"(?m)^\S*/(Users|home|private|var)/", stdout) is None

    def test_an_unknown_report_path_is_bad_input(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentic_bi import inspect_board as mod

        def missing(_path: str, **_kwargs: Any) -> dict:
            raise mod.PbirsPathError("Report not found at path: /Team/Nope")

        monkeypatch.setattr(mod, "inspect_board", missing)
        assert mod.main(["--path", "/Team/Nope"]) == EXIT_BAD_INPUT
        err = capsys.readouterr().err
        assert f"{mod.PROG}: error:" in err
        assert "/Team/Nope" in err

    def test_a_permission_error_is_a_runtime_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi import inspect_board as mod

        def denied(_path: str, **_kwargs: Any) -> dict:
            raise mod.PbirsAccessError("No permission to download 'x' (HTTP 403)")

        monkeypatch.setattr(mod, "inspect_board", denied)
        assert mod.main(["--path", "/Team/Sales"]) == EXIT_FAILED


class TestDaxDetailCli:
    DATA = {
        "summary": {
            "measures_total": 2,
            "calc_columns_total": 0,
            "power_query_tables": ["Sales"],
        },
        "distort": {"measure": {}, "calc_column": {}, "source": {}},
    }

    def test_help_lists_every_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        from agentic_bi.dax_detail import main

        out = _help(main, capsys)
        assert "--out" in out
        assert "--no-antipatterns" in out
        assert "--summary" in out

    def test_a_missing_pbix_is_bad_input(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentic_bi import dax_detail as mod

        assert mod.main(["missing.pbix"]) == EXIT_BAD_INPUT
        err = capsys.readouterr().err
        assert f"{mod.PROG}: error:" in err
        assert "missing.pbix" in err

    def test_success_writes_the_json(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi import dax_detail as mod

        monkeypatch.chdir(tmp_path)
        Path("board.pbix").write_bytes(b"x")
        monkeypatch.setattr(mod, "analyze_dax_detail", lambda *_a, **_k: self.DATA)

        assert mod.main(["board.pbix"]) == EXIT_OK
        saved = Path("output_files/dax_detail/board_dax.json")
        assert saved.is_file()
        stdout = capsys.readouterr().out
        assert "2 measure(s)" in stdout
        assert "Saved: output_files/dax_detail/board_dax.json" in stdout

    def test_a_missing_readback_extra_is_bad_input(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi import dax_detail as mod

        monkeypatch.chdir(tmp_path)
        Path("board.pbix").write_bytes(b"x")

        def no_pbixray(*_args: Any, **_kwargs: Any) -> dict:
            raise ImportError("No module named 'pbixray'")

        monkeypatch.setattr(mod, "analyze_dax_detail", no_pbixray)
        assert mod.main(["board.pbix"]) == EXIT_BAD_INPUT
        err = capsys.readouterr().err
        assert f"{mod.PROG}: error:" in err
        assert "readback extra" in err

    def test_summary_writes_no_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi import dax_detail as mod

        monkeypatch.chdir(tmp_path)
        Path("board.pbix").write_bytes(b"x")
        monkeypatch.setattr(mod, "analyze_dax_detail", lambda *_a, **_k: self.DATA)

        assert mod.main(["board.pbix", "--summary"]) == EXIT_OK
        assert not Path("output_files").exists()
        assert "-> OK" in capsys.readouterr().out


class TestBuildCli:
    def test_help_lists_every_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        from agentic_bi.build import main

        out = _help(main, capsys)
        assert "--out" in out
        assert "--display" in out
        assert "--no-visuals" in out

    def test_success_writes_a_project(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi.build import main

        monkeypatch.chdir(tmp_path)
        assert main(["--out", "proj"]) == EXIT_OK
        for name in (
            "proj.pbir",
            "proj.Report/report.json",
            "proj.Semantic/model.bim",
            "proj.Semantic/definition.pbism",
        ):
            assert (tmp_path / "proj" / name).is_file(), name
        stdout = capsys.readouterr().out
        assert "-> OK" in stdout
        assert "proj/proj.pbir" in stdout

    def test_no_visuals_writes_an_empty_page(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi.build import main

        monkeypatch.chdir(tmp_path)
        assert main(["--out", "blank", "--no-visuals"]) == EXIT_OK
        report = json.loads(Path("blank/blank.Report/report.json").read_text())
        assert report["sections"][0]["visualContainers"] == []

    def test_an_unwritable_out_is_bad_input(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi.build import main

        monkeypatch.chdir(tmp_path)
        Path("taken").write_text("a file, not a folder", encoding="utf-8")
        assert main(["--out", "taken"]) == EXIT_BAD_INPUT
        assert "agentic_bi.build: error:" in capsys.readouterr().err


class TestRebuildCli:
    def test_help_lists_every_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        from agentic_bi.rebuild import main

        out = _help(main, capsys)
        assert "--out" in out
        assert "--display" in out
        assert "output_files/rebuilt.pbix" in out

    def test_success_writes_the_pbix(
        self,
        template_copy: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi.rebuild import main

        monkeypatch.chdir(tmp_path)
        src = tmp_path / "donor.pbix"
        src.write_bytes(template_copy.read_bytes())

        assert main([str(src), "--out", "out.pbix"]) == EXIT_OK
        assert Path("out.pbix").is_file()
        stdout = capsys.readouterr().out
        assert "-> OK" in stdout
        assert "Saved: out.pbix" in stdout

    def test_a_missing_donor_is_bad_input(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentic_bi.rebuild import main

        assert main(["missing.pbix"]) == EXIT_BAD_INPUT
        err = capsys.readouterr().err
        assert "agentic_bi.rebuild: error:" in err
        assert "missing.pbix" in err

    def test_a_container_without_a_layout_is_bad_input(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi.rebuild import main

        monkeypatch.chdir(tmp_path)
        with zipfile.ZipFile("nolayout.pbix", "w") as archive:
            archive.writestr("Version", "1.28")
        assert main(["nolayout.pbix", "--out", "out.pbix"]) == EXIT_BAD_INPUT
        assert "Report/Layout" in capsys.readouterr().err

    def test_a_non_zip_donor_is_bad_input(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi.rebuild import main

        monkeypatch.chdir(tmp_path)
        Path("broken.pbix").write_bytes(b"not a zip")
        assert main(["broken.pbix", "--out", "out.pbix"]) == EXIT_BAD_INPUT
        assert "not a .pbix zip" in capsys.readouterr().err


class TestBrandAuditCli:
    def test_help_lists_every_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        from agentic_bi.brand_audit import main

        out = _help(main, capsys)
        assert "--config" in out
        assert "--json" in out
        assert "--fail-on" in out

    def test_a_missing_document_is_bad_input(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentic_bi.brand_audit import main

        assert main([str(tmp_path / "missing.pptx")]) == EXIT_BAD_INPUT
        err = capsys.readouterr().err
        assert "agentic-bi-brand-audit: error:" in err
        assert "missing.pptx" in err

    def test_an_unsupported_format_is_bad_input(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentic_bi.brand_audit import main

        doc = tmp_path / "notes.txt"
        doc.write_text("x", encoding="utf-8")
        assert main([str(doc)]) == EXIT_BAD_INPUT
        err = capsys.readouterr().err
        assert "agentic-bi-brand-audit: error:" in err
        assert ".txt" in err

    def test_a_document_that_cannot_be_read_is_bad_input(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentic_bi.brand_audit import main

        doc = tmp_path / "deck.pptx"
        doc.write_bytes(b"not a real pptx")
        assert main([str(doc)]) == EXIT_BAD_INPUT
        assert "agentic-bi-brand-audit: error:" in capsys.readouterr().err

    def test_a_clean_audit_is_exit_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi import brand_audit as mod
        from agentic_bi.brand.audit_types import AuditReport

        monkeypatch.chdir(tmp_path)
        doc = Path("deck.pptx")
        doc.write_bytes(b"x")
        monkeypatch.setattr(
            mod, "audit_document", lambda path, _cfg: AuditReport(path=str(path))
        )

        assert mod.main(["deck.pptx", "--json", "audit.json"]) == EXIT_OK
        assert Path("audit.json").is_file()
        stdout = capsys.readouterr().out
        assert "saved audit.json" in stdout

    def test_fail_on_error_returns_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi import brand_audit as mod
        from agentic_bi.brand.audit_types import AuditFinding, AuditReport

        doc = tmp_path / "deck.pptx"
        doc.write_bytes(b"x")

        def with_error(path: str, _cfg: Any) -> AuditReport:
            rep = AuditReport(path=str(path))
            rep.add(AuditFinding("R", "error", "color", "slide 1", "bad color"))
            return rep

        monkeypatch.setattr(mod, "audit_document", with_error)
        assert mod.main([str(doc), "--fail-on", "error"]) == EXIT_FAILED


class TestTestBuildCli:
    RESULT = {
        "out": "out.pbix",
        "bytes": 10,
        "rows": 3,
        "layout": "gallery",
        "datamodel_bytes": 5,
        "visual_errors": [],
        "verify_ok": True,
        "verify_passed": 4,
        "verify_failed": [],
        "verify_critical_failed": [],
        "verify_soft_failed": [],
    }

    def test_help_lists_every_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        from agentic_bi.test_build import main

        out = _help(main, capsys)
        for flag in (
            "--data",
            "--table",
            "--out",
            "--template",
            "--datamodel",
            "--desktop",
            "--database",
            "--layout",
            "--registry",
            "--model",
            "--report",
        ):
            assert flag in out, flag

    def test_a_missing_data_file_is_bad_input(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi import test_build

        monkeypatch.setattr(test_build.sys, "platform", "darwin")
        code = test_build.main(
            [
                "--data",
                str(tmp_path / "missing.csv"),
                "--table",
                "T",
                "--out",
                str(tmp_path / "o.pbix"),
            ]
        )
        assert code == EXIT_BAD_INPUT

    def test_success_returns_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi import test_build

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(test_build, "run", lambda _args: dict(self.RESULT))

        assert (
            test_build.main(["--data", "d.csv", "--table", "T", "--out", "out.pbix"])
            == EXIT_OK
        )
        stdout = capsys.readouterr().out
        assert "agentic-bi-test-build: 3 row(s)" in stdout
        assert "Saved: out.pbix" in stdout

    def test_failed_checks_return_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from agentic_bi import test_build

        monkeypatch.chdir(tmp_path)
        failed = dict(self.RESULT, verify_ok=False, verify_failed=["visuals"])
        monkeypatch.setattr(test_build, "run", lambda _args: failed)

        assert (
            test_build.main(["--data", "d.csv", "--table", "T", "--out", "out.pbix"])
            == EXIT_FAILED
        )
        assert "-> FAILED" in capsys.readouterr().out


class TestShimsDoNotPretendToWork:
    @pytest.mark.parametrize(
        "module_name", ["agentic_bi.brand_eval", "agentic_bi.brand_audit_extract"]
    )
    def test_python_m_on_a_shim_exits_two(self, module_name: str) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", module_name],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == EXIT_BAD_INPUT
        assert "no command-line interface" in proc.stderr
        assert "agentic-bi-brand-audit" in proc.stderr


def test_a_non_utf8_console_does_not_crash(tmp_path: Path) -> None:
    """A Cyrillic path must not raise UnicodeEncodeError on a cp866/ascii console."""
    env = dict(os.environ, PYTHONIOENCODING="ascii")
    proc = subprocess.run(
        [sys.executable, "-m", "agentic_bi.validate_pbix", "нет-такого.pbix"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == EXIT_BAD_INPUT
    assert "Traceback" not in proc.stderr
    assert "not found" in proc.stderr
