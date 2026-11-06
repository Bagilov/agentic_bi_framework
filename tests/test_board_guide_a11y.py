"""Accessibility and visible bookkeeping for guide hotspots.

A board guide is mostly a picture with numbered boxes; if those boxes are
mouse-only, or if off-canvas visuals disappear without a word, the guide is not
usable by keyboard and silently incomplete. These tests pin the ARIA contract,
the keyboard path and the dropped-visual counter.
"""

from __future__ import annotations

from agentic_bi.board_guide import GuidePage, GuideVisual, render_page_html
from agentic_bi.board_guide.guide_assets import PAGE_JS


def _page(*visuals: GuideVisual) -> GuidePage:
    page = GuidePage(name="P", width=1000, height=1000)
    page.visuals.extend(visuals)
    return page


def test_hotspots_are_keyboard_reachable_buttons() -> None:
    page = _page(
        GuideVisual(visual_type="card", title="KPI", x=0, y=0, width=400, height=300)
    )
    html = render_page_html(page, "p.png")
    assert 'role="button"' in html
    assert 'tabindex="0"' in html
    assert 'aria-label="#1 KPI"' in html


def test_accessible_name_escapes_quotes_and_markup() -> None:
    page = _page(
        GuideVisual(
            visual_type="card",
            title='A "quote" <tag>',
            x=0,
            y=0,
            width=400,
            height=300,
        )
    )
    html = render_page_html(page, "p.png")
    assert 'aria-label="#1 A &quot;quote&quot; &lt;tag&gt;"' in html


def test_keyboard_enter_and_space_activate_the_panel() -> None:
    assert "keydown" in PAGE_JS
    assert "event.key === 'Enter'" in PAGE_JS
    assert "event.key === ' '" in PAGE_JS
    assert "addEventListener('focus'" in PAGE_JS


def test_panel_announces_changes_to_screen_readers() -> None:
    html = render_page_html(GuidePage(name="P"), "p.png")
    assert 'id="panel" aria-live="polite"' in html


def test_a_broken_image_hides_the_hotspots_instead_of_leaving_bars() -> None:
    assert "addEventListener('error'" in PAGE_JS
    assert "hotspots скрыты" in PAGE_JS


def test_header_counts_visuals_outside_the_canvas() -> None:
    page = _page(
        GuideVisual(visual_type="card", x=0, y=0, width=100, height=100),
        GuideVisual(visual_type="card", x=200, y=0, width=100, height=100),
        GuideVisual(visual_type="card", x=5000, y=5000, width=10, height=10),
    )
    html = render_page_html(page, "p.png")
    assert "визуалов 3 · вне канваса 1" in html


def test_header_has_no_counter_when_every_visual_fits() -> None:
    page = _page(GuideVisual(visual_type="card", x=0, y=0, width=100, height=100))
    html = render_page_html(page, "p.png")
    assert "вне канваса" not in html
