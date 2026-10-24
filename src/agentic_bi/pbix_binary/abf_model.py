"""Binary DataModel (ABF) member model and its two XML indexes.

A decompressed `DataModel` member is an *ABF* buffer: a fixed prefix, a
`BackupLogHeader` XML page, the member payloads back to back, then a
`backup_log` XML and a `virtual_directory` XML. The `virtual_directory` gives
every stored member an absolute `m_cbOffsetHeader` and a `Size`; the
`backup_log` lists logical files (persist path + storage id) grouped by class.

This module is the single place that knows those structures. It parses them
into typed records while **keeping the original XML documents**, so unknown
engine-managed fields survive a rewrite verbatim. Callers can then replace or
append members of *arbitrary length* without knowing the layout.

Public API:
    VFile                     - one virtual-directory entry
    BackupFileEntry           - one backup-log file-list entry
    FileGroup                 - a backup-log file group (typed view)
    BackupLog                 - parsed `backup_log` document (raw + typed)
    ABFHeader                 - parsed `BackupLogHeader` (raw + typed)
    parse_header(buf) -> ABFHeader
    serialize_header(header, *, vdir_offset, vdir_size, files) -> bytes
    parse_virtual_directory(buf) -> list[VFile]
    serialize_virtual_directory(files) -> bytes
    parse_backup_log(buf) -> BackupLog
    serialize_backup_log(log) -> bytes
    DATA_GROUP_CLASS (str)    - class of the group holding data members
    storage_key() -> str      - a fresh uppercase storage id
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# Prefix layout of a decompressed ABF (verified against engine output).
SIGNATURE_SIZE = 72
HEADER_START = 72
HEADER_END = 4096
DATA_OFFSET = 4096
PREFIX_SIZE = 4236  # header + ADDITIONAL_LOG + PARTITIONS, kept verbatim

# Virtual-directory pseudo-members whose payload lives inside the prefix.
PREFIX_MEMBERS = ("ADDITIONAL_LOG", "PARTITIONS")
LOG_MEMBER = "LOG"

# Class of the file group that stores the data members (columns/sqlite/...).
DATA_GROUP_CLASS = "100069"

# Header fields this module owns (rewritten on every re-layout).
_HEADER_OFFSET = "m_cbOffsetHeader"
_HEADER_SIZE = "DataSize"
_HEADER_FILES = "Files"
_HEADER_DATA = "m_cbOffsetData"
_HEADER_MANAGED = (_HEADER_OFFSET, _HEADER_SIZE, _HEADER_FILES, _HEADER_DATA)


def storage_key() -> str:
    """Return a fresh uppercase 20-hex storage id for a new member."""
    return uuid.uuid4().hex.upper()[:20]


def _set_text(root: ET.Element, tag: str, value: str) -> None:
    """Set (creating if missing) the text of a direct child element."""
    child = root.find(tag)
    if child is None:
        child = ET.SubElement(root, tag)
    child.text = value


@dataclass
class VFile:
    """One `<BackupFile>` entry of the virtual directory."""

    path: str
    size: int
    offset: int
    delete: bool = False
    created_ts: int = 0
    access: int = 0
    last_write: int = 0


@dataclass
class BackupFileEntry:
    """One `<BackupFile>` of a backup-log file list."""

    path: str
    storage_path: str
    size: int
    last_write: int = 0


@dataclass
class FileGroup:
    """A backup-log `<FileGroup>` (class + persist root + file list)."""

    cls: str
    persist_root: str
    files: list[BackupFileEntry] = field(default_factory=list)


@dataclass
class BackupLog:
    """A parsed `backup_log` document: the raw tree plus a typed view.

    `root` is kept so serialization reproduces every engine-managed field
    (server roots, sync flags, encryption flags, ...) verbatim; the typed
    `groups` are a convenience view for lookups and size updates.
    """

    root: ET.Element
    groups: list[FileGroup] = field(default_factory=list)

    @property
    def data_group(self) -> FileGroup | None:
        """The group that stores data members (by class tag)."""
        return next((g for g in self.groups if g.cls == DATA_GROUP_CLASS), None)

    def persist_root(self) -> str:
        """The persist root of the data group (falls back to the first group)."""
        group = self.data_group or (self.groups[0] if self.groups else None)
        if group is None:
            raise ValueError("backup_log has no file groups")
        root = group.persist_root
        return root if root.endswith("\\") else root + "\\"

    def logical_name(self, entry: BackupFileEntry) -> str:
        """Map a file-list entry path to its name relative to the persist root."""
        root = self.persist_root()
        return entry.path[len(root) :] if entry.path.startswith(root) else entry.path

    def iter_files(self) -> list[BackupFileEntry]:
        """All file-list entries across every group, in document order."""
        return [entry for group in self.groups for entry in group.files]

    def set_size(self, storage_path: str, size: int) -> None:
        """Update the recorded size of one member across the raw tree."""
        for group in self.root.findall("FileGroups/FileGroup"):
            for bf in group.findall("FileList/BackupFile"):
                if bf.findtext("StoragePath") == storage_path:
                    _set_text(bf, "Size", str(size))

    def set_size_by_suffix(self, suffix: str, size: int) -> None:
        """Update the size of every file-list entry whose path ends in `suffix`."""
        for group in self.root.findall("FileGroups/FileGroup"):
            for bf in group.findall("FileList/BackupFile"):
                if (bf.findtext("Path") or "").endswith(suffix):
                    _set_text(bf, "Size", str(size))

    def add_data_file(
        self, logical_path: str, storage_path: str, size: int, last_write: int
    ) -> None:
        """Append a new BackupFile to the data group's file list."""
        for group in self.root.findall("FileGroups/FileGroup"):
            if group.findtext("Class") != DATA_GROUP_CLASS:
                continue
            list_el = group.find("FileList")
            if list_el is None:
                raise ValueError("data group has no FileList")
            bf = ET.SubElement(list_el, "BackupFile")
            ET.SubElement(bf, "Path").text = logical_path
            ET.SubElement(bf, "StoragePath").text = storage_path
            ET.SubElement(bf, "LastWriteTime").text = str(last_write)
            ET.SubElement(bf, "Size").text = str(size)
            return
        raise ValueError(f"no class-{DATA_GROUP_CLASS} file group")


