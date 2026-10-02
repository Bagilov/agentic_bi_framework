"""OPC operations on the `.pbix` container (zip): read members, swap the
DataModel, build a clean "scaffolding + our Layout + DataModel" package.

The single source of low-level zip handling (previously duplicated).

Public API:
    COPY_MEMBERS
    read_member(pbix, name) -> bytes
    list_members(pbix) -> list[tuple[str, int]]
    swap_datamodel(template, datamodel, out) -> int
    build_container(template, layout, datamodel, out, copy_members=None) -> int
"""

from __future__ import annotations

import logging
import struct
import zipfile
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)

# Environment scaffolding (theme/settings/bindings) independent of the model and
# the report, copied from the template container as-is.
COPY_MEMBERS = [
    "Version",
    "[Content_Types].xml",
    "DiagramLayout",
    "Settings",
    "Metadata",
    "Report/LinguisticSchema",
    "Report/StaticResources/SharedResources/BaseThemes/CY24SU05.json",
    "SecurityBindings",
]


def read_member(pbix: Path, name: str) -> bytes:
    """Return the bytes of a single `.pbix` member (OPC zip)."""
    with zipfile.ZipFile(pbix) as z:
        return z.read(name)


def list_members(pbix: Path) -> list[tuple[str, int]]:
    """Return (name, size) for each archive member in order."""
    with zipfile.ZipFile(pbix) as z:
        return [(i.filename, i.file_size) for i in z.infolist()]


def _locate_datamodel(orig: bytearray, template: Path) -> tuple[int, int, int]:
    """Return (local-header offset, data start, old length) of the DataModel."""
    with zipfile.ZipFile(template) as z:
        lho = next(i.header_offset for i in z.infolist() if i.filename == "DataModel")
    name_len, extra_len = struct.unpack("<HH", orig[lho + 26:lho + 30])
    data_start = lho + 30 + name_len + extra_len
    eocd = orig.rfind(b"PK\x05\x06")
    _cd_size, cd_off = struct.unpack("<II", orig[eocd + 12:eocd + 20])
    return lho, data_start, cd_off - data_start


def _rewrite_local_header(head: bytearray, lho: int, crc: int, size: int) -> None:
    """Patch CRC and both size fields in the DataModel local header."""
    struct.pack_into("<I", head, lho + 14, crc)
    struct.pack_into("<I", head, lho + 18, size)
    struct.pack_into("<I", head, lho + 22, size)


def _rewrite_central_dir(pb: bytearray, new_cd_offset: int, crc: int, size: int) -> None:
    """Patch the DataModel entry in the central directory and the EOCD offset."""
    pos = new_cd_offset
    while pos + 46 <= len(pb) and pb[pos:pos + 4] == b"PK\x01\x02":
        name_len, extra_len, comment_len = struct.unpack("<HHH", pb[pos + 28:pos + 34])
        name = pb[pos + 46:pos + 46 + name_len].decode("utf-8", "replace")
        if name == "DataModel":
            struct.pack_into("<I", pb, pos + 16, crc)
            struct.pack_into("<II", pb, pos + 20, size, size)
            break
        pos += 46 + name_len + extra_len + comment_len
    struct.pack_into("<I", pb, len(pb) - 22 + 16, new_cd_offset)


def swap_datamodel(template: Path, datamodel: bytes, out: Path) -> int:
    """Replace the `DataModel` member in `template` with `datamodel`, write `out`.

    Other members stay byte-for-byte. Returns the output size.
    """
    orig = bytearray(template.read_bytes())
    lho, data_start, old_len = _locate_datamodel(orig, template)
    crc = zlib.crc32(datamodel) & 0xFFFFFFFF
    head = bytearray(orig[:data_start])
    _rewrite_local_header(head, lho, crc, len(datamodel))
    pb = bytearray(bytes(head) + datamodel + bytes(orig[data_start + old_len:]))
    _rewrite_central_dir(pb, len(head) + len(datamodel), crc, len(datamodel))
    out.write_bytes(bytes(pb))
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None:
            raise ValueError("output zip invalid")
    logger.info("swap_datamodel: %s -> %s (%d B)", template.name, out.name, len(pb))
    return len(pb)


def build_container(template: Path, layout: bytes, datamodel: bytes, out: Path,
                    copy_members: list[str] | None = None) -> int:
    """Build a clean package: copy of the scaffolding + new `Report/Layout` + `DataModel`.

    Donor visuals are not carried over — the caller provides the full Layout.
    """
    members = copy_members or COPY_MEMBERS
    with zipfile.ZipFile(template) as src, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in members:
            dst.writestr(name, src.read(name))
        dst.writestr("Report/Layout", layout)
        dst.writestr("DataModel", datamodel)
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None:
            raise ValueError("output zip invalid")
    logger.info("build_container: %s (%d B)", out.name, out.stat().st_size)
    return out.stat().st_size