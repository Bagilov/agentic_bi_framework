"""Console output of `agentic-bi-shots`: counts, relative paths, split streams.

The summary must fit on one screen and be readable without the old log noise:
how many figures were built, skipped and failed, and where to find them. Errors
and warnings are separate lines on stderr, and no printed path is absolute.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.board_guide import guide_capture
from agentic_bi.shots import shots_build
from agentic_bi.shots.shots_cli import main
from agentic_bi.shots.shots_types import FigureSpec


def _fake_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: "/bin/true"
    )

    def fake_render(
        spec: FigureSpec, out_dir: Path, browser: str | None
    ) -> tuple[Path, int, int]:
        png = out_dir / spec.output_name()
        png.write_bytes(b"png")
        return png, spec.width, spec.height

    monkeypatch.setattr(shots_build, "_render_one", fake_render)


def _plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "card.html").write_text("<body></body>", encoding="utf-8")
    (tmp_path / "plan.json").write_text(
        json.dumps(
            {"base_dir": "src", "figures": [{"name": "card", "source": "card.html"}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)


def test_build_summary_fits_and_uses_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_renderer(monkeypatch)
    _plan(tmp_path, monkeypatch)
    rc = main(["--plan", "plan.json", "--out-dir", "out"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "figures: 1 built, 0 skipped, 0 failed" in captured.out
    assert "out: out" in captured.out
    assert "manifest: out/manifest.json" in captured.out
    assert str(tmp_path) not in captured.out
    assert len(captured.out.splitlines()) == 3
    assert captured.err == ""


def test_build_reports_the_manifest_name_that_was_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The summary used to hardcode `manifest.json`, ignoring the real name."""
    _fake_renderer(monkeypatch)
    _plan(tmp_path, monkeypatch)
    rc = main(
        [
            "--plan",
            "plan.json",
            "--out-dir",
            "out",
            "--manifest-name",
            "shots.json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "manifest: out/shots.json" in captured.out
    assert (tmp_path / "out" / "shots.json").exists()
    assert len(captured.out.splitlines()) == 3


def test_build_errors_and_warnings_are_separate_stdout_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_renderer(monkeypatch)
    src = tmp_path / "src"
    src.mkdir()
    (src / "card.html").write_text("<body></body>", encoding="utf-8")
    (tmp_path / "plan.json").write_text(
        json.dumps(
            {
                "base_dir": "src",
                "figures": [
                    {"name": "ok", "source": "card.html"},
                    {"name": "gone", "source": "gone.html"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    rc = main(["--plan", "plan.json", "--out-dir", "out"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "figures: 1 built, 0 skipped, 1 failed" in captured.out
    assert "error: figure 'gone': source not found" in captured.err
    assert "requested figure(s) were not produced" in captured.err
    assert "Traceback" not in captured.err


def test_verify_summary_and_drift_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentic_bi.shots import RenderRecord, write_manifest

    monkeypatch.chdir(tmp_path)
    record = RenderRecord(
        name="card",
        kind="html",
        source="card.html",
        png="card.png",
        width=10,
        height=10,
        scale=1.0,
        sha256="0" * 64,
        bytes=1,
    )
    write_manifest([record], tmp_path / "manifest.json", browser="chrome")
    rc = main(["verify", "--manifest", "manifest.json"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "figures: 1 checked, 1 problem(s)" in captured.out
    assert "DRIFT card: missing file" in captured.err
    assert "error: 1 problem(s) found" in captured.err
    assert "Traceback" not in captured.err
