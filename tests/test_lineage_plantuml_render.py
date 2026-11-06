"""Tests for the PlantUML render/export helpers behind the lineage CLI.

`render_png` must report failure honestly (no jar, renderer error, empty
output) and name the file it just produced, so a stale neighbour in the output
directory cannot be mistaken for the rendered diagram.
"""

from __future__ import annotations

from pathlib import Path

from agentic_bi.report import plantuml_tools


class TestSafeStem:
    """`safe_stem` must never let a caller escape the output directory."""

    def test_directory_components_are_stripped(self) -> None:
        assert plantuml_tools.safe_stem("../../etc/passwd") == "passwd"

    def test_spaces_become_underscores(self) -> None:
        assert plantuml_tools.safe_stem("my diagram") == "my_diagram"

    def test_only_the_last_path_component_is_kept(self) -> None:
        assert plantuml_tools.safe_stem("my diagram/v2") == "v2"

    def test_empty_result_falls_back(self) -> None:
        assert plantuml_tools.safe_stem("../..") == "diagram"
        assert plantuml_tools.safe_stem("", fallback="x") == "x"


class TestRenderPng:
    """`render_png` must report failure honestly and name its own output."""

    def test_returns_none_without_a_jar(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("PLANTUML_JAR", raising=False)
        monkeypatch.delenv("PLANTUML_JAR_DIR", raising=False)
        assert plantuml_tools.render_png("@startuml\n@enduml", tmp_path) is None

    def test_a_nonexistent_jar_path_counts_as_missing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("PLANTUML_JAR", str(tmp_path / "nope.jar"))
        monkeypatch.delenv("PLANTUML_JAR_DIR", raising=False)
        assert plantuml_tools.render_png("@startuml\n@enduml", tmp_path) is None

    def test_returns_the_file_it_produced_not_a_stale_neighbour(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        stale = tmp_path / "aaa_older.png"
        stale.write_bytes(b"not the diagram")

        def fake_run(jar, args, stdin_text=None):
            out_dir = Path(args[args.index("-o") + 1])
            stem = Path(args[-1]).stem
            (out_dir / f"{stem}.png").write_bytes(b"fresh diagram")
            return _Completed(0, "", "")

        monkeypatch.setattr(plantuml_tools, "_run", fake_run)
        png = plantuml_tools.render_png(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        assert png == tmp_path / "lineage.png"
        assert png is not None and png.read_bytes() == b"fresh diagram"

    def test_a_renderer_error_is_reported_as_none(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        def failing_run(jar, args, stdin_text=None):
            return _Completed(1, "Error line 3: syntax error", "")

        monkeypatch.setattr(plantuml_tools, "_run", failing_run)
        assert (
            plantuml_tools.render_png(
                "@startuml\nbad\n@enduml", tmp_path, jar="/fake/plantuml.jar"
            )
            is None
        )

    def test_an_empty_output_file_is_a_failure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        def empty_run(jar, args, stdin_text=None):
            out_dir = Path(args[args.index("-o") + 1])
            (out_dir / "diagram.png").write_bytes(b"")
            return _Completed(0, "", "")

        monkeypatch.setattr(plantuml_tools, "_run", empty_run)
        assert (
            plantuml_tools.render_png(
                "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar"
            )
            is None
        )


class _Completed:
    """A stand-in for `subprocess.CompletedProcess` (only fields `_run` reads)."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
