"""PNG identity for the board guide: signature and IHDR dimensions (stdlib only).

A screenshot is an external input: a file named `page_<stem>.png` may be a text
file, a truncated download, an HTML error page or a real PNG with a different
aspect ratio than the layout canvas. Both facts are visible in the first 24
bytes, so the guide verifies the signature before emitting an `<img>` and reads
the IHDR size before trusting percentage hotspots.

Public API:
    PNG_SIGNATURE          - the eight-byte PNG file signature
    png_size(path)         - `(width, height)` from IHDR, or None when not a PNG
"""

from __future__ import annotations

import struct
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_IHDR = b"IHDR"
_IHDR_LENGTH = 13
_HEADER_BYTES = len(PNG_SIGNATURE) + 8 + 8


def png_size(path: str | Path) -> tuple[int, int] | None:
    """The pixel size declared by a PNG's IHDR chunk, or None.

    None means "not a usable PNG" for the same reason every caller cares: the
    file is missing, shorter than a PNG header, carries another signature, its
    first chunk is not IHDR, or it declares a non-positive size. A truncated
    signature (for example the eight magic bytes alone) is rejected too, because
    the IHDR chunk that carries the dimensions is absent.
    """
    try:
        with Path(path).open("rb") as handle:
            header = handle.read(_HEADER_BYTES)
    except OSError:
        return None
    if len(header) < _HEADER_BYTES or header[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
        return None
    length = struct.unpack(">I", header[8:12])[0]
    if length != _IHDR_LENGTH or header[12:16] != _IHDR:
        return None
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        return None
    return width, height


__all__ = ["PNG_SIGNATURE", "png_size"]
