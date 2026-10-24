"""Regression tests for the binary-layer defects found in review.

Three defects were reproduced against the shipped donor before these tests:

1. the virtual directory was serialized with f-strings and never escaped, while
   the parser decodes XML entities, so a member path containing `&`/`<`/`>`
   round-tripped into a malformed document — and `apply_patches` still reported
   success, writing a `.pbix` whose `DataModel` could not be parsed;
2. an equal-length patch with several matching sites silently edited the first;
3. nothing re-read the produced `DataModel`, which is why (1) reached disk.

Each test here fails against the pre-fix code.
"""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import pytest

from agentic_bi.pbix_binary import abf_codec, abf_model, abf_relayout
from agentic_bi.pbix_binary.patch_pipeline import PatchError, apply_patches

pytest.importorskip("xpress9", reason="the 'xpress9' codec is optional")

SPECIAL_PATHS = ["R&D\\data", "a<b>c", "q'uote\"x", "ampersand&only"]


def _decompressed_abf(pbix: Path) -> bytes:
    with zipfile.ZipFile(pbix) as z:
        return abf_codec.decompress_datamodel(z.read("DataModel"))


def _escaped_donor(template: Path, out: Path, storage: str, escaped: str) -> Path:
    """Copy `template` with one virtual-directory path swapped for `escaped`.

    The replacement must be the escaped form of the same length, so every
    recorded offset stays valid and the document remains well-formed.
    """
    abf = _decompressed_abf(template)
    index = abf_relayout.parse_abf_index(abf)
    vdir_start = index.header.vdir_offset
    vdir_end = vdir_start + index.header.vdir_size
    vdir = abf[vdir_start:vdir_end]
    assert storage.encode() in vdir

    mutated = bytearray(abf)
    mutated[vdir_start:vdir_end] = vdir.replace(storage.encode(), escaped.encode(), 1)
    abf_relayout.parse_abf_index(bytes(mutated))  # the donor itself must parse

    from agentic_bi.engine_container import swap_datamodel

    swap_datamodel(template, abf_codec.compress_datamodel(bytes(mutated)), out)
    return out


def test_serialize_virtual_directory_escapes_special_characters():
    """A path with XML metacharacters must survive a serialize/parse round-trip."""
    for path in SPECIAL_PATHS:
        raw = abf_model.serialize_virtual_directory(
            [abf_model.VFile(path=path, size=7, offset=4096)]
        )
        parsed = abf_model.parse_virtual_directory(raw)
        assert parsed[0].path == path, path
        assert parsed[0].size == 7
        assert parsed[0].offset == 4096


def test_serialize_virtual_directory_matches_the_engine_for_plain_paths(
    template_pbix: Path,
):
    """The ElementTree rewrite must not change the bytes for ordinary paths."""
    abf = _decompressed_abf(template_pbix)
    index = abf_relayout.parse_abf_index(abf)
    original = abf[
        index.header.vdir_offset : index.header.vdir_offset + index.header.vdir_size
    ]

    assert abf_model.serialize_virtual_directory(index.files) == original


def test_serialize_virtual_directory_emits_no_xml_declaration():
    """The engine writes the directory without a declaration; keep it that way."""
    raw = abf_model.serialize_virtual_directory(
        [abf_model.VFile(path="A", size=1, offset=0)]
    )

    assert raw.startswith(b"<VirtualDirectory>")
    assert not raw.startswith(b"<?xml")


def test_relayout_preserves_a_path_with_xml_metacharacters(
    tmp_path: Path, template_pbix: Path
):
    """`relayout_abf` re-serializes the whole directory, escaping included.

    Defect 1 was reachable through this path too: a rebuild of a directory that
    contains an XML-escaped `&` produced a document that no longer parsed.
    """
    donor = _escaped_donor(
        template_pbix,
        tmp_path / "donor.pbix",
        _first_data_path(template_pbix),
        "A&amp;B_Storage_1234",
    )
    abf = _decompressed_abf(donor)
    before = abf_relayout.parse_abf_index(abf)
    assert any(vf.path == "A&B_Storage_1234" for vf in before.files)

    result = abf_relayout.relayout_abf(abf, add={"Health\\new.json": b"{}"})

    after = abf_relayout.parse_abf_index(result.data)
    assert any(vf.path == "A&B_Storage_1234" for vf in after.files)
    assert len(after.files) == len(before.files) + 1


def test_apply_patches_verifies_its_own_output(tmp_path: Path, template_pbix: Path):
    """A successful return means the written `DataModel` parses."""
    out = tmp_path / "out.pbix"
    apply_patches(
        template_pbix,
        [
            {
                "kind": "replace_member",
                "member": "metadata.sqlitedb",
                "data": base64.b64encode(b"z" * 64).decode(),
            }
        ],
        out,
    )

    assert abf_relayout.parse_abf_index(_decompressed_abf(out))


