"""Missing tools and bad sources in `shots`: skip with a reason, never crash.

The only external tool is the browser; the terminal card is built in Python, so
there is no font or terminal binary to miss. When the browser is absent the run
still finishes, records every figure as `skipped` with the reason, and the CLI
exits non-zero with that reason on stderr — a half-built set is reported, not
silently accepted and not a traceback.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.board_guide import guide_capture
from agentic_bi.shots import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED,
    ShotPlan,
    build_shots,
    shots_build,
    verify_manifest,
)
from agentic_bi.shots.shots_cli import main
from agentic_bi.shots.shots_types import FigureSpec


def _no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: None
    )


def _plan(*figures: dict[str, object]) -> ShotPlan:
    return ShotPlan.from_dict({"figures": list(figures)})


def test_missing_browser_skips_every_figure_with_a_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_browser(monkeypatch)
    plan = _plan(
        {"name": "a", "source": "a.html"},
        {"name": "b", "source": "b.html"},
    )
    result = build_shots(plan, tmp_path / "out")
    assert result.built == 0
    assert result.ok is False
    assert [name for name, _ in result.skipped] == ["a", "b"]
    assert "Chromium" in result.skipped[0][1]
    assert [f.status for f in result.manifest.figures] == [
        STATUS_SKIPPED,
        STATUS_SKIPPED,
    ]
    assert all(f.png == "" and f.sha256 == "" for f in result.manifest.figures)


def test_verify_reports_a_skipped_figure_as_not_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_browser(monkeypatch)
    result = build_shots(_plan({"name": "a", "source": "a.html"}), tmp_path)
    problems = verify_manifest(result.manifest)
    assert len(problems) == 1
    assert "not built (skipped" in problems[0]


def test_cli_exit_is_non_zero_and_explains_a_missing_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_browser(monkeypatch)
    plan_file = tmp_path / "figures.json"
    plan_file.write_text(
        json.dumps({"figures": [{"name": "a", "source": "a.html"}]}),
        encoding="utf-8",
    )
    rc = main(["--plan", str(plan_file), "--out-dir", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "figures: 0 built, 1 skipped, 0 failed" in captured.out
    assert "warning: skipped 1 figure(s)" in captured.err
    assert "Chromium" in captured.err
    assert "error:" in captured.err
    assert "Traceback" not in captured.err


def test_a_missing_source_still_builds_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad figure must not cancel the run (and is reported per figure)."""
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: "/bin/true"
    )

    def fake_render(
        spec: FigureSpec, out_dir: Path, browser: str | None
    ) -> tuple[Path, int, int]:
        png = out_dir / spec.output_name()
        png.write_bytes(b"ok")
        return png, spec.width, spec.height

    monkeypatch.setattr(shots_build, "_render_one", fake_render)
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.html").write_text("<body></body>", encoding="utf-8")
    plan = ShotPlan.from_dict(
        {
            "base_dir": str(src),
            "figures": [
                {"name": "gone", "source": "gone.html"},
                {"name": "ok", "source": "ok.html"},
            ],
        }
    )
    result = build_shots(plan, tmp_path / "out")
    assert result.built == 1
    assert [name for name, _ in result.failures] == ["gone"]
    assert [f.status for f in result.manifest.figures] == [
        STATUS_FAILED,
        STATUS_OK,
    ]
    assert result.ok is False


def test_empty_terminal_source_is_a_reported_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: "/bin/true"
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "empty.txt").write_text("  \n\n", encoding="utf-8")
    plan = ShotPlan.from_dict(
        {
            "base_dir": str(src),
            "figures": [
                {"name": "e", "kind": "terminal", "source": "empty.txt"},
            ],
        }
    )
    result = build_shots(plan, tmp_path / "out")
    assert "empty source" in result.failures[0][1]


def test_non_utf8_terminal_source_is_a_reported_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: "/bin/true"
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "raw.txt").write_bytes(b"\xff\xfe\x00\x00")
    plan = ShotPlan.from_dict(
        {
            "base_dir": str(src),
            "figures": [{"name": "r", "kind": "terminal", "source": "raw.txt"}],
        }
    )
    result = build_shots(plan, tmp_path / "out")
    assert "not valid UTF-8" in result.failures[0][1]
