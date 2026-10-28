"""Re-lay an ABF buffer around members of arbitrary (uneven) length.

The engine stores members back to back and records every absolute offset twice:
in the `virtual_directory` (a `m_cbOffsetHeader` per member) and in the
`BackupLogHeader` (the virtual directory's own offset). Replacing a member with
a different-length payload therefore invalidates both indexes — the bytes can no
longer be patched in place.

This module rebuilds the buffer from scratch: the verbatim prefix, the member
payloads in file-list order (with replacements and additions), the backup log,
then the virtual directory, recomputing every offset. The original XML trees are
reused, so engine-managed fields survive untouched.

Public API:
    ABFLayoutError
    ABFIndex                             - parsed header + log + virtual dir
    parse_abf_index(abf) -> ABFIndex
    relayout_abf(abf, *, replace=None, add=None) -> RelayoutResult
    member_blob(abf, storage_path) -> bytes
    find_member(abf, predicate) -> VFile | None

`relayout_abf` is the uneven-length counterpart of an in-place byte patch.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from agentic_bi.pbix_binary.abf_model import (
    HEADER_END,
    HEADER_START,
    LOG_MEMBER,
    PREFIX_MEMBERS,
    PREFIX_SIZE,
    ABFHeader,
    BackupLog,
    VFile,
    parse_backup_log,
    parse_header,
    parse_virtual_directory,
    serialize_backup_log,
    serialize_header,
    serialize_virtual_directory,
    storage_key,
)

logger = logging.getLogger(__name__)


class ABFLayoutError(ValueError):
    """Raised when an ABF buffer cannot be parsed or re-laid."""


@dataclass
class ABFIndex:
    """The three parsed indexes of an ABF buffer."""

    header: ABFHeader
    log: BackupLog
    files: list[VFile]

    @property
    def data_members(self) -> list[VFile]:
        """Virtual-directory entries that carry payloads (no prefix/LOG)."""
        return [vf for vf in self.files if vf.path not in (*PREFIX_MEMBERS, LOG_MEMBER)]

    def storage_of(self, logical_name: str) -> str | None:
        """Resolve a logical member name to its storage path (case-insensitive)."""
        wanted = logical_name.lower()
        for entry in self.log.iter_files():
            if self.log.logical_name(entry).lower() == wanted:
                return entry.storage_path
        return None


@dataclass
class RelayoutResult:
    """The re-laid ABF plus a human-readable log of the changes."""

    data: bytes
    log: list[str] = field(default_factory=list)


def parse_abf_index(abf: bytes) -> ABFIndex:
    """Parse the header, virtual directory and backup log of an ABF buffer."""
    try:
        header = parse_header(abf)
    except Exception as exc:
        raise ABFLayoutError(f"cannot parse ABF header: {exc}") from exc
    vdir_end = header.vdir_offset + header.vdir_size
    if header.vdir_offset <= 0 or vdir_end > len(abf):
        raise ABFLayoutError(
            "virtual directory range is outside the buffer "
            f"({header.vdir_offset}..{vdir_end} of {len(abf)})"
        )
    files = parse_virtual_directory(abf[header.vdir_offset : vdir_end])
    if not files:
        raise ABFLayoutError("virtual directory has no entries")
    anchor = files[-1]
    if anchor.path != LOG_MEMBER:
        raise ABFLayoutError(
            f"last virtual-directory entry is {anchor.path!r}, expected {LOG_MEMBER!r}"
        )
    try:
        log = parse_backup_log(abf[anchor.offset : anchor.offset + anchor.size])
    except Exception as exc:
        raise ABFLayoutError(f"cannot parse backup log: {exc}") from exc
    return ABFIndex(header=header, log=log, files=files)


def find_member(abf: bytes, predicate: Callable[[str], bool]) -> VFile | None:
    """Return the first data member whose storage path satisfies `predicate`."""
    for vf in parse_abf_index(abf).data_members:
        if predicate(vf.path):
            return vf
    return None


def member_blob(abf: bytes, storage_path: str) -> bytes:
    """Extract one member's payload by its virtual-directory storage path."""
    vf = find_member(abf, lambda path: path == storage_path)
    if vf is None:
        raise ABFLayoutError(f"member {storage_path!r} not found")
    return abf[vf.offset : vf.offset + vf.size]


