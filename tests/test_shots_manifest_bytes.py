"""`verify` must check the recorded size, not only the hash.

`bytes` is part of the manifest contract (and required for an `ok` record), but
`verify_manifest` re-hashed the file and never compared the size, so a manifest
with `"bytes": 999999` verified clean.
"""

from __future__ import annotations

from pathlib import Path

from agentic_bi.shots.shots_manifest import (
    STATUS_OK,
    RenderRecord,
    ShotManifest,
    sha256_file,
    verify_manifest,
)


def _manifest(tmp_path: Path, *, size: int | None = None) -> ShotManifest:
    png = tmp_path / "fig.png"
    png.write_bytes(b"\x89PNG" + b"0" * 100)
    record = RenderRecord(
        name="fig",
        kind="page",
        source="board.pbix",
        status=STATUS_OK,
        png=str(png),
        width=10,
        height=10,
        scale=1.0,
        sha256=sha256_file(png),
        bytes=size if size is not None else png.stat().st_size,
    )
    return ShotManifest(browser="chromium", root=str(tmp_path), figures=[record])


def test_a_matching_size_verifies_clean(tmp_path: Path) -> None:
    assert verify_manifest(_manifest(tmp_path)) == []


def test_a_wrong_size_is_drift(tmp_path: Path) -> None:
    problems = verify_manifest(_manifest(tmp_path, size=999_999))
    assert any("size mismatch" in problem for problem in problems)
