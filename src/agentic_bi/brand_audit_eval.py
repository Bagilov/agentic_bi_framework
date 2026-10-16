"""Evaluation of extracted observations against the brand rules.

Colour math (neutral test, luminance, contrast) and font-weight parsing live in
`brand_audit_math`; this module owns the rule dispatch and the individual rules
(colors, fonts, contrast, background, document-level, font size).

Public API:
    evaluate_observations(obs, cfg, rep) -> None
    limit_findings(rep, cfg) -> None
"""

from __future__ import annotations

from agentic_bi.brand_audit_extract import Observation
from agentic_bi.brand_audit_math import (
    contrast as _contrast,
)
from agentic_bi.brand_audit_math import (
    font_weight as _font_weight,
)
from agentic_bi.brand_audit_math import (
    is_neutral as _is_neutral,
)
from agentic_bi.brand_audit_types import AuditFinding, AuditReport
from agentic_bi.brand_config import BrandConfig, normalize_hex
from agentic_bi.brand_eval import is_brand_font

_LEVEL_RANK = {"error": 3, "warning": 2, "info": 1, "off": 0}


def _mk(
    rep: AuditReport,
    cfg: BrandConfig,
    rule_id: str,
    level: str | None,
    category: str,
    location: str,
    message: str,
    value: str = "",
    detail: str = "",
) -> None:
    if not cfg.enabled(rule_id):
        return
    lvl = level or cfg.severity_of(rule_id)
    rep.add(AuditFinding(rule_id, lvl, category, location, message, value, detail))


def _eval_colors(o: Observation, cfg: BrandConfig, rep: AuditReport) -> None:
    """Evaluate a color observation (text/fill/line) against the palette."""
    if not cfg.rules.get("check_colors", True):
        return
    h = normalize_hex(o.value)
    if not h or _is_neutral(h) or h in cfg.allow_extra:
        return
    if cfg.match(h) is None:
        _mk(
            rep,
            cfg,
            "BRAND-PALETTE-MEMBERSHIP",
            None,
            "color",
            o.location,
            f"Color {h} is outside the brand palette."
            + (" (from theme)" if o.from_theme else ""),
            o.value,
            "palette colors allowed; neutral backgrounds/black/white are ok",
        )


def _is_allowed_font(name: str, allowed: set[str], fallback: set[str]) -> bool:
    """Whether a family is allowed: a brand family or a system fallback."""
    low = str(name).lower().strip()
    if not low:
        return True
    if is_brand_font(low):
        # brand font - but must match a specific allowed family
        return any(a in low for a in allowed)
    return any(fb in low for fb in fallback)


def _eval_font(
    o: Observation,
    cfg: BrandConfig,
    rep: AuditReport,
    ignore_fonts: set[str],
    fallback: set[str],
    allowed_fonts: set[str],
    allowed_weights: set[str],
) -> None:
    """Evaluate a family/weight observation."""
    if not cfg.rules.get("check_fonts", True):
        return
    fn = o.value.lower().strip()
    if o.kind == "font":
        if fn in ignore_fonts:
            return
        if _is_allowed_font(o.value, allowed_fonts, fallback):
            return
        _mk(
            rep,
            cfg,
            "FONT-FAMILY-BRAND",
            None,
            "font",
            o.location,
            f"Family '{o.value}' is not a brand one.",
            o.value,
            "allowed: brand fonts or a system fallback",
        )
    elif o.kind == "font_weight":
        if not allowed_weights or not is_brand_font(o.value):
            return  # only check weight for brand families
        w = _font_weight(o.value)
        if w and w not in allowed_weights:
            _mk(
                rep,
                cfg,
                "FONT-WEIGHT-ALLOWED",
                None,
                "font",
                o.location,
                f"Disallowed weight '{w}' on {o.value}.",
                o.value,
                "allowed: " + ", ".join(cfg.weights),
            )


def _eval_contrast(
    text_colors: list[tuple[str, str]],
    backgrounds: list[tuple[str, str]],
    cfg: BrandConfig,
    rep: AuditReport,
) -> None:
    """Check text-to-background contrast (WCAG AA)."""
    if not cfg.rules.get("check_contrast", True):
        return
    bg_default = backgrounds[0][0] if backgrounds else "#ffffff"
    min_c = float(cfg.min_contrast)
    skip_brand = bool(cfg.audit.get("contrast_skip_brand", True))
    for h, loc in text_colors:
        if not h or _is_neutral(h):
            continue
        if skip_brand and cfg.match(h) is not None:
            continue  # brand colors are sanctioned by the style guide
        ratio = _contrast(h, bg_default)
        if ratio < min_c:
            _mk(
                rep,
                cfg,
                "BG-CONTRAST",
                None,
                "background",
                loc,
                f"Low contrast of text {h} to background {bg_default}: "
                f"{ratio}:1 (needs >= {min_c}:1).",
                f"{ratio}:1",
            )


