"""Contrast budgets computed from the CSS tokens (light, dark, print).

Badge text is 8.99 px bold, so WCAG AA requires 4.5:1. The light palette shipped
3.25-3.77:1 for the badge text on its tinted background; this test recomposites
the real stack (canvas -> element -> chrome -> badge) from the tokens, so a
regressed `--err`/`--warn`/`--info` or a heavier tint fails it.
"""

from __future__ import annotations

import re

from tests.web_report_fixtures import make_container, make_layout

from agentic_bi.web_report import inspect_layout, render_html

_TOKEN_RE = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;]+);")
_HEX_RE = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
_RGBA_RE = re.compile(r"rgba?\(([^)]*)\)")
_MIN_CONTRAST = 4.5
_TEXT_TOKEN = {"error": "err", "warning": "warn", "info": "info", "ok": "info"}


def _markup() -> str:
    visual = make_container(
        "card",
        {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
        ["Sum(Sales.amount)"],
        title="C",
    )
    return render_html(inspect_layout(make_layout([visual]), source="c.pbix"))


def _css_block(markup: str, header: str) -> str:
    if header not in markup:
        raise AssertionError(f"CSS block {header!r} is missing from the document")
    start = markup.index(header)
    opening = markup.index("{", start)
    depth = 0
    for pos in range(opening, len(markup)):
        if markup[pos] == "{":
            depth += 1
        elif markup[pos] == "}":
            depth -= 1
            if depth == 0:
                return markup[opening + 1 : pos]
    raise AssertionError(f"CSS block {header!r} is unbalanced")


def _tokens(header: str, markup: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2).strip()
        for match in _TOKEN_RE.finditer(_css_block(markup, header))
    }


def _parse_color(value: str) -> tuple[float, float, float, float]:
    """`#rgb`, `#rrggbb`, `rgb()`/`rgba()` or `transparent` -> (r, g, b, alpha)."""
    value = value.strip().lower()
    if value == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    hex_match = _HEX_RE.fullmatch(value)
    if hex_match:
        digits = hex_match.group(1)
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        channels = tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))
        return (float(channels[0]), float(channels[1]), float(channels[2]), 1.0)
    rgba_match = _RGBA_RE.fullmatch(value)
    if rgba_match:
        parts = [part.strip() for part in rgba_match.group(1).split(",")]
        if len(parts) not in (3, 4):
            raise AssertionError(f"unsupported colour {value!r}")
        channels = [float(part) for part in parts[:3]]
        alpha = float(parts[3]) if len(parts) == 4 else 1.0
        return (channels[0], channels[1], channels[2], alpha)
    raise AssertionError(f"unsupported colour {value!r}")


