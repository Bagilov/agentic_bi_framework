"""Byte-exactness and round-trip invariants of the `.pbix` writers.

Two properties that the plan calls out and that today's code already satisfies
are pinned here so they cannot silently regress:

1. **`swap_datamodel` with an identical payload is byte-identical.** The rewrite
   patching CRC/sizes/central-directory offsets must be a no-op when the payload
   does not change; any drift means the zipper is corrupting the container.
2. **`relayout → parse` round-trips.** Re-laying an ABF around a replaced member
   keeps the header/virtual-directory/payload offsets consistent, and parsing the
   re-serialized virtual directory reproduces the records verbatim.

The `xpress9` codec is required (the ABF buffer only exists compressed).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from agentic_bi.engine_container import swap_datamodel
from agentic_bi.pbix_binary import abf_codec, abf_relayout

pytest.importorskip("xpress9", reason="the 'xpress9' codec is optional")


def _abf(template: Path) -> bytes:
    with zipfile.ZipFile(template) as z:
        return abf_codec.decompress_datamodel(z.read("DataModel"))


def _assert_consistent(abf: bytes) -> abf_relayout.ABFIndex:
    """Assert the header/vdir/payload offsets agree; return the parsed index."""
    index = abf_relayout.parse_abf_index(abf)
    assert index.header.files == len(index.files)
    vdir_offset = index.header.vdir_offset
    for member in index.data_members:
        assert member.size >= 0
        assert member.offset >= 0
        assert member.offset + member.size <= vdir_offset, member.path
    return index


def _first_member(index: abf_relayout.ABFIndex) -> tuple[str, bytes]:
    """Return the logical name and payload of the first data member.

    `relayout_abf` keys replacements by *logical* name (the backup-log path
    relative to the persist root), not by the storage id in the directory.
    """
    member = index.data_members[0]
    entry = next(e for e in index.log.iter_files() if e.storage_path == member.path)
    return index.log.logical_name(entry), member


def test_swap_datamodel_with_an_identical_payload_is_byte_identical(
    template_pbix: Path, tmp_path: Path
) -> None:
    """Replacing the DataModel with itself must reproduce the container exactly."""
    with zipfile.ZipFile(template_pbix) as z:
        datamodel = z.read("DataModel")

    out = tmp_path / "identical.pbix"
    swap_datamodel(template_pbix, datamodel, out)

    assert out.read_bytes() == template_pbix.read_bytes(), (
        "an identity swap changed the container bytes"
    )


def test_swap_datamodel_change_then_inverse_restores_the_original(
    template_pbix: Path, tmp_path: Path
) -> None:
    """A change and its exact inverse must land back on the original bytes."""
    with zipfile.ZipFile(template_pbix) as z:
        original = z.read("DataModel")

    grown = tmp_path / "grown.pbix"
    swapped = original + b"\x00" * 8192
    swap_datamodel(template_pbix, swapped, grown)
    with zipfile.ZipFile(grown) as z:
        assert z.read("DataModel") == swapped

    restored = tmp_path / "restored.pbix"
    swap_datamodel(grown, original, restored)
    assert restored.read_bytes() == template_pbix.read_bytes()


class TestRelayoutRoundTrip:
    """`relayout_abf` keeps every offset consistent around a replaced member."""

    @pytest.mark.parametrize("extra", [0, 1, 4096])
    def test_a_replaced_member_keeps_the_index_consistent(
        self, template_pbix: Path, tmp_path: Path, extra: int
    ) -> None:
        abf = _abf(template_pbix)
        index = _assert_consistent(abf)
        logical, member = _first_member(index)
        payload = abf[member.offset : member.offset + member.size]
        replacement = payload + b"\x00" * extra

        result = abf_relayout.relayout_abf(abf, replace={logical: replacement})
        after = _assert_consistent(result.data)
        assert after.header.files == index.header.files

    def test_the_replaced_payload_is_readable_at_its_new_length(
        self, template_pbix: Path
    ) -> None:
        abf = _abf(template_pbix)
        index = _assert_consistent(abf)
        logical, member = _first_member(index)
        replacement = b"REPLACEMENT-BYTES"

        out = abf_relayout.relayout_abf(abf, replace={logical: replacement}).data
        after = _assert_consistent(out)
        new_member = next(
            m
            for m in after.data_members
            if after.log.logical_name(
                next(e for e in after.log.iter_files() if e.storage_path == m.path)
            )
            == logical
        )
        assert new_member.size == len(replacement)
        assert (
            out[new_member.offset : new_member.offset + new_member.size] == replacement
        )

    def test_recomputed_virtual_directory_round_trips(
        self, template_pbix: Path
    ) -> None:
        """Serializing the parsed directory back preserves every field."""
        from agentic_bi.pbix_binary.abf_model import (
            parse_virtual_directory,
            serialize_virtual_directory,
        )

        index = _assert_consistent(_abf(template_pbix))
        raw = serialize_virtual_directory(index.files)
        assert parse_virtual_directory(raw) == index.files

    def test_relayout_of_an_unchanged_member_is_a_fixed_point(
        self, template_pbix: Path
    ) -> None:
        """Replacing a member with its own bytes keeps the index stable twice over."""
        abf = _abf(template_pbix)
        index = _assert_consistent(abf)
        logical, member = _first_member(index)
        payload = abf[member.offset : member.offset + member.size]

        once = abf_relayout.relayout_abf(abf, replace={logical: payload}).data
        twice = abf_relayout.relayout_abf(once, replace={logical: payload}).data

        assert _assert_consistent(twice).header.files == index.header.files
        assert twice == once, "replacing with the same bytes must be idempotent"

    def test_an_unknown_replacement_name_raises(self, template_pbix: Path) -> None:
        with pytest.raises(abf_relayout.ABFLayoutError):
            abf_relayout.relayout_abf(
                _abf(template_pbix), replace={"does\\not\\exist": b"x"}
            )