def _eval_background(
    backgrounds: list[tuple[str, str]], cfg: BrandConfig, rep: AuditReport
) -> None:
    """Check background validity."""
    if not cfg.rules.get("check_colors", True):
        return
    for h, loc in backgrounds:
        if h and not (
            _is_neutral(h)
            or h in cfg.bg_preferred
            or h in cfg.bg_allowed
            or cfg.match(h)
        ):
            _mk(
                rep,
                cfg,
                "BG-ALLOWED",
                None,
                "background",
                loc,
                f"Disallowed background {h}.",
                h,
                "white/black/grey or a palette color",
            )


def _eval_document_rules(
    obs: list[Observation], cfg: BrandConfig, rep: AuditReport
) -> None:
    """Document-level rules: mandatory accent, min 2 of 3."""
    all_colors = {
        normalize_hex(o.value)
        for o in obs
        if o.kind in ("text_color", "fill", "line") and o.value
    }
    chromatic = {
        c for c in all_colors if c and not _is_neutral(c) and c not in cfg.allow_extra
    }
    matched_primary = {
        normalize_hex(m.hex)
        for c in chromatic
        if (m := cfg.match(c)) and normalize_hex(m.hex) in cfg.primary_hex
    }
    accent_hex = next(
        (c.hex.lower() for c in cfg.colors_primary if c.mandatory), "#d32f2f"
    )

    if cfg.rules.get("accent_mandatory", True) and accent_hex not in matched_primary:
        _mk(
            rep,
            cfg,
            "BRAND-ACCENT-MANDATORY",
            "error",
            "color",
            "document",
            f"The mandatory primary accent {accent_hex.upper()} was not found.",
            "",
            "the primary accent is mandatory in a communication",
        )

    min_primary = int(cfg.rules.get("primary_color_min", 2))
    extended = bool(chromatic - cfg.primary_hex)
    if extended and min_primary and len(matched_primary) < min_primary:
        _mk(
            rep,
            cfg,
            "BRAND-PRIMARY-COLORS-MIN",
            None,
            "color",
            "document",
            f"The palette is extended but only {len(matched_primary)} primary-range "
            f"color(s) are used (minimum {min_primary}).",
            ", ".join(sorted(matched_primary)),
        )

    min_base = int(cfg.rules.get("base_elements_min", 0) or 0)
    if min_base:
        has_color = bool(matched_primary)
        has_font = bool(cfg.rules.get("check_fonts", True)) and any(
            o.kind == "font" and is_brand_font(o.value) for o in obs
        )
        has_foundation = bool(cfg.audit.get("foundation_present", False))
        count = sum((has_color, has_font, has_foundation))
        if count < min_base:
            _mk(
                rep,
                cfg,
                "ELEM-BASE-2OF3",
                "info",
                "element",
                "document",
                f"{count} of 3 base brand elements are used "
                f"(at least {min_base} required).",
                "counted: brand color / brand font / foundation",
            )


def _eval_font_size(o: Observation, cfg: BrandConfig, rep: AuditReport) -> None:
    """Check the font-size step (non-designer values)."""
    if not cfg.audit.get("check_font_size", False):
        return
    try:
        size = float(o.value)
    except ValueError:
        return
    step = int(cfg.check_size_step or 0)
    if step and round(size / step) != size / step:
        _mk(
            rep,
            cfg,
            "FONT-SIZE-STEP",
            "info",
            "font",
            o.location,
            f"Size {size}pt is not a multiple of {step}pt (non-designer step).",
            o.value,
        )


def evaluate_observations(
    obs: list[Observation], cfg: BrandConfig, rep: AuditReport
) -> None:
    """Run the observations through all brand rules."""
    ignore_fonts = {f.lower() for f in cfg.audit.get("ignore_fonts", [])}
    fallback = {f.lower() for f in cfg.fonts_fallback}
    allowed_fonts = {f.lower() for f in cfg.fonts_allowed}
    allowed_weights = {w.lower() for w in cfg.weights}
    backgrounds: list[tuple[str, str]] = []
    check_color = cfg.audit.get("check_text_color", True)

    for o in obs:
        if o.kind == "text_color":
            if check_color:
                _eval_colors(o, cfg, rep)
        elif o.kind in ("fill", "line"):
            if cfg.audit.get(f"check_{o.kind}_color", True):
                _eval_colors(o, cfg, rep)
        elif o.kind == "background":
            backgrounds.append((normalize_hex(o.value), o.location))
        elif o.kind in ("font", "font_weight"):
            _eval_font(
                o, cfg, rep, ignore_fonts, fallback, allowed_fonts, allowed_weights
            )
        elif o.kind == "font_size":
            _eval_font_size(o, cfg, rep)

    text_colors = (
        [
            (normalize_hex(o.value), o.location)
            for o in obs
            if o.kind == "text_color" and o.value
        ]
        if check_color
        else []
    )
    _eval_contrast(text_colors, backgrounds, cfg, rep)
    _eval_background(backgrounds, cfg, rep)
    _eval_document_rules(obs, cfg, rep)


def limit_findings(rep: AuditReport, cfg: BrandConfig) -> None:
    n = int(cfg.audit.get("max_findings", 0) or 0)
    if n and len(rep.findings) > n:
        rep.findings = sorted(rep.findings, key=lambda f: -_LEVEL_RANK.get(f.level, 0))[
            :n
        ]


__all__ = ["evaluate_observations", "limit_findings"]
