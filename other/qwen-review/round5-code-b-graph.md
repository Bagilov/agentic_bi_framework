# Code bundle B: pbix binary + web report

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/pbix_binary/patch_pipeline.py ====================

"""Member-level patching of a `.pbix` container (equal and uneven length).

The `.pbix` is an OPC (zip) package whose `DataModel` member holds the binary
model (ABF, XPress9-framed). Two kinds of edits are supported:

* **Equal length** — an in-place byte substitution inside the ABF. Mutable
  offsets are untouched, so the buffer can be written straight back.
* **Uneven length** — replacing or adding a *member* whose payload differs in
  size. The ABF indexes no longer describe the buffer, so it is re-laid
  (`abf_relayout`) and re-framed (`abf_codec`), then swapped into the container.

The container swap is size-safe: it rewrites the CRC/size fields, the central
directory and the local-header offsets of every member stored after the
`DataModel` (which need not be the last member).

Patch kinds (a JSON spec is a list of objects):
    {"kind": "replace", "find": "<utf-16 text>", "with": "<same-length text>"}
    {"kind": "replace_hex", "find": "<hex>", "with": "<same-length hex>"}
    {"kind": "replace_member", "member": "<logical name>", "path": "<file>"}
    {"kind": "replace_member", "member": "<logical name>", "data": "<base64>"}

Equal-length patches must match exactly one site unless `occurrence` picks one
(`0`-based index) or `all` replaces every match; an ambiguous patch is an error
rather than a silent edit of the first match.

The written output is re-read and re-parsed before `apply_patches` returns, so a
patch can never report success while producing an unparseable `DataModel`.

Public API:
    PatchError
    classify_patches(patches) -> (even, uneven)
    apply_patches(pbix, patches, out) -> PatchReport
    swap_datamodel(template, datamodel, out) -> int  (re-exported)
"""

from __future__ import annotations

import base64
import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_bi.engine_container import swap_datamodel
from agentic_bi.pbix_binary import abf_codec, abf_relayout

logger = logging.getLogger(__name__)

__all__ = [
    "PatchError",
    "PatchReport",
    "apply_patches",
    "classify_patches",
    "load_spec",
    "swap_datamodel",
]


class PatchError(ValueError):
    """Raised for an invalid patch spec or an unmatchable pattern."""


@dataclass
class PatchReport:
    """Outcome of `apply_patches`: output path, size and an edit log."""

    out: Path
    size: int
    abf_size: int
    log: list[str] = field(default_factory=list)


def classify_patches(patches: list[dict[str, Any]]) -> tuple[list, list]:
    """Split patches into (equal-length pairs, uneven member patches).

    Equal-length patches stay byte-in-place; uneven member patches need a full
    container re-layout. A length-changing text/hex patch is rejected: it would
    shift the stream and silently corrupt the indexes.

    Raises:
        PatchError: for an unknown patch kind or a length-changing byte patch.
    """
    even: list[tuple[bytes, bytes, object]] = []
    uneven: list[dict[str, Any]] = []
    for patch in patches:
        kind = patch.get("kind", "replace")
        if kind in ("replace", "replace_hex"):
            if kind == "replace":
                find = patch["find"].encode("utf-16le")
                with_ = patch["with"].encode("utf-16le")
            else:
                find = bytes.fromhex(patch["find"])
                with_ = bytes.fromhex(patch["with"])
            if len(find) != len(with_):
                raise PatchError(
                    f"patch kind {kind!r} changes length; use 'replace_member' "
                    "for uneven-length content"
                )
            even.append((find, with_, patch.get("occurrence")))
        elif kind == "replace_member":
            uneven.append(patch)
        else:
            raise PatchError(f"unknown patch kind: {kind!r}")
    return even, uneven


def _member_payload(patch: dict[str, Any]) -> tuple[str, bytes]:
    member = patch.get("member") or patch.get("file")
    if not member:
        raise PatchError("'replace_member' needs a 'member' name")
    if "path" in patch:
        return member, Path(patch["path"]).read_bytes()
    if "data" in patch:
        return member, base64.b64decode(patch["data"])
    raise PatchError(f"'replace_member' {member!r} needs 'path' or 'data'")


