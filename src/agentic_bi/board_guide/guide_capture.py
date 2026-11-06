"""Optional: capture per-page screenshots of a rendered report (Playwright).

Nothing here is required for the guide: if you already have screenshots (a
Desktop capture, a CI artifact, a manual set) drop them as `page_<stem>.png` in
one directory and call `build_guide` directly. This module only automates the
"open a URL and shoot every page" step, and it is deliberately generic: the
report URL and every selector are parameters, and the browser executable is
discovered from `GUIDE_CHROME`/`PLAYWRIGHT_CHROME` or the usual per-OS locations
— no path is baked in.

Public API:
    find_browser_executable(explicit=None) -> str | None
    capture_pages(url, out_dir, geometry=None, ...) -> dict
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agentic_bi.board_guide.guide_geometry import GuideGeometry
from agentic_bi.board_guide.guide_names import (
    unique_stems,
    unique_stems_for_names,
)

logger = logging.getLogger(__name__)
# Candidate page-area selectors, tried in order. Overridable per call so a host
# that renders differently does not need a code change.
DEFAULT_AREA_SELECTORS = (".displayArea", ".visualContainerHost", "main")
# Visual container markers used only to validate that a page finished rendering
# (count > 0). The guide never reads pixels.
DEFAULT_VISUAL_SELECTOR = ".visualContainer"
_PAGE_ARIA_SKIP = "page navigation"

_VIEWPORT = {"width": 1600, "height": 1000}

_BROWSER_CANDIDATES: dict[str, tuple[str, ...]] = {
    "darwin": (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ),
    "linux": (
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
    ),
    "win32": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ),
}


def find_browser_executable(explicit: str | None = None) -> str | None:
    """Locate a Chromium-based browser, or None when none is found.

    Order: the `explicit` argument, `GUIDE_CHROME`, `PLAYWRIGHT_CHROME`, then the
    usual install locations for the current OS.

    Raises:
        ValueError: when `explicit` is given but does not exist. A user who
            names a browser must not be silently switched to another one; that
            produced a capture from a browser they did not choose.
    """
    if explicit:
        if not Path(explicit).exists():
            raise ValueError(f"browser executable not found: {explicit}")
        return explicit
    for candidate in (os.getenv("GUIDE_CHROME"), os.getenv("PLAYWRIGHT_CHROME")):
        if candidate and Path(candidate).exists():
            return candidate
    for candidate in _BROWSER_CANDIDATES.get(sys.platform, ()):
        if Path(candidate).exists():
            return candidate
    return None


def _js_string(value: str) -> str:
    """A JS single-quoted string literal for `value`, safely escaped.

    Selectors are parameters, but a selector may contain a quote or a backslash;
    interpolating it raw produced broken JS. `json.dumps` escapes backslashes,
    control characters and double quotes; the lone `'` (and the JS line
    terminators) are escaped here for the single-quoted context.
    """
    text = json.dumps(str(value), ensure_ascii=False)[1:-1]
    for char, escaped in (("'", "\\'"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        text = text.replace(char, escaped)
    return "'" + text + "'"


def _page_area_js(selectors: Sequence[str]) -> str:
    """JS returning the first matching area's bounding box (viewport px)."""
    encoded = ", ".join(_js_string(s) for s in selectors)
    return (
        "() => {"
        f" const cands = [{encoded}];"
        " for (const c of cands) { const e = document.querySelector(c);"
        " if (e) { const r = e.getBoundingClientRect();"
        " if (r.width > 2 && r.height > 2)"
        " return {x:r.x, y:r.y, w:r.width, h:r.height}; } }"
        " return null; }"
    )


def _visual_rects_js(selector: str) -> str:
    """JS returning the boxes of rendered visuals (used as a render gate)."""
    return (
        "() => {"
        f" const vcs = [...document.querySelectorAll({_js_string(selector)})];"
        " const out = [];"
        " for (const vc of vcs) {"
        f" const aria = vc.getAttribute('aria-label') || '';"
        f" if (/{_PAGE_ARIA_SKIP}/i.test(aria)) continue;"
        " const r = vc.getBoundingClientRect();"
        " if (r.width < 2 || r.height < 2) continue;"
        " out.push({x:r.x, y:r.y, w:r.width, h:r.height, aria}); }"
        " return out; }"
    )


def _report_frame(page):
    """The first child frame that looks like the embedded report, else None."""
    frames = list(page.frames)
    return frames[-1] if len(frames) > 1 else None


