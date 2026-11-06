"""Per-component brand rules: font families/weights and base elements.

Split out of `brand.eval` (which grew past the file-size budget): these rules judge
one component of a theme on its own (the font set, the base elements/logo
placement) and need only the shared color helpers and the brand constants.
`brand.eval` runs them together with the color and background rules and produces
the verdict report.

Public API:
    is_brand_font(name) / is_fallback(name)         - family classification
    font_family_findings(fonts)                     - font rules
    element_findings(theme)                         - base elements / logo rules
"""

from __future__ import annotations

from agentic_bi.brand.eval_common import (
    _ALL_HEX,
    _hex_norm,
    _is_neutral,
)
from agentic_bi.brand.fonts import FONTS
from agentic_bi.brand.rules import (
    ALLOWED_WEIGHTS,
    BASE_ELEMENTS_MIN,
    FALLBACK_FONTS,
    Finding,
)

_BRAND_FAMILY_TOKENS = tuple(f.family.lower() for f in FONTS)


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
    if theme and any(
        _hex_norm(c) in _ALL_HEX for c in theme.get("colors", {}).values()
    ):
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
        out.append(
            Finding(
                "FONT-FAMILY-BRAND",
                "warning",
                "No fonts specified - the brand fonts are not confirmed.",
                category="font",
            )
        )
        return out

    brand_fonts = [f for f in fonts if is_brand_font(f)]
    if not brand_fonts:
        out.append(
            Finding(
                "FONT-FAMILY-BRAND",
                "warning",
                "There is no brand font among the fonts.",
                "used: " + ", ".join(map(str, fonts)),
                category="font",
            )
        )
        return out

    for f in fonts:
        if is_brand_font(f) or is_fallback(f):
            continue
        out.append(
            Finding(
                "FONT-FAMILY-BRAND",
                "warning",
                f"Disallowed family: {f!r} (not in the brand book).",
                "allowed: brand fonts or a system fallback",
                category="font",
            )
        )

    for f in brand_fonts:
        fam = _font_family(f)
        weight = fam
        for tok in _BRAND_FAMILY_TOKENS:
            weight = weight.replace(tok, "")
        weight = weight.replace(" italic", "").strip()
        if weight and weight.title() not in ALLOWED_WEIGHTS:
            out.append(
                Finding(
                    "FONT-WEIGHT-ALLOWED",
                    "warning",
                    f"Disallowed brand weight: {weight!r}.",
                    category="font",
                )
            )
    return out


def element_findings(theme: dict) -> list[Finding]:
    """Evaluate brand elements: 2 of 3 base, foundation, logo."""
    out: list[Finding] = []
    be = _base_elements_count(theme)
    if be < BASE_ELEMENTS_MIN:
        out.append(
            Finding(
                "ELEM-BASE-2OF3",
                "info",
                f"{be} of 3 base brand elements are used "
                f"(at least {BASE_ELEMENTS_MIN} required).",
                "counted: brand color / brand font / foundation",
                category="element",
            )
        )
    if theme.get("has_logo") and not _is_neutral(
        _hex_norm(theme.get("background", "#ffffff"))
    ):
        out.append(
            Finding(
                "ELEM-LOGO-BG",
                "info",
                "The logo is placed on a non-neutral background - use a white backing.",
                f"bg={theme.get('background')}",
                category="element",
            )
        )
    return out


__all__ = [
    "is_brand_font",
    "is_fallback",
    "font_family_findings",
    "element_findings",
]
