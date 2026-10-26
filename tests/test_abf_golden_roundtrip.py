"""Golden round-trips for the ABF structural layers (`pbix_binary.abf_model`).

These pin the parsers against the *shapes the engine writes*, so a silent format
regression is caught without Power BI Desktop:

* `parse → serialize → parse` equality for the virtual directory and the backup
  log (the two documents that carry member paths and offsets),
* a frozen golden snapshot of the round-tripped virtual directory, so a change in
  the emitted element set/order is a visible diff rather than a surprise in a
  `.pbix` that Desktop then refuses to open,
* the boundary inputs the plan calls out: empty report, a very long path,
  Cyrillic and XML metacharacters, and truncation.

`serialize_virtual_directory` deliberately omits the XML declaration and escapes
special characters; both are pinned here because the engine's reader depends on
them.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from agentic_bi.pbix_binary.abf_model import (
    BackupFileEntry,
    FileGroup,
    VFile,
    parse_backup_log,
    parse_virtual_directory,
    serialize_backup_log,
    serialize_virtual_directory,
)


def _vfile(path: str, size: int = 100, offset: int = 0, **kw) -> VFile:
    return VFile(path=path, size=size, offset=offset, **kw)


def _round_trip(files: list[VFile]) -> list[VFile]:
    return parse_virtual_directory(serialize_virtual_directory(files))


class TestVirtualDirectoryRoundTrip:
    def test_an_empty_directory_round_trips(self) -> None:
        assert _round_trip([]) == []

    def test_a_single_entry_round_trips_all_fields(self) -> None:
        original = _vfile(
            "Data/metadata.sqlitedb",
            size=4096,
            offset=128,
            delete=True,
            created_ts=1700000000,
            access=7,
            last_write=1700000001,
        )
        assert _round_trip([original]) == [original]

    def test_many_entries_keep_their_order(self) -> None:
        original = [_vfile(f"Data/m{i}.dat", size=i, offset=i * 10) for i in range(50)]
        assert _round_trip(original) == original

    def test_a_very_long_path_round_trips(self) -> None:
        long_path = "Data/" + "a" * 5000 + ".dat"
        assert _round_trip([_vfile(long_path)])[0].path == long_path

    def test_cyrillic_paths_round_trip(self) -> None:
        path = "Данные/Отчёт «Продажи»/модель.dat"
        assert _round_trip([_vfile(path)])[0].path == path

    @pytest.mark.parametrize(
        "path", ["a&b.dat", "a<b.dat", "a>b.dat", 'a"b.dat', "a'b.dat"]
    )
    def test_xml_metacharacters_are_escaped_and_restored(self, path: str) -> None:
        assert _round_trip([_vfile(path)])[0].path == path

    def test_a_zero_size_entry_is_preserved(self) -> None:
        assert _round_trip([_vfile("empty", size=0, offset=0)])[0].size == 0

    def test_delete_false_is_preserved(self) -> None:
        assert _round_trip([_vfile("x", delete=False)])[0].delete is False


class TestVirtualDirectoryGolden:
    """A frozen snapshot of the emitted document (no XML declaration, one entry)."""

    GOLDEN = (
        "<VirtualDirectory><BackupFile><Path>Data/m.dat</Path><Size>4096</Size>"
        "<m_cbOffsetHeader>128</m_cbOffsetHeader><Delete>false</Delete>"
        "<CreatedTimestamp>0</CreatedTimestamp><Access>0</Access>"
        "<LastWriteTime>0</LastWriteTime></BackupFile></VirtualDirectory>"
    )

    def test_the_emitted_document_matches_the_golden_bytes(self) -> None:
        raw = serialize_virtual_directory([_vfile("Data/m.dat", size=4096, offset=128)])
        assert raw == self.GOLDEN.encode("utf-8")

    def test_the_document_carries_no_xml_declaration(self) -> None:
        raw = serialize_virtual_directory([_vfile("x")])
        assert not raw.startswith(b"<?xml")

    def test_the_document_is_utf8_without_a_bom(self) -> None:
        raw = serialize_virtual_directory([_vfile("x")])
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert raw.decode("utf-8")

    def test_it_is_a_single_root_element(self) -> None:
        root = ET.fromstring(serialize_virtual_directory([_vfile("x")]))
        assert root.tag == "VirtualDirectory"
        assert len(root) == 1


def _backup_log(groups: list[FileGroup]) -> bytes:
    """Build an engine-shaped backup_log (UTF-16 with a single leading BOM)."""
    root = ET.Element("BackupLog")
    container = ET.SubElement(root, "FileGroups")
    for group in groups:
        node = ET.SubElement(container, "FileGroup")
        ET.SubElement(node, "Class").text = group.cls
        ET.SubElement(node, "PersistLocationPath").text = group.persist_root
        file_list = ET.SubElement(node, "FileList")
        for entry in group.files:
            bf = ET.SubElement(file_list, "BackupFile")
            ET.SubElement(bf, "Path").text = entry.path
            ET.SubElement(bf, "StoragePath").text = entry.storage_path
            ET.SubElement(bf, "Size").text = str(entry.size)
            ET.SubElement(bf, "LastWriteTime").text = str(entry.last_write)
    return ("\ufeff" + ET.tostring(root, encoding="unicode")).encode("utf-16-le")


class TestBackupLogRoundTrip:
    def test_an_empty_log_round_trips(self) -> None:
        log = parse_backup_log(_backup_log([]))
        assert log.groups == []
        assert log.data_group is None

    def test_a_group_round_trips_all_fields(self) -> None:
        group = FileGroup(
            cls="100069",
            persist_root="C:\\ws\\Data\\",
            files=[BackupFileEntry("Data/m.dat", "Data\\m.dat", 4096, 1700000000)],
        )
        parsed = parse_backup_log(_backup_log([group]))
        assert parsed.groups == [group]

    def test_cyrillic_and_special_characters_round_trip(self) -> None:
        group = FileGroup(
            cls="1",
            persist_root="C:\\данные\\",
            files=[BackupFileEntry("a&b/c<d>.dat", "a\\c.dat", 1, 2)],
        )
        assert parse_backup_log(_backup_log([group])).groups == [group]

    def test_serialize_writes_exactly_one_bom(self) -> None:
        log = parse_backup_log(
            _backup_log([FileGroup(cls="1", persist_root="C:\\x\\")])
        )
        raw = serialize_backup_log(log)
        assert raw.startswith(b"\xff\xfe")
        assert not raw[2:].startswith(b"\xff\xfe")
        # A double BOM would decode as a forbidden U+FFFE inside the document.
        assert "\ufffe" not in raw.decode("utf-16")

    def test_serialize_is_idempotent(self) -> None:
        log = parse_backup_log(
            _backup_log([FileGroup(cls="1", persist_root="C:\\x\\")])
        )
        once = serialize_backup_log(log)
        twice = serialize_backup_log(parse_backup_log(once))
        assert once == twice

    def test_the_persist_root_always_ends_with_a_separator(self) -> None:
        log = parse_backup_log(
            _backup_log([FileGroup(cls="100069", persist_root="C:\\ws")])
        )
        assert log.persist_root().endswith("\\")

    def test_a_log_without_groups_raises_on_persist_root(self) -> None:
        with pytest.raises(ValueError, match="no file groups"):
            parse_backup_log(_backup_log([])).persist_root()


class TestTruncationIsADomainError:
    """A truncated document must raise a parse error, never crash the caller."""

    def test_a_truncated_virtual_directory_raises(self) -> None:
        raw = serialize_virtual_directory([_vfile("x")])
        with pytest.raises(ET.ParseError):
            parse_virtual_directory(raw[: len(raw) // 2])

    @pytest.mark.parametrize("cut", [1, 4, 28, 4096])
    def test_various_truncations_raise(self, cut: int) -> None:
        # Enough entries that the document is longer than the largest cut, so no
        # parameter is silently a no-op.
        raw = serialize_virtual_directory(
            [_vfile(f"Data/m{i}.dat", size=8192) for i in range(200)]
        )
        assert len(raw) > cut, "the fixture must be longer than the cut"
        with pytest.raises(ET.ParseError):
            parse_virtual_directory(raw[:-cut])

    def test_an_empty_buffer_raises(self) -> None:
        with pytest.raises(ET.ParseError):
            parse_virtual_directory(b"")

    def test_a_truncated_backup_log_raises(self) -> None:
        raw = _backup_log([FileGroup(cls="1", persist_root="C:\\x\\")])
        with pytest.raises((ET.ParseError, UnicodeDecodeError, ValueError)):
            parse_backup_log(raw[: len(raw) // 2])
