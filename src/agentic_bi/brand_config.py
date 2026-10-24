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
    "PAINT-UNRESOLVED": "info",
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
