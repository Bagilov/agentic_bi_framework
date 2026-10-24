# Bundle 1: brand audit

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/brand_audit.py ====================

"""Audit a document for compliance with the brand style.

Quickly locate places that deviate from the style guide: colors (text/fill/line/
background), fonts (family/weight/size) and rules (mandatory accent, at least 2
primary-range colors, "2 of 3" base elements). Driven by a
:class:`brand_config.BrandConfig` (defaults from :mod:`brand`).

This module is a thin facade + public entry points; the work lives in:
    brand_audit_types.py   - AuditFinding / AuditReport
    brand_audit_extract.py - ThemeResolver + observation extraction from .pptx
    brand_audit_eval.py    - evaluation of observations against the rules

Supported:
    - direct RGB colors and **theme (scheme) colors** (resolved via theme1.xml);
    - nested group shapes (recursively);
    - tables (cell -> paragraph -> run);
    - font weights and sizes.

Example:
    from agentic_bi.brand_audit import audit_pptx
    rep = audit_pptx("Presentation.pptx")
    print(rep.format())            # a readable report with locations
    rep.to_json("audit.json")      # a machine-readable result

CLI:
    python -m agentic_bi.brand_audit deck.pptx --config brand_config.yaml
    python -m agentic_bi.brand_audit deck.pptx --json report.json --fail-on error

Public API:
    AuditFinding   - a single non-compliance (rule/level/location/value)
    AuditReport    - the finding set + summary/format/to_json
    ThemeResolver  - resolves theme (scheme) colors to HEX
    audit_pptx(path, cfg=None)      -> AuditReport
    audit_document(path, cfg=None)  -> AuditReport   (pptx/docx/xlsx)

CLI exit codes: 0 normally (findings are reported, not fatal), 1 when `--fail-on`
is set and matched, 2 on a bad input (unreadable config / unsupported format).
"""

from __future__ import annotations

import logging
from pathlib import Path

from agentic_bi.brand_audit_eval import (  # noqa: F401
    evaluate_observations,
    limit_findings,
)
from agentic_bi.brand_audit_extract import (  # noqa: F401
    ThemeResolver,
    iter_pptx_observations,
)
from agentic_bi.brand_audit_types import (  # noqa: F401
    AuditFinding,
    AuditReport,
)
from agentic_bi.brand_config import BrandConfig
from agentic_bi.brand_eval import is_brand_font  # noqa: F401 (public re-export)

logger = logging.getLogger(__name__)


def audit_pptx(path: str | Path, cfg: BrandConfig | None = None) -> AuditReport:
    """Check a `.pptx` presentation for brand compliance."""
    cfg = cfg or BrandConfig.default()
    rep = AuditReport(path=str(path))
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "python-pptx is required: uv pip install python-pptx"
        ) from exc
    try:
        prs = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001 - corrupted/non-pptx file
        logger.warning("could not open %s: %s", path, exc)
        rep.add(
            AuditFinding(
                "DOC-UNREADABLE",
                "error",
                "document",
                str(path),
                f"File does not open as .pptx: {exc}",
                str(path),
            )
        )
        return rep
    theme = (
        ThemeResolver.from_presentation(prs)
        if cfg.audit.get("resolve_theme_colors", True)
        else ThemeResolver()
    )
    obs = iter_pptx_observations(prs, cfg, theme)
    rep.theme = theme.as_dict()
    rep.stats = {
        "slides": len(prs.slides),
        "color_observations": sum(1 for o in obs if o.kind != "font"),
        "font_observations": sum(1 for o in obs if o.kind == "font"),
        "theme_slots": len(theme.slots),
    }
    rep.stats["theme_colors_resolved"] = sum(1 for o in obs if o.from_theme)
    evaluate_observations(obs, cfg, rep)
    limit_findings(rep, cfg)
    return rep


def audit_document(path: str | Path, cfg: BrandConfig | None = None) -> AuditReport:
    """Check a document by extension (.pptx/.docx/.xlsx)."""
    ext = Path(path).suffix.lower()
    if ext == ".pptx":
        return audit_pptx(path, cfg)
    raise NotImplementedError(f"format {ext!r} is not supported yet (.pptx only)")


