"""Browser-measured layout checks for the board guide (headless Chromium).

CSS-substring assertions cannot catch a letterboxed screenshot or a fixed panel
sitting on top of a hotspot: both are layout facts. These tests render a real
guide page, load it in headless Chrome and measure the drawn image, each hotspot
and the panel with `getBoundingClientRect`/`elementFromPoint`. The checks are
skipped when no Chromium binary is installed, since the geometry itself is a
browser result.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

import pytest
from tests.test_board_guide_png import png_bytes

from agentic_bi.board_guide import GuidePage, GuideVisual, render_page_html
from agentic_bi.board_guide.guide_capture import find_browser_executable

_CHROME = find_browser_executable()

pytestmark = pytest.mark.skipif(
    _CHROME is None, reason="no headless Chromium binary on this machine"
)

_MEASURE_JS = """
window.addEventListener('load', () => {
  const rect = el => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return [r.x, r.y, r.width, r.height];
  };
  const result = {
    wrap: rect(document.querySelector('.imgwrap')),
    panel: rect(document.querySelector('.panel')),
    img: null,
    drawn: null,
    hots: []
  };
  const img = document.querySelector('.imgwrap img');
  if (img) {
    const r = img.getBoundingClientRect();
    result.img = [r.x, r.y, r.width, r.height, img.naturalWidth, img.naturalHeight];
    const nw = img.naturalWidth, nh = img.naturalHeight;
    if (nw && nh) {
      const scale = Math.min(r.width / nw, r.height / nh);
      result.drawn = [r.x + (r.width - nw * scale) / 2,
                      r.y + (r.height - nh * scale) / 2,
                      nw * scale, nh * scale];
    }
  }
  document.querySelectorAll('.hot').forEach(h => {
    const r = h.getBoundingClientRect();
    let dead = 0;
    for (let gx = 1; gx < 10; gx++) {
      for (let gy = 1; gy < 10; gy++) {
        const x = r.x + r.width * gx / 10;
        const y = r.y + r.height * gy / 10;
        if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) continue;
        const el = document.elementFromPoint(x, y);
        if (el && el.closest('.panel')) dead++;
      }
    }
    result.hots.push({i: Number(h.dataset.i), box: rect(h), dead: dead});
  });
  document.title = 'RES:' + btoa(JSON.stringify(result));
});
"""


def _with_measure_script(html: str) -> str:
    return html.replace("</body>", f"<script>{_MEASURE_JS}</script></body>")


def _measure(html: str, width: int, height: int, work: Path) -> dict:
    """Load `html` in headless Chrome and return the measured layout."""
    page = work / f"guide_{width}_{height}_{abs(hash(html)) % 100000}.html"
    page.write_text(_with_measure_script(html), encoding="utf-8")
    command = [
        str(_CHROME),
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--force-device-scale-factor=1",
        f"--window-size={width},{height}",
        "--virtual-time-budget=4000",
        "--dump-dom",
        page.as_uri(),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
    match = re.search(r"RES:([A-Za-z0-9+/=]+)", proc.stdout)
    assert match, proc.stderr[-2000:]
    return json.loads(base64.b64decode(match.group(1)))


def _guide_page() -> GuidePage:
    page = GuidePage(name="Tall", width=1280, height=720)
    page.visuals.append(
        GuideVisual(visual_type="card", title="full", x=0, y=0, width=1280, height=720)
    )
    return page


def _panel_page() -> GuidePage:
    page = GuidePage(name="Board", width=1300, height=1050)
    page.visuals.append(
        GuideVisual(
            visual_type="card", title="right", x=900, y=0, width=400, height=120
        )
    )
    return page


def _print_html(html: str) -> str:
    """Immitate the print stylesheet in a screen viewport (`@media print` -> all)."""
    return html.replace("@media print {", "@media all {")


def test_print_does_not_letterbox_a_tall_screenshot(tmp_path: Path) -> None:
    """720x1600 on A4: the image is scaled by width, hotspots stay on it."""
    (tmp_path / "shot.png").write_bytes(png_bytes(720, 1600))
    html = _print_html(render_page_html(_guide_page(), "shot.png"))
    data = _measure(html, 1440, 1000, tmp_path)
    assert data["img"] is not None and data["drawn"] is not None
    assert data["img"][4:] == [720, 1600]
    drawn = data["drawn"]
    image = data["img"][:4]
    assert abs(image[2] - drawn[2]) <= 1, (image, drawn)
    assert abs(image[3] - drawn[3]) <= 1, (image, drawn)
    hotspot = data["hots"][0]["box"]
    assert abs(hotspot[0] - drawn[0]) <= 1, (hotspot, drawn)
    assert abs(hotspot[2] - drawn[2]) <= 1, (hotspot, drawn)


@pytest.mark.parametrize("width", [1440, 1180, 900])
def test_screen_keeps_hotspots_on_the_drawn_image(tmp_path: Path, width: int) -> None:
    (tmp_path / "shot.png").write_bytes(png_bytes(720, 1600))
    html = render_page_html(_guide_page(), "shot.png")
    data = _measure(html, width, 1000, tmp_path)
    drawn = data["drawn"]
    hotspot = data["hots"][0]["box"]
    assert abs(hotspot[0] - drawn[0]) <= 1, (hotspot, drawn)
    assert abs(hotspot[2] - drawn[2]) <= 1, (hotspot, drawn)


@pytest.mark.parametrize("width", [1440, 1200, 905])
def test_fixed_panel_never_covers_a_hotspot(tmp_path: Path, width: int) -> None:
    """No point inside a hotspot may resolve to the panel at 1440/1200/905."""
    (tmp_path / "shot.png").write_bytes(png_bytes(1300, 1050))
    html = render_page_html(_panel_page(), "shot.png")
    data = _measure(html, width, 900, tmp_path)
    dead = {hot["i"]: hot["dead"] for hot in data["hots"]}
    assert sum(dead.values()) == 0, (width, dead, data["panel"])