def _occurrences(
    abf: bytes | bytearray, find: bytes, *, limit: int | None = None
) -> list[int]:
    """Up to `limit` start offsets where `find` occurs, scanned non-overlapping.

    The scan resumes at `start + len(find)`, so matches never overlap (an overlap
    would let `occurrence: "all"` rewrite bytes a previous match already rewrote)
    and a run of the same byte is not miscounted as many sites. `limit` stops the
    scan early: callers that only need "is it ambiguous" or "the n-th site" do not
    pay for a full-buffer enumeration of a short, repeated pattern.
    """
    offsets: list[int] = []
    start = 0
    while limit is None or len(offsets) < limit:
        start = abf.find(find, start)
        if start < 0:
            break
        offsets.append(start)
        start += len(find)
    return offsets


def _select_offsets(
    abf: bytes | bytearray, find: bytes, occurrence: object
) -> list[int]:
    """Resolve which occurrence(s) of `find` a patch applies to.

    Raises:
        PatchError: when `find` is absent, when multiple sites match and neither
            `occurrence` nor `all` says which to take, or when `occurrence` is
            out of range. Guessing (first match) is what silently edits the wrong
            bytes, so ambiguity is an error here.
    """
    if occurrence == "all":
        offsets = _occurrences(abf, find)
        if not offsets:
            raise PatchError(f"pattern not found: {find[:40]!r}")
        return offsets
    if occurrence is None:
        offsets = _occurrences(abf, find, limit=2)
        if not offsets:
            raise PatchError(f"pattern not found: {find[:40]!r}")
        if len(offsets) > 1:
            total = len(_occurrences(abf, find))
            raise PatchError(
                f"pattern {find[:40]!r} matches {total} sites; set "
                "'occurrence' (0-based index) or 'all' to choose"
            )
        return offsets
    if isinstance(occurrence, bool) or not isinstance(occurrence, int):
        raise PatchError(f"'occurrence' must be an int or 'all', got {occurrence!r}")
    if occurrence < 0:
        raise PatchError(f"'occurrence' must be >= 0, got {occurrence}")
    offsets = _occurrences(abf, find, limit=occurrence + 1)
    if not offsets:
        raise PatchError(f"pattern not found: {find[:40]!r}")
    if occurrence >= len(offsets):
        total = len(_occurrences(abf, find))
        raise PatchError(f"'occurrence' {occurrence} out of range ({total} match(es))")
    return [offsets[occurrence]]


def _apply_even(
    abf: bytearray, even: list[tuple[bytes, bytes, object]], log: list[str]
) -> None:
    for find, with_, occurrence in even:
        for index in _select_offsets(abf, find, occurrence):
            abf[index : index + len(find)] = with_
            log.append(f"replace: {len(find)} B at offset {index}")


def _verify_output(out: Path) -> None:
    """Re-read the written `.pbix` and confirm its `DataModel` still parses.

    `swap_datamodel` only proves the archive is a valid zip; this proves the
    model inside it is intact. It is the guard that turns any future writer bug
    (e.g. an unescaped member path) into a loud failure instead of a file that
    Power BI cannot open.

    Raises:
        PatchError: when the output cannot be re-read or its ABF index is broken.
    """
    try:
        with zipfile.ZipFile(out) as z:
            datamodel = z.read("DataModel")
        abf = abf_codec.decompress_datamodel(datamodel)
        abf_relayout.parse_abf_index(abf)
    except PatchError:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure means an invalid output
        raise PatchError(f"written .pbix failed self-verification: {exc}") from exc