def main(argv: list[str] | None = None) -> int:
    import argparse

    from agentic_bi.cli_support import run_boundary

    ap = argparse.ArgumentParser(
        prog="agentic-bi-brand-audit",
        description="Audit a document for brand-style compliance",
    )
    ap.add_argument("document", help="path to a .pptx")
    ap.add_argument("--config", default=None, help="brand_config.yaml/json")
    ap.add_argument("--json", dest="json_out", default=None, help="save JSON")
    ap.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="never",
        help="exit code 1 on findings of this level",
    )
    args = ap.parse_args(argv)

    def body() -> int:
        cfg = BrandConfig.load(args.config) if args.config else BrandConfig.default()
        rep = audit_document(args.document, cfg)
        print(rep.format(max_findings=int(cfg.audit.get("max_findings", 0) or 0)))
        if args.json_out:
            rep.to_json(args.json_out)
            print(f"\nJSON: {args.json_out}")

        if args.fail_on == "error" and rep.errors:
            return 1
        if args.fail_on == "warning" and (rep.errors or rep.warnings):
            return 1
        return 0

    return run_boundary(body, prog="agentic-bi-brand-audit")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuditFinding",
    "AuditReport",
    "ThemeResolver",
    "audit_document",
    "audit_pptx",
    "is_brand_font",
]

==================== FILE: src/agentic_bi/brand_audit_eval.py ====================

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

==================== FILE: src/agentic_bi/brand_audit_extract.py ====================