def capture_pages(
    url: str,
    out_dir: str | Path,
    geometry: GuideGeometry | None = None,
    *,
    browser_executable: str | None = None,
    area_selectors: Sequence[str] = DEFAULT_AREA_SELECTORS,
    visual_selector: str = DEFAULT_VISUAL_SELECTOR,
    page_names: Sequence[str] | None = None,
    tab_wait_ms: int = 4500,
    settle_ms: int = 12000,
    attempts: int = 4,
    max_pages: int | None = None,
    headless: bool = True,
    ignore_https_errors: bool = True,
) -> dict[str, Any]:
    """Screenshot every page of a rendered report.

    Args:
        url: the report URL to open.
        out_dir: the directory the PNGs are written to (`page_<stem>.png`).
        geometry: when given, the page names/stems come from it (so the file
            names line up with `build_guide`); otherwise the on-page tabs are
            used.
        browser_executable: an explicit Chromium binary (see
            `find_browser_executable`).
        area_selectors: candidate selectors for the report page area, tried in
            order; the clip is taken exactly over the match.
        visual_selector: the marker used to detect that a page finished
            rendering (at least one box must appear).
        page_names: restrict to pages whose title contains one of these strings.
        tab_wait_ms: pause after switching a tab.
        settle_ms: pause after load before interacting.
        attempts: retries per page when the area or the visuals are not ready.
        max_pages: cap the number of captured pages.
        headless: run the browser headless.
        ignore_https_errors: accept a self-signed certificate.

    Returns:
        `{"out_dir", "pages": [{"name", "png", "area", "n"}]}`.

    Raises:
        ValueError: when Playwright is missing, the Chromium binary cannot be
            launched (including a missing explicit `--browser` path), or the
            report frame cannot be located. All are user-facing configuration or
            page problems, so the CLI boundary reports them as a bad input
            (exit 2) instead of a traceback (`cli_support`).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ValueError(
            "capture requires Playwright: pip install 'agentic-bi-framework[guide]'"
        ) from exc

    executable = find_browser_executable(browser_executable)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"out_dir": str(out), "pages": []}

    with sync_playwright() as p:
        launch: dict[str, Any] = {"headless": headless}
        if executable:
            launch["executable_path"] = executable
        if ignore_https_errors:
            launch["args"] = ["--ignore-certificate-errors"]
        try:
            browser = p.chromium.launch(**launch)
        except Exception as exc:
            raise ValueError(
                "capture requires a Chromium binary: install Chromium/Chrome, set "
                "GUIDE_CHROME, or pass --browser PATH"
            ) from exc
        ctx = browser.new_context(
            ignore_https_errors=ignore_https_errors, viewport=_VIEWPORT
        )
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="load", timeout=60000)
            pg.wait_for_selector("iframe", timeout=30000)
            pg.wait_for_timeout(settle_ms)

            frame = _report_frame(pg)
            if frame is None:
                raise ValueError(f"report frame not found on {url}")

            iframe_box = pg.evaluate(
                "() => { const ifs=[...document.querySelectorAll('iframe')];"
                " const f = ifs[ifs.length-1]; if (!f) return {x:0,y:0};"
                " const r = f.getBoundingClientRect(); return {x:r.x, y:r.y}; }"
            )

            wanted = [n.strip().lower() for n in (page_names or []) if n.strip()]
            if geometry is not None:
                # Stems come from the *full* page list, exactly as `build_guide`
                # numbers them, so `page_<stem>.png` and `guide_<stem>.html`
                # always agree even when only some pages are captured.
                pairs = list(
                    zip(
                        [p.name for p in geometry.pages],
                        unique_stems(geometry.pages),
                        strict=True,
                    )
                )
            else:
                tabs = [
                    t.strip()
                    for t in frame.locator("[role=tab], .tab").all_inner_texts()
                    if t.strip()
                ]
                pairs = list(zip(tabs, unique_stems_for_names(tabs), strict=True))
            if wanted:
                pairs = [p for p in pairs if any(w in p[0].lower() for w in wanted)]
            if max_pages:
                pairs = pairs[:max_pages]

            for name, stem in pairs:
                area = boxes = None
                for _ in range(max(1, attempts)):
                    try:
                        frame.get_by_text(name, exact=False).first.evaluate(
                            "el => { el.click(); }"
                        )
                    except Exception:  # noqa: BLE001 - tab not addressable yet
                        pg.wait_for_timeout(2000)
                        continue
                    pg.wait_for_timeout(tab_wait_ms)
                    area = frame.evaluate(_page_area_js(area_selectors))
                    boxes = frame.evaluate(_visual_rects_js(visual_selector))
                    if area and boxes:
                        break
                    pg.wait_for_timeout(1500)
                if not area or not boxes:
                    logger.warning("page '%s': not rendered after retries", name)
                    continue
                clip = {
                    "x": iframe_box.get("x", 0) + area["x"],
                    "y": iframe_box.get("y", 0) + area["y"],
                    "width": area["w"],
                    "height": area["h"],
                }
                fpath = out / f"page_{stem}.png"
                pg.screenshot(path=str(fpath), clip=clip)
                result["pages"].append(
                    {
                        "name": name,
                        "stem": stem,
                        "png": str(fpath),
                        "area": {k: round(float(v), 1) for k, v in area.items()},
                        "n": len(boxes),
                    }
                )
                logger.info("page '%s' -> %s (n=%d)", name, fpath.name, len(boxes))
        finally:
            browser.close()
    return result


__all__ = [
    "DEFAULT_AREA_SELECTORS",
    "DEFAULT_VISUAL_SELECTOR",
    "capture_pages",
    "find_browser_executable",
]