@dataclass
class ABFHeader:
    """The `BackupLogHeader` XML page: the raw tree plus parsed scalars."""

    root: ET.Element
    vdir_offset: int
    vdir_size: int
    files: int
    data_offset: int
    object_id: str


def _strip_nul(text: str) -> str:
    return text.replace("\x00", "")


def parse_header(buf: bytes) -> ABFHeader:
    """Parse the `BackupLogHeader` XML page at [72:4096] of a decompressed ABF."""
    xml = _strip_nul(buf[HEADER_START:HEADER_END].decode("utf-16", "ignore"))
    root = ET.fromstring(xml)
    return ABFHeader(
        root=root,
        vdir_offset=int(root.findtext(_HEADER_OFFSET)),
        vdir_size=int(root.findtext(_HEADER_SIZE)),
        files=int(root.findtext(_HEADER_FILES)),
        data_offset=int(root.findtext(_HEADER_DATA)),
        object_id=root.findtext("ObjectID") or "",
    )


def serialize_header(
    header: ABFHeader, *, vdir_offset: int, vdir_size: int, files: int
) -> str:
    """Rebuild the header XML with fresh offsets and counts (in place)."""
    _set_text(header.root, _HEADER_OFFSET, str(vdir_offset))
    _set_text(header.root, _HEADER_SIZE, str(vdir_size))
    _set_text(header.root, _HEADER_FILES, str(files))
    _set_text(header.root, _HEADER_DATA, str(header.data_offset))
    return ET.tostring(header.root, encoding="unicode")


def parse_virtual_directory(buf: bytes) -> list[VFile]:
    """Parse the virtual-directory XML into `VFile` records, in order."""
    root = ET.fromstring(buf.decode("utf-8"))
    return [
        VFile(
            path=entry.findtext("Path") or "",
            size=int(entry.findtext("Size") or 0),
            offset=int(entry.findtext("m_cbOffsetHeader") or 0),
            delete=(entry.findtext("Delete") == "true"),
            created_ts=int(entry.findtext("CreatedTimestamp") or 0),
            access=int(entry.findtext("Access") or 0),
            last_write=int(entry.findtext("LastWriteTime") or 0),
        )
        for entry in root.findall("BackupFile")
    ]


def serialize_virtual_directory(files: list[VFile]) -> bytes:
    """Serialize virtual-directory entries (UTF-8, no BOM) back to XML bytes.

    Built with `ElementTree` rather than string interpolation so member paths are
    escaped: the parser decodes entities, so a path containing ``&``/``<``/``>``
    would otherwise round-trip into a malformed document. No XML declaration is
    emitted, matching what the engine writes.
    """
    root = ET.Element("VirtualDirectory")
    for f in files:
        entry = ET.SubElement(root, "BackupFile")
        ET.SubElement(entry, "Path").text = f.path
        ET.SubElement(entry, "Size").text = str(f.size)
        ET.SubElement(entry, "m_cbOffsetHeader").text = str(f.offset)
        ET.SubElement(entry, "Delete").text = "true" if f.delete else "false"
        ET.SubElement(entry, "CreatedTimestamp").text = str(f.created_ts)
        ET.SubElement(entry, "Access").text = str(f.access)
        ET.SubElement(entry, "LastWriteTime").text = str(f.last_write)
    return ET.tostring(root, encoding="unicode").encode("utf-8")


def parse_backup_log(buf: bytes) -> BackupLog:
    """Parse the `backup_log` document (UTF-16) into `BackupLog`."""
    root = ET.fromstring(buf.decode("utf-16"))
    groups: list[FileGroup] = []
    for group in root.findall("FileGroups/FileGroup"):
        entries = [
            BackupFileEntry(
                path=bf.findtext("Path") or "",
                storage_path=bf.findtext("StoragePath") or "",
                size=int(bf.findtext("Size") or 0),
                last_write=int(bf.findtext("LastWriteTime") or 0),
            )
            for bf in group.findall("FileList/BackupFile")
        ]
        groups.append(
            FileGroup(
                cls=group.findtext("Class") or "",
                persist_root=group.findtext("PersistLocationPath") or "",
                files=entries,
            )
        )
    return BackupLog(root=root, groups=groups)


def serialize_backup_log(log: BackupLog) -> bytes:
    """Serialize the backup log with a single leading BOM (UTF-16LE).

    The engine writes `b'\\xff\\xfe' + <utf-16le body>`; using `.encode('utf-16')`
    on top of an explicit ``\\ufeff`` would emit a double BOM (a forbidden
    U+FFFE) and the reader rejects the document. So the BOM is written once, by
    hand, and the body is encoded as UTF-16LE.
    """
    body = ET.tostring(log.root, encoding="unicode")
    return ("\ufeff" + body).encode("utf-16-le")
