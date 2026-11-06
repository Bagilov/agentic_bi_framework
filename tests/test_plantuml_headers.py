"""Header analysis and output accounting tests.

These pin the two data-loss defects fixed against PlantUML 1.2025.4: duplicate
``@startuml <name>`` headers collapsed to one image, and stem collisions dropped
one of two produced files. Both are prevented by rewriting unsafe or duplicate
headers to unique markers and matching outputs by relative path.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agentic_bi.report import plantuml_names


def _puml(*headers: str) -> str:
    return "".join(f"@startuml {header}\nblock\n@enduml\n" for header in headers)


class TestPrepareSource:
    def test_duplicate_headers_are_made_unique_but_keep_source_order(self) -> None:
        prepared = plantuml_names.prepare_source(_puml("dup", "dup", "other"))
        assert prepared.names == ("dup", "__dg_2", "other")
        assert prepared.text.count("@startuml ") == 3
        assert "@startuml dup" in prepared.text
        assert "@startuml __dg_2" in prepared.text
        assert "@startuml other" in prepared.text

    def test_a_duplicate_header_emits_a_warning(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger=plantuml_names.__name__):
            plantuml_names.prepare_source(_puml("dup", "dup"))
        assert "Duplicate @startuml header" in caplog.text

    def test_a_nameless_block_gets_a_marker(self) -> None:
        prepared = plantuml_names.prepare_source("@startuml\nbody\n@enduml\n")
        assert prepared.names == ("__dg_1",)
        assert prepared.text.startswith("@startuml __dg_1")

    def test_a_path_like_header_cannot_escape(self) -> None:
        prepared = plantuml_names.prepare_source(_puml("../x", "a/b", "ok"))
        assert prepared.names == ("__dg_1", "__dg_2", "ok")

    def test_markers_do_not_collide_with_a_declared_header(self) -> None:
        prepared = plantuml_names.prepare_source(_puml("__dg_1", "../x"))
        assert prepared.names == ("__dg_1", "__dg_2")

    def test_a_phantom_header_inside_a_note_is_ignored(self) -> None:
        source = "@startuml first\nnote right\n@startuml fake\nend note\n@enduml\n"
        prepared = plantuml_names.prepare_source(source)
        assert prepared.names == ("first",)
        assert "@startuml fake" in prepared.text

    def test_a_single_line_note_does_not_swallow_following_headers(self) -> None:
        source = (
            '@startuml first\nnote "text" as N1\n@enduml\n@startuml second\n@enduml\n'
        )
        prepared = plantuml_names.prepare_source(source)
        assert prepared.names == ("first", "second")

    def test_legend_blocks_are_skipped(self) -> None:
        source = "@startuml first\nlegend right\n@startuml fake\nendlegend\n@enduml\n"
        prepared = plantuml_names.prepare_source(source)
        assert prepared.names == ("first",)


class TestOrderProduced:
    def test_colliding_stems_are_kept_by_relative_path(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        (work / "a").mkdir(parents=True)
        first = work / "a" / "b.png"
        second = work / "b.png"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        ordered = plantuml_names.order_produced([second, first], ("a/b", "b"), work)
        assert ordered == [first, second]

    def test_unmatched_files_are_published_and_reported(
        self, tmp_path: Path, caplog
    ) -> None:
        work = tmp_path / "work"
        work.mkdir()
        stray = work / "stray.png"
        stray.write_bytes(b"stray")
        with caplog.at_level(logging.WARNING, logger=plantuml_names.__name__):
            ordered = plantuml_names.order_produced([stray], ("declared",), work)
        assert ordered == [stray]
        assert "no @startuml header names" in caplog.text