def apply_patches(pbix: Path, patches: list[dict[str, Any]], out: Path) -> PatchReport:
    """Apply a patch list to a `.pbix` and write `out`.

    Equal-length patches are applied in place on the decompressed ABF; uneven
    member patches trigger one re-layout of the whole buffer. The result is
    re-framed and swapped into a copy of the container, then re-read and verified
    before returning.

    Args:
        pbix: the source `.pbix` (its DataModel is the base).
        patches: the patch list (see the module docstring for kinds).
        out: the destination `.pbix`.

    Returns:
        PatchReport with the output path, container/ABF sizes and an edit log.

    Raises:
        PatchError: on an invalid spec, an unmatched or ambiguous pattern, or an
            output that fails self-verification.
    """
    pbix = Path(pbix)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    even, uneven = classify_patches(patches)
    datamodel = _read_member(pbix, "DataModel")
    abf = bytearray(abf_codec.decompress_datamodel(datamodel))
    log: list[str] = []

    _apply_even(abf, even, log)

    if uneven:
        replace: dict[str, bytes] = {}
        for patch in uneven:
            member, payload = _member_payload(patch)
            replace[member] = payload
            log.append(f"replace_member {member}: {len(payload)} B")
        result = abf_relayout.relayout_abf(bytes(abf), replace=replace)
        abf = bytearray(result.data)
        log.extend(result.log)

    new_datamodel = abf_codec.compress_datamodel(bytes(abf))
    size = swap_datamodel(pbix, new_datamodel, out)
    _verify_output(out)
    logger.info("apply_patches: %s -> %s (%d B)", pbix.name, out.name, size)
    return PatchReport(out=out, size=size, abf_size=len(abf), log=log)


def load_spec(path: Path) -> list[dict[str, Any]]:
    """Load a patch list from a JSON document (`{"patches": [...]}` or a list)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    patches = data.get("patches") if isinstance(data, dict) else data
    if not isinstance(patches, list):
        raise PatchError("patch spec must be a list or {'patches': [...]}")
    return patches


def _read_member(pbix: Path, name: str) -> bytes:
    with zipfile.ZipFile(pbix) as z:
        return z.read(name)

==================== FILE: src/agentic_bi/pbix_binary/abf_model.py ====================

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

==================== FILE: src/agentic_bi/web_report/web_render.py ====================

"""Render the dashboard clone as a *layout* of the original report.

The output mirrors the source report: page tabs, and on each page every element
is placed at its true `Report/Layout` position/size and drawn with a mock glyph
for its visual type (the real visuals cannot render without the engine). Each
element is interactive:

* hovering shows a tooltip with its metrics and the checks it violated;
* problem elements are outlined by severity (red/amber);
* the filter panel (severity / page / visual type / check id) dims everything
  that does not match, so problem spots can be isolated on the layout.

A collapsed "details" section carries the flat metrics table and the issue list
for those who want the tabular view.

Public API:
    render_html(model, title=...) -> str
    write_html(model, path, title=...) -> Path

The page needs no network except the vis-network CDN (unused when the layout has
no graph); the layout itself is pure HTML/CSS.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

from agentic_bi.web_report.web_assets import CSS, SCRIPT
from agentic_bi.web_report.web_mock import mock_body
from agentic_bi.web_report.web_model import ElementReport, WebReportModel

logger = logging.getLogger(__name__)

_SEVERITY_LABEL = {"error": "Ошибка", "warning": "Предупр.", "info": "Инфо"}

# Fallback canvas when a page has no explicit size.
_DEFAULT_W, _DEFAULT_H = 1280, 720


# Characters json.dumps leaves alone that are unsafe inside a <script> element.
_SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _json_for_script(payload: object) -> str:
    """Serialize `payload` for embedding inside a `<script>` element.

    `json.dumps` escapes quotes and backslashes but not `<` or `>`, so a string
    taken from the report (a visual title, an entity name in an issue message)
    could close the script element early and inject markup. Escaping happens at
    this single sink rather than per input, so every current and future source is
    covered. The escape keeps the document valid JSON.
    """
    text = json.dumps(payload, ensure_ascii=False)
    for char, escaped in _SCRIPT_ESCAPES.items():
        text = text.replace(char, escaped)
    return text


