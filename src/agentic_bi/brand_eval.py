"""Evaluation of a theme against the brand rules (fonts/colors/background/elements).

Pure evaluation logic: given a normalized ``theme`` dict, it produces
:class:`Finding` objects. Palette/fonts/thresholds come from the sibling brand
modules so the rules live in one place.
"""
from __future__ import annotations

from agentic_bi.brand_fonts import FONTS
from agentic_bi.brand_palette import PALETTE_PRIMARY, ColorSpec
from agentic_bi.brand_rules import (
    ALLOWED_WEIGHTS,
    BASE_ELEMENTS_MIN,
    FALLBACK_FONTS,
    MIN_CONTRAST_RATIO,
    PREFERRED_BACKGROUNDS,
    PRIMARY_COLOR_MIN,
    Finding,
)
from agentic_bi.brand_eval_common import (
    _ALL_HEX,
    _chromatic_off_palette,
    _hex_norm,
    _is_neutral,
    _match_hex,
    _only_brand_colors,
    _primary_count,
)

_BRAND_FAMILY_TOKENS = tuple(f.family.lower() for f in FONTS)


# Re-exported for backward compatibility (used by the audit modules).
_color_catalog = None


def _font_family(name: str) -> str:
    """Normalize a font name to a lowercase, single-spaced form."""
    n = str(name).lower().replace("_", " ").replace("-", " ")
    return " ".join(n.split())


def is_brand_font(name: str) -> bool:
    """Whether the font is a configured brand family."""
    f = _font_family(name)
    return any(tok in f for tok in _BRAND_FAMILY_TOKENS)


def is_fallback(name: str) -> bool:
    """Whether the font is an allowed system fallback (not a brand font)."""
    f = _font_family(name)
    return any(fb in f for fb in FALLBACK_FONTS)


def _base_elements_count(theme: dict) -> int:
    """Number of base brand elements present in the theme.

    color  - at least one brand color;
    font   - a brand font is present in ``theme.get("fonts")``;
    foundation - ``theme.get("foundation", False)`` (pattern/foundation).
    """
    count = 0
    if theme and any(_hex_norm(c) in _ALL_HEX for c in theme.get("colors", {}).values()):
        count += 1
    fonts = theme.get("fonts", [])
    if any(is_brand_font(str(f)) for f in fonts):
        count += 1
    if bool(theme.get("foundation")):
        count += 1
    return count


def font_family_findings(fonts: list[str] | None) -> list[Finding]:
    """Evaluate the font set: presence of brand fonts and allowed weights."""
    out: list[Finding] = []
    fonts = fonts or []
    if not fonts:
        out.append(Finding(
            "FONT-FAMILY-BRAND", "warning",
            "No fonts specified - the brand fonts are not confirmed.",
            category="font"))
        return out

    brand_fonts = [f for f in fonts if is_brand_font(f)]
    if not brand_fonts:
        out.append(Finding(
            "FONT-FAMILY-BRAND", "warning",
            "There is no brand font among the fonts.",
            "used: " + ", ".join(map(str, fonts)), category="font"))
        return out

    for f in fonts:
        if is_brand_font(f) or is_fallback(f):
            continue
        out.append(Finding(
            "FONT-FAMILY-BRAND", "warning",
            f"Disallowed family: {f!r} (not in the brand book).",
            "allowed: brand fonts or a system fallback", category="font"))

    for f in brand_fonts:
        fam = _font_family(f)
        weight = fam
        for tok in _BRAND_FAMILY_TOKENS:
            weight = weight.replace(tok, "")
        weight = weight.replace(" italic", "").strip()
        if weight and weight.title() not in ALLOWED_WEIGHTS:
            out.append(Finding(
                "FONT-WEIGHT-ALLOWED", "warning",
                f"Disallowed brand weight: {weight!r}.", category="font"))
    return out


# ── Background ─────────────────────────────────────────────