"""Observation extraction from a `.pptx` presentation (colors/fonts).

Reuses python-pptx (optional). Resolves both direct RGB colors and theme
(scheme) colors via the presentation theme, traverses groups and tables, and
emits flat observations with their location.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agentic_bi.brand_config import BrandConfig, normalize_hex

logger = logging.getLogger(__name__)

_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_THEME_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"

# Theme scheme slots (scheme tag -> key)
_SCHEME_TAGS = {
    "dk1": "dk1",
    "lt1": "lt1",
    "dk2": "dk2",
    "lt2": "lt2",
    "accent1": "accent1",
    "accent2": "accent2",
    "accent3": "accent3",
    "accent4": "accent4",
    "accent5": "accent5",
    "accent6": "accent6",
    "hlink": "hlink",
    "folHlink": "folHlink",
}

# MSO_THEME_COLOR semantic names -> scheme slot
_THEME_SLOT = {
    "DARK_1": "dk1",
    "LIGHT_1": "lt1",
    "DARK_2": "dk2",
    "LIGHT_2": "lt2",
    "TEXT_1": "dk1",
    "BACKGROUND_1": "lt1",
    "TEXT_2": "dk2",
    "BACKGROUND_2": "lt2",
    "ACCENT_1": "accent1",
    "ACCENT_2": "accent2",
    "ACCENT_3": "accent3",
    "ACCENT_4": "accent4",
    "ACCENT_5": "accent5",
    "ACCENT_6": "accent6",
    "HYPERLINK": "hlink",
    "FOLLOWED_HYPERLINK": "folHlink",
}


class ThemeResolver:
    """Resolve a presentation's theme (scheme) colors to HEX.

    Reads the master's ``ppt/theme/theme1.xml``: the ``clrScheme`` (dk1/lt1/
    accent1-6/hlink/...). Needed because most shapes use theme colors rather than
    direct RGB.
    """

    def __init__(self) -> None:
        self.slots: dict[str, str] = {}

    @classmethod
    def from_presentation(cls, prs) -> ThemeResolver:
        tr = cls()
        for master in prs.slide_masters:
            try:
                part = master.part.part_related_by(_THEME_REL)
                tr._parse(part.blob)
                if tr.slots:
                    return tr
            except Exception as exc:  # noqa: BLE001
                logger.debug("theme parse failed: %s", exc)
        return tr

    def _parse(self, blob: bytes) -> None:
        from lxml import etree

        try:
            root = etree.fromstring(blob)
        except Exception as exc:  # noqa: BLE001
            logger.debug("theme xml invalid: %s", exc)
            return
        scheme = root.find(f".//{{{_A_NS}}}clrScheme")
        if scheme is None:
            return
        for child in scheme:
            tag = etree.QName(child).localname
            key = _SCHEME_TAGS.get(tag)
            if not key:
                continue
            srgb = child.find(f"{{{_A_NS}}}srgbClr")
            sysc = child.find(f"{{{_A_NS}}}sysClr")
            val = ""
            if srgb is not None:
                val = srgb.get("val", "")
            elif sysc is not None:
                val = sysc.get("lastClr", "")
            if val:
                self.slots[key] = normalize_hex(val)

    def resolve(self, theme_color) -> str:
        """MSO_THEME_COLOR -> HEX ('' if it cannot be resolved)."""
        if theme_color is None:
            return ""
        slot = _THEME_SLOT.get(str(theme_color).split(".")[-1].split(" ")[0])
        if not slot:
            # sometimes it arrives as 'ACCENT_1 (5)'
            for name, s in _THEME_SLOT.items():
                if name in str(theme_color):
                    slot = s
                    break
        return self.slots.get(slot, "") if slot else ""

    def as_dict(self) -> dict:
        return dict(self.slots)


@dataclass
class Observation:
    """An observation: a color/font with a location and context."""

    kind: str  # text_color|fill|line|background|font|font_weight|font_size
    value: str
    location: str
    context: str = ""
    from_theme: bool = False


def color_hex(color_format, theme: ThemeResolver) -> tuple[str, bool]:
    """HEX + a 'from theme' flag from a ColorFormat ('' if not set)."""
    try:
        if color_format is None or color_format.type is None:
            return "", False
        name = str(color_format.type)
        if "RGB" in name:
            return normalize_hex(str(color_format.rgb)), False
        if "SCHEME" in name:
            h = theme.resolve(color_format.theme_color)
            return h, bool(h)
    except Exception as exc:  # noqa: BLE001 - theme/inherited color
        logger.debug("color resolve failed: %s", exc)
    return "", False


def iter_pptx_observations(
    prs, cfg: BrandConfig, theme: ThemeResolver
) -> list[Observation]:
    """Collect all observations from the presentation (including groups and tables)."""
    obs: list[Observation] = []
    for si, slide in enumerate(prs.slides, start=1):
        page = f"slide {si}"
        if cfg.audit.get("check_background", True):
            bg = _slide_background(slide, theme)
            if bg:
                obs.append(Observation("background", bg, f"{page} / background"))
        for shape in slide.shapes:
            obs.extend(_shape_observations(shape, page, cfg, theme))
    return obs


def _slide_background(slide, theme: ThemeResolver) -> str:
    try:
        fill = slide.background.fill
        if fill.type is not None and "SOLID" in str(fill.type):
            h, _ = color_hex(fill.fore_color, theme)
            return h
    except Exception as exc:  # noqa: BLE001
        logger.debug("slide background unavailable: %s", exc)
    return ""


def _is_placeholder(shape) -> bool:
    try:
        return bool(shape.is_placeholder)
    except Exception:  # noqa: BLE001
        return False


def _shape_observations(
    shape, page: str, cfg: BrandConfig, theme: ThemeResolver
) -> list[Observation]:
    """Observations for one shape (recursively into groups)."""
    obs: list[Observation] = []
    name = shape.name or str(shape.shape_type)
    loc = f"{page} / shape '{name}'"

    # group shapes: traverse nested ones
    try:
        if shape.shape_type is not None and "GROUP" in str(shape.shape_type):
            for child in shape.shapes:
                obs.extend(_shape_observations(child, loc, cfg, theme))
            return obs
    except Exception as exc:  # noqa: BLE001
        logger.debug("group traversal failed at %s: %s", loc, exc)

    # layout placeholders: do not check fill/line (inherited from the master)
    skip_style = _is_placeholder(shape) and cfg.audit.get(
        "ignore_layout_placeholders", True
    )

    if not skip_style and cfg.audit.get("check_fill_color", True):
        obs.extend(_paint_observations(shape, "fill", loc, theme))
    if not skip_style and cfg.audit.get("check_line_color", True):
        obs.extend(_paint_observations(shape, "line", loc, theme))

    if cfg.audit.get("check_text_color", True) or cfg.rules.get("check_fonts", True):
        if getattr(shape, "has_text_frame", False):
            obs.extend(_textframe_observations(shape.text_frame, loc, cfg, theme))
        if getattr(shape, "has_table", False):
            for ri, row in enumerate(shape.table.rows):
                for ci, cell in enumerate(row.cells):
                    obs.extend(
                        _textframe_observations(
                            cell.text_frame, f"{loc} / table[{ri}][{ci}]", cfg, theme
                        )
                    )
    return obs


def _paint_observations(
    shape, kind: str, loc: str, theme: ThemeResolver
) -> list[Observation]:
    try:
        if kind == "fill":
            fill = shape.fill
            if fill.type is not None and "SOLID" in str(fill.type):
                h, t = color_hex(fill.fore_color, theme)
                if h:
                    return [Observation("fill", h, f"{loc} / fill", from_theme=t)]
        else:
            h, t = color_hex(shape.line.color, theme)
            if h:
                return [Observation("line", h, f"{loc} / line", from_theme=t)]
    except Exception as exc:  # noqa: BLE001 - a shape may have no fill/line
        logger.debug("%s color unavailable at %s: %s", kind, loc, exc)
    return []


def _textframe_observations(
    tf, loc: str, cfg: BrandConfig, theme: ThemeResolver
) -> list[Observation]:
    obs: list[Observation] = []
    if tf is None:
        return obs
    for pi, para in enumerate(tf.paragraphs):
        for ri, run in enumerate(para.runs):
            rloc = f"{loc} / p{pi}r{ri}"
            if cfg.audit.get("check_text_color", True):
                h, t = color_hex(run.font.color, theme)
                if h:
                    obs.append(
                        Observation("text_color", h, f"{rloc} / text", from_theme=t)
                    )
            if cfg.rules.get("check_fonts", True):
                fname = run.font.name
                if fname:
                    obs.append(Observation("font", fname, f"{rloc} / font"))
                    obs.append(Observation("font_weight", fname, f"{rloc} / weight"))
                    if cfg.audit.get("check_font_size", False) and run.font.size:
                        size = round(run.font.size.pt, 1)
                        obs.append(
                            Observation("font_size", str(size), f"{rloc} / size")
                        )
    return obs


__all__ = [
    "ThemeResolver",
    "Observation",
    "color_hex",
    "iter_pptx_observations",
]

==================== FILE: src/agentic_bi/brand_audit_math.py ====================

"""Color/contrast math and font-weight parsing for the brand audit.