def _tooltip(el: ElementReport) -> str:
    m = el.metrics
    head = f"{el.label} · {el.visual_type}"
    lines = [
        f"полей: {m.fields}",
        f"ролей: {m.roles}",
        f"цветов: {m.colors}",
        f"фильтров: {m.filters}",
    ]
    body = " | ".join(lines)
    if not el.issues:
        return f"{head}\n{body}\nнарушений нет"
    found = "\n".join(f"[{i.severity}] {i.check_id}: {i.message}" for i in el.issues)
    return f"{head}\n{body}\n{found}"


def _page_tabs(model: WebReportModel) -> str:
    tabs = []
    for idx, page in enumerate(model.pages):
        worst = _page_worst(page)
        bad = sum(1 for e in page.elements if e.issues)
        cls = f"tab {worst}" if bad else "tab ok"
        active = " active" if idx == 0 else ""
        tabs.append(
            f'<button class="{cls}{active}" data-page-tab="{idx}" '
            f'onclick="showPage({idx})">{_e(page.name)}'
            f'<span class="tab-badge">{bad}</span></button>'
        )
    return "".join(tabs)


def _page_worst(page) -> str:
    if any(i.severity == "error" for e in page.elements for i in e.issues):
        return "error"
    if any(i.severity == "warning" for e in page.elements for i in e.issues):
        return "warning"
    if any(e.issues for e in page.elements):
        return "info"
    return "ok"


def _element_box(el: ElementReport) -> str:
    m = el.metrics
    severity = m.worst if el.issues else "ok"
    checks = ",".join(sorted({i.check_id for i in el.issues}))
    corner = _SEVERITY_LABEL[m.worst] if el.issues else "OK"
    style = f"left:{el.x}px;top:{el.y}px;width:{el.width}px;height:{el.height}px;"
    return (
        f'<div class="el {severity}" data-el="1" data-page="{_e(el.page)}" '
        f'data-kind="{_e(el.visual_type)}" data-severity="{severity}" '
        f'data-checks="{_e(checks)}" data-key="{_e(el.key)}" style="{style}" '
        f'title="{_e(_tooltip(el))}">'
        f'<div class="el-chrome"><span class="el-title">{_e(el.label)}</span>'
        f'<span class="badge {severity}">{corner}</span></div>'
        f'<div class="el-body">{mock_body(el.visual_type)}</div>'
        f"</div>"
    )


def _pages(model: WebReportModel) -> str:
    out = []
    for idx, page in enumerate(model.pages):
        w = int(page.width or _DEFAULT_W)
        h = int(page.height or _DEFAULT_H)
        active = " active" if idx == 0 else ""
        boxes = "".join(_element_box(el) for el in page.elements)
        out.append(
            f'<section class="canvas-wrap{active}" data-page="{idx}">'
            f'<div class="canvas" style="width:{w}px;height:{h}px">{boxes}</div>'
            f"</section>"
        )
    return "".join(out)


def _summary_cards(model: WebReportModel) -> str:
    s = model.summary()
    cards = [
        ("", s["pages"], "Страниц"),
        ("", s["elements"], "Элементов"),
        ("error", s["error"], "Ошибок"),
        ("warning", s["warning"], "Предупреждений"),
        ("info", s["info"], "Инфо"),
    ]
    return "".join(
        f'<div class="stat-card {cls}"><div class="stat-value">{val}</div>'
        f'<div class="stat-label">{label}</div></div>'
        for cls, val, label in cards
    )


def _filter_options(model: WebReportModel) -> tuple[str, str, str]:
    pages = [(i, p.name) for i, p in enumerate(model.pages)]
    kinds = sorted({e.visual_type for e in model.elements})
    checks = sorted({i.check_id for e in model.elements for i in e.issues})
    page_opts = '<option value="">Все страницы</option>' + "".join(
        f'<option value="{i}">{_e(n)}</option>' for i, n in pages
    )
    kind_opts = '<option value="">Все типы</option>' + "".join(
        f'<option value="{_e(k)}">{_e(k)}</option>' for k in kinds
    )
    check_opts = '<option value="">Все проверки</option>' + "".join(
        f'<option value="{_e(c)}">{_e(c)}</option>' for c in checks
    )
    return page_opts, kind_opts, check_opts


