"""Evaluation of extracted observations against the brand rules.

Colour math (neutral test, luminance, contrast) and font-weight parsing live in
`brand_audit_math`; typography rules (family/weight/size) live in
`brand_audit_typography`; this module owns the dispatch plus the colour,
contrast, background and document-level rules.

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
    is_neutral as _is_neutral,
)
from agentic_bi.brand_audit_types import AuditFinding, AuditReport
from agentic_bi.brand_audit_typography import (
    eval_font as _eval_font,
)
from agentic_bi.brand_audit_typography import (
    eval_font_size as _eval_font_size,
)
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


def _eval_contrast(
    text_colors: list[tuple[str, str]],
    backgrounds: list[tuple[str, str]],
    cfg: BrandConfig,
    rep: AuditReport,
) -> None:
    """Check text-to-background contrast (WCAG AA).

    Only a background that resolves to a real hex color can be measured; an
    unknown background is NOT replaced with white (that would silently pass a
    light-on-dark violation), the text colors are reported as un-assessed once.
    """
    if not cfg.rules.get("check_contrast", True):
        return
    valid_bg = [h for h, _ in backgrounds if h]
    min_c = float(cfg.min_contrast)
    skip_brand = bool(cfg.audit.get("contrast_skip_brand", True))
    checked = [
        (h, loc)
        for h, loc in text_colors
        if h and not _is_neutral(h) and not (skip_brand and cfg.match(h) is not None)
    ]
    if not valid_bg:
        if checked:
            _mk(
                rep,
                cfg,
                "BG-CONTRAST",
                None,
                "background",
                checked[0][1],
                "Background is unknown - text contrast could not be assessed.",
                "",
                "declare the slide/theme background so contrast can be measured",
            )
        return
    bg_default = valid_bg[0]
    for h, loc in checked:
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
        elif o.kind == "unresolved_paint":
            _mk(
                rep,
                cfg,
                "PAINT-UNRESOLVED",
                None,
                "color",
                o.location,
                f"Fill/line color could not be read ({o.context}) - not checked.",
                "",
                "gradient/pattern/picture fills are outside the palette check",
            )
        elif o.kind in ("font", "font_weight"):
            _eval_font(
                o, cfg, rep, ignore_fonts, fallback, allowed_fonts, allowed_weights, _mk
            )
        elif o.kind == "font_size":
            _eval_font_size(o, cfg, rep, _mk)

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
