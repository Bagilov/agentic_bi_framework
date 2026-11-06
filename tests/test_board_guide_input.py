"""Bad `.pbix` input for the guide: exit 2 with a message, not a traceback.

`Report/Layout` lives inside a zip, and a user can pass a renamed file, a `.pbix`
without that member, or a layout whose bytes are not JSON. Each of those is a
bad *input*: the CLI boundary (`cli_support`, exit 2) must catch it, and the
message must name the file so the caller knows what to fix.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from agentic_bi.board_guide import extract_page_geometry
from agentic_bi.board_guide.guide_layout import load_layout


def test_not_a_zip_is_a_value_error_naming_the_file(tmp_path: Path) -> None:
    pbix = tmp_path / "board.pbix"
    pbix.write_bytes(b"definitely not a zip")
    with pytest.raises(ValueError, match="not a .pbix") as excinfo:
        load_layout(pbix)
    assert "board.pbix" in str(excinfo.value)


def test_zip_without_a_layout_member_is_a_value_error(tmp_path: Path) -> None:
    pbix = tmp_path / "no-layout.pbix"
    with zipfile.ZipFile(pbix, "w") as archive:
        archive.writestr("DataModel", b"\x00")
    with pytest.raises(ValueError, match="no Report/Layout member"):
        load_layout(pbix)


def test_undecodable_layout_is_a_value_error(tmp_path: Path) -> None:
    pbix = tmp_path / "bad-layout.pbix"
    with zipfile.ZipFile(pbix, "w") as archive:
        archive.writestr("Report/Layout", b"\xff\x00\x01\x02 not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_layout(pbix)


def test_extract_geometry_propagates_a_bad_input_as_value_error(
    tmp_path: Path,
) -> None:
    pbix = tmp_path / "board.pbix"
    pbix.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="board.pbix"):
        extract_page_geometry(pbix)


def test_cli_reports_a_broken_pbix_as_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentic_bi.board_guide.guide_cli import main

    pbix = tmp_path / "board.pbix"
    pbix.write_bytes(b"not a zip")
    rc = main(["--pbix", str(pbix), "--out-dir", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "board.pbix" in captured.err
    assert "Traceback" not in captured.err


def test_cli_reports_a_missing_pbix_as_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentic_bi.board_guide.guide_cli import main

    rc = main(["--pbix", str(tmp_path / "gone.pbix"), "--out-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "gone.pbix: file not found" in captured.err
    assert "Traceback" not in captured.err


def test_capture_without_playwright_is_bad_input_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing optional dependency is configuration, so the CLI exits 2."""
    import sys

    from agentic_bi.board_guide.guide_capture import capture_pages

    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(ValueError, match="requires Playwright"):
        capture_pages("https://example.test/report", tmp_path / "shots")
