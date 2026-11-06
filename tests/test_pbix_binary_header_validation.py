"""Boundary validation of the ABF header parser (input from a .pbix DataModel).

The header XML comes from a binary file that may be truncated or foreign. A
missing or non-numeric offset must be a `ValueError` naming the header field, not
`int(None)` raising a bare `TypeError` inside the engine.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from agentic_bi.pbix_binary.abf_model import (
    HEADER_START,
    ABFHeader,
    parse_header,
)

_FIELDS = {
    "m_cbOffsetHeader": "8192",
    "DataSize": "4096",
    "Files": "3",
    "m_cbOffsetData": "12288",
    "ObjectID": "abc",
}


def _buffer(fields: dict[str, str | None]) -> bytes:
    root = ET.Element("BackupLogHeader")
    for tag, text in fields.items():
        ET.SubElement(root, tag).text = text
    return b"\x00" * HEADER_START + ET.tostring(root, encoding="utf-16")


class TestHappyPath:
    def test_a_complete_header_is_parsed(self) -> None:
        header = parse_header(_buffer(_FIELDS))
        assert isinstance(header, ABFHeader)
        assert (header.vdir_offset, header.vdir_size) == (8192, 4096)
        assert (header.files, header.data_offset) == (3, 12288)
        assert header.object_id == "abc"

    def test_zero_offsets_are_accepted(self) -> None:
        fields = dict(_FIELDS, m_cbOffsetHeader="0", DataSize="0", Files="0")
        header = parse_header(_buffer(fields))
        assert (header.vdir_offset, header.vdir_size, header.files) == (0, 0, 0)

    def test_a_maximum_integer_is_accepted(self) -> None:
        biggest = str(2**63 - 1)
        fields = dict(_FIELDS, m_cbOffsetHeader=biggest)
        assert parse_header(_buffer(fields)).vdir_offset == 2**63 - 1

    def test_a_missing_object_id_becomes_empty(self) -> None:
        fields = {k: v for k, v in _FIELDS.items() if k != "ObjectID"}
        assert parse_header(_buffer(fields)).object_id == ""


class TestHeaderErrors:
    @pytest.mark.parametrize(
        "tag", ["m_cbOffsetHeader", "DataSize", "Files", "m_cbOffsetData"]
    )
    def test_a_missing_offset_names_the_field(self, tag: str) -> None:
        fields = {k: v for k, v in _FIELDS.items() if k != tag}
        with pytest.raises(ValueError, match=rf"field '{tag}' is missing"):
            parse_header(_buffer(fields))

    def test_a_non_integer_offset_names_the_field(self) -> None:
        fields = dict(_FIELDS, DataSize="not-a-number")
        with pytest.raises(
            ValueError, match=r"field 'DataSize': expected integer, got 'not-a-number'"
        ):
            parse_header(_buffer(fields))

    def test_an_empty_offset_is_not_an_integer(self) -> None:
        fields = dict(_FIELDS, Files="")
        with pytest.raises(
            ValueError, match=r"field 'Files': expected integer, got ''"
        ):
            parse_header(_buffer(fields))

    def test_a_non_xml_buffer_raises_a_parse_error(self) -> None:
        with pytest.raises(ET.ParseError):
            parse_header(b"\x00" * HEADER_START)