These are the dependency-free primitives shared by the observation evaluators:
WCAG relative luminance, a neutral (achromatic) test, the contrast ratio and the
weight token extracted from a font-family name.

Colors arrive as raw strings from a `.pptx`; every entry point normalizes first,
so callers may pass `#abc`, `abc`, `#AABBCC` or `AABBCC` interchangeably.

Public API:
    is_neutral(hex_color) -> bool
    luminance(hex_color) -> float
    contrast(fg, bg) -> float
    font_weight(name) -> str
    WEIGHT_KEYWORDS        - recognized weight tokens (longest first)
"""

from __future__ import annotations

from agentic_bi.brand_config import normalize_hex

# Weight tokens in a family name, longest first so "extrabold" wins over "bold".
WEIGHT_KEYWORDS = (
    "thin",
    "extralight",
    "ultralight",
    "light",
    "regular",
    "normal",
    "book",
    "medium",
    "semibold",
    "demibold",
    "bold",
    "extrabold",
    "black",
    "heavy",
)


def is_neutral(hex_color: str) -> bool:
    """Whether the color is achromatic (R == G == B): grey/white/black."""
    h = normalize_hex(hex_color)
    if not h:
        return False
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return r == g == b


def luminance(hex_color: str) -> float:
    """WCAG relative luminance of a hex color (0.0 = black, 1.0 = white)."""
    h = normalize_hex(hex_color)
    ch = [int(h[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio between a foreground and a background color."""
    l1, l2 = luminance(fg), luminance(bg)
    lo, hi = min(l1, l2), max(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


def font_weight(name: str) -> str:
    """The font weight from the family name ('' if not recognized)."""
    low = name.lower()
    for w in (
        "extrabold",
        "ultralight",
        "semibold",
        "demibold",
        "extralight",
        "regular",
        "medium",
        "light",
        "black",
        "heavy",
        "bold",
        "book",
        "normal",
        "thin",
    ):
        if w in low:
            return w
    return ""

==================== FILE: src/agentic_bi/brand_audit_types.py ====================

"""Result types for the document brand audit."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

_LEVEL_RANK = {"error": 3, "warning": 2, "info": 1, "off": 0}


@dataclass
class AuditFinding:
    """A single brand-book non-compliance."""

    rule_id: str
    level: str  # error | warning | info
    category: str  # color | font | background | element
    location: str  # e.g. 'slide 3 / shape "Title 1" / run 0'
    message: str
    value: str = ""  # the actual value (hex/font/...)
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditReport:
    """The document audit result."""

    path: str = ""
    findings: list[AuditFinding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    theme: dict = field(default_factory=dict)

    @property
    def errors(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.level == "warning"]

    def ok(self) -> bool:
        return not self.errors

    def by_category(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.category] = out.get(f.category, 0) + 1
        return out

    def by_rule(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.rule_id] = out.get(f.rule_id, 0) + 1
        return out

    def add(self, f: AuditFinding) -> None:
        self.findings.append(f)

    def to_json(self, path: str | Path | None = None) -> str:
        payload = {
            "path": self.path,
            "summary": {
                "total": len(self.findings),
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "by_category": self.by_category(),
                "by_rule": self.by_rule(),
                "document": self.stats,
            },
            "theme_colors": self.theme,
            "findings": [f.as_dict() for f in self.findings],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if path:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def format(self, max_findings: int = 0) -> str:
        if not self.findings:
            return f"OK: {self.path} - no non-compliances found."
        info = len([f for f in self.findings if f.level == "info"])
        summary = (
            f"  total: {len(self.findings)} (error={len(self.errors)}, "
            f"warning={len(self.warnings)}, info={info})"
        )
        lines = [
            f"Audit: {self.path}",
            summary,
            f"  by category: {self.by_category()}",
            f"  by rule: {self.by_rule()}",
            "",
        ]
        shown = self.findings[:max_findings] if max_findings else self.findings
        for f in shown:
            lines.append(f"  [{f.level.upper():7}] {f.rule_id} @ {f.location}")
            lines.append(f"            {f.message}")
            if f.value:
                lines.append(f"            value: {f.value}")
        if max_findings and len(self.findings) > max_findings:
            lines.append(f"  ... {len(self.findings) - max_findings} more")
        return "\n".join(lines)


__all__ = ["AuditFinding", "AuditReport"]

