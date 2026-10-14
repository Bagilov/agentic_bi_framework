"""Autotests for the ABF index + uneven-length re-layout on a real `.pbix`.

These read the donor's decompressed ABF, re-lay it around a different-length
member, and assert the structural invariants that make a `.pbix` load: the
virtual directory and header agree with the payload offsets, the members before
the directory do not run into it, and a replaced SQLite member stays readable.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest

from agentic_bi.pbix_binary import abf_codec, abf_relayout
from agentic_bi.pbix_binary.abf_model import (
    HEADER_END,
    LOG_MEMBER,
    PREFIX_MEMBERS,
    PREFIX_SIZE,
)

pytest.importorskip("xpress9", reason="the 'xpress9' codec is optional")


def _decompressed_abf(template: Path) -> bytes:
    with zipfile.ZipFile(template) as z:
        return abf_codec.decompress_datamodel(z.read("DataModel"))


def _assert_index_consistent(abf: bytes) -> abf_relayout.ABFIndex:
    """Assert the header/vdir/payload offsets agree; return the parsed index."""
    index = abf_relayout.parse_abf_index(abf)
    assert index.header.files == len(index.files)
    vdir_offset = index.header.vdir_offset
    for vf in index.data_members:
        assert vf.offset + vf.size <= vdir_offset, (
            f"{vf.path} runs past the virtual directory"
        )
    assert index.files[-1].path == LOG_MEMBER
    return index


def _sqlite_member(index: abf_relayout.ABFIndex) -> tuple[str, bytes | None]:
    for entry in index.log.iter_files():
        if index.log.logical_name(entry).endswith("metadata.sqlitedb"):
            return entry.storage_path, None
    return "", None


def test_parse_index_reads_donor_structures(template_pbix: Path):
    abf = _decompressed_abf(template_pbix)
    index = _assert_index_consistent(abf)
    assert len(index.data_members) > 100
    assert index.log.data_group is not None
    assert index.log.data_group.cls == "100069"


def test_persist_root_survives_and_names_are_relative(template_pbix: Path):
    abf = _decompressed_abf(template_pbix)
    index = abf_relayout.parse_abf_index(abf)
    root = index.log.persist_root()
    assert root.endswith("\\")
    logical = [index.log.logical_name(e) for e in index.log.iter_files()]
    assert any(name.endswith("metadata.sqlitedb") for name in logical)
    assert not any(name.startswith(root) for name in logical)


def test_relayout_without_changes_is_identity(template_pbix: Path):
    abf = _decompressed_abf(template_pbix)
    result = abf_relayout.relayout_abf(abf)
    assert result.data == abf
    assert result.log == []


def test_unknown_replacement_raises(template_pbix: Path):
    abf = _decompressed_abf(template_pbix)
    with pytest.raises(abf_relayout.ABFLayoutError, match="not found"):
        abf_relayout.relayout_abf(abf, replace={"no.such.member": b"x"})


def test_uneven_sqlite_replacement_keeps_sqlite_readable(template_pbix: Path):
    abf = _decompressed_abf(template_pbix)
    index = abf_relayout.parse_abf_index(abf)
    storage, _ = _sqlite_member(index)
    assert storage, "donor has no metadata.sqlitedb member"
    original = abf_relayout.member_blob(abf, storage)

    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    Path(tmp).write_bytes(original)
    con = sqlite3.connect(tmp)
    con.execute("PRAGMA user_version=4242")
    con.commit()
    con.close()
    grown = Path(tmp).read_bytes() + b"\x00" * 4096
    os.unlink(tmp)
    assert len(grown) != len(original)

    result = abf_relayout.relayout_abf(abf, replace={"metadata.sqlitedb": grown})
    _assert_index_consistent(result.data)

    rebuilt = abf_relayout.member_blob(result.data, storage)
    assert len(rebuilt) == len(grown)
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    Path(tmp).write_bytes(rebuilt)
    con = sqlite3.connect(tmp)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("PRAGMA user_version").fetchone()[0] == 4242
    con.close()
    os.unlink(tmp)


def test_relayout_offsets_follow_payload_lengths(template_pbix: Path):
    abf = _decompressed_abf(template_pbix)
    index = abf_relayout.parse_abf_index(abf)
    storage, _ = _sqlite_member(index)
    shorter = abf_relayout.member_blob(abf, storage)[:4096]
    result = abf_relayout.relayout_abf(abf, replace={"metadata.sqlitedb": shorter})
    new_index = _assert_index_consistent(result.data)
    # With a shorter payload the whole buffer shrinks and the directory moves
    # up to sit just after the payloads + backup log.
    assert len(result.data) < len(abf)
    assert new_index.header.vdir_offset < index.header.vdir_offset


def test_add_member_appends_storage_entry(template_pbix: Path):
    abf = _decompressed_abf(template_pbix)
    payload = b"brand new member payload" * 10
    result = abf_relayout.relayout_abf(abf, add={"extra.dat": payload})
    index = _assert_index_consistent(result.data)
    storage = index.storage_of("extra.dat")
    assert storage is not None
    assert abf_relayout.member_blob(result.data, storage) == payload
    assert result.log and any("extra.dat" in line for line in result.log)


def test_prefix_members_stay_in_place(template_pbix: Path):
    abf = _decompressed_abf(template_pbix)
    result = abf_relayout.relayout_abf(
        abf, replace={"metadata.sqlitedb": b"\x00" * 100}
    )
    # The prefix (signature + ADDITIONAL_LOG + PARTITIONS) is verbatim; only the
    # header page inside it is rewritten with the new directory offset.
    assert result.data[HEADER_END:PREFIX_SIZE] == abf[HEADER_END:PREFIX_SIZE]
    offsets = {}
    for vf in abf_relayout.parse_abf_index(result.data).files:
        offsets[vf.path] = vf.offset
    assert offsets["ADDITIONAL_LOG"] == 4096
    assert offsets["PARTITIONS"] == 4208
    assert "ADDITIONAL_LOG" in PREFIX_MEMBERS
