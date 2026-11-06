"""Publishing safety tests: same-device staging, failure isolation, exit mapping."""

from __future__ import annotations

import errno
import os
import re
from pathlib import Path
from typing import BinaryIO

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
    for index, name in enumerate(names, start=1):
        (out_dir / f"{name}.png").write_bytes(f"block {index}".encode())
    return _Completed()


class TestPublishSafety:
    def test_staging_happens_inside_the_output_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        real_replace = os.replace
        recorded: list[tuple[Path, Path]] = []

        def recording_replace(src: object, dst: object) -> None:
            recorded.append((Path(str(src)), Path(str(dst))))
            real_replace(src, dst)

        monkeypatch.setattr(plantuml_publish.os, "replace", recording_replace)
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header)
        plantuml_tools.render_png(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        assert recorded
        assert all(source.parent == tmp_path for source, _ in recorded)

    def test_publishing_never_moves_from_the_temporary_work_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("shutil.move must not publish across filesystems")

        monkeypatch.setattr(plantuml_publish.shutil, "move", forbidden)
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header)
        png = plantuml_tools.render_png(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        assert png == tmp_path / "lineage.png"

    def test_a_failed_stage_copy_keeps_the_previous_artifact(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        target = tmp_path / "lineage.png"
        target.write_bytes(b"previous good diagram")

        def broken_copy(reader: BinaryIO, writer: BinaryIO) -> None:
            writer.write(b"partial")
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(plantuml_publish.shutil, "copyfileobj", broken_copy)
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header)
        png, diagnostic = plantuml_tools.render_png_ex(
            "@startuml\n@enduml", tmp_path, jar="/fake/plantuml.jar", name="lineage"
        )
        assert png is None
        assert "could not publish" in diagnostic
        assert target.read_bytes() == b"previous good diagram"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["lineage.png"]

    def test_a_rename_failure_is_a_diagnostic_and_leaves_the_primary(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        target = tmp_path / "lineage.png"
        target.write_bytes(b"previous primary")
        real_replace = os.replace

        def failing_replace(src: object, dst: object) -> None:
            if Path(str(dst)).name == "lineage_2.png":
                raise PermissionError(errno.EACCES, "sharing violation")
            real_replace(src, dst)

        monkeypatch.setattr(plantuml_publish.os, "replace", failing_replace)
        monkeypatch.setattr(plantuml_tools, "_run", _write_by_header)
        png, diagnostic = plantuml_tools.render_png_ex(
            "@startuml one\n@enduml\n@startuml two\n@enduml",
            tmp_path,
            jar="/fake/plantuml.jar",
            name="lineage",
        )
        assert png is None
        assert "could not publish" in diagnostic
        assert target.read_bytes() == b"previous primary"
        assert not (tmp_path / "lineage_2.png").exists()
        assert list(tmp_path.glob("*.tmp")) == []
