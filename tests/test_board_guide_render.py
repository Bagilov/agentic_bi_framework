"""Render + CLI tests for the annotated board guide (`board_guide`).

The guide renders a screenshot with hotspot overlays. No real capture happens:
the tests supply a placeholder image file (or a URL prefix) and assert the
geometry-driven overlay, the injected help data and the CLI behaviour.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from agentic_bi.board_guide import (
    GuideGeometry,
    GuidePage,
    GuideVisual,
    build_guide,
    render_page_html,
)
from agentic_bi.board_guide.guide_assets import PAGE_JS


def _write_pbix(path: Path, layout: dict) -> Path:
    payload = json.dumps(layout, ensure_ascii=False).encode("utf-16-le")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Report/Layout", payload)
    return path


def _geometry() -> GuideGeometry:
    page = GuidePage(name="Overview", width=1300, height=1050)
    page.visuals.append(
        GuideVisual(
            visual_type="card",
            title="Total",
            x=130,
            y=105,
            width=260,
            height=210,
            measures=["Total Amount"],
            dax={"Total Amount": "Sales :: SUM(Sales[amount])"},
        )
    )
    page.visuals.append(
        GuideVisual(visual_type="shape", title="", x=0, y=0, width=65, height=52)
    )
    return GuideGeometry(source="board.pbix", pages=[page])


def test_render_page_html_places_hotspots_as_percentages() -> None:
    html = render_page_html(_geometry().pages[0], "page_Overview.png")
    assert 'class="imgwrap"' in html
    assert 'src="page_Overview.png"' in html
    # 130/1300 = 10%, 105/1050 = 10%, 260/1300 = 20%
    assert "left:10.00%;top:10.00%;width:20.00%;height:20.00%" in html
    # the static visual still gets a hotspot (its geometry is real)
    assert html.count('class="hot"') == 2


def test_render_page_html_escapes_and_injects_help() -> None:
    page = GuidePage(name="P<1>", width=100, height=100)
    page.visuals.append(
        GuideVisual(
            visual_type="card",
            title="<script>alert(1)</script>",
            x=0,
            y=0,
            width=10,
            height=10,
            measures=["M"],
        )
    )
    html = render_page_html(page, "a.png")
    assert "<script>alert(1)</script>" not in html
    # the injected payload keeps the document valid: script-closing chars escaped
    assert "\\u003c" in html
    payload = html.split("window.__GUIDE_REFS__ = ", 1)[1].split(";</script>", 1)[0]
    refs = json.loads(payload)
    assert len(refs) == 1
    assert "alert" in refs[0]


def test_render_page_html_marks_static_visual() -> None:
    html = render_page_html(_geometry().pages[0], "a.png")
    assert "статический элемент" in html
    assert "DAX (1)" in html
    assert PAGE_JS.splitlines()[0] in html


def test_build_guide_skips_pages_without_a_screenshot(tmp_path: Path) -> None:
    geometry = _geometry()
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "page_Overview.png").write_bytes(b"\x89PNG\r\n")
    saved = build_guide(geometry, tmp_path / "out", screenshots=shots)
    names = {p.name for p in saved}
    assert names == {"guide_Overview.html", "index.html"}
    body = (tmp_path / "out" / "guide_Overview.html").read_text(encoding="utf-8")
    assert str(shots / "page_Overview.png") in body


def test_build_guide_without_screenshots_writes_only_index(tmp_path: Path) -> None:
    saved = build_guide(_geometry(), tmp_path / "out")
    assert [p.name for p in saved] == ["index.html"]


def test_build_guide_src_prefix_emits_every_page(tmp_path: Path) -> None:
    saved = build_guide(
        _geometry(),
        tmp_path / "out",
        src_prefix="https://example.test/media",
    )
    assert [p.name for p in saved] == ["guide_Overview.html", "index.html"]
    body = (tmp_path / "out" / "guide_Overview.html").read_text(encoding="utf-8")
    assert "https://example.test/media/page_Overview.png" in body


def test_build_guide_unique_names_for_colliding_page_names(tmp_path: Path) -> None:
    """Two Cyrillic pages must not overwrite one `guide_page.html`.

    Before the fix, `safe_name` mapped both to `page`, so the guide wrote only
    one page file and the index linked both entries to it.
    """
    geometry = GuideGeometry(
        source="b.pbix",
        pages=[
            GuidePage(name="Прибыль по регионам"),
            GuidePage(name="Продажи по месяцам"),
        ],
    )
    saved = build_guide(geometry, tmp_path / "out", src_prefix="https://x.test/m")
    names = [p.name for p in saved]
    assert len(names) == 3
    assert len(set(names)) == 3
    index = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert index.count("guide_") == 2


def test_build_guide_every_page_gets_its_own_file(tmp_path: Path) -> None:
    """A page named like the disambiguation suffix must not share a file.

    `A_B`, `A_B` and `A_B-2` previously produced only two files (the third page
    overwrote the second) while reporting three written pages.
    """
    geometry = GuideGeometry(
        source="b.pbix",
        pages=[
            GuidePage(name="A_B"),
            GuidePage(name="A_B"),
            GuidePage(name="A_B-2"),
        ],
    )
    out = tmp_path / "out"
    saved = build_guide(geometry, out, src_prefix="https://x.test/m")
    page_files = [p for p in saved if p.name != "index.html"]
    on_disk = sorted(p.name for p in out.glob("guide_*.html"))
    assert len(page_files) == 3
    assert len(on_disk) == 3
    index = (out / "index.html").read_text(encoding="utf-8")
    assert index.count("guide_") == 3


def test_build_guide_case_only_names_do_not_overwrite(tmp_path: Path) -> None:
    """`Sales`/`sales` must survive on a case-insensitive filesystem (macOS)."""
    geometry = GuideGeometry(
        source="b.pbix",
        pages=[GuidePage(name="Sales"), GuidePage(name="sales")],
    )
    out = tmp_path / "out"
    saved = build_guide(geometry, out, src_prefix="https://x.test/m")
    page_files = [p for p in saved if p.name != "index.html"]
    on_disk = sorted(p.name for p in out.glob("guide_*.html"))
    assert len(page_files) == 2
    assert len(on_disk) == 2


def test_build_guide_long_page_name_does_not_abort(tmp_path: Path) -> None:
    """A very long page name must not fail the run and drop later pages."""
    geometry = GuideGeometry(
        source="b.pbix",
        pages=[GuidePage(name="First"), GuidePage(name="Z" * 300)],
    )
    out = tmp_path / "out"
    saved = build_guide(geometry, out, src_prefix="https://x.test/m")
    assert [p.name for p in saved][-1] == "index.html"
    assert len([p for p in saved if p.name != "index.html"]) == 2
    assert len(list(out.glob("guide_*.html"))) == 2


def test_render_page_html_escapes_js_line_separator() -> None:
    """U+2028/U+2029 are valid JSON but break a `<script>` payload if left raw."""
    page = GuidePage(name="P", width=100, height=100)
    page.visuals.append(
        GuideVisual(
            visual_type="card",
            title="line\u2028sep\u2029end",
            x=0,
            y=0,
            width=10,
            height=10,
            measures=["M"],
        )
    )
    html = render_page_html(page, "a.png")
    payload = html.split("window.__GUIDE_REFS__ = ", 1)[1].split(";</script>", 1)[0]
    # The script payload must not contain a raw JS line terminator...
    assert "\u2028" not in payload
    assert "\u2029" not in payload
    # ...but the decoded value keeps the real characters.
    ref = json.loads(payload)[0]
    assert "line\u2028sep\u2029end" in ref


def test_render_page_html_clamps_offscreen_hotspots() -> None:
    """Hotspot percentages stay in `[0, 100]`; no `nan` leaks into the CSS."""
    page = GuidePage(name="P", width=100, height=100)
    page.visuals.append(
        GuideVisual(visual_type="x", title="", x=-50, y=-60, width=10, height=10)
    )
    page.visuals.append(
        GuideVisual(visual_type="y", title="", x=5000, y=5000, width=10, height=10)
    )
    html = render_page_html(page, "a.png")
    assert "left:0.00%;top:0.00%;width:10.00%;height:10.00%" in html
    assert "left:100.00%;top:100.00%;width:0.00%;height:0.00%" in html
    assert "nan" not in html.lower()


def test_render_page_html_guards_non_finite_canvas() -> None:
    """A `nan`/`inf` canvas must show the default, not `канвас nan×nan`."""
    page = GuidePage(name="P", width=float("nan"), height=float("inf"))
    html = render_page_html(page, "a.png")
    assert "nan" not in html.lower()
    assert "inf" not in html.lower()
