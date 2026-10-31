"""Render an HTML document to a PNG with a headless Chromium.

One place owns every Chromium flag, the temporary-file dance and the failure
report; `shots_build` only decides *what* to render. The browser is discovered
via `board_guide.guide_capture.find_browser_executable` (an explicit path,
`GUIDE_CHROME`, `PLAYWRIGHT_CHROME`, then the usual per-OS locations), so no
machine-specific path is baked in.

Determinism: the viewport, the device scale factor and the virtual time budget
are all fixed per shot, and `--virtual-time-budget` lets the page settle without
a wall-clock sleep, so two runs of the same input produce the same image.

Public API:
    BrowserNotFound            - raised when no Chromium binary is available
    RenderError                - raised when the browser produced no PNG
    render_html_file(...) -> Path
    render_html_string(...) -> Path
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from agentic_bi.board_guide.guide_capture import find_browser_executable
from agentic_bi.shots.shots_types import MIN_WINDOW_HEIGHT

logger = logging.getLogger(__name__)

_DEFAULT_BUDGET_MS = 250
_DEFAULT_TIMEOUT_S = 60.0
_POLL_INTERVAL_S = 0.05


class BrowserNotFound(RuntimeError):
    """No Chromium-based browser could be located."""


class RenderError(RuntimeError):
    """The browser ran but produced no PNG, or exited non-zero."""


def window_height(height: int) -> int:
    """Raise `height` to the shortest window Chromium will lay out.

    Below `MIN_WINDOW_HEIGHT` the browser clamps the layout viewport but still
    writes a full-height PNG, so the bottom of the page is silently cut off.
    Raising the window is the only option that keeps the result deterministic and
    dependency-free; a shorter page (a small terminal card) then sits at the top
    of its own background, so the spare strip is invisible and nothing is lost.
    """
    return max(height, MIN_WINDOW_HEIGHT)


def _flags(width: int, height: int, scale: float, budget_ms: int) -> list[str]:
    """The Chromium command-line flags for one deterministic screenshot.

    `--no-first-run`/`--no-default-browser-check` matter with a `user-data-dir`
    (see `_run`): without them a brand-new profile blocks on first-run setup and
    the render never returns.
    """
    return [
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-extensions",
        f"--force-device-scale-factor={scale:g}",
        f"--virtual-time-budget={budget_ms}",
        "--window-size=" + f"{width},{window_height(height)}",
    ]


def _run(browser: str, url: str, out: Path, flags: list[str]) -> Path:
    """Invoke the browser once and assert a non-empty PNG appeared.

    The browser is **polled for a settled PNG and then terminated**, it is not
    waited on. Measured on the shipped Chrome/macOS: the screenshot is written in
    under a second, but the process does not always exit on its own (with a
    `--user-data-dir` it never does; and its crashpad child inherits the
    stdout/stderr pipe, so reading that pipe to EOF also blocks even after the
    file is on disk). Waiting on exit would hang renders, so the file is polled
    until its size is stable across several checks and the process is then
    killed.

    A throwaway `--user-data-dir` is used so a render never touches or is
    affected by the user's real browser profile; it is not required for
    correctness of a single run.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="abf-shots-") as profile:
        proc = subprocess.Popen(
            [browser, f"--user-data-dir={profile}", *flags, f"--screenshot={out}", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for_stable_file(out, proc)
        finally:
            _terminate(proc)
    if not out.exists() or out.stat().st_size == 0:
        raise RenderError(f"no screenshot at {out} (browser exit {proc.returncode})")
    return out


def _wait_for_stable_file(path: Path, proc: subprocess.Popen) -> None:
    """Block until `path` exists with a size unchanged for a few checks."""
    last = -1
    stable = 0
    deadline = time.monotonic() + _DEFAULT_TIMEOUT_S
    while time.monotonic() < deadline:
        if path.exists():
            size = path.stat().st_size
            if size > 0 and size == last:
                stable += 1
                if stable >= 3:
                    return
            else:
                stable = 0
            last = size
        elif proc.poll() is not None:
            return  # browser exited without producing a file
        time.sleep(_POLL_INTERVAL_S)
    raise RenderError(f"timed out waiting for {path}")


def _terminate(proc: subprocess.Popen) -> None:
    """Terminate a browser process, killing it if it does not stop promptly."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def render_html_file(
    html_path: str | Path,
    out_png: str | Path,
    *,
    width: int = 1000,
    height: int = 640,
    scale: float = 2.0,
    settle_ms: int = _DEFAULT_BUDGET_MS,
    browser_executable: str | None = None,
) -> Path:
    """Screenshot an existing HTML file.

    Args:
        html_path: the file to open (`file://` URL is built from it).
        out_png: the PNG to write.
        width: viewport width in CSS pixels.
        height: viewport height in CSS pixels.
        scale: device scale factor.
        settle_ms: virtual time budget in milliseconds.
        browser_executable: an explicit Chromium path.

    Returns:
        The written PNG path.

    Raises:
        BrowserNotFound: when no Chromium binary is found.
        RenderError: when the browser produced no PNG.
        FileNotFoundError: when `html_path` does not exist.
    """
    src = Path(html_path)
    if not src.exists():
        raise FileNotFoundError(f"html source not found: {src}")
    browser = find_browser_executable(browser_executable)
    if not browser:
        raise BrowserNotFound(
            "no Chromium browser found; set GUIDE_CHROME or pass a path"
        )
    return _run(
        browser,
        src.resolve().as_uri(),
        Path(out_png),
        _flags(width, height, scale, settle_ms),
    )


def render_html_string(
    html_text: str,
    out_png: str | Path,
    *,
    width: int = 1000,
    height: int = 640,
    scale: float = 2.0,
    settle_ms: int = _DEFAULT_BUDGET_MS,
    browser_executable: str | None = None,
) -> Path:
    """Write `html_text` to a temp file, screenshot it, then remove the temp.

    The temp HTML lives next to `out_png` (not in the system temp dir) so any
    relative asset the document references still resolves.

    `mkstemp` returns an open descriptor, and that descriptor is closed before
    anything else: a `with`-less usage leaks one fd per call, which a figure set
    of many terminal cards would exhaust. The file is then written by path.
    """
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{out.stem}-", suffix=".html", dir=out.parent
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(html_text, encoding="utf-8")
        return render_html_file(
            tmp,
            out,
            width=width,
            height=height,
            scale=scale,
            settle_ms=settle_ms,
            browser_executable=browser_executable,
        )
    finally:
        tmp.unlink(missing_ok=True)


__all__ = [
    "MIN_WINDOW_HEIGHT",
    "BrowserNotFound",
    "RenderError",
    "render_html_file",
    "render_html_string",
    "window_height",
]
