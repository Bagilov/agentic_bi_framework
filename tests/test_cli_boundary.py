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

    def test_dax_detail_out_dir_is_relative(self, monkeypatch, tmp_path) -> None:
        from agentic_bi import dax_detail

        monkeypatch.chdir(tmp_path)
        assert dax_detail.OUT_DIR == Path("output_files")
        assert Path(dax_detail.__file__).resolve().parent not in (
            dax_detail.OUT_DIR.resolve().parents
        )

    def test_inspect_board_out_dir_is_relative(self, monkeypatch, tmp_path) -> None:
        from agentic_bi import inspect_board

        monkeypatch.chdir(tmp_path)
        assert inspect_board.OUT_DIR == Path("output_files")
        assert Path(inspect_board.__file__).resolve().parent not in (
            inspect_board.OUT_DIR.resolve().parents
        )


class TestPackageRelativeWritesAreGone:
    """Every default write path must live outside the installed package.

    A read-only install (site-packages owned by another user) must not raise
    `PermissionError` before doing any work; these pin the resolved locations.
    """

    def test_no_module_defaults_a_write_into_the_package(self) -> None:
        from agentic_bi import (
            board_fake,
            build,
            engine,
            skeleton_assembly,
            validate_pbix,
        )

        pkg = Path(engine.__file__).resolve().parent
        candidates = [
            engine.EnginePipeline(work_dir=None).work_dir,
            build.paths.output_dir("demo_events"),
            skeleton_assembly.paths.output_dir("skel_behavior"),
            board_fake.paths.output_dir("board.pbix"),
            validate_pbix.paths.output_dir("sample.pbix"),
        ]
        for path in candidates:
            assert pkg not in path.resolve().parents, path

    @pytest.mark.parametrize(
        "module_name",
        [
            "board_fake",
            "build",
            "dax_detail",
            "engine",
            "inspect_board",
            "skeleton_assembly",
            "validate_pbix",
        ],
    )
    def test_module_source_has_no_package_relative_output_path(
        self, module_name: str
    ) -> None:
        """The fix is structural: no `__file__`-anchored output path may remain."""
        import importlib

        module = importlib.import_module(f"agentic_bi.{module_name}")
        source = Path(module.__file__).read_text(encoding="utf-8")
        for line in source.splitlines():
            if "output_files" not in line:
                continue
            assert "__file__" not in line, f"{module_name}: {line.strip()}"

    def test_engine_work_dir_is_under_the_temp_root(
        self, monkeypatch, tmp_path
    ) -> None:
        from agentic_bi.engine import core

        monkeypatch.setattr(core.paths.tempfile, "gettempdir", lambda: str(tmp_path))
        assert core.EnginePipeline().work_dir == tmp_path / "agentic_bi" / "_work"
        assert core.EnginePipeline().work_dir.is_dir()

    def test_output_dir_is_cwd_relative(self, monkeypatch, tmp_path) -> None:
        from agentic_bi import paths

        monkeypatch.chdir(tmp_path)
        assert paths.output_dir("a", "b.json") == Path("output_files/a/b.json")
        assert not paths.output_dir("a").is_absolute()

    def test_scratch_dir_is_created_outside_the_package(
        self, monkeypatch, tmp_path
    ) -> None:
        from agentic_bi import paths

        monkeypatch.setattr(paths.tempfile, "gettempdir", lambda: str(tmp_path))
        created = paths.scratch_dir("_test")
        assert created.is_dir()
        assert created == tmp_path / "agentic_bi" / "_test"


class TestBuildDatamodelSpecHandling:
    """The engine spec handoff must not leak temp files or collide across runs."""

    def test_spec_file_is_unique_and_removed(self, monkeypatch, tmp_path) -> None:
        from agentic_bi.engine import core

        seen: list[Path] = []

        def fake_build(spec_path: Path, abf: Path, port: int | None = None) -> str:
            seen.append(Path(spec_path))
            assert Path(spec_path).exists(), "spec must exist while the build runs"
            abf.write_bytes(b"abf")
            return "ok"

        monkeypatch.setattr(core.engine_host, "kill_desktop", lambda: None)
        monkeypatch.setattr(core.subprocess, "Popen", lambda *a, **k: None)
        monkeypatch.setattr(core.engine_host, "wait_port", lambda *a, **k: 1234)
        monkeypatch.setattr(core.engine_host, "run_engine_build", fake_build)

        pipeline = core.EnginePipeline(work_dir=tmp_path / "w")
        assert pipeline.build_datamodel({"database": "D", "tables": []}) == b"abf"

        assert len(seen) == 1
        assert not seen[0].exists(), "the temp spec must be cleaned up"

    def test_two_builds_do_not_share_a_spec_path(self, monkeypatch, tmp_path) -> None:
        from agentic_bi.engine import core

        seen: list[Path] = []

        def fake_build(spec_path: Path, abf: Path, port: int | None = None) -> str:
            seen.append(Path(spec_path))
            abf.write_bytes(b"abf")
            return "ok"

        monkeypatch.setattr(core.engine_host, "kill_desktop", lambda: None)
        monkeypatch.setattr(core.subprocess, "Popen", lambda *a, **k: None)
        monkeypatch.setattr(core.engine_host, "wait_port", lambda *a, **k: 1234)
        monkeypatch.setattr(core.engine_host, "run_engine_build", fake_build)

        pipeline = core.EnginePipeline(work_dir=tmp_path / "w")
        pipeline.build_datamodel({"database": "D", "tables": []})
        pipeline.build_datamodel({"database": "D", "tables": []})

        assert len(seen) == 2
        assert seen[0] != seen[1], "parallel runs must not collide on one spec path"


def test_cli_support_exports_the_documented_codes() -> None:
    assert (EXIT_OK, EXIT_FAILED, EXIT_BAD_INPUT) == (0, 1, 2)