def _srgb_channel(v: float) -> float:
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    h = _hex_norm(hex_color)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return (0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g)
            + 0.0722 * _srgb_channel(b))


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """WCAG contrast ratio between text (fg) and background (bg)."""
    l1, l2 = _luminance(fg_hex), _luminance(bg_hex)
    lo, hi = min(l1, l2), max(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


def background_findings(background: str | None,
                        text_color: str | None = None) -> list[Finding]:
    """Evaluate the background: color validity and text contrast (if given)."""
    out: list[Finding] = []
    if not background:
        out.append(Finding(
            "BG-ALLOWED", "warning", "No background specified - brand background not confirmed.",
            category="background"))
        return out
    h = _hex_norm(background)
    allowed = h in PREFERRED_BACKGROUNDS or h in _ALL_HEX or _is_neutral(h)
    if not allowed:
        out.append(Finding(
            "BG-ALLOWED", "warning",
            f"Disallowed background {background!r}.",
            "allowed: white/black/grey or a palette color", category="background"))
    if text_color:
        ratio = contrast_ratio(text_color, background)
        if ratio < MIN_CONTRAST_RATIO:
            out.append(Finding(
                "BG-CONTRAST", "warning",
                f"Low text-to-background contrast: {ratio}:1 "
                f"(needs >= {MIN_CONTRAST_RATIO}:1).",
                f"text={text_color} bg={background}", category="background"))
    return out


# ── Elements ───────────────────────────────────────────────


def element_findings(theme: dict) -> list[Finding]:
    """Evaluate brand elements: 2 of 3 base, foundation, logo."""
    out: list[Finding] = []
    be = _base_elements_count(theme)
    if be < BASE_ELEMENTS_MIN:
        out.append(Finding(
            "ELEM-BASE-2OF3", "info",
            f"{be} of 3 base brand elements are used "
            f"(at least {BASE_ELEMENTS_MIN} required).",
            "counted: brand color / brand font / foundation",
            category="element"))
    if theme.get("has_logo") and not _is_neutral(
            _hex_norm(theme.get("background", "#ffffff"))):
        out.append(Finding(
            "ELEM-LOGO-BG", "info",
            "The logo is placed on a non-neutral background - use a white backing.",
            f"bg={theme.get('background')}", category="element"))
    return out


def evaluate_theme(theme: dict | None) -> list[Finding]:
    """Run ``theme`` through all brand rules (color/font/background/elements).

    ``theme`` format:
        {"colors": {"accent": "#D32F2F", "grey": "#4A4A4A"},
         "fonts": ["Brand Sans", "Brand Sans Text"],
         "background": "#FFFFFF",
         "text_color": "#000000",
         "foundation": True,
         "has_logo": True}

    Returns:
        a list of ``Finding`` (empty if there are no remarks).
    """
    if not theme:
        return [Finding("BRAND-PALETTE-MEMBERSHIP", "error",
                        "Empty theme - no data to evaluate brand compliance.",
                        category="color")]
    colors = theme.get("colors", {})
    findings: list[Finding] = []

    if not colors:
        findings.append(Finding(
            "BRAND-ACCENT-MANDATORY", "error",
            "The theme has no colors - the primary accent (#D32F2F) is missing.",
            category="color"))
    else:
        accent_matches = any(
            (m := _match_hex(c)) and m.mandatory for c in colors.values())
        if not accent_matches:
            findings.append(Finding(
                "BRAND-ACCENT-MANDATORY", "error",
                "The mandatory primary accent #D32F2F is not set / does not match.",
                f"colors={list(colors.values())}", category="color"))

    off_palette = _chromatic_off_palette(theme)
    if off_palette:
        findings.append(Finding(
            "BRAND-PALETTE-MEMBERSHIP", "warning",
            "Chromatic colors outside the brand palette: " + ", ".join(off_palette),
            "allowed: colors from PALETTE_PRIMARY/PALETTE_ADDITIONAL; "
            "neutral background/grey/black/white are not violations",
            category="color"))

    if colors and _primary_count(colors) < PRIMARY_COLOR_MIN:
        findings.append(Finding(
            "BRAND-PRIMARY-COLORS-MIN", "warning",
            f"The theme has fewer than {PRIMARY_COLOR_MIN} primary-range colors.",
            category="color"))

    # fonts / background / elements
    findings.extend(font_family_findings(theme.get("fonts")))
    findings.extend(background_findings(theme.get("background"),
                                        theme.get("text_color")))
    findings.extend(element_findings(theme))

    return findings


def check_brand_compliance(
    colors: dict[str, str] | None = None,
    fonts: list[str] | None = None,
    foundation: bool = False,
    background: str | None = None,
    text_color: str | None = None,
    has_logo: bool = False,
) -> dict:
    """A summary compliance report of a dashboard theme with the brand style.

    Args:
        colors: role => HEX dict (e.g. ``{"accent": "#D32F2F", "grey": "#4A4A4A"}``)
        fonts: a list of fonts (primarily the brand families)
        foundation: whether the "foundation" element (pattern) is used
        background: HEX of the page/visual background
        text_color: HEX of the text color (for the contrast check)
        has_logo: whether a logo is placed (affects the background rule)

    Returns:
        {"ok": bool, "findings": [ {...}, ... ], "used": {...}}
    """
    theme = {"colors": colors or {},
             "fonts": fonts or [],
             "foundation": bool(foundation),
             "background": background,
             "text_color": text_color,
             "has_logo": bool(has_logo)}
    findings = evaluate_theme(theme)
    errors = [f for f in findings if f.level == "error"]
    return {
        "ok": not errors,
        "findings": [f.as_dict() for f in findings],
        "used": theme,
    }


def color_catalog() -> list[dict]:
    """The full catalog of brand colors (for README/doc)."""
    from dataclasses import asdict as _asdict
    from agentic_bi.brand_palette import PALETTE_ADDITIONAL as _PA
    return [_asdict(c) for c in (*PALETTE_PRIMARY, *_PA)]


__all__ = [
    "is_brand_font",
    "is_fallback",
    "font_family_findings",
    "contrast_ratio",
    "background_findings",
    "element_findings",
    "evaluate_theme",
    "check_brand_compliance",
    "color_catalog",
]