"""Tests for the atomic ``.puml`` export (permissions, UTF-8/LF, long names)."""

from __future__ import annotations

import os

import pytest

from agentic_bi.report import plantuml_publish, plantuml_tools


class TestExportPuml:
    def test_returns_the_written_path(self, tmp_path) -> None:
        target = tmp_path / "nested" / "lineage.puml"
        written = plantuml_tools.export_puml("@startuml\n@enduml", target)
        assert written == target
        assert target.read_text(encoding="utf-8") == "@startuml\n@enduml"

    def test_overwrites_an_existing_file_completely(self, tmp_path) -> None:
        target = tmp_path / "lineage.puml"
        target.write_text("old and much longer content", encoding="utf-8")
        plantuml_tools.export_puml("@startuml\n@enduml", target)
        assert target.read_text(encoding="utf-8") == "@startuml\n@enduml"

    def test_a_failed_write_leaves_no_partial_or_temp_file(
        self, tmp_path, monkeypatch
    ) -> None:
        target = tmp_path / "lineage.puml"

        def broken_replace(src: object, dst: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(plantuml_publish.os, "replace", broken_replace)
        with pytest.raises(OSError, match="disk full"):
            plantuml_tools.export_puml("@startuml\n@enduml", target)
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []

    def test_a_long_target_name_is_writable(self, tmp_path) -> None:
        target = tmp_path / (("x" * 245) + ".puml")
        assert len(target.name) == 250
        plantuml_tools.export_puml("@startuml\n@enduml", target)
        assert target.read_text(encoding="utf-8") == "@startuml\n@enduml"
        assert list(tmp_path.iterdir()) == [target]

    def test_the_content_is_utf8_without_bom_or_crlf(self, tmp_path) -> None:
        text = "@startuml\nAlice --> Боб : привет\n@enduml\n"
        target = tmp_path / "lineage.puml"
        plantuml_tools.export_puml(text, target)
        raw = target.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" not in raw
        assert raw.decode("utf-8") == text


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
class TestExportPumlPermissions:
    def test_a_new_file_gets_the_documented_mode(self, tmp_path) -> None:
        target = tmp_path / "lineage.puml"
        plantuml_tools.export_puml("@startuml\n@enduml", target)
        assert target.stat().st_mode & 0o777 == 0o644

    def test_an_existing_target_keeps_its_mode(self, tmp_path) -> None:
        target = tmp_path / "lineage.puml"
        target.write_text("old", encoding="utf-8")
        os.chmod(target, 0o600)
        plantuml_tools.export_puml("@startuml\n@enduml", target)
        assert target.stat().st_mode & 0o777 == 0o600

    def test_the_process_umask_is_never_read_or_changed(
        self, tmp_path, monkeypatch
    ) -> None:
        def forbidden(mask: int) -> int:
            raise AssertionError("export_puml must not touch the process umask")

        monkeypatch.setattr(os, "umask", forbidden)
        target = tmp_path / "lineage.puml"
        plantuml_tools.export_puml("@startuml\n@enduml", target)
        assert target.exists()
