"""PNG header and dimension checks for the board guide (`guide_png`).

A screenshot is external input, so the guide verifies the PNG signature before
emitting an `<img>` and reads the IHDR dimensions before trusting percentage
hotspots. `png_bytes` builds a genuinely valid PNG (deflated pixels, correct
CRCs) for tests that need a real image with chosen dimensions.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from agentic_bi.board_guide.guide_png import PNG_SIGNATURE, png_size


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png_bytes(width: int, height: int) -> bytes:
    """A valid opaque-white RGB PNG of exactly `width` x `height` pixels."""
    row = b"\x00" + b"\xff\xff\xff" * width
    raw = row * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


MINIMAL_PNG = png_bytes(1, 1)


def test_png_size_reads_the_ihdr_dimensions(tmp_path: Path) -> None:
    image = tmp_path / "page_Tall.png"
    image.write_bytes(png_bytes(720, 1600))
    assert png_size(image) == (720, 1600)


def test_png_size_rejects_a_truncated_signature(tmp_path: Path) -> None:
    """The eight magic bytes alone are not a PNG: the IHDR size is missing."""
    image = tmp_path / "page_Bad.png"
    image.write_bytes(PNG_SIGNATURE)
    assert png_size(image) is None


def test_png_size_rejects_text_named_png(tmp_path: Path) -> None:
    image = tmp_path / "page_Text.png"
    image.write_bytes(b"<html>not a screenshot</html>")
    assert png_size(image) is None


def test_png_size_rejects_a_missing_file(tmp_path: Path) -> None:
    assert png_size(tmp_path / "absent.png") is None
