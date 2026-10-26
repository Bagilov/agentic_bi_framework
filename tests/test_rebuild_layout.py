"""Rebuild a `.pbix` from a donor: layout replacement in the zip (`rebuild`).

`rebuild_pbix` is one of the two paths that *write* a `.pbix`, and it is the one
that keeps the donor's binary `DataModel` byte-for-byte while replacing only
`Report/Layout`. A regression here ships a container that Desktop refuses to
open, so this suite pins:

* the encoding round-trip (Desktop writes UTF-16LE without BOM; a reused layout
  that was UTF-8 must stay UTF-8),
* that every non-layout member survives byte-for-byte,
* the generated single-visual layout's shape (`_new_layout`), and
* the failure mode for a source whose layout cannot be decoded.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from agentic_bi.rebuild import (
    _extract_layout,
    _new_layout,
    rebuild_pbix,
)


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {name: z.read(name) for name in z.namelist()}


def _make_donor(
    path: Path, layout_bytes: bytes, extra: dict[str, bytes] | None = None
) -> Path:
    """A minimal container with a `Report/Layout` and a few other members."""
    members: dict[str, bytes] = {
        "Version": b"1.28",
        "Report/Layout": layout_bytes,
        "DataModel": b"CANONICAL-DATAMODEL",
    }
    members.update(extra or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


class TestExtractLayout:
    def test_utf16_without_bom_is_normalized_to_utf16le(self, tmp_path: Path) -> None:
        donor = _make_donor(
            tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-16-le")
        )
        layout, enc = _extract_layout(donor)
        assert layout == {"id": 1}
        assert enc == "utf-16le"

    def test_a_utf16_bom_is_normalized_to_utf16le(self, tmp_path: Path) -> None:
        donor = _make_donor(tmp_path / "d.pbix", json.dumps({"id": 2}).encode("utf-16"))
        layout, enc = _extract_layout(donor)
        assert layout == {"id": 2}
        assert enc == "utf-16le"

    def test_a_utf8_layout_is_preserved_as_utf8(self, tmp_path: Path) -> None:
        donor = _make_donor(tmp_path / "d.pbix", json.dumps({"id": 3}).encode("utf-8"))
        layout, enc = _extract_layout(donor)
        assert layout == {"id": 3}
        assert enc == "utf-8"

    def test_an_undecodable_layout_raises_a_domain_error(self, tmp_path: Path) -> None:
        donor = _make_donor(tmp_path / "d.pbix", b"\x00\x01\x02not-json")
        with pytest.raises(
            ValueError, match="Could not decode the source Report/Layout"
        ):
            _extract_layout(donor)

    def test_a_missing_layout_member_raises_key_error(self, tmp_path: Path) -> None:
        path = tmp_path / "nolayout.pbix"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Version", "1.28")
        with pytest.raises(KeyError):
            _extract_layout(path)

    def test_cyrillic_and_special_characters_round_trip(self, tmp_path: Path) -> None:
        payload = {"title": "Отчёт «Продажи»", "emoji": "→ ✓", "quote": 'a"b\\c'}
        donor = _make_donor(
            tmp_path / "d.pbix",
            json.dumps(payload, ensure_ascii=False).encode("utf-16-le"),
        )
        layout, _ = _extract_layout(donor)
        assert layout == payload


class TestNewLayout:
    def test_it_references_the_requested_objects(self) -> None:
        layout = _new_layout("Page", "Sales", "Region", "Total", {"id": 7})
        assert layout["id"] == 7
        section = layout["sections"][0]
        assert section["displayName"] == "Page"
        config = json.loads(section["visualContainers"][0]["config"])
        assert config["singleVisual"]["visualType"] == "clusteredColumnChart"
        select = config["singleVisual"]["prototypeQuery"]["Select"]
        assert select[0]["Column"]["Property"] == "Region"
        assert select[1]["Measure"]["Expression"]["MeasureRef"]["Property"] == "Total"

    def test_the_source_table_is_the_query_entity(self) -> None:
        layout = _new_layout("P", "Sales", "c", "m", {})
        config = json.loads(layout["sections"][0]["visualContainers"][0]["config"])
        assert config["singleVisual"]["prototypeQuery"]["From"] == [
            {"Name": "e", "Entity": "Sales"}
        ]

    def test_a_missing_base_id_defaults_to_zero(self) -> None:
        assert _new_layout("P", "T", "c", "m", {})["id"] == 0

    def test_the_new_layout_replaces_the_sections_of_the_base(self) -> None:
        base = {
            "sections": ["donor-page"],
            "resourcePackages": [{"name": "SharedResources"}],
        }
        layout = _new_layout("P", "T", "c", "m", base)
        assert layout["sections"] != ["donor-page"]
        assert layout["resourcePackages"] == [{"name": "SharedResources"}]


class TestRebuildPbix:
    def test_every_non_layout_member_survives_byte_for_byte(
        self, tmp_path: Path
    ) -> None:
        donor = _make_donor(
            tmp_path / "d.pbix",
            json.dumps({"id": 1}).encode("utf-16-le"),
            extra={"DataModel": b"model-bytes", "Settings": b"settings-bytes"},
        )
        before = _members(donor)
        out = tmp_path / "out.pbix"
        rebuild_pbix(donor, out, display_name="New")

        after = _members(out)
        assert set(after) == set(before)
        for name, data in before.items():
            if name != "Report/Layout":
                assert after[name] == data, f"{name} changed"

    def test_the_layout_is_replaced_with_the_requested_page(
        self, tmp_path: Path
    ) -> None:
        donor = _make_donor(
            tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-16-le")
        )
        out = tmp_path / "out.pbix"
        rebuild_pbix(
            donor, out, display_name="My page", table="T", col="C", measure="M"
        )
        layout, _ = _extract_layout(out)
        assert layout["sections"][0]["displayName"] == "My page"

    def test_a_utf8_donor_stays_utf8(self, tmp_path: Path) -> None:
        donor = _make_donor(tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-8"))
        out = tmp_path / "out.pbix"
        rebuild_pbix(donor, out)
        with zipfile.ZipFile(out) as z:
            raw = z.read("Report/Layout")
        assert json.loads(raw.decode("utf-8"))["sections"]

    def test_a_utf16_donor_writes_utf16le_without_bom(self, tmp_path: Path) -> None:
        donor = _make_donor(tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-16"))
        out = tmp_path / "out.pbix"
        rebuild_pbix(donor, out)
        with zipfile.ZipFile(out) as z:
            raw = z.read("Report/Layout")
        assert not raw.startswith((b"\xff\xfe", b"\xfe\xff"))
        assert json.loads(raw.decode("utf-16-le"))["sections"]

    def test_an_explicit_layout_is_used_as_is(self, tmp_path: Path) -> None:
        donor = _make_donor(
            tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-16-le")
        )
        ready = {"id": 9, "sections": [{"displayName": "From skeleton"}]}
        out = tmp_path / "out.pbix"
        rebuild_pbix(donor, out, layout=ready)
        layout, _ = _extract_layout(out)
        assert layout["sections"] == [{"displayName": "From skeleton"}]

    def test_the_output_directory_is_created(self, tmp_path: Path) -> None:
        donor = _make_donor(
            tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-16-le")
        )
        out = tmp_path / "nested" / "deep" / "out.pbix"
        rebuild_pbix(donor, out)
        assert out.is_file()

    def test_the_output_is_a_valid_zip(self, tmp_path: Path) -> None:
        donor = _make_donor(
            tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-16-le")
        )
        out = tmp_path / "out.pbix"
        rebuild_pbix(donor, out)
        with zipfile.ZipFile(out) as z:
            assert z.testzip() is None

    def test_the_encoding_marker_is_utf16le_after_a_rebuild(
        self, tmp_path: Path
    ) -> None:
        donor = _make_donor(
            tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-16-le")
        )
        out = tmp_path / "out.pbix"
        rebuild_pbix(donor, out)
        assert _extract_layout(out)[1] == "utf-16le"


class TestRebuildMain:
    """The module's CLI entry point parses argv and writes the requested path."""

    def test_main_builds_the_requested_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi import rebuild

        donor = _make_donor(
            tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-16-le")
        )
        out = tmp_path / "cli.pbix"
        monkeypatch.setattr(
            "sys.argv",
            ["rebuild", str(donor), "--out", str(out), "--display", "CLI page"],
        )
        rebuild.main()
        assert out.is_file()
        assert _extract_layout(out)[0]["sections"][0]["displayName"] == "CLI page"

    def test_main_defaults_the_display_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_bi import rebuild

        donor = _make_donor(
            tmp_path / "d.pbix", json.dumps({"id": 1}).encode("utf-16-le")
        )
        out = tmp_path / "default.pbix"
        monkeypatch.setattr("sys.argv", ["rebuild", str(donor), "--out", str(out)])
        rebuild.main()
        assert _extract_layout(out)[0]["sections"][0]["displayName"] == "Rebuilt report"
