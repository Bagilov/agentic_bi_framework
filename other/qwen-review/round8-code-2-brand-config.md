# Bundle 2: brand config and palette

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/brand.py ====================

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
from agentic_bi.brand_fonts import (  # noqa: F401
    BRAND_ITALIC,
    BRAND_WEIGHTS,
    EMBEDDED_BRAND_FONTS,
    FONT_DIR,
    FONT_FILES,
    FONTS,
    FontSpec,
    font_catalog,
    font_files,
)
from agentic_bi.brand_palette import (  # noqa: F401
    PALETTE_ADDITIONAL,
    PALETTE_PRIMARY,
    ColorSpec,
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

==================== FILE: src/agentic_bi/brand_config.py ====================

"""Configuration for auditing documents against the brand style guide.

Reads ``brand_config.yaml`` (or JSON) and merges it with the defaults from
:mod:`brand`. Anything not set in the config is taken from ``brand.py`` - the
config contains only overrides and tolerances of a particular check.

Example:
    from agentic_bi.brand_config import BrandConfig
    cfg = BrandConfig.load("brand_config.yaml")        # or BrandConfig.default()
    cfg.all_palette          # {hex_norm: PaletteColor}
    cfg.severity_of("BG-CONTRAST")   # 'warning' | 'error' | 'info' | 'off'

Public API:
    PaletteColor        - a palette color (name/hex/mandatory/approx/ref)
    BrandConfig         - the effective audit configuration
    rgb_distance()      - Euclidean distance between two HEX colors (0..441)
    normalize_hex()     - normalize a color to '#rrggbb'
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import agentic_bi.brand as brand

_DEFAULT_SEVERITY = {
    "BRAND-ACCENT-MANDATORY": "error",
    "BRAND-PALETTE-MEMBERSHIP": "warning",
    "BRAND-PRIMARY-COLORS-MIN": "warning",
    "FONT-FAMILY-BRAND": "warning",
    "FONT-WEIGHT-ALLOWED": "warning",
    "FONT-SIZE-STEP": "info",
    "BG-ALLOWED": "warning",
    "BG-CONTRAST": "warning",
    "ELEM-BASE-2OF3": "info",
}


def normalize_hex(value: str | None) -> str:
    """Normalize a color to '#rrggbb' (lowercase); '' if not a hex color."""
    if not value:
        return ""
    v = str(value).strip().lstrip("#")
    if len(v) == 8:  # ARGB from openpyxl
        v = v[2:]
    if len(v) == 3:
        v = "".join(2 * ch for ch in v)
    if len(v) != 6:
        return ""
    try:
        int(v, 16)
    except ValueError:
        return ""
    return "#" + v.lower()


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = normalize_hex(hex_color)
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


def rgb_distance(a: str, b: str) -> float:
    """Euclidean distance between colors in RGB (0 = identical)."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5


def _normalize_severity(base: dict, override: dict) -> dict:
    """Merge severity, coercing YAML values to strings.

    YAML parses ``off``/``on``/``no``/``yes`` as bool - we map them back to
    ``off``/``info``, otherwise a rule cannot be disabled correctly.
    """
    out = dict(base)
    for k, v in (override or {}).items():
        if v is False:
            v = "off"
        elif v is True:
            v = "info"
        out[k] = str(v).lower()
    return out


@dataclass
class PaletteColor:
    """A palette color from the config."""

    name: str
    hex: str
    mandatory: bool = False
    approx: bool = False
    ref: str = ""


@dataclass
class BrandConfig:
    """The effective audit configuration (config + brand.py values)."""

    colors_primary: list[PaletteColor] = field(default_factory=list)
    colors_additional: list[PaletteColor] = field(default_factory=list)
    allow_extra: list[str] = field(default_factory=list)
    tolerance_rgb: int = 12
    fonts_allowed: list[str] = field(default_factory=list)
    fonts_fallback: list[str] = field(default_factory=list)
    weights: list[str] = field(default_factory=list)
    check_size_step: int = 2
    bg_preferred: list[str] = field(default_factory=list)
    bg_allowed: list[str] = field(default_factory=list)
    min_contrast: float = 4.5
    rules: dict = field(default_factory=dict)
    severity: dict = field(default_factory=dict)
    audit: dict = field(default_factory=dict)
    source: str = ""

    # ── construction ──────────────────────────────────────
    @classmethod
    def default(cls) -> BrandConfig:
        """The default configuration from brand.py."""
        cfg = cls(
            fonts_allowed=[f.family for f in brand.FONTS],
            fonts_fallback=list(brand.FALLBACK_FONTS),
            weights=list(brand.ALLOWED_WEIGHTS),
            bg_preferred=["#FFFFFF"],
            bg_allowed=[c.hex for c in brand.PALETTE_PRIMARY],
            min_contrast=brand.MIN_CONTRAST_RATIO,
            rules={
                "accent_mandatory": True,
                "primary_color_min": brand.PRIMARY_COLOR_MIN,
                "base_elements_min": brand.BASE_ELEMENTS_MIN,
                "check_contrast": True,
                "check_fonts": True,
                "check_colors": True,
            },
            severity=dict(_DEFAULT_SEVERITY),
            audit={
                "check_text_color": True,
                "check_fill_color": True,
                "check_line_color": True,
                "check_background": True,
                "ignore_layout_placeholders": True,
                "max_findings": 200,
                "accent_tolerance": 20,
                "ignore_fonts": ["+mn-lt", "+mj-lt", "+mn-ea", "+mj-ea"],
            },
        )
        cfg.colors_primary = [
            PaletteColor(c.name, c.hex, c.mandatory, c.approx, c.ref)
            for c in brand.PALETTE_PRIMARY
        ]
        cfg.colors_additional = [
            PaletteColor(c.name, c.hex, c.mandatory, c.approx, c.ref)
            for c in brand.PALETTE_ADDITIONAL
        ]
        return cfg

    @classmethod
    def from_dict(cls, data: dict, source: str = "") -> BrandConfig:
        """Build a config from a dict (over default())."""
        cfg = cls.default()
        cfg.source = source
        cols = data.get("colors", {})
        if cols.get("primary"):
            cfg.colors_primary = [PaletteColor(**c) for c in cols["primary"]]
        if cols.get("additional"):
            cfg.colors_additional = [PaletteColor(**c) for c in cols["additional"]]
        cfg.allow_extra = [normalize_hex(c) for c in cols.get("allow_extra", [])]
        cfg.tolerance_rgb = int(cols.get("tolerance_rgb", cfg.tolerance_rgb))

        fonts = data.get("fonts", {})
        if fonts.get("allowed"):
            cfg.fonts_allowed = list(fonts["allowed"])
        if fonts.get("fallback"):
            cfg.fonts_fallback = list(fonts["fallback"])
        if fonts.get("weights"):
            cfg.weights = list(fonts["weights"])
        cfg.check_size_step = int(fonts.get("check_size_step", cfg.check_size_step))

        bg = data.get("background", {})
        if bg.get("preferred"):
            cfg.bg_preferred = [normalize_hex(c) for c in bg["preferred"]]
        if bg.get("allowed"):
            cfg.bg_allowed = [normalize_hex(c) for c in bg["allowed"]]
        cfg.min_contrast = float(bg.get("min_contrast", cfg.min_contrast))

        cfg.rules = {**cfg.rules, **data.get("rules", {})}
        cfg.severity = _normalize_severity(cfg.severity, data.get("severity", {}))
        cfg.audit = {**cfg.audit, **data.get("audit", {})}
        return cfg

    @classmethod
    def load(cls, path: str | Path) -> BrandConfig:
        """Load a config from YAML/JSON."""
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("YAML needs PyYAML: uv pip install pyyaml") from exc
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        return cls.from_dict(data or {}, source=str(p))

    # ── derived ────────────────────────────────────────────
    @property
    def all_palette(self) -> dict[str, PaletteColor]:
        """{hex_norm: PaletteColor} over the whole palette."""
        out: dict[str, PaletteColor] = {}
        for c in (*self.colors_primary, *self.colors_additional):
            out[normalize_hex(c.hex)] = c
        return out

    @property
    def all_palette_hex(self) -> set[str]:
        return set(self.all_palette)

    @property
    def primary_hex(self) -> set[str]:
        return {normalize_hex(c.hex) for c in self.colors_primary}

    def match(self, hex_color: str) -> PaletteColor | None:
        """Find a palette color honoring the tolerance_rgb."""
        h = normalize_hex(hex_color)
        if not h:
            return None
        pal = self.all_palette
        if h in pal:
            return pal[h]
        for ph, pc in pal.items():
            tol = self.tolerance_rgb
            if pc.mandatory:
                tol = max(tol, int(self.audit.get("accent_tolerance", tol)))
            if rgb_distance(h, ph) <= tol:
                return pc
        return None

    def severity_of(self, rule_id: str) -> str:
        return self.severity.get(rule_id, "warning")

    def enabled(self, rule_id: str) -> bool:
        return self.severity_of(rule_id) != "off"

    def as_dict(self) -> dict:
        return asdict(self)

==================== FILE: src/agentic_bi/brand_rules.py ====================

"""Brand rule registry and thresholds used by the automated checks.

The rules are grouped into four categories: ``color``, ``font``,
``background`` and ``element``. Thresholds here are neutral; adjust them to your
own style guide.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from agentic_bi.brand_fonts import BRAND_WEIGHTS
from agentic_bi.brand_palette import PALETTE_PRIMARY

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

==================== FILE: src/agentic_bi/brand_palette.py ====================

"""Brand palette: color specifications and the primary/additional ranges.

This module is **organization-agnostic**: the palette below is a set of neutral
placeholders. Replace them with your own design tokens to enforce a real style.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ColorSpec:
    """A single brand color."""

    name: str
    hex: str
    role: str = ""
    ref: str = ""  # external reference (e.g. a swatch code), optional
    cmyk: str = ""
    rgb: tuple[int, int, int] | None = None
    mandatory: bool = False
    approx: bool = False  # True = RGB/HEX not authoritative, approximated

    def __post_init__(self) -> None:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", self.hex):
            raise ValueError(f"bad hex: {self.hex!r}")
        if self.rgb is None:
            object.__setattr__(
                self,
                "rgb",
                (
                    int(self.hex[1:3], 16),
                    int(self.hex[3:5], 16),
                    int(self.hex[5:7], 16),
                ),
            )


# Primary range ("Primary colors").
# NOTE: neutral placeholders - replace with your own design tokens.
PALETTE_PRIMARY: tuple[ColorSpec, ...] = (
    ColorSpec(
        name="Accent Red",
        hex="#D32F2F",
        role="primary accent - MANDATORY for use",
        ref="",
        cmyk="",
        rgb=(211, 47, 47),
        mandatory=True,
    ),
    ColorSpec(
        name="Black",
        hex="#000000",
        role="black",
        ref="",
        cmyk="C-0 M-0 Y-0 K-100",
        rgb=(0, 0, 0),
    ),
    ColorSpec(
        name="Grey Dark",
        hex="#4A4A4A",
        role="grey (dark)",
        ref="",
        cmyk="",
        rgb=(74, 74, 74),
    ),
    ColorSpec(
        name="Grey Light",
        hex="#D9D9D9",
        role="grey (light)",
        ref="",
        cmyk="",
        rgb=(217, 217, 217),
    ),
)

# Additional palette ("Additional colors").
# RGB/HEX may be approximated; flagged approx=True.
PALETTE_ADDITIONAL: tuple[ColorSpec, ...] = (
    ColorSpec(
        name="Violet",
        hex="#6020C0",
        role="sub-brands / complement to the primary range",
        ref="",
        approx=True,
    ),
    ColorSpec(
        name="Silver",
        hex="#A7A9AB",
        role="sub-brands / complement to the primary range (special effect)",
        ref="",
        approx=True,
    ),
    ColorSpec(
        name="Teal",
        hex="#00E0E0",
        role="sub-brands / complement to the primary range",
        ref="",
        approx=True,
    ),
)

_ALL_HEX: dict[str, ColorSpec] = {
    c.hex.lower(): c for c in (*PALETTE_PRIMARY, *PALETTE_ADDITIONAL)
}
_ALL_BY_NAME: dict[str, ColorSpec] = {
    c.name: c for c in (*PALETTE_PRIMARY, *PALETTE_ADDITIONAL)
}


__all__ = [
    "ColorSpec",
    "PALETTE_PRIMARY",
    "PALETTE_ADDITIONAL",
]

==================== FILE: src/agentic_bi/brand_fonts.py ====================

"""Brand fonts: family specifications, weights and the local font library.

This module is **organization-agnostic**: the families below are neutral
placeholders. Replace them with your own design tokens to enforce a real style.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FontSpec:
    """A brand font and its roles."""

    family: str
    app: str
    embedded: str = ""  # family name as embedded in a document (e.g. get_fonts)


FONTS: tuple[FontSpec, ...] = (
    FontSpec(
        "Brand Sans",
        "display, level 1-2 headings, short communications; geometric grotesque",
        embedded="BrandSans",
    ),
    FontSpec(
        "Brand Sans Text",
        "body text at large volumes (utilitarian), sub-brands "
        "(Brand Sans Text Medium low case, same size as in the logo)",
        embedded="BrandSansText",
    ),
)

# Brand weights: Regular/Light (+ Italic) - text; Medium - emphasis and level
# 1-2 headings; Bold; Black - display.
BRAND_WEIGHTS = ("Light", "Regular", "Medium", "Bold", "Black")
BRAND_ITALIC = tuple(f"{w} Italic" for w in BRAND_WEIGHTS)
# Confirmed embedded families (visible via get_fonts).
EMBEDDED_BRAND_FONTS = (
    "Brand Sans Light",
    "Brand Sans Regular",
    "Brand Sans Medium",
    "Brand Sans Bold",
    "Brand Sans Black",
    "Brand Sans Thin",
    "Brand Sans Text Light",
    "Brand Sans Text Regular",
    "Brand Sans Text Medium",
    "Brand Sans Text Bold",
    "Brand Sans Text Black",
)

# Local font library in the repository (assets/fonts).
FONT_DIR = "assets/fonts/Brand Sans"
FONT_FILES: dict[str, str] = {
    **{f"Brand Sans Thin{w}": f"Brand Sans-Thin{w}.otf" for w in ("", " Italic")},
    **{f"Brand Sans Light{w}": f"Brand Sans-Light{w}.otf" for w in ("", " Italic")},
    **{f"Brand Sans Regular{w}": f"Brand Sans-Regular{w}.otf" for w in ("", " Italic")},
    **{f"Brand Sans Medium{w}": f"Brand Sans-Medium{w}.otf" for w in ("", " Italic")},
    **{f"Brand Sans Bold{w}": f"Brand Sans-Bold{w}.otf" for w in ("", " Italic")},
    **{f"Brand Sans Black{w}": f"Brand Sans-Black{w}.otf" for w in ("", " Italic")},
}


def font_catalog() -> list[dict]:
    """The catalog of brand fonts."""
    return [asdict(f) for f in FONTS]


def font_files(repo_root: str | None = None) -> dict[str, str]:
    """Map font name -> file path in the local library.

    Args:
        repo_root: repository root; defaults to the current working directory.
    """
    from pathlib import Path

    base = Path(repo_root) if repo_root else Path.cwd()
    return {name: str(base / FONT_DIR / fname) for name, fname in FONT_FILES.items()}


__all__ = [
    "FontSpec",
    "FONTS",
    "BRAND_WEIGHTS",
    "BRAND_ITALIC",
    "EMBEDDED_BRAND_FONTS",
    "FONT_DIR",
    "FONT_FILES",
    "font_catalog",
    "font_files",
]

