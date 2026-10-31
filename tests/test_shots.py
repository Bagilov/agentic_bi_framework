"""Tests for the screenshot pipeline (`shots`), pure parts.

Plan validation, terminal wrapping, manifest hashing and the build's failure
reporting need no browser and always run. Anything that renders a real PNG lives
in `tests/test_shots_render.py`, which skips without Chromium, so this module
stays green on a machine that has none.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.shots import (
    BrowserNotFound,
    FigureSpec,
    ShotPlan,
    build_shots,
    build_terminal_html,
    render_html_file,
)
from agentic_bi.shots.shots_render import MIN_WINDOW_HEIGHT, window_height
from agentic_bi.shots.shots_terminal import (
    MAX_COLUMNS,
    card_size,
    highlight_markers,
    wrap,
)

# --------------------------------------------------------------------------- plan


def test_figure_spec_requires_name_kind_source() -> None:
    with pytest.raises(ValueError, match="'name' is required"):
        FigureSpec.from_dict({"kind": "html", "source": "a.html"})
    with pytest.raises(ValueError, match="'source' is required"):
        FigureSpec.from_dict({"name": "x", "kind": "html"})


def test_figure_spec_rejects_unknown_kind_and_keys() -> None:
    with pytest.raises(ValueError, match="kind must be one of"):
        FigureSpec.from_dict({"name": "x", "source": "a", "kind": "pdf"})
    with pytest.raises(ValueError, match="unknown key"):
        FigureSpec.from_dict({"name": "x", "source": "a", "colour": "red"})


def test_figure_out_must_be_a_bare_file_name() -> None:
    """A plan is data: `out` must not escape the output directory."""
    with pytest.raises(ValueError, match="bare file name"):
        FigureSpec.from_dict({"name": "x", "source": "a", "out": "../escape.png"})
    with pytest.raises(ValueError, match="bare file name"):
        FigureSpec.from_dict({"name": "x", "source": "a", "out": "/etc/x.png"})
    with pytest.raises(ValueError, match="bare file name"):
        FigureSpec.from_dict({"name": "x", "source": "a", "out": "sub/x.png"})
    # a plain name is fine
    assert FigureSpec.from_dict({"name": "x", "source": "a", "out": "x.png"}).out


def test_figure_name_must_be_a_bare_identifier() -> None:
    with pytest.raises(ValueError, match="bare identifier"):
        FigureSpec.from_dict({"name": "../x", "source": "a"})
    with pytest.raises(ValueError, match="bare identifier"):
        FigureSpec.from_dict({"name": "sub/x", "source": "a"})


def test_figure_spec_defaults_kind_to_html_and_validates_numbers() -> None:
    spec = FigureSpec.from_dict({"name": "x", "source": "a.html"})
    assert spec.kind == "html"
    assert spec.output_name() == "x.png"
    with pytest.raises(ValueError, match="width must be positive"):
        FigureSpec.from_dict({"name": "x", "source": "a", "width": 0})
    with pytest.raises(ValueError, match="scale must be positive"):
        FigureSpec.from_dict({"name": "x", "source": "a", "scale": -1})


def test_plan_defaults_apply_then_figure_wins() -> None:
    plan = ShotPlan.from_dict(
        {
            "defaults": {"scale": 3.0, "width": 800},
            "figures": [
                {"name": "a", "source": "a.html"},
                {"name": "b", "source": "b.html", "scale": 1.0},
            ],
        }
    )
    assert plan.figures[0].scale == 3.0
    assert plan.figures[0].width == 800
    assert plan.figures[1].scale == 1.0


def test_plan_rejects_duplicate_outputs_and_empty_figures() -> None:
    with pytest.raises(ValueError, match="non-empty list"):
        ShotPlan.from_dict({"figures": []})
    with pytest.raises(ValueError, match="duplicate output"):
        ShotPlan.from_dict(
            {
                "figures": [
                    {"name": "a", "source": "a.html", "out": "same.png"},
                    {"name": "b", "source": "b.html", "out": "same.png"},
                ]
            }
        )


def test_plan_relative_base_dir_resolves_against_plan_file(tmp_path: Path) -> None:
    plan_file = tmp_path / "figures.toml"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.html").write_text("<html></html>", encoding="utf-8")
    plan_file.write_text(
        'base_dir = "src"\n[[figures]]\nname = "a"\nkind = "html"\nsource = "a.html"\n',
        encoding="utf-8",
    )
    plan = ShotPlan.load(plan_file)
    assert Path(plan.figures[0].source).parent == (tmp_path / "src").resolve()


def test_plan_selected_filters_and_rejects_unknown() -> None:
    plan = ShotPlan.from_dict(
        {
            "figures": [
                {"name": "a", "source": "a.html"},
                {"name": "b", "source": "b.html"},
            ]
        }
    )
    assert [f.name for f in plan.selected(["b"]).figures] == ["b"]
    assert [f.name for f in plan.selected(None).figures] == ["a", "b"]
    with pytest.raises(ValueError, match="unknown figure"):
        plan.selected(["nope"])


def test_plan_round_trips_through_dict() -> None:
    plan = ShotPlan.from_dict({"figures": [{"name": "a", "source": "a.html"}]})
    again = ShotPlan.from_dict(plan.to_dict())
    assert again.figures[0].name == "a"


# ----------------------------------------------------------------------- terminal


def test_wrap_preserves_indent_and_caps_columns() -> None:
    line = "  " + "x" * 200
    wrapped = wrap(line, 1000)  # capped at MAX_COLUMNS
    assert len(wrapped) > 1
    assert wrapped[0].startswith("  ")
    assert all(len(w) <= MAX_COLUMNS for w in wrapped)


def test_wrap_counts_display_cells_not_code_points() -> None:
    """A wide glyph occupies two monospace cells; wrapping must account for it.

    Counting code points let 88 CJK characters exceed the card width and clip.
    """
    from agentic_bi.shots.shots_terminal import _cells

    for line in ("\u6708" * 88, "x" * 300, "  " + "y" * 200):
        wrapped = wrap(line, 88)
        assert len(wrapped) >= 2
        assert all(_cells(w) <= 88 for w in wrapped), [(_cells(w)) for w in wrapped]
    # a zero-width combining mark costs no cell
    assert wrap("e\u0301" * 10, 40) == ["e\u0301" * 10]


def test_wrap_keeps_a_line_that_exactly_fits() -> None:
    assert wrap("x" * 40, 40) == ["x" * 40]


def test_terminal_card_narrow_run_is_not_full_width() -> None:
    """The card width follows the wrap width, not MAX_COLUMNS."""
    _html, width, _height = build_terminal_html("a\nb", columns=40)
    _wide_html, wide_width, _ = build_terminal_html("a\nb", columns=88)
    assert width < wide_width


def test_window_height_raises_short_renders_to_the_browser_floor() -> None:
    """Chromium clamps its layout viewport below `MIN_WINDOW_HEIGHT`.

    A shorter window keeps the requested PNG height but drops the bottom of the
    page, so a short terminal card silently lost its body. Every window is
    raised to the floor instead.
    """
    assert window_height(10) == MIN_WINDOW_HEIGHT
    assert window_height(MIN_WINDOW_HEIGHT) == MIN_WINDOW_HEIGHT
    assert window_height(640) == 640


def test_short_terminal_card_grows_to_the_window_floor() -> None:
    """A card that would be shorter than the floor is padded, not clipped."""
    _html, _width, height = build_terminal_html("one line", columns=40)
    assert height >= MIN_WINDOW_HEIGHT
    # a tall card is unaffected
    _tall_html, _tall_width, tall_height = build_terminal_html(
        "\n".join(f"line {i}" for i in range(40)), columns=40
    )
    assert tall_height > MIN_WINDOW_HEIGHT


def test_card_size_matches_terminal_html_and_never_dips_below_floor() -> None:
    lines = wrap("a\nb", 88)
    _html, width, height = build_terminal_html("a\nb", columns=88)
    assert card_size(lines, point=13, columns=88) == (width, height)
    assert card_size(["x"], point=13, columns=88)[1] == MIN_WINDOW_HEIGHT


def test_build_terminal_html_escapes_and_highlights() -> None:
    html, width, height = build_terminal_html(
        "<script>alert(1)</script>\nAll checks passed!", title="t"
    )
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert '<span class="ok">All checks passed!</span>' in html
    assert width > 0 and height > 0


def test_highlight_marks_each_occurrence() -> None:
    out = highlight_markers("passed and passed", markers=("passed",))
    assert out.count('<span class="ok">passed</span>') == 2


def test_highlight_does_not_nest_a_substring_marker() -> None:
    """`passed` is a substring of `All checks passed!` — no nested spans."""
    out = highlight_markers(
        "All checks passed!", markers=("passed", "All checks passed!")
    )
    assert '<span class="ok">All checks passed!</span>' in out
    assert out.count("<span") == 1


# ------------------------------------------------------------------------ build


def test_build_shots_reports_missing_source(tmp_path: Path) -> None:
    """A missing source is a reported failure, not a traceback."""
    plan = ShotPlan.from_dict({"figures": [{"name": "x", "source": "gone.html"}]})
    result = build_shots(plan, tmp_path / "out")
    assert not result.ok
    assert result.failures[0][0] == "x"


def test_figure_spec_output_name_honours_out() -> None:
    spec = FigureSpec.from_dict({"name": "a", "source": "a.html", "out": "b.png"})
    assert spec.output_name() == "b.png"


def test_plan_load_json(tmp_path: Path) -> None:
    path = tmp_path / "f.json"
    path.write_text(
        json.dumps({"figures": [{"name": "a", "source": "a.html"}]}), encoding="utf-8"
    )
    assert ShotPlan.load(path).figures[0].name == "a"


def test_browser_not_found_error_is_exported() -> None:
    assert issubclass(BrowserNotFound, RuntimeError)


def test_render_html_file_missing_source_raises() -> None:
    """A missing source fails before any browser is involved."""
    with pytest.raises(FileNotFoundError):
        render_html_file("/tmp/does-not-exist-xyz.html", "/tmp/x.png")