def test_apply_patches_rejects_ambiguous_pattern(tmp_path: Path, template_copy: Path):
    """Many matching sites must be an error, not a silent first-match edit."""
    abf = _decompressed_abf(template_copy)
    # A repeated four-byte sequence in the padding region: common, and swapping
    # it for different bytes of the same length keeps the ABF structurally valid
    # when the user explicitly opts in.
    pattern = _ambiguous_pattern(abf)
    sites = abf.count(pattern)
    assert sites > 1, "the donor must contain a repeated sequence"

    with pytest.raises(PatchError, match="matches .* sites"):
        apply_patches(
            template_copy,
            [
                {
                    "kind": "replace_hex",
                    "find": pattern.hex(),
                    "with": (b"\xaa" * len(pattern)).hex(),
                }
            ],
            tmp_path / "ambiguous.pbix",
        )


def test_apply_patches_honours_an_explicit_occurrence(
    tmp_path: Path, template_copy: Path
):
    """`occurrence` selects one site deterministically out of many."""
    abf = _decompressed_abf(template_copy)
    pattern = _ambiguous_pattern(abf)
    marker = b"\xaa" * len(pattern)
    first = abf.find(pattern)
    second = abf.find(pattern, first + 1)

    report = apply_patches(
        template_copy,
        [
            {
                "kind": "replace_hex",
                "find": pattern.hex(),
                "with": marker.hex(),
                "occurrence": 1,
            }
        ],
        tmp_path / "one.pbix",
    )

    assert report.log == [f"replace: {len(pattern)} B at offset {second}"]
    patched = _decompressed_abf(tmp_path / "one.pbix")
    assert patched[second : second + len(pattern)] == marker
    assert patched[first : first + len(pattern)] == pattern


def test_apply_patches_occurrence_out_of_range_is_an_error(
    tmp_path: Path, template_copy: Path
):
    pattern = _ambiguous_pattern(_decompressed_abf(template_copy))
    with pytest.raises(PatchError, match="out of range"):
        apply_patches(
            template_copy,
            [
                {
                    "kind": "replace_hex",
                    "find": pattern.hex(),
                    "with": (b"\xaa" * len(pattern)).hex(),
                    "occurrence": 100_000,
                }
            ],
            tmp_path / "oob.pbix",
        )


def test_apply_patches_all_replaces_every_site(tmp_path: Path, template_copy: Path):
    """`all` is the explicit opt-in for a multi-site replacement."""
    abf = _decompressed_abf(template_copy)
    pattern = _ambiguous_pattern(abf)
    total = abf.count(pattern)

    report = apply_patches(
        template_copy,
        [
            {
                "kind": "replace_hex",
                "find": pattern.hex(),
                "with": (b"\xaa" * len(pattern)).hex(),
                "occurrence": "all",
            }
        ],
        tmp_path / "all.pbix",
    )

    assert sum(1 for line in report.log if line.startswith("replace:")) == total


def test_apply_patches_rejects_a_non_integer_occurrence(
    tmp_path: Path, template_copy: Path
):
    pattern = _ambiguous_pattern(_decompressed_abf(template_copy))
    with pytest.raises(PatchError, match="'occurrence' must be"):
        apply_patches(
            template_copy,
            [
                {
                    "kind": "replace_hex",
                    "find": pattern.hex(),
                    "with": (b"\xaa" * len(pattern)).hex(),
                    "occurrence": "second",
                }
            ],
            tmp_path / "bad.pbix",
        )


def test_escaped_path_in_the_donor_survives_a_patch(
    tmp_path: Path, template_pbix: Path
):
    """End-to-end guard for defect 1: an `&` in a donor path must not break output.

    The donor is edited to hold a validly-escaped member path, then patched. With
    the unescaped serializer this wrote a `.pbix` whose `DataModel` no longer
    parsed, while still returning success.
    """
    donor = _escaped_donor(
        template_pbix,
        tmp_path / "donor.pbix",
        _first_data_path(template_pbix),
        "A&amp;B_Storage_1234",
    )
    out = tmp_path / "patched.pbix"

    apply_patches(
        donor,
        [
            {
                "kind": "replace_member",
                "member": "metadata.sqlitedb",
                "data": base64.b64encode(b"z" * 64).decode(),
            }
        ],
        out,
    )

    assert abf_relayout.parse_abf_index(_decompressed_abf(out))
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None


def _first_data_path(pbix: Path) -> str:
    """The first 20-character storage id in the donor's virtual directory."""
    index = abf_relayout.parse_abf_index(_decompressed_abf(pbix))
    for vf in index.data_members:
        if len(vf.path) == 20:
            return vf.path
    raise AssertionError("the donor has no 20-character storage path")


def _ambiguous_pattern(abf: bytes, width: int = 8) -> bytes:
    """A byte sequence occurring more than once, safe to overwrite repeatedly.

    Only runs of a single repeated byte are used, so the pattern cannot straddle
    two different structures; replacing one such run with a different byte of the
    same length keeps every offset intact. The function proves the choice works
    before handing it to a test.
    """
    for candidate in (b"\x00", b"\xff"):
        pattern = candidate * width
        if abf.count(pattern) < 2:
            continue
        marker = (b"\xaa" if candidate == b"\x00" else b"\x55") * width
        probe = bytearray(abf)
        start = probe.find(pattern)
        probe[start : start + width] = marker
        try:
            abf_relayout.parse_abf_index(bytes(probe))
        except Exception:  # noqa: BLE001 - this candidate is structurally unsafe
            continue
        return pattern
    raise AssertionError("no structurally safe ambiguous pattern in the donor")
