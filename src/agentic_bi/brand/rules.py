"""Brand rule registry and thresholds used by the automated checks.

The rules are grouped into four categories: ``color``, ``font``,
``background`` and ``element``. Thresholds here are neutral; adjust them to your
own style guide.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from agentic_bi.brand.fonts import BRAND_WEIGHTS
from agentic_bi.brand.palette import PALETTE_PRIMARY

# The three base components of the logo/style: brand font, color, foundation.
BASE_ELEMENTS = ("font", "color", "foundation")
# The primary accent is mandatory.
MANDATORY_ACCENT = True
# Minimum number of primary-palette colors when extending the palette.
PRIMARY_COLOR_MIN = 2
# Minimum number of base elements in a communication: >=2 of 3.
BASE_ELEMENTS_MIN = 2
# Minimum text-to-background contrast (WCAG AA for normal text) — for readability.
MIN_CONTRAST_RATIO = 4.5

# Brand weights allowed by the style guide.
ALLOWED_WEIGHTS = tuple(BRAND_WEIGHTS)
# Preferred backgrounds for the logo/backdrops: white is ideal, black for the
# negative version; grey is recommended.
PREFERRED_BACKGROUNDS = {
    "#ffffff": "white - ideal and preferred background",
    "#000000": "black - for the negative logo version",
    "#4a4a4a": "Grey Dark - recommended grey",
    "#d9d9d9": "Grey Light - recommended light grey",
}
# System fallback fonts (not brand fonts, but acceptable in UI/Desktop).
FALLBACK_FONTS = (
    "segoe ui",
    "arial",
    "helvetica",
    "calibri",
    "lato",
    "roboto",
    "din",
    "open sans",
)

# HEX allowed in a theme without change (primary palette). The accent is mandatory.
_ACCEPTABLE_NO_VIOLATION = {c.hex.lower() for c in PALETTE_PRIMARY}

# Rule registry: id/level/category/rule/source. Categories:
#   color | font | background | element
RULES: tuple[dict, ...] = (
    # ── COLOR ───────────────────────────────────────────────
    {
        "id": "BRAND-ACCENT-MANDATORY",
        "level": "error",
        "category": "color",
        "rule": "The primary accent (#D32F2F) is MANDATORY in a communication.",
        "source": "brand book, color section",
    },
    {
        "id": "BRAND-PALETTE-MEMBERSHIP",
        "level": "warning",
        "category": "color",
        "rule": "Chromatic colors must be part of the brand palette "
        "(primary + additional).",
        "source": "brand book, color section",
    },
    {
        "id": "PAINT-UNRESOLVED",
        "level": "info",
        "category": "color",
        "rule": "A fill/line color could not be read (gradient/pattern/picture); "
        "it is outside the palette check and reported instead of skipped.",
        "source": "audit coverage guard",
    },
    {
        "id": "BRAND-PRIMARY-COLORS-MIN",
        "level": "warning",
        "category": "color",
        "rule": f"When extending the palette, use at least {PRIMARY_COLOR_MIN} colors "
        "from the primary range.",
        "source": "brand book, color section",
    },
    # ── FONT ────────────────────────────────────────────────
    {
        "id": "FONT-FAMILY-BRAND",
        "level": "warning",
        "category": "font",
        "rule": "Brand fonts are Brand Sans (display/headings) and Brand Sans Text "
        "(body text). Other families are a deviation from the brand book.",
        "source": "brand book, typography section",
    },
    {
        "id": "FONT-WEIGHT-ALLOWED",
        "level": "warning",
        "category": "font",
        "rule": "Allowed weights: " + ", ".join(ALLOWED_WEIGHTS) + " (+ Italic).",
        "source": "brand book, typography section",
    },
    {
        "id": "FONT-ROLE-ACCENT",
        "level": "info",
        "category": "font",
        "rule": "Headings/display use Brand Sans; body text uses Brand Sans Text.",
        "source": "brand book, typography section",
    },
    {
        "id": "FONT-SUBBRAND-TEXT-MEDIUM",
        "level": "info",
        "category": "font",
        "rule": "Sub-brands use Brand Sans Text Medium (low case, same size as in the logo).",
        "source": "brand book, sub-brand section",
    },
    # ── BACKGROUND ──────────────────────────────────────────
    {
        "id": "BG-ALLOWED",
        "level": "warning",
        "category": "background",
        "rule": "Background is white (ideal), black/grey (neutral) or a brand palette "
        "color. Any other chromatic background is a deviation.",
        "source": "brand book, background section",
    },
    {
        "id": "BG-WHITE-PREFERRED",
        "level": "info",
        "category": "background",
        "rule": "White is the preferred background in all versions.",
        "source": "brand book, background section",
    },
    {
        "id": "BG-CONTRAST",
        "level": "warning",
        "category": "background",
        "rule": f"Text-to-background contrast >= {MIN_CONTRAST_RATIO}:1 (readability).",
        "source": "brand book, background section; WCAG AA",
    },
    {
        "id": "BG-LOGO-NEGATIVE",
        "level": "info",
        "category": "background",
        "rule": "The negative logo version is placed on a black background (exception).",
        "source": "brand book, background section",
    },
    # ── ELEMENTS ────────────────────────────────────────────
    {
        "id": "ELEM-BASE-2OF3",
        "level": "info",
        "category": "element",
        "rule": "At least 2 of 3 base brand elements "
        "(brand color / font / foundation).",
        "source": "brand book, elements section",
    },
    {
        "id": "ELEM-FOUNDATION",
        "level": "info",
        "category": "element",
        "rule": 'The "foundation" is a recognizable element (underlining line/pattern) '
        "to connect to the brand without a direct logo.",
        "source": "brand book, foundation section",
    },
    {
        "id": "ELEM-LOGO-SAFE-ZONE",
        "level": "warning",
        "category": "element",
        "rule": "Around the logo keep a safe zone x/1.5x/2x; do not overlap elements.",
        "source": "brand book, logo section",
    },
    {
        "id": "ELEM-LOGO-BG",
        "level": "info",
        "category": "element",
        "rule": "The logo goes on a white background (positive version); white is ideal.",
        "source": "brand book, logo section",
    },
)

_CATEGORY_ORDER = ("color", "font", "background", "element")


@dataclass
class Finding:
    """A single brand-compliance violation / warning."""

    rule_id: str
    level: str  # error | warning | info
    message: str
    detail: str = ""
    category: str = ""  # color | font | background | element

    def as_dict(self) -> dict:
        return asdict(self)


def rule_catalog(category: str | None = None) -> list[dict]:
    """The rule catalog (id/level/category/rule/source), optionally by category."""
    return [
        {
            "id": r["id"],
            "level": r["level"],
            "category": r["category"],
            "rule": r["rule"],
            "source": r["source"],
        }
        for r in RULES
        if category is None or r["category"] == category
    ]


def rules_by_category() -> dict[str, list[dict]]:
    """Rules grouped by category (color/font/background/element)."""
    return {cat: rule_catalog(cat) for cat in _CATEGORY_ORDER}


__all__ = [
    "BASE_ELEMENTS",
    "MANDATORY_ACCENT",
    "PRIMARY_COLOR_MIN",
    "BASE_ELEMENTS_MIN",
    "MIN_CONTRAST_RATIO",
    "ALLOWED_WEIGHTS",
    "PREFERRED_BACKGROUNDS",
    "FALLBACK_FONTS",
    "RULES",
    "Finding",
    "rule_catalog",
    "rules_by_category",
]