def _detail_rows(model: WebReportModel) -> str:
    rows = []
    for el in model.elements:
        m = el.metrics
        severity = m.worst if el.issues else "ok"
        badge_text = _SEVERITY_LABEL[m.worst] if el.issues else "OK"
        checks = ", ".join(sorted({i.check_id for i in el.issues})) or "—"
        rows.append(
            f'<tr data-detail="{_e(el.key)}" data-severity="{severity}">'
            f"<td>{_e(el.page)}</td><td>{_e(el.label)}</td>"
            f"<td>{_e(el.visual_type)}</td><td>{m.fields}</td>"
            f"<td>{m.roles}</td><td>{m.colors}</td><td>{m.filters}</td>"
            f'<td style="color:#ff4757">{m.errors}</td>'
            f'<td style="color:#ffa502">{m.warnings}</td>'
            f"<td>{_e(checks)}</td>"
            f'<td><span class="badge {severity}">{badge_text}</span></td></tr>'
        )
    return "".join(rows)


def render_html(model: WebReportModel, title: str = "Dashboard Clone") -> str:
    """Render the report clone as an interactive layout."""
    page_opts, kind_opts, check_opts = _filter_options(model)
    model_json = _json_for_script(_model_payload(model))
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(title)} · {_e(model.source)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <h1>{_e(title)}</h1>
  <div class="subtitle">Макет отчёта: {_e(model.source)} · наведите на элемент и
    включите фильтры, чтобы выделить проблемные места</div>

  <div class="stats-grid">{_summary_cards(model)}</div>

  <div class="page-tabs" id="pageTabs">{_page_tabs(model)}</div>
  <div class="layout-host" id="layoutHost">{_pages(model)}</div>

  <details class="section" id="detailsSection">
    <summary>Метрики и нарушения по элементам (таблица)</summary>
    <table class="data-table" id="metrics-table">
      <thead><tr>
        <th>Страница</th><th>Элемент</th><th>Тип</th><th>Полей</th>
        <th>Ролей</th><th>Цветов</th><th>Фильтров</th><th>Ошибок</th>
        <th>Предупр.</th><th>Проверки</th><th>Статус</th>
      </tr></thead>
      <tbody>{_detail_rows(model)}</tbody>
    </table>
  </details>
</div>

<div class="filter-toggle" onclick="toggleFilterPanel()">Фильтры</div>
<div class="filter-panel" id="filterPanel">
  <div class="filter-header">
    <h3>Проблемные места</h3>
    <button class="btn-close" onclick="toggleFilterPanel()">×</button>
  </div>
  <div class="filter-group">
    <label for="filter-severity">Уровень</label>
    <select id="filter-severity" onchange="applyFilters()">
      <option value="">Все уровни</option>
      <option value="error">Только ошибки</option>
      <option value="warning">Предупреждения</option>
      <option value="info">Инфо</option>
      <option value="ok">Без нарушений</option>
    </select>
  </div>
  <div class="filter-group">
    <label for="filter-page">Страница</label>
    <select id="filter-page" onchange="applyFilters()">{page_opts}</select>
  </div>
  <div class="filter-group">
    <label for="filter-kind">Тип визуала</label>
    <select id="filter-kind" onchange="applyFilters()">{kind_opts}</select>
  </div>
  <div class="filter-group">
    <label for="filter-check">Проверка</label>
    <select id="filter-check" onchange="applyFilters()">{check_opts}</select>
  </div>
  <div class="filter-group">
    <button onclick="resetFilters()">Сбросить</button>
  </div>
  <div class="filter-group"><span id="filter-count" class="stat-label"></span></div>
</div>

<div class="footer">{_e(title)} · agentic_bi.web_report</div>
<div id="detailCard"></div>

<script>window.__REPORT_MODEL__ = {model_json};</script>
<script>{SCRIPT}</script>
</body>
</html>
"""


def _model_payload(model: WebReportModel) -> dict:
    """The compact model handed to the client (details lookup)."""
    return {
        "source": model.source,
        "summary": model.summary(),
        "pages": [
            {
                "name": p.name,
                "width": p.width,
                "height": p.height,
                "elements": [
                    {
                        "key": e.key,
                        "label": e.label,
                        "visual_type": e.visual_type,
                        "x": e.x,
                        "y": e.y,
                        "width": e.width,
                        "height": e.height,
                        "metrics": vars(e.metrics),
                        "issues": [vars(i) for i in e.issues],
                    }
                    for e in p.elements
                ],
            }
            for p in model.pages
        ],
    }


def write_html(
    model: WebReportModel, path: str | Path, title: str = "Dashboard Clone"
) -> Path:
    """Render and write the clone HTML; returns the written path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(model, title=title), encoding="utf-8")
    logger.info("web_report: %s (%d B)", path, path.stat().st_size)
    return path

