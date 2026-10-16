"""Color/contrast math and font-weight parsing for the brand audit.

These are the dependency-free primitives shared by the observation evaluators:
WCAG relative luminance, a neutral (achromatic) test, the contrast ratio and the
weight token extracted from a font-family name.

Colors arrive as raw strings from a `.pptx`; every entry point normalizes first,
so callers may pass `#abc`, `abc`, `#AABBCC` or `AABBCC` interchangeably.

Public API:
    is_neutral(hex_color) -> bool
    luminance(hex_color) -> float
    contrast(fg, bg) -> float
    font_weight(name) -> str
    WEIGHT_KEYWORDS        - recognized weight tokens (longest first)
"""

from __future__ import annotations

from agentic_bi.brand_config import normalize_hex

# Weight tokens in a family name, longest first so "extrabold" wins over "bold".
WEIGHT_KEYWORDS = (
    "thin",
    "extralight",
    "ultralight",
    "light",
    "regular",
    "normal",
    "book",
    "medium",
    "semibold",
    "demibold",
    "bold",
    "extrabold",
    "black",
    "heavy",
)


def is_neutral(hex_color: str) -> bool:
    """Whether the color is achromatic (R == G == B): grey/white/black."""
    h = normalize_hex(hex_color)
    if not h:
        return False
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return r == g == b


def luminance(hex_color: str) -> float:
    """WCAG relative luminance of a hex color (0.0 = black, 1.0 = white)."""
    h = normalize_hex(hex_color)
    ch = [int(h[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio between a foreground and a background color."""
    l1, l2 = luminance(fg), luminance(bg)
    lo, hi = min(l1, l2), max(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


def font_weight(name: str) -> str:
    """The font weight from the family name ('' if not recognized)."""
    low = name.lower()
    for w in (
        "extrabold",
        "ultralight",
        "semibold",
        "demibold",
        "extralight",
        "regular",
        "medium",
        "light",
        "black",
        "heavy",
        "bold",
        "book",
        "normal",
        "thin",
    ):
        if w in low:
            return w
    return ""
