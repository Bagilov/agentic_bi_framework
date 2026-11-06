"""Console output of `agentic-bi-board-guide`: short, relative, split streams.

The guide prints a summary a person can read at a glance: how many pages were
written and skipped, and where. Absolute machine paths are noise (and leak a
home directory into logs), so every printed path is relative to the CWD when it
is inside it, and warnings stay on stderr, apart from the summary.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from tests.test_board_guide_png import MINIMAL_PNG
from tests.web_report_fixtures import make_container, make_layout


def _two_page_pbix(path: Path) -> Path:
    layout = make_layout(
        [
            make_container(
                "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
            )
        ],
        page="Overview",
    )
    layout["sections"].append(
        {
            "displayName": "Sales",
            "width": 1280,
            "height": 720,
            "visualContainers": [],
        }
    )
    payload = json.dumps(layout, ensure_ascii=False).encode("utf-16-le")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Report/Layout", payload)
    return path


def test_summary_is_short_and_uses_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentic_bi.board_guide.guide_cli import main

    pbix = _two_page_pbix(tmp_path / "board.pbix")
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "page_Overview.png").write_bytes(MINIMAL_PNG)
    monkeypatch.chdir(tmp_path)

    rc = main(["--pbix", str(pbix), "--out-dir", "out", "--shots", "shots"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "guide: 1 лист(ов) записано, 1 пропущено -> out" in captured.out
    assert "index: out/index.html" in captured.out
    assert str(tmp_path) not in captured.out
    assert len(captured.out.splitlines()) == 3


def test_skipped_page_reason_goes_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentic_bi.board_guide.guide_cli import main

    pbix = _two_page_pbix(tmp_path / "board.pbix")
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "page_Overview.png").write_bytes(MINIMAL_PNG)
    monkeypatch.chdir(tmp_path)

    main(["--pbix", str(pbix), "--out-dir", "out", "--shots", "shots"])
    captured = capsys.readouterr()
    assert "warning: лист 'Sales' пропущен: нет файла page_Sales.png" in captured.err
    assert "warning" not in captured.out


def test_no_screenshot_warning_is_still_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentic_bi.board_guide.guide_cli import main

    pbix = _two_page_pbix(tmp_path / "board.pbix")
    monkeypatch.chdir(tmp_path)
    rc = main(["--pbix", str(pbix), "--out-dir", "out"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "no page had a screenshot" in captured.err