def _over(
    top: tuple[float, float, float, float],
    bottom: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Composite `top` over `bottom` (both non-premultiplied)."""
    alpha = top[3] + bottom[3] * (1 - top[3])
    if alpha == 0:
        return (0.0, 0.0, 0.0, 0.0)
    channels = [
        (top[i] * top[3] + bottom[i] * bottom[3] * (1 - top[3])) / alpha
        for i in range(3)
    ]
    return (channels[0], channels[1], channels[2], alpha)


def _luminance(color: tuple[float, float, float, float]) -> float:
    def channel(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(color[i]) for i in range(3))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    high = max(_luminance(first), _luminance(second))
    low = min(_luminance(first), _luminance(second))
    return (high + 0.05) / (low + 0.05)


def _badge_background(tokens: dict[str, str], severity: str) -> tuple[float, ...]:
    """canvas -> element background -> chrome strip -> badge tint."""
    background = _parse_color(tokens["surface-2"])
    if severity in ("error", "warning"):
        # .el.error/.el.warning replace the base `.el` background instead of
        # layering on it; the panel tint is not part of this stack.
        background = _over(_parse_color(tokens[_tint_token(severity)]), background)
    else:
        background = _over(_parse_color(tokens["panel"]), background)
    background = _over(_parse_color(tokens["chrome"]), background)
    return _over(_parse_color(tokens[_tint_token(severity)]), background)


def _tint_token(severity: str) -> str:
    return f"{_TEXT_TOKEN[severity]}-bg"


def _badge_text(tokens: dict[str, str], severity: str) -> tuple[float, ...]:
    return _parse_color(tokens[_TEXT_TOKEN[severity]])


def _assert_badges_pass(tokens: dict[str, str], theme: str) -> None:
    for severity in ("error", "warning", "info", "ok"):
        ratio = _contrast(
            _badge_text(tokens, severity), _badge_background(tokens, severity)
        )
        assert ratio >= _MIN_CONTRAST, f"{theme} {severity} badge contrast {ratio:.2f}"


def test_light_theme_badges_meet_aa_contrast():
    _assert_badges_pass(_tokens(":root", _markup()), "light")


def test_dark_theme_badges_meet_aa_contrast():
    markup = _markup()
    _assert_badges_pass(_tokens("@media (prefers-color-scheme: dark)", markup), "dark")


def test_print_theme_badges_meet_aa_contrast():
    _assert_badges_pass(_tokens("@media print", _markup()), "print")


def _section_backgrounds(tokens: dict[str, str]) -> list[tuple[float, ...]]:
    """The table badge sits on `.section` (`--panel`) over the body gradient.

    The gradient runs from `--bg-from` to `--bg-to`, so both ends are checked:
    compositing the badge tint over `--surface` alone models the wrong stack and
    hid a 4.26:1 dark error badge.
    """
    stacks = []
    for end in ("bg-from", "bg-to"):
        stacks.append(_over(_parse_color(tokens["panel"]), _parse_color(tokens[end])))
    return stacks


def test_badge_text_stays_readable_on_the_details_surface():
    markup = _markup()
    for header in (":root", "@media (prefers-color-scheme: dark)", "@media print"):
        tokens = _tokens(header, markup)
        for severity in ("error", "warning", "info", "ok"):
            tint = _tint_token(severity)
            for base in _section_backgrounds(tokens):
                background = _over(_parse_color(tokens[tint]), base)
                ratio = _contrast(_badge_text(tokens, severity), background)
                assert ratio >= _MIN_CONTRAST, (
                    f"{header} {severity} table badge {ratio:.2f}"
                )


def _hex(color: tuple[float, ...]) -> str:
    channels = tuple(round(value) for value in color[:3])
    return "#{:02x}{:02x}{:02x}".format(*channels)


def _same_hex(left: str, right: str) -> bool:
    """Compare two hex colours after expanding the `#rgb` shorthand."""

    def expand(value: str) -> str:
        value = value.lower()
        if len(value) == 4:
            return "#" + "".join(char * 2 for char in value[1:])
        return value

    return expand(left) == expand(right)


def test_donut_hole_token_is_the_element_background():
    """The hole must match what is *actually* behind it on each element.

    `.el` sits on `.canvas` (`--surface-2`). A plain element paints `--panel`
    there; a severity element paints its tint instead, so the single
    `--el-bg` token was wrong on exactly the elements whose glyph matters.
    """
    markup = _markup()
    assert 'circle[fill="var(--surface-2)"] { fill:var(--el-bg); }' in markup
    assert (
        '.el.error .el-body svg circle[fill="var(--surface-2)"] '
        "{ fill:var(--el-bg-error); }" in markup
    )
    assert (
        '.el.warning .el-body svg circle[fill="var(--surface-2)"] '
        "{ fill:var(--el-bg-warning); }" in markup
    )
    for header in (
        ":root",
        "@media (prefers-color-scheme: dark)",
        "@media print",
    ):
        tokens = _tokens(header, markup)
        canvas = _parse_color(tokens["surface-2"])
        assert _same_hex(
            tokens["el-bg"], _hex(_over(_parse_color(tokens["panel"]), canvas))
        ), header
        for severity in ("error", "warning"):
            expected = _hex(_over(_parse_color(tokens[_tint_token(severity)]), canvas))
            assert _same_hex(tokens[f"el-bg-{severity}"], expected), header


_NON_TEXT_MIN = 3.0


def _el_fill(tokens: dict[str, str]) -> tuple[float, ...]:
    """The plain element's fill: the panel tint over the canvas."""
    return _over(_parse_color(tokens["panel"]), _parse_color(tokens["surface-2"]))


def _border_over_canvas(tokens: dict[str, str]) -> tuple[float, ...]:
    return _over(_parse_color(tokens["border"]), _parse_color(tokens["surface-2"]))


def test_the_element_boundary_is_visible_without_colour(tmp_path) -> None:
    """The border is the only boundary of a clean element; WCAG needs 3:1.

    Measured before the fix: `--border` was `rgba(0,105,163,0.28)` in light
    (1.60:1 against the canvas, 1.49:1 against the element fill) and
    `rgba(0,212,255,0.22)` in dark (1.86:1 / 1.63:1). The R4 audit covered badge
    *text* only, so a clean, clickable element had no perceivable edge.
    """
    markup = _markup()
    for header, theme in (
        (":root", "light"),
        ("@media (prefers-color-scheme: dark)", "dark"),
    ):
        tokens = _tokens(header, markup)
        on_canvas = _contrast(
            _border_over_canvas(tokens), _parse_color(tokens["surface-2"])
        )
        on_fill = _contrast(_border_over_canvas(tokens), _el_fill(tokens))
        assert on_canvas >= _NON_TEXT_MIN, f"{theme} border/canvas {on_canvas:.2f}"
        assert on_fill >= _NON_TEXT_MIN, f"{theme} border/fill {on_fill:.2f}"
