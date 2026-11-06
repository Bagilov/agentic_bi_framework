"""CLI contract tests for `agentic-bi-web-clone`.

Pins the boundary behaviour of the command: expected input failures exit 2 with
one short stderr line (no traceback), an empty `--registry` means "no registry"
instead of turning on membership checks, the generated document is checked with
`html_issues` (a warning by default, a failure under `--strict`), and `--out`
creates missing directories.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from agentic_bi.web_report import web_cli
from agentic_bi.web_report.web_cli import main
from agentic_bi.web_report.web_model import WebReportModel
from agentic_bi.web_report.web_render import write_html as render_to_path


def _pbix(tmp_path: Path, layout: dict) -> Path:
    path = tmp_path / "board.pbix"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Report/Layout", json.dumps(layout).encode("utf-8"))
    return path


def _card_layout() -> dict:
    from tests.web_report_fixtures import make_container

    return {
        "sections": [
            {
                "displayName": "P",
                "width": 1280,
                "height": 720,
                "visualContainers": [
                    make_container(
                        "card",
                        {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
                        ["Sum(Sales.amount)"],
                        title="Total",
                    )
                ],
            }
        ]
    }


def _run(tmp_path: Path, *extra: str) -> int:
    return main(
        ["--pbix", str(tmp_path / "board.pbix"), "--out", str(tmp_path / "o.html")]
        + list(extra)
    )


def test_empty_registry_is_treated_as_no_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    _pbix(tmp_path, _card_layout())
    registry = tmp_path / "reg.json"
    registry.write_text("{}", encoding="utf-8")
    rc = _run(tmp_path, "--registry", str(registry))
    captured = capsys.readouterr()
    assert rc == 0
    assert "checks were skipped" in captured.err
    assert "пуст" in captured.err
    assert "ошибок: 0" in captured.out


def test_non_empty_registry_runs_membership_checks_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    _pbix(tmp_path, _card_layout())
    registry = tmp_path / "reg.json"
    registry.write_text(
        json.dumps({"Sales": {"columns": ["amount"], "measures": []}}),
        encoding="utf-8",
    )
    rc = _run(tmp_path, "--registry", str(registry))
    captured = capsys.readouterr()
    assert rc == 0
    assert "checks were skipped" not in captured.err


def _strip_detail_close(model: WebReportModel, path: str | Path, **_: Any) -> Path:
    written = render_to_path(model, path)
    written.write_text(
        written.read_text(encoding="utf-8").replace(' id="detailClose"', ""),
        encoding="utf-8",
    )
    return written


def test_document_marker_regression_is_reported_by_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    _pbix(tmp_path, _card_layout())
    monkeypatch.setattr(web_cli, "write_html", _strip_detail_close)
    rc = _run(tmp_path)
    captured = capsys.readouterr()
    assert rc == 0
    assert "HTML-A11Y-DETAIL-CLOSE" in captured.err


def test_document_marker_regression_fails_strict_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    _pbix(tmp_path, _card_layout())
    monkeypatch.setattr(web_cli, "write_html", _strip_detail_close)
    rc = _run(tmp_path, "--strict")
    captured = capsys.readouterr()
    assert rc == 1
    assert "(--strict)" in captured.err


def test_strict_mode_passes_a_report_with_warnings_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    layout = _card_layout()
    layout["sections"][0]["visualContainers"] = [
        {
            "x": 0,
            "y": 0,
            "width": 100,
            "height": 100,
            "config": json.dumps(
                {
                    "singleVisual": {
                        "visualType": "textbox",
                        "projections": {},
                        "prototypeQuery": {},
                    }
                }
            ),
            "filters": "[]",
        }
    ]
    _pbix(tmp_path, layout)
    rc = _run(tmp_path, "--strict")
    assert rc == 0


def test_strict_mode_fails_a_report_with_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    layout = _card_layout()
    layout["sections"][0]["visualContainers"][0]["config"] = json.dumps(
        {"singleVisual": {"visualType": "card", "projections": {}}}
    )
    _pbix(tmp_path, layout)
    rc = _run(tmp_path, "--strict")
    assert rc == 1


def test_out_creates_missing_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    _pbix(tmp_path, _card_layout())
    nested = tmp_path / "a" / "b" / "clone.html"
    rc = main(["--pbix", str(tmp_path / "board.pbix"), "--out", str(nested)])
    assert rc == 0
    assert nested.is_file()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"not a zip", "не zip-контейнер"),
        (b'{"sections":', "не разбирается как JSON"),
    ],
)
def test_unreadable_input_is_one_short_error_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: bytes, expected: str
):
    path = tmp_path / "board.pbix"
    if payload == b"not a zip":
        path.write_bytes(payload)
    else:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Report/Layout", payload)
    rc = _run(tmp_path)
    captured = capsys.readouterr()
    assert rc == 2
    assert expected in captured.err
    assert str(path) in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


def test_registry_with_a_non_object_table_is_an_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    _pbix(tmp_path, _card_layout())
    registry = tmp_path / "reg.json"
    registry.write_text('{"Sales": null}', encoding="utf-8")
    rc = _run(tmp_path, "--registry", str(registry))
    captured = capsys.readouterr()
    assert rc == 2
    assert "должно быть объектом" in captured.err
    assert "Traceback" not in captured.err
