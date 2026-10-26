"""Tests for the `.pbix` container layer (`engine_container`).

This module is the single source of zip handling for the whole framework: it
copies the donor scaffolding, swaps the binary `DataModel`, and builds a clean
package. The tests target the two ways it can corrupt a deliverable:

* writing a container whose zip is unreadable (the guard exists; here it is
  exercised by making `ZipFile.testzip` report a bad member), and
* losing or reordering the scaffolding members that Desktop needs.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from agentic_bi import engine_container
from agentic_bi.engine_container import (
    COPY_MEMBERS,
    build_container,
    list_members,
    read_member,
    swap_datamodel,
)


def _template(tmp_path: Path, members: dict[str, bytes] | None = None) -> Path:
    """A stand-in donor carrying every `COPY_MEMBERS` entry plus a `DataModel`."""
    path = tmp_path / "donor.pbix"
    data: dict[str, bytes] = {name: f"<{name}/>".encode() for name in COPY_MEMBERS}
    data["Report/Layout"] = b'{"sections":[]}'
    data["DataModel"] = b"ORIGINAL-MODEL"
    data.update(members or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in data.items():
            z.writestr(name, payload)
    # A member *after* DataModel is the classic pitfall (the donor template has
    # docProps stored after it), so keep one.
    with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("docProps/custom.xml", b"<props/>")
    return path


class TestReadAndList:
    def test_read_member_returns_the_exact_bytes(self, tmp_path: Path) -> None:
        template = _template(tmp_path)
        assert read_member(template, "DataModel") == b"ORIGINAL-MODEL"

    def test_read_member_of_a_missing_name_raises(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError):
            read_member(_template(tmp_path), "NoSuchMember")

    def test_list_members_reports_names_and_sizes_in_order(
        self, tmp_path: Path
    ) -> None:
        template = _template(tmp_path)
        listed = list_members(template)
        with zipfile.ZipFile(template) as z:
            expected = [(i.filename, i.file_size) for i in z.infolist()]
        assert listed == expected
        assert listed[0][0] == "Version"

    def test_list_members_of_an_empty_zip_is_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.pbix"
        with zipfile.ZipFile(path, "w"):
            pass
        assert list_members(path) == []


class TestSwapDatamodel:
    def test_the_payload_is_replaced_and_others_survive(self, tmp_path: Path) -> None:
        template = _template(tmp_path)
        before = dict(list_members(template))
        out = tmp_path / "out.pbix"
        size = swap_datamodel(template, b"NEW-MODEL-BYTES", out)
        assert size == out.stat().st_size

        with zipfile.ZipFile(out) as z:
            assert z.testzip() is None
            assert z.read("DataModel") == b"NEW-MODEL-BYTES"
            for name in before:
                if name != "DataModel":
                    assert z.read(name) == read_member(template, name)

    @pytest.mark.parametrize("size", [0, 1, 100_000])
    def test_grow_and_shrink_keep_the_archive_consistent(
        self, tmp_path: Path, size: int
    ) -> None:
        # The payload is built here, not passed as a parameter: pytest records
        # the parameter repr in `PYTEST_CURRENT_TEST`, and a 100 kB bytes literal
        # exceeds Windows' 32767-character environment limit (CI caught it).
        payload = b"y" * size
        template = _template(tmp_path)
        out = tmp_path / "out.pbix"
        swap_datamodel(template, payload, out)
        with zipfile.ZipFile(out) as z:
            assert z.testzip() is None
            assert z.read("DataModel") == payload
            assert z.read("docProps/custom.xml") == b"<props/>"

    def test_it_accepts_a_stored_datamodel_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "stored.pbix"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
            z.writestr("DataModel", b"stored-model")
            z.writestr("Version", b"1.28")
        out = tmp_path / "out.pbix"
        swap_datamodel(path, b"replacement", out)
        with zipfile.ZipFile(out) as z:
            assert z.read("DataModel") == b"replacement"

    def test_an_unreadable_output_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard must not be silent: a bad zip raises instead of shipping."""
        template = _template(tmp_path)
        out = tmp_path / "out.pbix"
        monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: "DataModel")
        with pytest.raises(ValueError, match="output zip invalid"):
            swap_datamodel(template, b"payload", out)


class TestBuildContainer:
    def test_only_the_requested_members_are_written(self, tmp_path: Path) -> None:
        template = _template(tmp_path)
        out = tmp_path / "clean.pbix"
        size = build_container(template, b'{"sections":[]}', b"MODEL", out)
        assert size == out.stat().st_size
        with zipfile.ZipFile(out) as z:
            assert z.testzip() is None
            names = z.namelist()
        assert names == [*COPY_MEMBERS, "Report/Layout", "DataModel"]

    def test_the_layout_and_datamodel_are_the_given_bytes(self, tmp_path: Path) -> None:
        template = _template(tmp_path)
        out = tmp_path / "clean.pbix"
        build_container(template, b"LAYOUT", b"MODEL", out)
        with zipfile.ZipFile(out) as z:
            assert z.read("Report/Layout") == b"LAYOUT"
            assert z.read("DataModel") == b"MODEL"

    def test_donor_visuals_are_not_carried_over(self, tmp_path: Path) -> None:
        """A clean build must not leak the donor's own layout or extras."""
        template = _template(tmp_path, {"Report/Extra": b"donor-only"})
        out = tmp_path / "clean.pbix"
        build_container(template, b"LAYOUT", b"MODEL", out)
        with zipfile.ZipFile(out) as z:
            assert "Report/Extra" not in z.namelist()
            assert "docProps/custom.xml" not in z.namelist()

    def test_a_custom_member_list_is_honoured(self, tmp_path: Path) -> None:
        template = _template(tmp_path)
        out = tmp_path / "clean.pbix"
        build_container(template, b"LAYOUT", b"MODEL", out, copy_members=["Version"])
        with zipfile.ZipFile(out) as z:
            assert z.namelist() == ["Version", "Report/Layout", "DataModel"]

    def test_a_missing_member_in_the_donor_raises(self, tmp_path: Path) -> None:
        template = _template(tmp_path)
        out = tmp_path / "clean.pbix"
        with pytest.raises(KeyError):
            build_container(template, b"L", b"M", out, copy_members=["DoesNotExist"])

    def test_an_unreadable_output_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        template = _template(tmp_path)
        out = tmp_path / "clean.pbix"
        monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: "DataModel")
        with pytest.raises(ValueError, match="output zip invalid"):
            build_container(template, b"L", b"M", out)


class TestEncodePayload:
    def test_a_stored_payload_is_returned_unchanged(self) -> None:
        assert engine_container._encode_payload(b"abc", zipfile.ZIP_STORED) == b"abc"

    def test_a_deflated_payload_round_trips(self) -> None:
        import zlib

        raw = b"repeat me " * 500
        encoded = engine_container._encode_payload(raw, zipfile.ZIP_DEFLATED)
        assert zlib.decompress(encoded, -zlib.MAX_WBITS) == raw

    def test_an_unsupported_method_raises_a_domain_error(self) -> None:
        with pytest.raises(
            ValueError, match="unsupported DataModel compression method"
        ):
            engine_container._encode_payload(b"x", zipfile.ZIP_BZIP2)
