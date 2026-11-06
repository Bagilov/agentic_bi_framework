"""CLI + capture-helper tests for the annotated board guide (`board_guide`).

These exercise the `agentic-bi-board-guide` entry point and the parts of
`guide_capture` that can be checked without a browser.
"""

from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

import pytest
from tests.test_board_guide_png import MINIMAL_PNG
from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.board_guide.guide_capture import (
    capture_pages,
    find_browser_executable,
)


def _write_pbix(path: Path, layout: dict) -> Path:
    payload = json.dumps(layout, ensure_ascii=False).encode("utf-16-le")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Report/Layout", payload)
    return path


def test_cli_builds_guide_from_shots(tmp_path: Path) -> None:
    from agentic_bi.board_guide.guide_cli import main

    layout = make_layout(
        [
            make_container(
                "card",
                {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
                ["Sum(Sales.amount)"],
                title="Total",
            )
        ],
        page="Overview",
    )
    pbix = _write_pbix(tmp_path / "b.pbix", layout)
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "page_Overview.png").write_bytes(MINIMAL_PNG)
    out = tmp_path / "guide"
    rc = main(
        [
            "--pbix",
            str(pbix),
            "--out-dir",
            str(out),
            "--shots",
            str(shots),
        ]
    )
    assert rc == 0
    assert (out / "index.html").exists()
    assert (out / "guide_Overview.html").exists()


def test_cli_writes_geometry_json(tmp_path: Path, capsys) -> None:
    from agentic_bi.board_guide.guide_cli import main

    layout = make_layout(
        [
            make_container(
                "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
            )
        ]
    )
    pbix = _write_pbix(tmp_path / "b.pbix", layout)
    geom_json = tmp_path / "geom.json"
    rc = main(
        [
            "--pbix",
            str(pbix),
            "--out-dir",
            str(tmp_path / "g"),
            "--geometry-json",
            str(geom_json),
        ]
    )
    assert rc == 0
    payload = json.loads(geom_json.read_text(encoding="utf-8"))
    assert payload["pages"][0]["visuals"][0]["type"] == "card"
    assert "no page had a screenshot" in capsys.readouterr().err


def test_cli_reports_bad_input_as_exit_2(tmp_path: Path) -> None:
    from agentic_bi.board_guide.guide_cli import main

    rc = main(["--pbix", str(tmp_path / "missing.pbix"), "--out-dir", str(tmp_path)])
    assert rc == 2


def test_cli_writes_standard_json_for_non_finite_coords(tmp_path: Path) -> None:
    """`--geometry-json` must never emit `NaN`/`Infinity` tokens."""
    from agentic_bi.board_guide.guide_cli import main

    layout = {
        "sections": [
            {
                "displayName": "P",
                "width": "nan",
                "height": "inf",
                "visualContainers": [
                    {"x": "nan", "y": "nan", "config": json.dumps({"singleVisual": {}})}
                ],
            }
        ]
    }
    pbix = _write_pbix(tmp_path / "b.pbix", layout)
    geom_json = tmp_path / "geom.json"
    rc = main(
        [
            "--pbix",
            str(pbix),
            "--out-dir",
            str(tmp_path / "g"),
            "--geometry-json",
            str(geom_json),
        ]
    )
    assert rc == 0
    text = geom_json.read_text(encoding="utf-8")
    assert "NaN" not in text
    assert "Infinity" not in text
    json.loads(text)


def test_capture_js_escapes_selector_quotes() -> None:
    """A selector containing `'`/`\\` must not break the generated JS."""
    from agentic_bi.board_guide.guide_capture import (
        _page_area_js,
        _visual_rects_js,
    )

    js = _visual_rects_js("a'); alert(1); //")
    assert "querySelectorAll('a\\'); alert(1); //')" in js
    area = _page_area_js(["x';", "y"])
    assert "['x\\';', 'y']" in area


def test_find_browser_executable_honors_explicit(tmp_path: Path) -> None:
    fake = tmp_path / "chrome"
    fake.write_text("#!/bin/sh\n")
    assert find_browser_executable(str(fake)) == str(fake)


def test_find_browser_executable_rejects_a_missing_explicit_path(
    tmp_path: Path,
) -> None:
    """A named browser must never be silently replaced by another one."""
    with pytest.raises(ValueError, match="browser executable not found"):
        find_browser_executable(str(tmp_path / "nope"))


def test_capture_converts_a_launch_failure_to_a_bad_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Playwright installed but Chromium missing: exit 2, not a traceback."""

    class _Chromium:
        def launch(self, **kwargs: object) -> object:
            raise RuntimeError("Executable doesn't exist")

    class _Playwright:
        chromium = _Chromium()

    class _Context:
        def __enter__(self) -> _Playwright:
            return _Playwright()

        def __exit__(self, *exc: object) -> bool:
            return False

    def _sync_playwright() -> _Context:
        return _Context()

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = _sync_playwright
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)

    with pytest.raises(ValueError, match="Chromium binary"):
        capture_pages("https://example.test/report", tmp_path)


def test_cli_reports_a_missing_browser_as_exit_2(tmp_path: Path) -> None:
    from agentic_bi.board_guide.guide_cli import main

    layout = make_layout(
        [
            make_container(
                "card", {"Values": [{"queryRef": "Sales.amount"}]}, ["Sales.amount"]
            )
        ]
    )
    pbix = _write_pbix(tmp_path / "b.pbix", layout)
    rc = main(
        [
            "--pbix",
            str(pbix),
            "--out-dir",
            str(tmp_path / "guide"),
            "--capture-url",
            "https://example.test/report",
            "--browser",
            str(tmp_path / "missing-chrome"),
        ]
    )
    assert rc == 2
