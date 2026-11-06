"""The generated guide must survive narrow screens and a printer.

Real geometry (a letterboxed image, a panel over a hotspot) is measured in
`test_board_guide_layout_browser.py`; the checks here are the deterministic
static contract: the print block must not cap the image height, a wide screen
must reserve the panel column, and paper must carry the visual legend because a
hover label is invisible there.
"""

from __future__ import annotations

from agentic_bi.board_guide import GuidePage, GuideVisual, render_page_html
from agentic_bi.board_guide.guide_assets import PAGE_CSS
from agentic_bi.board_guide.guide_render import render_index_html


def _print_block() -> str:
    return PAGE_CSS.split("@media print {", 1)[1]


def test_print_does_not_cap_the_image_height() -> None:
    """A height cap activates `object-fit: contain` and shifts every hotspot."""
    block = _print_block()
    assert ".imgwrap img" not in block
    assert "100vh" not in block


def test_wide_screen_reserves_the_panel_column() -> None:
    assert "@media (min-width: 1101px)" in PAGE_CSS
    wide = PAGE_CSS.split("@media (min-width: 1101px)", 1)[1].split("}", 1)[0]
    assert "padding-right: 400px" in wide


def test_narrow_screen_stacks_the_panel_below_the_image() -> None:
    assert "@media (max-width: 1100px)" in PAGE_CSS
    assert "position: static" in PAGE_CSS


def test_print_has_no_shadows_or_dark_backgrounds() -> None:
    assert "@page" in PAGE_CSS
    assert "box-shadow: none" in _print_block()


def test_print_does_not_split_the_page_image() -> None:
    assert "break-inside: avoid" in PAGE_CSS
    assert "page-break-inside: avoid" in PAGE_CSS


def test_print_hides_hover_labels() -> None:
    """A hover label is invisible on paper; it must not print over the image."""
    assert ".hotlabel { display: none !important; }" in PAGE_CSS


def test_print_hides_the_hover_hint_and_shows_the_legend() -> None:
    assert ".panel .hint { display: none; }" in _print_block()
    assert ".printlist { display: block; margin: 10px 0 0; }" in _print_block()
    assert ".printlist { display: none; font-size: 12px; }" in PAGE_CSS


def test_printed_legend_lists_every_visible_visual() -> None:
    """The numbers on paper need a type/fields/measures key next to them."""
    page = GuidePage(name="P", width=1000, height=1000)
    page.visuals.append(
        GuideVisual(
            visual_type="clusteredBarChart",
            title="Sales",
            x=0,
            y=0,
            width=400,
            height=300,
            fields=["Sales.region"],
            measures=["Total Amount"],
            filters=["Sales[year]: year = 2026"],
        )
    )
    page.visuals.append(
        GuideVisual(visual_type="offcanvas", x=5000, y=5000, width=10, height=10)
    )
    html = render_page_html(page, "p.png")
    legend = html.split('<section class="printlist">', 1)[1]
    assert "#1 clusteredBarChart" in legend
    assert "поля: Sales.region" in legend
    assert "меры: Total Amount" in legend
    assert "фильтры: Sales[year]: year = 2026" in legend
    assert "#2" not in legend.split("</section>", 1)[0]


def test_rendered_page_embeds_the_adaptive_stylesheet() -> None:
    html = render_page_html(GuidePage(name="P"), "p.png")
    assert "@media print" in html
    assert "@media (max-width: 1100px)" in html
    assert 'name="viewport"' in html


def test_index_declares_a_viewport_and_an_empty_state_style() -> None:
    html = render_index_html([], "board.pbix")
    assert 'name="viewport"' in html
    assert 'class="empty"' in html
    assert ".empty" in html