==================== FILE: src/agentic_bi/web_report/web_assets.py ====================

"""Static HTML/CSS/JS assets for the dashboard clone (layout view).

Adapted from the process-mining HTML report tooling: the dark shell, the stats
grid, the slide-in filter panel and the hover-tooltip interaction are reused.
The centerpiece is different — instead of a process graph, the clone draws the
report **layout**: every element at its true position/size, with a mock glyph for
its visual type. Hovering shows metrics and violations; the filter panel dims
everything that does not match a chosen problem area.

The assets are plain strings (no interpolation); values are injected by
`web_render`.
"""

from __future__ import annotations

# Dark shell + layout canvas: same tokens as the process-mining report.
CSS = """
:root {
  --accent:#00d4ff; --err:#ff4757; --warn:#ffa502; --info:#4ecca3;
  --panel:rgba(255,255,255,0.05); --border:rgba(0,212,255,0.2); --canvas:#0f1526;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;
  background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);
  color:#e0e0e0; min-height:100vh; padding:20px;
}
.container { max-width:1600px; margin:0 auto; }
h1 { text-align:center; color:var(--accent); margin-bottom:10px; font-size:2.2em;
  text-shadow:0 0 10px rgba(0,212,255,0.5); }
.subtitle { text-align:center; color:#888; margin-bottom:22px; }
.stats-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  gap:16px; margin-bottom:22px; }
.stat-card { background:var(--panel); border-radius:15px; padding:16px;
  text-align:center; border:1px solid var(--border); }
.stat-value { font-size:2em; font-weight:bold; color:var(--accent); }
.stat-card.error .stat-value { color:var(--err); }
.stat-card.warning .stat-value { color:var(--warn); }
.stat-card.info .stat-value { color:var(--info); }
.stat-label { color:#888; margin-top:5px; font-size:.9em; }

/* page tabs */
.page-tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
.tab { background:var(--panel); color:#cfd8e3; border:1px solid var(--border);
  border-radius:10px 10px 0 0; padding:9px 16px; cursor:pointer; font-size:.95em; }
.tab:hover { background:rgba(0,212,255,0.18); }
.tab.active { background:rgba(0,212,255,0.25); color:#fff; font-weight:bold; }
.tab.error { border-color:var(--err); } .tab.warning { border-color:var(--warn); }
.tab-badge { margin-left:8px; font-size:.8em; opacity:.85; }

/* layout canvas mirrors the report page */
.layout-host { overflow:auto; border:1px solid var(--border); border-radius:10px;
  background:var(--canvas); padding:10px; }
.canvas-wrap { display:none; }
.canvas-wrap.active { display:block; }
.canvas { position:relative; margin:0 auto; background:#121a2e;
  background-image:linear-gradient(rgba(255,255,255,0.03) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,0.03) 1px,transparent 1px);
  background-size:40px 40px; }

/* one element box, placed by true geometry */
.el { position:absolute; background:rgba(255,255,255,0.05);
  border:2px solid rgba(255,255,255,0.18); border-radius:6px; overflow:hidden;
  cursor:pointer; transition:opacity .15s, box-shadow .15s, border-color .15s; }
.el:hover { box-shadow:0 0 0 2px var(--accent), 0 0 14px rgba(0,212,255,.5); z-index:5; }
.el.error { border-color:var(--err); background:rgba(255,71,87,0.10); }
.el.warning { border-color:var(--warn); background:rgba(255,165,2,0.10); }
.el.ok { border-color:rgba(78,204,163,0.45); }
.el.dim { opacity:0.14; }
.el-chrome { display:flex; justify-content:space-between; align-items:center;
  gap:6px; padding:3px 6px; background:rgba(0,0,0,0.28); font-size:.72em; }
.el-title { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:#dfe8f3; }
.el-body { width:100%; height:calc(100% - 20px); color:#9fd8ff; padding:4px; }
.el-body svg { width:100%; height:100%; display:block; }
.badge { border-radius:10px; padding:1px 8px; font-size:.78em; font-weight:bold; }
.badge.error { background:rgba(255,71,87,0.25); color:var(--err); }
.badge.warning { background:rgba(255,165,2,0.25); color:var(--warn); }
.badge.info { background:rgba(78,204,163,0.22); color:var(--info); }
.badge.ok { background:rgba(78,204,163,0.18); color:var(--info); }

/* details table */
.section { background:var(--panel); border-radius:15px; padding:20px;
  margin-top:22px; border:1px solid var(--border); }
.section > summary { cursor:pointer; color:var(--accent); font-size:1.15em;
  font-weight:bold; }
.data-table { width:100%; border-collapse:collapse; margin-top:14px; }
.data-table th, .data-table td { padding:8px 10px; text-align:left;
  border-bottom:1px solid rgba(255,255,255,0.1); font-size:.92em; }
.data-table th { background:rgba(0,212,255,0.2); color:var(--accent); }
.data-table tr:hover { background:rgba(255,255,255,0.05); }
.data-table tr.dim { opacity:0.25; }

/* filters (slide-in) */
.filter-toggle { position:fixed; left:0; top:120px; z-index:20; cursor:pointer;
  background:var(--accent); color:#04212b; font-weight:bold; padding:10px 14px;
  border-radius:0 12px 12px 0; }
.filter-panel { position:fixed; left:-320px; top:0; width:320px; height:100%;
  z-index:30; background:#141a2f; border-right:1px solid var(--border);
  padding:22px; overflow:auto; transition:left .25s ease; }
.filter-header { display:flex; justify-content:space-between; align-items:center;
  margin-bottom:18px; }
.filter-header h3 { color:var(--accent); }
.btn-close, .filter-panel button { background:var(--panel); color:var(--accent);
  border:1px solid var(--border); border-radius:8px; padding:6px 12px; cursor:pointer; }
.filter-group { margin-bottom:14px; }
.filter-group label { display:block; color:#aaa; font-size:.85em; margin-bottom:4px; }
.filter-group select { width:100%; padding:8px; border-radius:8px;
  background:#0f1526; color:#e0e0e0; border:1px solid var(--border); }
.footer { text-align:center; margin-top:26px; color:#666; font-size:.9em; }

/* detail popover */
#detailCard { position:fixed; right:18px; bottom:18px; width:380px; max-height:60vh;
  overflow:auto; z-index:40; background:#141a2f; border:1px solid var(--border);
  border-radius:12px; padding:16px; display:none; box-shadow:0 8px 30px rgba(0,0,0,.5); }
#detailCard h3 { color:var(--accent); margin-bottom:8px; font-size:1.05em; }
#detailCard .row { font-size:.9em; color:#c9d4e0; margin:3px 0; }
#detailCard ul { margin:8px 0 0 16px; font-size:.88em; }
#detailCard li { margin:3px 0; }
"""

