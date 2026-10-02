"""Brand/design-system style — a machine-readable spec for automated checks.

This module is now a **facade** over focused submodules:

    brand_palette.py - ColorSpec + PALETTE_PRIMARY/PALETTE_ADDITIONAL
    brand_fonts.py   - FontSpec + FONTS + weights + the local font library
    brand_rules.py   - thresholds + the rule registry + Finding/rule_catalog
    brand_eval.py    - theme evaluation (fonts/colors/background/elements)

It re-exports the public API so existing imports (``from agentic_bi.brand
import ...``) keep working unchanged.

The palette and fonts are **organization-agnostic neutrals**: replace them with
your own design tokens (here or via ``brand_config.yaml``) to enforce a real
corporate style.
"""
from __future__ import annotations

from agentic_bi.brand_palette import (  # noqa: F401
    ColorSpec,
    PALETTE_ADDITIONAL,
    PALETTE_PRIMARY,
)
from agentic_bi.brand_fonts import (  # noqa: F401
    BRAND_ITALIC,
    BRAND_WEIGHTS,
    EMBEDDED_BRAND_FONTS,
    FONTS,
    FONT_DIR,
    FONT_FILES,
    FontSpec,
    font_catalog,
    font_files,
)
from agentic_bi.brand_rules import (  # noqa: F401
    ALLOWED_WEIGHTS,
    BASE_ELEMENTS,
    BASE_ELEMENTS_MIN,
    FALLBACK_FONTS,
    MANDATORY_ACCENT,
    MIN_CONTRAST_RATIO,
    PREFERRED_BACKGROUNDS,
    PRIMARY_COLOR_MIN,
    RULES,
    Finding,
    rule_catalog,
    rules_by_category,
)
from agentic_bi.brand_eval import (  # noqa: F401
    background_findings,
    check_brand_compliance,
    color_catalog,
    contrast_ratio,
    element_findings,
    evaluate_theme,
    font_family_findings,
    is_brand_font,
    is_fallback,
)

__all__ = [
    "ALLOWED_WEIGHTS",
    "BASE_ELEMENTS",
    "BASE_ELEMENTS_MIN",
    "BRAND_ITALIC",
    "BRAND_WEIGHTS",
    "EMBEDDED_BRAND_FONTS",
    "FALLBACK_FONTS",
    "FONTS",
    "FONT_DIR",
    "FONT_FILES",
    "MANDATORY_ACCENT",
    "MIN_CONTRAST_RATIO",
    "PALETTE_ADDITIONAL",
    "PALETTE_PRIMARY",
    "PREFERRED_BACKGROUNDS",
    "PRIMARY_COLOR_MIN",
    "RULES",
    "ColorSpec",
    "Finding",
    "FontSpec",
    "background_findings",
    "check_brand_compliance",
    "color_catalog",
    "contrast_ratio",
    "element_findings",
    "evaluate_theme",
    "font_catalog",
    "font_family_findings",
    "font_files",
    "is_brand_font",
    "is_fallback",
    "rule_catalog",
    "rules_by_category",
]