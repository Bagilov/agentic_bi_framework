"""A figure that is not `ok` must not leave its previous PNG behind.

Measured: a plan whose source was missing reported `status: failed` while the
PNG from an earlier run was still in the output directory, so anything staging
`out/*.png` shipped a picture the manifest does not describe — only an explicit
`verify` caught it. The removal covers every non-`ok` outcome: a failure before
the renderer runs, a render that dies half-way, a skipped figure (`--no-strict`
or a missing browser).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi.board_guide import guide_capture
from agentic_bi.shots import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    ShotPlan,
    build_shots,
    shots_build,
)
from agentic_bi.shots.shots_render import RenderError
from agentic_bi.shots.shots_types import FigureSpec


def _plan(tmp_path: Path) -> ShotPlan:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "card.html").write_text("<body>card</body>", encoding="utf-8")
    return ShotPlan.from_dict(
        {
            "base_dir": str(src),
            "figures": [{"name": "card", "source": "card.html"}],
        }
    )


def _stale(out: Path) -> Path:
    png = out / "card.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG\r\n\x1a\nprevious-run")
    return png


def _browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: "/bin/true"
    )


def test_missing_source_removes_a_previous_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure happens before the renderer, so nothing else would unlink."""
    _browser(monkeypatch)
    stale = _stale(tmp_path / "out")
    plan = ShotPlan.from_dict(
        {
            "base_dir": str(tmp_path / "src"),
            "figures": [{"name": "card", "source": "gone.html"}],
        }
    )

    result = build_shots(plan, tmp_path / "out")

    assert result.failures
    assert result.manifest.figures[0].status == STATUS_FAILED
    assert not stale.exists()


def test_failed_render_removes_a_partial_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A render that wrote part of the file and then died leaves nothing."""
    _browser(monkeypatch)
    stale = _stale(tmp_path / "out")

    def fake_render(
        spec: FigureSpec, out_dir: Path, browser: str | None
    ) -> tuple[Path, int, int]:
        (out_dir / spec.output_name()).write_bytes(b"\x89PNG\r\n\x1a\npartial")
        raise RenderError("no screenshot at card.png (browser exit 1)")

    monkeypatch.setattr(shots_build, "_render_one", fake_render)
    result = build_shots(_plan(tmp_path), tmp_path / "out")

    assert result.manifest.figures[0].status == STATUS_FAILED
    assert not stale.exists()


def test_no_strict_removes_a_previous_png_of_a_left_out_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--no-strict` drops the figure from the manifest; the PNG must go too."""
    _browser(monkeypatch)
    stale = _stale(tmp_path / "out")
    plan = ShotPlan.from_dict(
        {
            "base_dir": str(tmp_path / "src"),
            "figures": [{"name": "card", "source": "gone.html"}],
        }
    )

    result = build_shots(plan, tmp_path / "out", strict=False)

    assert result.manifest.figures == []
    assert not stale.exists()


def test_missing_browser_removes_a_previous_png_of_every_skipped_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: None
    )
    stale = _stale(tmp_path / "out")

    result = build_shots(_plan(tmp_path), tmp_path / "out")

    assert result.manifest.figures[0].status == STATUS_SKIPPED
    assert not stale.exists()


def test_a_built_figure_keeps_its_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cleanup must not touch an `ok` figure's output."""
    _browser(monkeypatch)

    def fake_render(
        spec: FigureSpec, out_dir: Path, browser: str | None
    ) -> tuple[Path, int, int]:
        png = out_dir / spec.output_name()
        png.write_bytes(b"\x89PNG\r\n\x1a\nfresh")
        return png, spec.width, spec.height

    monkeypatch.setattr(shots_build, "_render_one", fake_render)
    result = build_shots(_plan(tmp_path), tmp_path / "out")

    assert result.ok
    assert (tmp_path / "out" / "card.png").read_bytes().endswith(b"fresh")
