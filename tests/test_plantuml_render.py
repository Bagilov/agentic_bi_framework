"""Rendering tests: output selection, source-order publishing and diagnostics.

The fake jar mimics the real one closely enough to exercise the failure modes
that were verified against PlantUML 1.2025.4: it names every output after the
``@startuml`` header it sees in the (already rewritten) source, so duplicate or
path-like headers behave exactly like the real jar.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import re
from collections.abc import Callable
from pathlib import Path

from agentic_bi.report import plantuml_tools


class _Completed:
    """A stand-in for `subprocess.CompletedProcess` (only fields `_run` reads)."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _write_by_header() -> Callable[..., _Completed]:
    """Fake `_run` that writes ``<out>/<header>.png`` for every header."""

    def fake_run(jar: str, args: list[str], stdin_text: str | None = None):
        out_dir = Path(args[args.index("-o") + 1])
        text = Path(args[-1]).read_text(encoding="utf-8")
        names = [
            match.group(1).strip()
            for match in re.finditer(r"^\s*@startuml\b(.*)$", text, re.MULTILINE)
        ]
        for index, name in enumerate(names, start=1):
            target = out_dir / f"{name}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"block {index}".encode())
        return _Completed()

    return fake_run


class TestRenderPngOutputSelection:
    def test_a_stale_same_named_png_is_replaced_by_the_fresh_one(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        stale = tmp_path / "lineage.png"
        stale.write_bytes(b"stale")
        neighbour = tmp_path / "zzz_other.png"
        neighbour.write_bytes(b"unrelated")

        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header())
        png = plantuml_tools.render_png(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        assert png == tmp_path / "lineage.png"
        assert png is not None and png.read_bytes() == b"block 1"
        assert neighbour.read_bytes() == b"unrelated"

    def test_multiple_diagrams_follow_source_order_not_alphabetical(
        self, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header())
        with caplog.at_level(logging.WARNING, logger=plantuml_tools.__name__):
            png = plantuml_tools.render_png(
                "@startuml beta\n@enduml\n@startuml alpha\n@enduml",
                tmp_path,
                jar="/fake/plantuml.jar",
                name="lineage",
            )
        assert png == tmp_path / "lineage.png"
        assert (tmp_path / "lineage.png").read_bytes() == b"block 1"
        assert (tmp_path / "lineage_2.png").read_bytes() == b"block 2"
        assert "2 diagrams" in caplog.text

    def test_the_warning_names_blocks_not_temporary_paths(
        self, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header())
        with caplog.at_level(logging.WARNING, logger=plantuml_tools.__name__):
            plantuml_tools.render_png(
                "@startuml\n@enduml\n@startuml\n@enduml",
                tmp_path,
                jar="/fake/plantuml.jar",
                name="lineage",
            )
        assert "lineage.png" in caplog.text and "lineage_2.png" in caplog.text
        assert str(tmp_path) not in caplog.text

    def test_a_single_diagram_does_not_produce_a_suffixed_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header())
        png = plantuml_tools.render_png(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        assert png == tmp_path / "lineage.png"
        assert sorted(p.name for p in tmp_path.glob("*.png")) == ["lineage.png"]

    def test_stale_suffixes_from_a_larger_run_are_removed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header())
        plantuml_tools.render_png(
            "@startuml a\n@enduml\n@startuml b\n@enduml\n@startuml c\n@enduml",
            tmp_path,
            jar="/fake/plantuml.jar",
            name="lineage",
        )
        assert (tmp_path / "lineage_2.png").exists()
        assert (tmp_path / "lineage_3.png").exists()

        plantuml_tools.render_png(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        assert sorted(p.name for p in tmp_path.glob("*.png")) == ["lineage.png"]

    def test_an_empty_second_block_is_not_published(
        self, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        def fake_run(jar: str, args: list[str], stdin_text: str | None = None):
            out_dir = Path(args[args.index("-o") + 1])
            payloads = {"__dg_1": b"first", "__dg_2": b""}
            for name, payload in payloads.items():
                (out_dir / f"{name}.png").write_bytes(payload)
            return _Completed()

        monkeypatch.setattr(plantuml_tools, "_run", fake_run)
        plantuml_tools.render_png(
            "@startuml alpha\n@enduml\n@startuml beta\n@enduml",
            tmp_path,
            jar="/fake/plantuml.jar",
            name="lineage",
        )
        assert (tmp_path / "lineage.png").read_bytes() == b"first"
        assert not (tmp_path / "lineage_2.png").exists()

    def test_two_runs_into_one_directory_both_publish_fresh_content(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header())
        first = plantuml_tools.render_png(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        second = plantuml_tools.render_png(
            "@startuml second\n@enduml",
            tmp_path,
            jar="/fake/plantuml.jar",
            name="lineage",
        )
        assert first == second == tmp_path / "lineage.png"
        assert second is not None and second.read_bytes() == b"block 1"

    def test_header_payloads_land_in_source_order(self, tmp_path: Path, monkeypatch):
        def fake_run(jar: str, args: list[str], stdin_text: str | None = None):
            out_dir = Path(args[args.index("-o") + 1])
            (out_dir / "beta.png").write_bytes(b"second")
            (out_dir / "alpha.png").write_bytes(b"first")
            return _Completed()

        monkeypatch.setattr(plantuml_tools, "_run", fake_run)
        plantuml_tools.render_png(
            "@startuml alpha\n@enduml\n@startuml beta\n@enduml",
            tmp_path,
            jar="/fake/plantuml.jar",
            name="lineage",
        )
        assert (tmp_path / "lineage.png").read_bytes() == b"first"
        assert (tmp_path / "lineage_2.png").read_bytes() == b"second"

    def test_outputs_outside_the_work_directory_are_never_published(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.setattr(
            plantuml_tools.tempfile,
            "TemporaryDirectory",
            lambda: contextlib.nullcontext(str(work)),
        )

        def escaping_run(jar: str, args: list[str], stdin_text: str | None = None):
            (work / "__dg_1.png").write_bytes(b"inside")
            (tmp_path / "escaped.png").write_bytes(b"outside")
            return _Completed()

        monkeypatch.setattr(plantuml_tools, "_run", escaping_run)
        png = plantuml_tools.render_png(
            "@startuml ../escaped\n@enduml",
            tmp_path / "out",
            jar="/fake/plantuml.jar",
            name="lineage",
        )
        assert png is not None and png.read_bytes() == b"inside"
        assert (tmp_path / "escaped.png").read_bytes() == b"outside"
        assert not (tmp_path / "out" / "escaped.png").exists()

    def test_a_missing_jar_is_still_none(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("PLANTUML_JAR", raising=False)
        monkeypatch.delenv("PLANTUML_JAR_DIR", raising=False)
        assert plantuml_tools.render_png("@startuml\n@enduml", tmp_path) is None


class TestRenderPngDiagnostics:
    def test_a_failed_run_returns_the_render_diagnostic(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            plantuml_tools,
            "_run",
            lambda *args, **kwargs: _Completed(
                1, "", "Error line 3: syntax error near -->"
            ),
        )
        png, diagnostic = plantuml_tools.render_png_ex(
            "@startuml\nbad\n@enduml", tmp_path, jar="/fake/plantuml.jar"
        )
        assert png is None
        assert "line 3" in diagnostic

    def test_a_partial_png_does_not_mask_a_nonzero_exit(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        def broken_run(jar: str, args: list[str], stdin_text: str | None = None):
            out_dir = Path(args[args.index("-o") + 1])
            (out_dir / "diagram.png").write_bytes(b"error placeholder")
            return _Completed(1, "", "Error line 5: unexpected token")

        monkeypatch.setattr(plantuml_tools, "_run", broken_run)
        png, diagnostic = plantuml_tools.render_png_ex(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        assert png is None
        assert "line 5" in diagnostic
        assert not (tmp_path / "lineage.png").exists()

    def test_no_output_with_a_clean_exit_is_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            plantuml_tools, "_run", lambda *args, **kwargs: _Completed(0, "", "")
        )
        png, diagnostic = plantuml_tools.render_png_ex(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar"
        )
        assert png is None
        assert "no PNG" in diagnostic

    def test_a_refused_java_runtime_is_a_diagnostic_not_an_exception(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        def no_java(jar: str, args: list[str], stdin_text: str | None = None):
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", "java")

        monkeypatch.setattr(plantuml_tools, "_run", no_java)
        png, diagnostic = plantuml_tools.render_png_ex(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar"
        )
        assert png is None
        assert "java not runnable" in diagnostic

    def test_the_plain_wrapper_still_returns_a_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header())
        png = plantuml_tools.render_png(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        assert png == tmp_path / "lineage.png"
