"""Background and WCAG-contrast evaluation for a brand theme.

Split out of `brand_eval` (which grew past the file-size budget): the color-math
and background rules are self-contained and only need the shared color helpers.

Public API:
    contrast_ratio(fg_hex, bg_hex) -> float
    background_findings(background, text_color=None) -> list[Finding]
"""

from __future__ import annotations

from agentic_bi.brand_eval_common import (
    _ALL_HEX,
    _hex_norm,
    _is_neutral,
)
from agentic_bi.brand_rules import (
    MIN_CONTRAST_RATIO,
    PREFERRED_BACKGROUNDS,
    Finding,
)


def _srgb_channel(v: float) -> float:
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    h = _hex_norm(hex_color)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return (
        0.2126 * _srgb_channel(r)
        + 0.7152 * _srgb_channel(g)
        + 0.0722 * _srgb_channel(b)
    )


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """WCAG contrast ratio between text (fg) and background (bg)."""
    l1, l2 = _luminance(fg_hex), _luminance(bg_hex)
    lo, hi = min(l1, l2), max(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


def background_findings(
    background: str | None, text_color: str | None = None
) -> list[Finding]:
    """Evaluate the background: color validity and text contrast (if given)."""
    out: list[Finding] = []
    if not background:
        out.append(
            Finding(
                "BG-ALLOWED",
                "warning",
                "No background specified - brand background not confirmed.",
                category="background",
            )
        )
        return out
    h = _hex_norm(background)
    allowed = h in PREFERRED_BACKGROUNDS or h in _ALL_HEX or _is_neutral(h)
    if not allowed:
        out.append(
            Finding(
                "BG-ALLOWED",
                "warning",
                f"Disallowed background {background!r}.",
                "allowed: white/black/grey or a palette color",
                category="background",
            )
        )
    if text_color:
        ratio = contrast_ratio(text_color, background)
        if ratio < MIN_CONTRAST_RATIO:
            out.append(
                Finding(
                    "BG-CONTRAST",
                    "warning",
                    f"Low text-to-background contrast: {ratio}:1 "
                    f"(needs >= {MIN_CONTRAST_RATIO}:1).",
                    f"text={text_color} bg={background}",
                    category="background",
                )
            )
    return out
