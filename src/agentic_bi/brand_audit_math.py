"""Color/contrast math and font-weight parsing for the brand audit.

These are the dependency-free primitives shared by the observation evaluators:
WCAG relative luminance, a neutral (achromatic) test, the contrast ratio and the
weight token extracted from a font-family name.

Colors arrive as raw strings from a `.pptx`; every entry point normalizes first,
so callers may pass `#abc`, `abc`, `#AABBCC` or `AABBCC` interchangeably.

Public API:
    is_neutral(hex_color) -> bool
    luminance(hex_color) -> float       (raises ValueError on a non-hex color)
    contrast(fg, bg) -> float           (raises ValueError on a non-hex color)
    font_weight(name) -> str
    WEIGHT_KEYWORDS        - recognized weight tokens (longest first)
"""

from __future__ import annotations

import re

from agentic_bi.brand_config import normalize_hex

# Weight tokens in a family name, ordered so a compound token is tested before the
# generic one it embeds ("extrabold"/"semibold" before "bold", "ultralight" before
# "light").
WEIGHT_KEYWORDS = (
    "extrabold",
    "ultralight",
    "extralight",
    "semibold",
    "demibold",
    "regular",
    "normal",
    "medium",
    "black",
    "heavy",
    "light",
    "bold",
    "book",
    "thin",
)


def _channels(hex_color: str) -> tuple[int, int, int] | None:
    """RGB channels of a normalized hex color, or None if it is not a hex."""
    h = normalize_hex(hex_color)
    if not h:
        return None
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def is_neutral(hex_color: str) -> bool:
    """Whether the color is achromatic (R == G == B): grey/white/black."""
    ch = _channels(hex_color)
    if ch is None:
        return False
    r, g, b = ch
    return r == g == b


def luminance(hex_color: str) -> float:
    """WCAG relative luminance of a hex color (0.0 = black, 1.0 = white).

    Raises:
        ValueError: the value is not a hex color. Callers must validate input
            (e.g. via `normalize_hex`) before comparing contrast.
    """
    ch = _channels(hex_color)
    if ch is None:
        raise ValueError(f"not a hex color: {hex_color!r}")
    lin = [c / 255 for c in ch]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in lin]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio between a foreground and a background color."""
    l1, l2 = luminance(fg), luminance(bg)
    lo, hi = min(l1, l2), max(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


def font_weight(name: str) -> str:
    """The font weight from the family name ('' if not recognized).

    Spaces/underscores/hyphens are ignored when matching, so "Extra Bold",
    "Extra-Bold" and "ExtraBold" all resolve to the same token.
    """
    low = re.sub(r"[\s_-]+", "", name.lower())
    for w in WEIGHT_KEYWORDS:
        if w in low:
            return w
    return ""
