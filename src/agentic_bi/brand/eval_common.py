"""Shared color helpers for brand-theme evaluation."""

from __future__ import annotations

from agentic_bi.brand.palette import PALETTE_ADDITIONAL, PALETTE_PRIMARY, ColorSpec

_ALL_HEX: dict[str, ColorSpec] = {
    c.hex.lower(): c for c in (*PALETTE_PRIMARY, *PALETTE_ADDITIONAL)
}


def _hex_norm(value: str) -> str:
    v = value.strip().lower()
    if not v.startswith("#"):
        v = "#" + v
    if len(v) == 4:  # #abc -> #aabbcc
        v = "#" + "".join(2 * ch for ch in v[1:])
    return v


def _match_hex(hex_color: str) -> ColorSpec | None:
    """Match a HEX against the palette (exact, case-insensitive)."""
    return _ALL_HEX.get(_hex_norm(hex_color))


def _is_neutral(hex_color: str) -> bool:
    """An achromatic (grey/white/black) color is a neutral background, not a violation.

    White is the ideal logo background, black and grey shades are recommended.
    Achromatic colors (R==G==B) are treated as neutral service backgrounds, not
    brand colors. A value that is not a 6-digit hex is not neutral (it is handled
    as an off-palette color by the caller) rather than raising.
    """
    h = _hex_norm(hex_color or "")
    if len(h) != 7:
        return False
    try:
        r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    except ValueError:
        return False
    return r == g == b


def _chromatic_off_palette(theme: dict) -> list[str]:
    """Off-brand theme colors requiring attention (excluding neutral backgrounds)."""
    out = []
    for k, v in theme.get("colors", {}).items():
        h = _hex_norm(v)
        if h in _ALL_HEX or _is_neutral(h):
            continue
        out.append(k)
    return out


def _only_brand_colors(theme: dict) -> bool:
    """All chromatic HEX of the theme are part of the brand palette.

    Achromatic (white/grey/black) backgrounds are not violations.
    """
    return not _chromatic_off_palette(theme)


def _primary_count(theme: dict) -> int:
    """Number of unique theme colors in the primary range."""
    primary = {c.hex.lower() for c in PALETTE_PRIMARY}
    return sum(1 for c in theme.values() if _hex_norm(c) in primary)