# Interactivity: page tabs, filter dimming, hover tooltips (native title),
# detail popover from the injected model.
SCRIPT = """
const MODEL = window.__REPORT_MODEL__;

function indexModel() {
  const byKey = {};
  MODEL.pages.forEach((p, pi) => p.elements.forEach(e => {
    e._page = p.name; e._pi = pi; byKey[e.key] = e;
  }));
  return byKey;
}
const BY_KEY = indexModel();

function showPage(idx) {
  document.querySelectorAll('.canvas-wrap').forEach(s =>
    s.classList.toggle('active', s.dataset.page === String(idx)));
  document.querySelectorAll('.tab').forEach((t, i) =>
    t.classList.toggle('active', i === idx));
}

let filterOpen = false;
function toggleFilterPanel() {
  filterOpen = !filterOpen;
  document.getElementById('filterPanel').style.left = filterOpen ? '0' : '-320px';
  document.querySelector('.filter-toggle').style.left = filterOpen ? '320px' : '0';
}

function resetFilters() {
  document.getElementById('filter-severity').value = '';
  document.getElementById('filter-page').value = '';
  document.getElementById('filter-kind').value = '';
  document.getElementById('filter-check').value = '';
  applyFilters();
}

function matches(el, sev, page, kind, check) {
  if (sev) {
    if (sev === 'ok') { if (el.dataset.severity !== 'ok') return false; }
    else if (el.dataset.severity !== sev) return false;
  }
  if (page && el.dataset.page !== page) return false;
  if (kind && el.dataset.kind !== kind) return false;
  if (check && !(el.dataset.checks || '').split(',').includes(check)) return false;
  return true;
}

function applyFilters() {
  const sev = document.getElementById('filter-severity').value;
  const pageIdx = document.getElementById('filter-page').value;
  const page = pageIdx === '' ? '' : (MODEL.pages[+pageIdx] || {}).name;
  const kind = document.getElementById('filter-kind').value;
  const check = document.getElementById('filter-check').value;
  let visible = 0;
  document.querySelectorAll('.el').forEach(el => {
    const ok = matches(el, sev, page, kind, check);
    el.classList.toggle('dim', !ok);
    if (ok) visible++;
  });
  // jump to the selected page when filtering by page
  if (pageIdx !== '') showPage(+pageIdx);
  // dim matching detail rows too (the details table only honors severity)
  document.querySelectorAll('tr[data-detail]').forEach(tr => {
    tr.classList.toggle('dim', !!sev && sev !== 'ok' && tr.dataset.severity !== sev);
  });
  document.getElementById('filter-count').innerText =
    visible + ' элементов показано';
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function showDetails(key) {
  const el = BY_KEY[key];
  const card = document.getElementById('detailCard');
  if (!el) { card.style.display = 'none'; return; }
  const m = el.metrics;
  const e = escapeHtml;
  const issues = (el.issues || []).length
    ? '<ul>' + el.issues.map(i =>
        '<li><span class="badge ' + e(i.severity) + '">' + e(i.severity) + '</span> '
        + e(i.check_id) + ' — ' + e(i.message) + '</li>').join('') + '</ul>'
    : '<div class="row">нарушений нет</div>';
  card.innerHTML = '<h3>' + e(el.label) + ' · ' + e(el.visual_type) + '</h3>'
    + '<div class="row">страница: ' + e(el._page) + '</div>'
    + '<div class="row">полей: ' + m.fields + ' · ролей: ' + m.roles
    + ' · цветов: ' + m.colors + ' · фильтров: ' + m.filters + '</div>'
    + '<div class="row">ошибок: ' + m.errors + ' · предупр.: ' + m.warnings + '</div>'
    + issues;
  card.style.display = 'block';
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.el').forEach(el => {
    el.addEventListener('click', () => showDetails(el.dataset.key));
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      document.getElementById('detailCard').style.display = 'none';
      if (filterOpen) toggleFilterPanel();
    }
  });
});
"""

