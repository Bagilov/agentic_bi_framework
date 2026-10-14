"""Autotests for the `.pbix` patch pipeline and the size-safe container swap.

Covers the guard rails (length-changing byte patches are rejected), the
equal-length in-place path, the uneven `replace_member` path, spec loading, and
the `swap_datamodel` rewrite when `DataModel` is not the last archive member.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest

from agentic_bi import engine_container
from agentic_bi.pbix_binary import abf_codec, abf_relayout
from agentic_bi.pbix_binary.patch_pipeline import (
    PatchError,
    apply_patches,
    classify_patches,
    load_spec,
)

pytest.importorskip("xpress9", reason="the 'xpress9' codec is optional")


def _sqlite_grown(pbix: Path, extra: int) -> bytes:
    """Return the donor sqlite member plus `extra` trailing bytes."""
    with zipfile.ZipFile(pbix) as z:
        abf = abf_codec.decompress_datamodel(z.read("DataModel"))
    index = abf_relayout.parse_abf_index(abf)
    storage = index.storage_of("metadata.sqlitedb")
    assert storage is not None
    original = abf_relayout.member_blob(abf, storage)
    return original + b"\x00" * extra


def test_classify_rejects_length_changing_text_patch():
    with pytest.raises(PatchError, match="changes length"):
        classify_patches([{"kind": "replace", "find": "AB", "with": "ABCD"}])


def test_classify_rejects_length_changing_hex_patch():
    with pytest.raises(PatchError, match="changes length"):
        classify_patches([{"kind": "replace_hex", "find": "00", "with": "0000"}])


def test_classify_rejects_unknown_kind():
    with pytest.raises(PatchError, match="unknown patch kind"):
        classify_patches([{"kind": "magic"}])


def test_classify_splits_even_and_uneven():
    even, uneven = classify_patches(
        [
            {"kind": "replace", "find": "A", "with": "B"},
            {"kind": "replace_member", "member": "metadata.sqlitedb", "data": ""},
        ]
    )
    assert len(even) == 1 and len(uneven) == 1


def test_apply_patches_rejects_unmatched_pattern(template_copy: Path, tmp_path: Path):
    with pytest.raises(PatchError, match="pattern not found"):
        apply_patches(
            template_copy,
            [{"kind": "replace", "find": "NOPE", "with": "SAME"}],
            tmp_path / "out.pbix",
        )


def test_apply_patches_uneven_member_round_trips_sqlite(
    template_copy: Path, tmp_path: Path
):
    grown = _sqlite_grown(template_copy, 8192)
    patch = {
        "kind": "replace_member",
        "member": "metadata.sqlitedb",
        "data": base64.b64encode(grown).decode(),
    }
    out = tmp_path / "out.pbix"
    report = apply_patches(template_copy, [patch], out)

    assert out.exists() and report.size == out.stat().st_size
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert "DataModel" in z.namelist()
        abf = abf_codec.decompress_datamodel(z.read("DataModel"))
    index = abf_relayout.parse_abf_index(abf)
    storage = index.storage_of("metadata.sqlitedb")
    rebuilt = abf_relayout.member_blob(abf, storage)
    assert len(rebuilt) == len(grown)

    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    Path(tmp).write_bytes(rebuilt)
    con = sqlite3.connect(tmp)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()
    os.unlink(tmp)


def test_apply_patches_preserves_other_members(template_copy: Path, tmp_path: Path):
    grown = _sqlite_grown(template_copy, 1024)
    out = tmp_path / "out.pbix"
    apply_patches(
        template_copy,
        [
            {
                "kind": "replace_member",
                "member": "metadata.sqlitedb",
                "data": base64.b64encode(grown).decode(),
            }
        ],
        out,
    )
    with zipfile.ZipFile(template_copy) as zs, zipfile.ZipFile(out) as zd:
        original = {n: zs.read(n) for n in zs.namelist() if n != "DataModel"}
        rebuilt = {n: zd.read(n) for n in zd.namelist() if n != "DataModel"}
    assert original == rebuilt


def test_load_spec_accepts_object_and_list(tmp_path: Path):
    obj = tmp_path / "spec.json"
    obj.write_text(
        json.dumps({"patches": [{"kind": "replace_member"}]}), encoding="utf-8"
    )
    assert load_spec(obj) == [{"kind": "replace_member"}]
    lst = tmp_path / "list.json"
    lst.write_text(json.dumps([{"kind": "replace_member"}]), encoding="utf-8")
    assert load_spec(lst) == [{"kind": "replace_member"}]


def test_load_spec_rejects_bad_shape(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"nope": 1}), encoding="utf-8")
    with pytest.raises(PatchError, match="must be a list"):
        load_spec(bad)


def test_swap_datamodel_works_when_datamodel_is_not_last(
    template_pbix: Path, tmp_path: Path
):
    """The donor template stores docProps after DataModel — the classic pitfall."""
    with zipfile.ZipFile(template_pbix) as z:
        names = z.namelist()
        datamodel = z.read("DataModel")
    assert names.index("DataModel") < len(names) - 1, (
        "test requires a member stored after DataModel"
    )

    for label, payload in (
        ("same", datamodel),
        ("grow", datamodel + b"\x00" * 4096),
        ("shrink", datamodel[: len(datamodel) // 2]),
    ):
        out = tmp_path / f"swap_{label}.pbix"
        engine_container.swap_datamodel(template_pbix, payload, out)
        with zipfile.ZipFile(out) as z:
            assert z.testzip() is None
            assert z.read("DataModel") == payload
            assert len(z.namelist()) == len(names)
