"""Evaluation of a theme against the brand rules (fonts/colors/background/elements).

Pure evaluation logic: given a normalized ``theme`` dict, it produces
:class:`Finding` objects. Palette/fonts/thresholds come from the sibling brand
modules so the rules live in one place.

Background/contrast evaluation lives in `brand.eval_background`, the per-component
font/element rules in `brand.eval_rules`, and both are re-exported here so
`brand.eval` stays the single public entry point; this module owns running every
rule on a theme and assembling the verdict report.

Public API:
    is_brand_font(name) / is_fallback(name)         - family classification
    font_family_findings(fonts)                     - font rules
    contrast_ratio(fg, bg) / background_findings(...) - re-exported background rules
    element_findings(theme)                         - base elements / logo rules
    evaluate_theme(theme) -> list[Finding]          - all rules on a theme dict
    check_brand_compliance(...) -> dict             - summary report
    color_catalog() -> list[dict]                   - the brand color catalog
"""

from __future__ import annotations

from agentic_bi.brand.eval_background import (
    background_findings,
    contrast_ratio,
)
from agentic_bi.brand.eval_common import (
    _chromatic_off_palette,
    _match_hex,
    _primary_count,
)
from agentic_bi.brand.eval_rules import (
    _BRAND_FAMILY_TOKENS as _BRAND_FAMILY_TOKENS,
)
from agentic_bi.brand.eval_rules import (
    _base_elements_count as _base_elements_count,
)
from agentic_bi.brand.eval_rules import (
    _font_family as _font_family,
)
from agentic_bi.brand.eval_rules import (
    element_findings,
    font_family_findings,
    is_brand_font,
    is_fallback,
)
from agentic_bi.brand.palette import PALETTE_PRIMARY
from agentic_bi.brand.rules import (
    PRIMARY_COLOR_MIN,
    Finding,
)


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
        return [
            Finding(
                "BRAND-PALETTE-MEMBERSHIP",
                "error",
                "Empty theme - no data to evaluate brand compliance.",
                category="color",
            )
        ]
    colors = theme.get("colors", {})
    findings: list[Finding] = []

    if not colors:
        findings.append(
            Finding(
                "BRAND-ACCENT-MANDATORY",
                "error",
                "The theme has no colors - the primary accent (#D32F2F) is missing.",
                category="color",
            )
        )
    else:
        accent_matches = any(
            (m := _match_hex(c)) and m.mandatory for c in colors.values()
        )
        if not accent_matches:
            findings.append(
                Finding(
                    "BRAND-ACCENT-MANDATORY",
                    "error",
                    "The mandatory primary accent #D32F2F is not set / does not match.",
                    f"colors={list(colors.values())}",
                    category="color",
                )
            )

    off_palette = _chromatic_off_palette(theme)
    if off_palette:
        findings.append(
            Finding(
                "BRAND-PALETTE-MEMBERSHIP",
                "warning",
                "Chromatic colors outside the brand palette: " + ", ".join(off_palette),
                "allowed: colors from PALETTE_PRIMARY/PALETTE_ADDITIONAL; "
                "neutral background/grey/black/white are not violations",
                category="color",
            )
        )

    if colors and _primary_count(colors) < PRIMARY_COLOR_MIN:
        findings.append(
            Finding(
                "BRAND-PRIMARY-COLORS-MIN",
                "warning",
                f"The theme has fewer than {PRIMARY_COLOR_MIN} primary-range colors.",
                category="color",
            )
        )

    # fonts / background / elements
    findings.extend(font_family_findings(theme.get("fonts")))
    findings.extend(
        background_findings(theme.get("background"), theme.get("text_color"))
    )
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
    theme = {
        "colors": colors or {},
        "fonts": fonts or [],
        "foundation": bool(foundation),
        "background": background,
        "text_color": text_color,
        "has_logo": bool(has_logo),
    }
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

    from agentic_bi.brand.palette import PALETTE_ADDITIONAL as _PA

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