def relayout_abf(
    abf: bytes,
    *,
    replace: dict[str, bytes] | None = None,
    add: dict[str, bytes] | None = None,
) -> RelayoutResult:
    """Rebuild `abf`, replacing/adding members of any length and re-offsetting.

    Args:
        abf: a decompressed ABF buffer.
        replace: ``{logical_name: bytes}`` — overwrite existing members. The name
            is matched case-insensitively against each member's logical name
            (its backup-log path relative to the persist root).
        add: ``{logical_name: bytes}`` — append brand-new members. Names not
            already present get a fresh storage id and a backup-log entry.

    Returns:
        RelayoutResult with the new buffer and a change log.

    Raises:
        ABFLayoutError: if the buffer is malformed, a replacement name is not
            found, or the rebuilt header does not fit its page.
    """
    replace = dict(replace or {})
    add = dict(add or {})
    if not replace and not add:
        return RelayoutResult(data=abf, log=[])

    index = parse_abf_index(abf)
    persist_root = index.log.persist_root()
    replace_lower = {name.lower(): blob for name, blob in replace.items()}
    entry_by_storage = {e.storage_path: e for e in index.log.iter_files()}

    out = bytearray(abf[:PREFIX_SIZE])
    cursor = PREFIX_SIZE
    new_vdir: list[VFile] = []
    log_lines: list[str] = []

    by_path = {vf.path: vf for vf in index.files}
    for name in PREFIX_MEMBERS:
        if name in by_path:
            new_vdir.append(_clone(by_path[name]))

    seen: set[str] = set()
    for vf in index.files:
        if vf.path in (*PREFIX_MEMBERS, LOG_MEMBER):
            continue
        entry = entry_by_storage.get(vf.path)
        logical = index.log.logical_name(entry) if entry else vf.path
        key = logical.lower()
        seen.add(key)
        if key in replace_lower:
            blob = replace_lower.pop(key)
            log_lines.append(f"replace {logical}: {vf.size} -> {len(blob)} B")
        else:
            blob = abf[vf.offset : vf.offset + vf.size]
        out += blob
        index.log.set_size(vf.path, len(blob))
        new_vdir.append(
            VFile(
                path=vf.path,
                size=len(blob),
                offset=cursor,
                delete=vf.delete,
                created_ts=vf.created_ts,
                access=vf.access,
                last_write=vf.last_write,
            )
        )
        cursor += len(blob)

    if replace_lower:
        raise ABFLayoutError(
            "replacement member(s) not found: " + ", ".join(sorted(replace_lower))
        )

    for logical, blob in add.items():
        if logical.lower() in seen:
            continue
        storage = storage_key()
        out += blob
        new_vdir.append(VFile(path=storage, size=len(blob), offset=cursor))
        cursor += len(blob)
        index.log.add_data_file(persist_root + logical, storage, len(blob), 0)
        log_lines.append(f"add {logical}: {len(blob)} B (storage {storage})")

    log_bytes = serialize_backup_log(index.log)
    log_offset = len(out)
    out += log_bytes

    vdir_offset = len(out)
    new_vdir.append(VFile(path=LOG_MEMBER, size=len(log_bytes), offset=log_offset))
    vdir_bytes = serialize_virtual_directory(new_vdir)
    out += vdir_bytes

    header_xml = serialize_header(
        index.header,
        vdir_offset=vdir_offset,
        vdir_size=len(vdir_bytes),
        files=len(new_vdir),
    )
    # The header page is UTF-16LE without a BOM (verified against engine output).
    header_bytes = header_xml.encode("utf-16-le")
    page = HEADER_END - HEADER_START
    if len(header_bytes) > page:
        raise ABFLayoutError(f"header XML too large for the {page}-byte page")
    out[HEADER_START:HEADER_END] = header_bytes + b"\x00" * (page - len(header_bytes))

    logger.debug(
        "relayout_abf: %d -> %d B, %d members", len(abf), len(out), len(new_vdir)
    )
    return RelayoutResult(data=bytes(out), log=log_lines)


def _clone(vf: VFile) -> VFile:
    return VFile(
        path=vf.path,
        size=vf.size,
        offset=vf.offset,
        delete=vf.delete,
        created_ts=vf.created_ts,
        access=vf.access,
        last_write=vf.last_write,
    )
