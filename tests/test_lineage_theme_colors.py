"""Theme-only colours must not be reported as "verified clean".

`_collect_colors` emits `theme#<ColorId>` for a `ThemeDataColor`, and the theme is
not in the lineage JSON, so `_hex_from` cannot resolve those ids. They were
dropped silently: a page whose only colours were theme tokens reported
`colors.total = 0`, `compliance = None` and — with a compliant font — `level=ok`
for data that were never read.
"""

from __future__ import annotations

from agentic_bi.lineage.lineage_brand_metrics import (
    brand_label,
    page_brand_metrics,
    visual_brand_metrics,
)


def test_a_theme_only_page_is_not_rated_ok() -> None:
    metrics = page_brand_metrics({"colors": ["theme#0", "theme#1"], "fonts": ["Arial"]})
    assert metrics["colors"]["total"] == 0
    assert metrics["colors"]["unresolved"] == 2
    assert metrics["level"] == "unknown"


def test_a_resolved_palette_is_still_evaluated() -> None:
    metrics = page_brand_metrics(
        {"colors": ["hex#D32F2F", "hex#FFFFFF"], "fonts": ["Arial"]}
    )
    assert metrics["colors"]["total"] >= 1
    assert metrics["colors"]["unresolved"] == 0
    assert metrics["level"] in ("ok", "warning")


def test_a_theme_only_visual_is_not_rated_ok() -> None:
    metrics = visual_brand_metrics({"colors": ["theme#3"], "fonts": ["Arial"]})
    assert metrics["colors"]["unresolved"] == 1
    assert metrics["level"] == "unknown"


def test_a_page_with_no_colour_data_at_all_stays_unknown() -> None:
    metrics = page_brand_metrics({"colors": [], "fonts": ["Arial"]})
    assert metrics["colors"]["unresolved"] == 0
    assert metrics["level"] == "ok", "fonts alone are still a measurable result"


def test_the_label_says_not_available_instead_of_none_percent() -> None:
    label = brand_label(
        {
            "fonts": {"compliance": None},
            "colors": {"compliance": None, "unresolved": 2},
        }
    )
    assert "None%" not in label
    assert "fonts n/a" in label
    assert "theme colours unresolved: 2" in label
