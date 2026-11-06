"""Tests for the artifact manifest: only this tool's own stale files are removed."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from agentic_bi.report import plantuml_publish, plantuml_tools


class _Completed:
    """A stand-in for `subprocess.CompletedProcess` (only fields `_run` reads)."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _write_by_header(jar: str, args: list[str], stdin_text: str | None = None):
    out_dir = Path(args[args.index("-o") + 1])
    text = Path(args[-1]).read_text(encoding="utf-8")
    names = [
        match.group(1).strip()
        for match in re.finditer(r"^\s*@startuml\b(.*)$", text, re.MULTILINE)
    ]
    for name in names:
        (out_dir / f"{name}.png").write_bytes(name.encode())
    return _Completed()


class TestManifestCleanup:
    def test_a_larger_run_records_a_manifest_and_a_smaller_run_prunes_it(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header)
        plantuml_tools.render_png(
            "@startuml a\n@enduml\n@startuml b\n@enduml\n@startuml c\n@enduml",
            tmp_path,
            jar="/fake/plantuml.jar",
            name="lineage",
        )
        manifest = plantuml_publish.manifest_path(tmp_path, "lineage")
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        assert recorded["artifacts"] == [
            "lineage.png",
            "lineage_2.png",
            "lineage_3.png",
        ]

        plantuml_tools.render_png(
            "@startuml only\n@enduml",
            tmp_path,
            jar="/fake/plantuml.jar",
            name="lineage",
        )
        assert sorted(p.name for p in tmp_path.glob("*.png")) == ["lineage.png"]

    def test_without_a_manifest_a_lookalike_user_file_is_kept_and_reported(
        self, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        user_file = tmp_path / "lineage_2.png"
        user_file.write_bytes(b"user's own diagram")
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header)
        with caplog.at_level(logging.WARNING, logger=plantuml_publish.__name__):
            plantuml_tools.render_png(
                "@startuml only\n@enduml",
                tmp_path,
                jar="/fake/plantuml.jar",
                name="lineage",
            )
        assert user_file.read_bytes() == b"user's own diagram"
        assert "may belong to the user" in caplog.text

    def test_a_malformed_manifest_is_ignored_and_nothing_is_deleted(
        self, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        user_file = tmp_path / "lineage_2.png"
        user_file.write_bytes(b"user's own diagram")
        manifest = plantuml_publish.manifest_path(tmp_path, "lineage")
        manifest.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header)
        with caplog.at_level(logging.WARNING, logger=plantuml_publish.__name__):
            plantuml_tools.render_png(
                "@startuml only\n@enduml",
                tmp_path,
                jar="/fake/plantuml.jar",
                name="lineage",
            )
        assert user_file.exists()
        assert "unreadable diagram manifest" in caplog.text

    def test_a_manifest_entry_outside_the_stem_is_never_deleted(
        self, tmp_path: Path
    ) -> None:
        foreign = tmp_path / "unrelated.png"
        foreign.write_bytes(b"keep me")
        manifest = plantuml_publish.manifest_path(tmp_path, "lineage")
        manifest.write_text(
            json.dumps({"version": 1, "artifacts": ["unrelated.png"]}),
            encoding="utf-8",
        )
        plantuml_publish._remove_stale_targets(
            tmp_path, "lineage", {"lineage.png"}, ["unrelated.png"]
        )
        assert foreign.exists()
