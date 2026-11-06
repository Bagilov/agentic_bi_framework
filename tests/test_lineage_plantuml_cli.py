"""CLI tests for the lineage PlantUML artifacts (`.puml` / rendered PNG).

Pins the defect that made the diagram unreachable: `--plantuml` was accepted and
silently ignored, so no run ever produced a `.puml`, and nothing could render one
to an image. The JSON-mode interaction and the stdout/exit-code contract live in
`test_lineage_cli_json_modes.py`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentic_bi import cli_support
from agentic_bi.report import plantuml_tools


class _Completed:
    """A stand-in for `subprocess.CompletedProcess` (only fields `_run` reads)."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


class TestLineageCliPlantumlFlags:
    """`--plantuml` must write a `.puml`; `--plantuml-png` must not lie."""

    def test_plantuml_flag_writes_the_source(
        self, template_pbix: Path, tmp_path: Path
    ) -> None:
        from agentic_bi.lineage.pbi_lineage import main

        code = main([str(template_pbix), "--out-dir", str(tmp_path), "--plantuml"])
        assert code == cli_support.EXIT_OK
        puml = tmp_path / "lineage.puml"
        assert puml.exists()
        text = puml.read_text(encoding="utf-8")
        assert text.startswith("@startuml") and text.rstrip().endswith("@enduml")
        assert "POWER QUERY" in text

    def test_without_the_flag_no_puml_is_written(
        self, template_pbix: Path, tmp_path: Path
    ) -> None:
        from agentic_bi.lineage.pbi_lineage import main

        assert main([str(template_pbix), "--out-dir", str(tmp_path)]) == (
            cli_support.EXIT_OK
        )
        assert not (tmp_path / "lineage.puml").exists()

    def test_plantuml_flag_rejects_a_source_without_a_block(
        self, template_pbix: Path, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from agentic_bi.lineage import pbi_lineage

        monkeypatch.setattr(
            pbi_lineage.PbiLineage, "to_plantuml", lambda self: "@startuml\nA --> B"
        )
        code = pbi_lineage.main(
            [str(template_pbix), "--out-dir", str(tmp_path), "--plantuml"]
        )
        assert code == cli_support.EXIT_FAILED
        assert "@enduml" in capsys.readouterr().err
        assert not (tmp_path / "lineage.puml").exists()

    def test_plantuml_flag_rejects_an_empty_source(
        self, template_pbix: Path, tmp_path: Path, monkeypatch
    ) -> None:
        from agentic_bi.lineage import pbi_lineage

        monkeypatch.setattr(pbi_lineage.PbiLineage, "to_plantuml", lambda self: "  ")
        code = pbi_lineage.main(
            [str(template_pbix), "--out-dir", str(tmp_path), "--plantuml"]
        )
        assert code == cli_support.EXIT_FAILED
        assert not (tmp_path / "lineage.puml").exists()

    def test_png_flag_fails_when_no_jar_is_available(
        self, template_pbix: Path, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from agentic_bi.lineage.pbi_lineage import main

        monkeypatch.delenv("PLANTUML_JAR", raising=False)
        monkeypatch.delenv("PLANTUML_JAR_DIR", raising=False)
        code = main([str(template_pbix), "--out-dir", str(tmp_path), "--plantuml-png"])
        assert code == cli_support.EXIT_BAD_INPUT
        err = capsys.readouterr().err
        assert "PLANTUML_JAR" in err
        assert "configured" in err
        assert "source is invalid" not in err
        assert (tmp_path / "lineage.puml").exists()
        assert not (tmp_path / "lineage.png").exists()

    def test_png_flag_fails_when_java_is_missing(
        self, template_pbix: Path, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from agentic_bi.lineage import pbi_lineage

        jar = tmp_path / "plantuml.jar"
        jar.write_bytes(b"")
        monkeypatch.setenv("PLANTUML_JAR", str(jar))
        monkeypatch.delenv("PLANTUML_JAR_DIR", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        code = pbi_lineage.main(
            [str(template_pbix), "--out-dir", str(tmp_path), "--plantuml-png"]
        )
        assert code == cli_support.EXIT_BAD_INPUT
        assert "Java" in capsys.readouterr().err
        assert not (tmp_path / "lineage.png").exists()

    def test_png_flag_writes_the_image_when_rendering_works(
        self, template_pbix: Path, tmp_path: Path, monkeypatch
    ) -> None:
        from agentic_bi.lineage import pbi_lineage

        _fake_jar(monkeypatch)
        monkeypatch.setattr(plantuml_tools, "render_png_ex", _successful_render)
        code = pbi_lineage.main(
            [str(template_pbix), "--out-dir", str(tmp_path), "--plantuml-png"]
        )
        assert code == cli_support.EXIT_OK
        assert (tmp_path / "lineage.png").read_bytes() == b"rendered"

    def test_png_flag_uses_a_single_java_run(
        self, template_pbix: Path, tmp_path: Path, monkeypatch
    ) -> None:
        from agentic_bi.lineage import pbi_lineage

        _fake_jar(monkeypatch)
        calls: list[list[str]] = []

        def fake_run(jar_path, args, stdin_text=None):
            calls.append(args)
            out_dir = Path(args[args.index("-o") + 1])
            (out_dir / "only.png").write_bytes(b"rendered")
            return _Completed(0, "", "")

        def validate_must_not_run(*args, **kwargs):
            raise AssertionError("validate_text must not be called by the CLI")

        monkeypatch.setattr(plantuml_tools, "_run", fake_run)
        monkeypatch.setattr(plantuml_tools, "validate_text", validate_must_not_run)
        code = pbi_lineage.main(
            [str(template_pbix), "--out-dir", str(tmp_path), "--plantuml-png"]
        )
        assert code == cli_support.EXIT_OK
        assert len(calls) == 1
        assert "-tpng" in calls[0]
        assert (tmp_path / "lineage.png").read_bytes() == b"rendered"

    def test_png_flag_reports_a_failed_render_as_exit_failed(
        self, template_pbix: Path, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """The render helper is reached, its negative result is the exit code."""
        from agentic_bi.lineage import pbi_lineage

        seen: list[str] = []

        def fake_render(puml_text, out_dir, jar=None, *, name="diagram"):
            seen.append(puml_text)
            return None, "java: command not found"

        _fake_jar(monkeypatch)
        monkeypatch.setattr(plantuml_tools, "render_png_ex", fake_render)
        code = pbi_lineage.main(
            [str(template_pbix), "--out-dir", str(tmp_path), "--plantuml-png"]
        )
        assert code == cli_support.EXIT_FAILED
        assert len(seen) == 1 and seen[0].startswith("@startuml")
        assert "java: command not found" in capsys.readouterr().err


class TestPngValidationDiagnostics:
    """A broken source must report the PlantUML diagnostic, not a generic hint."""

    def test_render_diagnostic_reports_the_line_number(
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
            [str(template_pbix), "--out-dir", str(tmp_path), "--plantuml-png"]
        )
        assert code == cli_support.EXIT_FAILED
        err = capsys.readouterr().err
        assert "line 3" in err
        assert "PlantUML PNG not rendered" in err


@pytest.mark.parametrize("flag", ["--plantuml", "--plantuml-png"])
def test_help_documents_the_flags(flag: str, capsys) -> None:
    """The flags are part of the documented CLI surface."""
    from agentic_bi.lineage.pbi_lineage import main

    with pytest.raises(SystemExit):
        main(["--help"])
    assert flag in capsys.readouterr().out
