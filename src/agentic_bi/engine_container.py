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


def _locate_datamodel(orig: bytearray, template: Path) -> tuple[int, int, int, int]:
    """Return (local-header offset, data start, old stored length, method)."""
    with zipfile.ZipFile(template) as z:
        info = next(i for i in z.infolist() if i.filename == "DataModel")
    lho = info.header_offset
    name_len, extra_len = struct.unpack("<HH", orig[lho + 26 : lho + 30])
    data_start = lho + 30 + name_len + extra_len
    # The payload length is the stored size, NOT the distance to the central
    # directory: another member may follow DataModel in the archive.
    return lho, data_start, info.compress_size, info.compress_type


def _encode_payload(payload: bytes, method: int) -> bytes:
    """Encode a member payload with the entry's compression method."""
    if method == zipfile.ZIP_STORED:
        return payload
    if method == zipfile.ZIP_DEFLATED:
        compressor = zlib.compressobj(level=9, wbits=-zlib.MAX_WBITS)
        return compressor.compress(payload) + compressor.flush()
    raise ValueError(f"unsupported DataModel compression method: {method}")


def _rewrite_local_header(
    head: bytearray, lho: int, crc: int, usize: int, csize: int
) -> None:
    """Patch CRC and both size fields in the DataModel local header."""
    struct.pack_into("<I", head, lho + 14, crc)
    struct.pack_into("<I", head, lho + 18, csize)
    struct.pack_into("<I", head, lho + 22, usize)


def _central_dir_offset(pb: bytes) -> int:
    """Return the central-directory offset recorded in the EOCD record."""
    eocd = pb.rfind(b"PK\x05\x06")
    _cd_size, cd_off = struct.unpack("<II", pb[eocd + 12 : eocd + 20])
    return cd_off


def _rewrite_central_dir(
    pb: bytearray,
    new_cd_offset: int,
    crc: int,
    usize: int,
    csize: int,
    shift_from: int,
    shift: int,
) -> None:
    """Patch the central directory after the DataModel payload changed size.

    Rewrites the DataModel entry (CRC + both sizes) and adds `shift` to the local
    header offset of every member stored after the DataModel payload, then moves
    the central-directory offset in the EOCD record.
    """
    pos = new_cd_offset
    while pos + 46 <= len(pb) and pb[pos : pos + 4] == b"PK\x01\x02":
        name_len, extra_len, comment_len = struct.unpack(
            "<HHH", pb[pos + 28 : pos + 34]
        )
        name = pb[pos + 46 : pos + 46 + name_len].decode("utf-8", "replace")
        if name == "DataModel":
            struct.pack_into("<I", pb, pos + 16, crc)
            struct.pack_into("<II", pb, pos + 20, csize, usize)
        else:
            entry_off = struct.unpack("<I", pb[pos + 42 : pos + 46])[0]
            if entry_off >= shift_from:
                struct.pack_into("<I", pb, pos + 42, entry_off + shift)
        pos += 46 + name_len + extra_len + comment_len
    struct.pack_into("<I", pb, len(pb) - 22 + 16, new_cd_offset)


def swap_datamodel(template: Path, datamodel: bytes, out: Path) -> int:
    """Replace the `DataModel` member in `template` with `datamodel`, write `out`.

    Other members stay byte-for-byte. Works whether or not `DataModel` is the
    last archive member (the central directory and the local-header offsets of
    all following members are shifted by the size delta), and preserves the
    entry's compression method. Returns the output size.
    """
    orig = bytearray(template.read_bytes())
    lho, data_start, old_len, method = _locate_datamodel(orig, template)
    old_cd_offset = _central_dir_offset(orig)
    encoded = _encode_payload(datamodel, method)
    shift = len(encoded) - old_len
    crc = zlib.crc32(datamodel) & 0xFFFFFFFF
    head = bytearray(orig[:data_start])
    _rewrite_local_header(head, lho, crc, len(datamodel), len(encoded))
    pb = bytearray(bytes(head) + encoded + bytes(orig[data_start + old_len :]))
    new_cd_offset = old_cd_offset + shift
    _rewrite_central_dir(
        pb,
        new_cd_offset,
        crc,
        len(datamodel),
        len(encoded),
        shift_from=data_start + old_len,
        shift=shift,
    )
    out.write_bytes(bytes(pb))
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None:
            raise ValueError("output zip invalid")
    logger.info("swap_datamodel: %s -> %s (%d B)", template.name, out.name, len(pb))
    return len(pb)


def build_container(
    template: Path,
    layout: bytes,
    datamodel: bytes,
    out: Path,
    copy_members: list[str] | None = None,
) -> int:
    """Build a clean package: copy of the scaffolding + new `Report/Layout` + `DataModel`.

    Donor visuals are not carried over — the caller provides the full Layout.
    """
    members = copy_members or COPY_MEMBERS
    with (
        zipfile.ZipFile(template) as src,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for name in members:
            dst.writestr(name, src.read(name))
        dst.writestr("Report/Layout", layout)
        dst.writestr("DataModel", datamodel)
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None:
            raise ValueError("output zip invalid")
    logger.info("build_container: %s (%d B)", out.name, out.stat().st_size)
    return out.stat().st_size
