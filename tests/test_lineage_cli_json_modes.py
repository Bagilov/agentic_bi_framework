"""Lineage CLI: JSON output modes and the stdout/exit-code contract.

`--print-json` promises machine-readable stdout. Diagram checks and the PNG
configuration pre-flight run before the payload is printed, so a non-zero exit
never leaves a complete JSON document on stdout.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from agentic_bi import cli_support
from agentic_bi.report import plantuml_tools


def _successful_render(puml_text, out_dir, jar=None, *, name="diagram"):
    """Stub for ``render_png_ex`` that writes a PNG and reports no diagnostic."""
    png = Path(out_dir) / f"{name}.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"rendered")
    return png, ""


def _fake_jar(monkeypatch) -> None:
    """Pretend a jar and Java are available so only rendering is exercised."""
    monkeypatch.setattr(
        plantuml_tools, "find_plantuml_jar", lambda: "/fake/plantuml.jar"
    )
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/java")


class TestPlantumlFlagsWithJsonModes:
    """Diagram artifacts must not depend on how the JSON is emitted."""

    def test_print_json_still_writes_the_puml(
        self, template_pbix: Path, tmp_path: Path, capsys
    ) -> None:
        from agentic_bi.lineage.pbi_lineage import main

        code = main(
            [
                str(template_pbix),
                "--out-dir",
                str(tmp_path),
                "--print-json",
                "--plantuml",
            ]
        )
        assert code == cli_support.EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert "plantuml" in payload
        assert (tmp_path / "lineage.puml").exists()
        assert not (tmp_path / "lineage.json").exists()
        assert not (tmp_path / "lineage.xlsx").exists()
        assert not (tmp_path / "REPORT.md").exists()

    def test_print_json_without_artifacts_creates_no_out_dir(
        self, template_pbix: Path, tmp_path: Path, capsys
    ) -> None:
        from agentic_bi.lineage.pbi_lineage import main

        missing = tmp_path / "not-created"
        code = main([str(template_pbix), "--out-dir", str(missing), "--print-json"])
        assert code == cli_support.EXIT_OK
        assert "plantuml" in json.loads(capsys.readouterr().out)
        assert not missing.exists()

    def test_print_json_needs_no_writable_output_directory(
        self, template_pbix: Path, tmp_path: Path, capsys
    ) -> None:
        """A read-only run must not fail only because a directory cannot be made.

        The parent is a regular file, so any `mkdir` on the requested `--out-dir`
        raises a real `OSError` (exit 2) without patching `Path.mkdir` globally.
        """
        from agentic_bi.lineage.pbi_lineage import main

        blocker = tmp_path / "readonly"
        blocker.write_text("not a directory", encoding="utf-8")
        missing = blocker / "out"
        code = main([str(template_pbix), "--out-dir", str(missing), "--print-json"])
        assert code == cli_support.EXIT_OK
        assert "plantuml" in json.loads(capsys.readouterr().out)
        assert not missing.exists()

    def test_no_json_still_writes_the_puml(
        self, template_pbix: Path, tmp_path: Path, monkeypatch
    ) -> None:
        from agentic_bi.lineage.pbi_lineage import main

        exported: list[Path] = []
        real_export = plantuml_tools.export_puml

        def counting_export(text: str, path: str | Path) -> Path:
            written = real_export(text, path)
            exported.append(written)
            return written

        monkeypatch.setattr(plantuml_tools, "export_puml", counting_export)
        code = main(
            [str(template_pbix), "--out-dir", str(tmp_path), "--no-json", "--plantuml"]
        )
        assert code == cli_support.EXIT_OK
        assert (tmp_path / "lineage.puml").exists()
        assert not (tmp_path / "lineage.json").exists()
        assert len(exported) == 1

    def test_no_md_still_renders_the_png(
        self, template_pbix: Path, tmp_path: Path, monkeypatch
    ) -> None:
        from agentic_bi.lineage import pbi_lineage

        _fake_jar(monkeypatch)
        monkeypatch.setattr(plantuml_tools, "render_png_ex", _successful_render)
        code = pbi_lineage.main(
            [
                str(template_pbix),
                "--out-dir",
                str(tmp_path),
                "--no-md",
                "--plantuml-png",
            ]
        )
        assert code == cli_support.EXIT_OK
        assert (tmp_path / "lineage.puml").exists()
        assert (tmp_path / "lineage.png").read_bytes() == b"rendered"
        assert not (tmp_path / "REPORT.md").exists()


class TestPrintJsonNeverHidesAFailure:
    """A non-zero exit must not leave a complete payload on stdout."""

    def test_missing_jar_keeps_stdout_empty(
        self, template_pbix: Path, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from agentic_bi.lineage.pbi_lineage import main

        monkeypatch.delenv("PLANTUML_JAR", raising=False)
        monkeypatch.delenv("PLANTUML_JAR_DIR", raising=False)
        code = main(
            [
                str(template_pbix),
                "--out-dir",
                str(tmp_path),
                "--print-json",
                "--plantuml-png",
            ]
        )
        captured = capsys.readouterr()
        assert code == cli_support.EXIT_BAD_INPUT
        assert captured.out == ""
        assert "PLANTUML_JAR" in captured.err
        assert (tmp_path / "lineage.puml").exists()
        assert not (tmp_path / "lineage.png").exists()

    def test_failed_render_keeps_stdout_empty(
        self, template_pbix: Path, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from agentic_bi.lineage import pbi_lineage

        _fake_jar(monkeypatch)
        monkeypatch.setattr(
            plantuml_tools,
            "render_png_ex",
            lambda *args, **kwargs: (None, "Error line 3: syntax error"),
        )
        code = pbi_lineage.main(
            [
                str(template_pbix),
                "--out-dir",
                str(tmp_path),
                "--print-json",
                "--plantuml-png",
            ]
        )
        captured = capsys.readouterr()
        assert code == cli_support.EXIT_FAILED
        assert captured.out == ""
        assert "Error line 3" in captured.err

    def test_rejected_source_keeps_stdout_empty(
        self, template_pbix: Path, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from agentic_bi.lineage import pbi_lineage

        monkeypatch.setattr(
            pbi_lineage.PbiLineage,
            "to_plantuml",
            lambda self: "@STARTUML\nA --> B\n@ENDUMl",
        )
        code = pbi_lineage.main(
            [
                str(template_pbix),
                "--out-dir",
                str(tmp_path),
                "--print-json",
                "--plantuml",
            ]
        )
        captured = capsys.readouterr()
        assert code == cli_support.EXIT_FAILED
        assert captured.out == ""
        assert "@startuml" in captured.err
        assert not (tmp_path / "lineage.puml").exists()
