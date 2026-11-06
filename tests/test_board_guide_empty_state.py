"""Empty and partial input for the guide: explicit states, never blank output.

A page with no visuals, a page whose visuals are all off-canvas, a missing or
zero-byte screenshot and a report with no usable page at all must each say what
happened. Before this, the guide wrote an image with no hotspots or an index
with an empty list, which reads like a broken render rather than missing input.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_board_guide_png import MINIMAL_PNG, png_bytes

from agentic_bi.board_guide import (
    GuideGeometry,
    GuidePage,
    GuideVisual,
    build_guide,
    render_page_html,
)
from agentic_bi.board_guide.guide_render import render_index_html


def test_page_without_visuals_renders_an_explicit_empty_state() -> None:
    html = render_page_html(GuidePage(name="Empty"), "page_Empty.png")
    assert "нет визуалов" in html
    assert "визуалов 0" in html
    assert 'data-i="' not in html


def test_page_whose_visuals_are_all_off_canvas_says_so() -> None:
    page = GuidePage(name="P", width=100, height=100)
    page.visuals.append(GuideVisual(visual_type="x", x=500, y=500, width=10, height=10))
    html = render_page_html(page, "p.png")
    assert "не попадает в границы канваса" in html
    assert 'data-i="' not in html


def test_missing_image_is_an_empty_state_not_a_broken_img_tag() -> None:
    """`<img src="">` renders as a broken icon; say it is missing instead."""
    html = render_page_html(GuidePage(name="P"), "")
    assert "<img" not in html
    assert "Изображение страницы не найдено" in html


def test_index_without_usable_pages_explains_what_to_put_where() -> None:
    html = render_index_html(
        [],
        "board.pbix",
        skipped=[("Overview", "нет файла page_Overview.png")],
    )
    assert "нет ни одного листа с изображением" in html
    assert "page_&lt;stem&gt;.png" in html
    assert "Пропущено листов: 1" in html
    assert "нет файла page_Overview.png" in html


def test_index_reports_skipped_pages_next_to_generated_ones() -> None:
    html = render_index_html(
        [("Overview", "guide_Overview.html", 3)],
        "board.pbix",
        skipped=[("Sales", "пустой файл page_Sales.png (0 байт)")],
    )
    assert "guide_Overview.html" in html
    assert "Пропущено листов: 1" in html
    assert "пустой файл page_Sales.png" in html


def test_build_guide_skips_a_zero_byte_screenshot_and_reports_it(
    tmp_path: Path,
) -> None:
    """An empty PNG is a broken picture: skip the page and name the file."""
    geometry = GuideGeometry(
        source="b.pbix", pages=[GuidePage(name="Overview"), GuidePage(name="Sales")]
    )
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "page_Overview.png").write_bytes(MINIMAL_PNG)
    (shots / "page_Sales.png").write_bytes(b"")
    reported: list[tuple[str, str]] = []
    saved = build_guide(
        geometry,
        tmp_path / "out",
        screenshots=shots,
        on_skip=lambda name, reason: reported.append((name, reason)),
    )
    assert [p.name for p in saved] == ["guide_Overview.html", "index.html"]
    assert reported == [("Sales", "пустой файл page_Sales.png (0 байт)")]
    index = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "пустой файл page_Sales.png" in index


def test_build_guide_skips_a_truncated_png_signature(tmp_path: Path) -> None:
    """Eight magic bytes are not a screenshot: no broken `<img>`, a reason."""
    geometry = GuideGeometry(source="b.pbix", pages=[GuidePage(name="Bad")])
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "page_Bad.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    reported: list[tuple[str, str]] = []
    saved = build_guide(
        geometry,
        tmp_path / "out",
        screenshots=shots,
        on_skip=lambda name, reason: reported.append((name, reason)),
    )
    assert [p.name for p in saved] == ["index.html"]
    assert reported == [("Bad", "файл page_Bad.png не PNG (нет сигнатуры/IHDR)")]


def test_build_guide_skips_a_non_png_file_named_png(tmp_path: Path) -> None:
    geometry = GuideGeometry(source="b.pbix", pages=[GuidePage(name="Bad")])
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "page_Bad.png").write_text("<html>error</html>", encoding="utf-8")
    reported: list[tuple[str, str]] = []
    saved = build_guide(
        geometry,
        tmp_path / "out",
        screenshots=shots,
        on_skip=lambda name, reason: reported.append((name, reason)),
    )
    assert [p.name for p in saved] == ["index.html"]
    assert reported == [("Bad", "файл page_Bad.png не PNG (нет сигнатуры/IHDR)")]
    index = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "не PNG" in index


def test_build_guide_warns_when_the_image_aspect_differs_from_the_canvas(
    tmp_path: Path,
) -> None:
    """A 1280x800 image on a 1280x720 canvas puts `top:50%` at y=400, not 360."""
    geometry = GuideGeometry(source="b.pbix", pages=[GuidePage(name="Wide")])
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "page_Wide.png").write_bytes(png_bytes(1280, 800))
    saved = build_guide(geometry, tmp_path / "out", screenshots=shots)
    assert [p.name for p in saved] == ["guide_Wide.html", "index.html"]
    index = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "Предупреждения: 1" in index
    assert "1280×800" in index
    assert "hotspots сместятся" in index


def test_build_guide_accepts_a_matching_aspect_without_a_warning(
    tmp_path: Path,
) -> None:
    geometry = GuideGeometry(source="b.pbix", pages=[GuidePage(name="Board")])
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "page_Board.png").write_bytes(png_bytes(1280, 720))
    build_guide(geometry, tmp_path / "out", screenshots=shots)
    index = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "Предупреждения" not in index


def test_build_guide_warns_when_the_capture_area_aspect_differs(
    tmp_path: Path,
) -> None:
    """The rendered `area` must match the canvas too, not only the PNG."""
    geometry = GuideGeometry(source="b.pbix", pages=[GuidePage(name="Board")])
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "page_Board.png").write_bytes(png_bytes(1280, 720))
    build_guide(
        geometry,
        tmp_path / "out",
        screenshots=shots,
        capture_areas={"Board": (1400.0, 720.0)},
    )
    index = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "область захвата 1400×720" in index
