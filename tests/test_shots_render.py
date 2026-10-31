"""Browser-dependent tests for the screenshot renderer (`shots`).

Everything here needs a real Chromium and is skipped without one, so the rest of
the suite stays green on a machine that has no browser. The pure parts of the
pipeline (plan validation, terminal wrapping, manifest hashing) are covered in
`tests/test_shots.py`.

The pixel assertions exist because a render can *look* fine and still be wrong:
the PNG can have the requested size while its content was clamped away, and a
`<canvas>` figure can come back blank if its drawing never ran.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentic_bi.shots import (
    ShotPlan,
    build_shots,
    build_terminal_html,
    render_html_string,
    sha256_file,
    verify_manifest,
)
from agentic_bi.shots.shots_render import find_browser_executable
from agentic_bi.shots.shots_terminal import BAR_HEIGHT

_HAS_BROWSER = find_browser_executable() is not None
_needs_browser = pytest.mark.skipif(not _HAS_BROWSER, reason="no Chromium available")


def _png_pixels(path: Path):
    """A loaded pixel accessor for a rendered PNG (Pillow is a report extra)."""
    pytest.importorskip("PIL.Image", reason="reading rendered pixels needs Pillow")
    from PIL import Image

    return Image.open(path).convert("RGB").load()


def _open_fd_count() -> int:
    """How many descriptors this process currently holds (portable enough)."""
    for candidate in ("/dev/fd", "/proc/self/fd"):
        if os.path.isdir(candidate):
            return len(os.listdir(candidate))
    pytest.skip("no /dev/fd or /proc/self/fd to count descriptors")


@_needs_browser
def test_render_html_string_is_deterministic(tmp_path: Path) -> None:
    html = "<!doctype html><body style='margin:0;background:#fff'>hi</body>"
    a = render_html_string(html, tmp_path / "a.png", width=120, height=60, scale=1.0)
    b = render_html_string(html, tmp_path / "b.png", width=120, height=60, scale=1.0)
    assert sha256_file(a) == sha256_file(b)


@_needs_browser
def test_render_html_string_does_not_leak_file_descriptors(tmp_path: Path) -> None:
    """The temp-file dance must not leak an fd per call.

    `mkstemp` returns an open descriptor; leaving it unclosed leaked one fd per
    rendered string figure, so a set of terminal cards exhausted the limit. The
    count is compared across renders because the absolute value is the runtime's.
    """
    html = "<!doctype html><body style='margin:0'>leak check</body>"
    render_html_string(html, tmp_path / "warm.png", width=120, height=144, scale=1.0)
    before = _open_fd_count()
    for i in range(8):
        render_html_string(
            html, tmp_path / f"f{i}.png", width=120, height=144, scale=1.0
        )
    assert _open_fd_count() <= before


@_needs_browser
def test_short_terminal_card_keeps_its_body_in_the_png(tmp_path: Path) -> None:
    """The regression that the window floor fixes, asserted on the pixels.

    Before the floor, a two-line card was rendered at ~121 px, below Chromium's
    layout minimum, so the PNG was the right size but contained only the title
    bar. The body text must actually be painted.
    """
    html, width, height = build_terminal_html(
        "$ ruff check .\nAll checks passed!", title="t", columns=88
    )
    png = render_html_string(
        html, tmp_path / "short.png", width=width, height=height, scale=1.0
    )
    pixels = _png_pixels(png)
    body_rows = [
        y
        for y in range(BAR_HEIGHT, height)
        if any(sum(pixels[x, y]) > 500 for x in range(width))
    ]
    assert body_rows, (
        "terminal card body was not painted (window clamped below the floor)"
    )


_CANVAS_PAGE = """<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;background:#000}canvas{display:block}</style>
<canvas id="c" width="80" height="40"></canvas>
<script>
  document.getElementById("c").getContext("2d").fillRect(0, 0, 80, 40);
</script>"""

_CANVAS_TIMER_PAGE = """<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;background:#000}canvas{display:block}</style>
<canvas id="c" width="80" height="40"></canvas>
<script>
  var ctx = document.getElementById("c").getContext("2d");
  setTimeout(function () { ctx.fillStyle = "#00ff00"; ctx.fillRect(0, 0, 80, 40); }, 200);
</script>"""


@_needs_browser
def test_canvas_is_painted_and_deterministic(tmp_path: Path) -> None:
    """A `<canvas>` figure is plain `html`; the browser must paint it.

    Canvas is how charts and diagrams are drawn, so it is covered explicitly:
    the render is only useful if the drawing survives the screenshot, and only
    trustworthy if it is byte-identical across runs.
    """
    first = render_html_string(
        _CANVAS_PAGE, tmp_path / "a.png", width=80, height=60, scale=1.0
    )
    second = render_html_string(
        _CANVAS_PAGE, tmp_path / "b.png", width=80, height=60, scale=1.0
    )
    assert sha256_file(first) == sha256_file(second)
    assert _png_pixels(first)[40, 20] == (0, 0, 0)


@_needs_browser
def test_canvas_draw_scheduled_within_settle_ms_is_captured(tmp_path: Path) -> None:
    """A timer draw inside `settle_ms` lands in the PNG; beyond it does not.

    `--virtual-time-budget` fast-forwards virtual time (a 5 s timer does not make
    the render take 5 s), so a canvas that draws from `setTimeout` is captured as
    long as the callback is scheduled within the budget. This fixes the contract
    a plan author relies on when picking `settle_ms`.
    """
    inside = render_html_string(
        _CANVAS_TIMER_PAGE,
        tmp_path / "in.png",
        width=80,
        height=60,
        scale=1.0,
        settle_ms=500,
    )
    outside = render_html_string(
        _CANVAS_TIMER_PAGE,
        tmp_path / "out.png",
        width=80,
        height=60,
        scale=1.0,
        settle_ms=100,
    )
    assert _png_pixels(inside)[40, 20] == (0, 255, 0)
    assert _png_pixels(outside)[40, 20] == (0, 0, 0)


@_needs_browser
def test_build_shots_end_to_end(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "run.txt").write_text("$ pytest\nAll checks passed!", encoding="utf-8")
    (src / "card.html").write_text(
        "<!doctype html><body style='margin:0'>card</body>", encoding="utf-8"
    )
    plan = ShotPlan.from_dict(
        {
            "base_dir": str(src),
            "figures": [
                {"name": "run", "kind": "terminal", "source": "run.txt"},
                {
                    "name": "card",
                    "kind": "html",
                    "source": "card.html",
                    "width": 200,
                    "height": 100,
                },
            ],
        }
    )
    result = build_shots(plan, tmp_path / "out")
    assert result.ok
    assert len(result.manifest.figures) == 2
    assert (tmp_path / "out" / "manifest.json").exists()
    assert verify_manifest(result.manifest) == []
