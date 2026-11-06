"""One definition of "has a diagram" for both lineage CLI paths.

The old check was case-insensitive and order-blind, so `@STARTUML` (which
PlantUML rejects) and an end-before-start block passed `--plantuml` while the
PNG path failed later. `_has_diagram_body` now mirrors the renderer, and these
tests pin that `--plantuml` and `--plantuml-png` agree.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentic_bi import cli_support
from agentic_bi.lineage.pbi_lineage import _has_diagram_body
from agentic_bi.report import plantuml_tools


@pytest.mark.parametrize(
    "text",
    [
        "@startuml\nA --> B\n@enduml",
        "@startuml lineage_x\nA --> B\n@enduml\n",
        "  @startuml\nA --> B\n  @enduml",
        "@startuml\n\n@enduml\n@startuml\nA --> B\n@enduml",
    ],
)
def test_a_real_block_is_recognised(text: str) -> None:
    assert _has_diagram_body(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n\t",
        "@startuml\n@enduml",
        "@startuml\n  \n\t\n@enduml",
        "@STARTUML\nA --> B\n@ENDUMl",
        "@enduml\nA --> B\n@startuml",
        "@startuml@enduml",
        "A --> B",
    ],
)
def test_a_non_diagram_is_rejected(text: str) -> None:
    assert not _has_diagram_body(text)


@pytest.mark.parametrize(
    "text",
    [
        "@STARTUML\nA --> B\n@ENDUMl",
        "@enduml\nA --> B\n@startuml",
        "@startuml@enduml",
        "@startuml\n@enduml",
    ],
)
def test_both_cli_paths_reject_the_same_source(
    text: str, template_pbix: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    from agentic_bi.lineage import pbi_lineage

    monkeypatch.setattr(pbi_lineage.PbiLineage, "to_plantuml", lambda self: text)
    monkeypatch.setattr(
        plantuml_tools, "find_plantuml_jar", lambda: "/fake/plantuml.jar"
    )
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/java")

    def render_must_not_run(*args, **kwargs):
        raise AssertionError("the renderer must not run for a non-diagram")

    monkeypatch.setattr(plantuml_tools, "render_png_ex", render_must_not_run)

    for flag in ("--plantuml", "--plantuml-png"):
        out_dir = tmp_path / flag.lstrip("-")
        code = pbi_lineage.main([str(template_pbix), "--out-dir", str(out_dir), flag])
        assert code == cli_support.EXIT_FAILED
        assert not (out_dir / "lineage.puml").exists()
        assert not (out_dir / "lineage.png").exists()

    assert "no @startuml/@enduml block" in capsys.readouterr().err
