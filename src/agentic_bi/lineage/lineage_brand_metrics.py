"""Brand-compliance metrics of a dashboard page's elements.

Embedded in the data-lineage process: for each page it computes the compliance
of the **used fonts and colors** with the corporate style. The result is
compliance percentages (fonts/colors), a level (`ok`/`warning`/`error`/`unknown`)
and a list of `color`/`font` findings.

The single source of rules is :class:`agentic_bi.brand.config.BrandConfig`
(palette/ΔRGB tolerance/`allow_extra`/fonts/weights/severity). It is the same
config as the document audit (`brand_audit.py`), so tolerances and severity are
set in one place (`brand_config.yaml`).

The metrics go into:
- the `PbiLineage.to_json()` JSON -> the `brand` key (+ `pages[].brand`);
- the PlantUML diagram, layer 7 "Elements and palette" (metrics on the page node);
- the flat matrix `lineage_table.py` ("Brand book · ..." columns) - right side.

Neutral colors (R==G==B) are not violations. The primary accent is recognized with a
"near-accent" tolerance (`#D0302A`/`#D3212A`).

Public API:
    page_brand_metrics(page, cfg=None)  -> dict  - metrics of one page
    visual_brand_metrics(visual, cfg=None) -> dict - metrics of one visual
    brand_audit_pages(pages, cfg=None)  -> dict  - metrics of all pages + summary
    brand_label(metrics)                -> str   - a string for PlantUML/report

Token, config and finding primitives are owned by
:mod:`agentic_bi.lineage.lineage_brand_primitives`.
"""

from __future__ import annotations

import logging

from agentic_bi.lineage.lineage_brand_primitives import (
    _PLACEHOLDER_FONTS,
    _allow_extra,
    _clean_fonts,
    _finding,
    _hex_from,
    _is_neutral,
    _load_config,
    _pct,
)

_log = logging.getLogger(__name__)

__all__ = [
    "_LEVEL_ORDER",
    "_log",
    "_PLACEHOLDER_FONTS",
    "_allow_extra",
    "_clean_fonts",
    "_finding",
    "_hex_from",
    "_is_neutral",
    "_load_config",
    "_pct",
    "brand_audit_pages",
    "brand_label",
    "page_brand_metrics",
    "visual_brand_metrics",
]


# Size exception (>300 lines): page and visual metrics share one palette/font
# evaluation; splitting them duplicated the rules and they drifted once already.


def _split_colors(tokens: object) -> tuple[set[str], int]:
    """Resolve colour tokens into hex values; count the ones that stay unresolved.

    `_collect_colors` emits `theme#<ColorId>` for a `ThemeDataColor` reference,
    and the theme itself is not part of the lineage JSON, so those ids cannot be
    turned into hex here. They used to be discarded silently: a page whose only
    colours were theme tokens reported `colors.total = 0`, `compliance = None`
    and — because a compliant font was enough — `level = "ok"`, i.e. "verified
    clean" for data that were never read. Counting them lets the caller say
    "no colour data" instead.
    """
    raw: set[str] = set()
    unresolved = 0
    for token in tokens if isinstance(tokens, (list, tuple, set)) else []:
        if not isinstance(token, str):
            continue
        hexv = _hex_from(token)
        if hexv:
            raw.add(hexv)
        elif token.strip():
            unresolved += 1
    return raw, unresolved


def page_brand_metrics(page: dict, cfg=None) -> dict:
    """Brand-book compliance metrics of one page.

    Args:
        page: an element of the `pages` list from `PbiLineage.to_json()` (or a
            compatible dict with `colors[]` and `fonts[]` keys).
        cfg: :class:`BrandConfig`; defaults to `brand_config.yaml`/`brand.py`.

    Returns:
        A metrics dict: font/color percentages, level, findings.
    """
    if cfg is None:
        cfg = _load_config()

    raw_colors, unresolved = _split_colors(page.get("colors"))
    chromatic = sorted(c for c in raw_colors if not _is_neutral(c))
    allow_extra = _allow_extra(cfg)
    off_palette = sorted(
        c for c in chromatic if cfg.match(c) is None and c not in allow_extra
    )
    has_accent = any((m := cfg.match(c)) and m.mandatory for c in chromatic)
    color_compliance = _pct(len(chromatic) - len(off_palette), len(chromatic))

    fonts = _clean_fonts(page.get("fonts"))
    allowed = [f.lower() for f in cfg.fonts_allowed]
    fallback = [f.lower() for f in cfg.fonts_fallback]
    brand_fonts = [f for f in fonts if any(a in f.lower() for a in allowed)]
    off_fonts = [
        f
        for f in fonts
        if not any(a in f.lower() for a in allowed)
        and not any(fb in f.lower() for fb in fallback)
    ]
    font_compliance = _pct(len(fonts) - len(off_fonts), len(fonts))

    # --- color/font findings (severity from the config) ---
    findings: list[dict] = []
    if chromatic and not has_accent:
        findings.append(
            _finding(
                "BRAND-ACCENT-MANDATORY",
                cfg.severity_of("BRAND-ACCENT-MANDATORY"),
                "color",
                "The mandatory primary accent #D32F2F was not found.",
            )
        )
    if off_palette:
        findings.append(
            _finding(
                "BRAND-PALETTE-MEMBERSHIP",
                cfg.severity_of("BRAND-PALETTE-MEMBERSHIP"),
                "color",
                "Colors outside the brand palette: " + ", ".join(off_palette) + ".",
            )
        )
    if off_fonts:
        findings.append(
            _finding(
                "FONT-FAMILY-BRAND",
                cfg.severity_of("FONT-FAMILY-BRAND"),
                "font",
                "Families outside the brand ones: " + ", ".join(off_fonts) + ".",
            )
        )

    parts = [v for v in (font_compliance, color_compliance) if v is not None]
    score = round(sum(parts) / len(parts)) if parts else None

    if not chromatic and not fonts:
        level = "unknown"
    elif not chromatic and unresolved:
        # Colours exist but could not be resolved (theme ids): the palette was
        # not verified, so this page is not "ok".
        level = "unknown"
    elif any(f["level"] == "error" for f in findings):
        level = "error"
    elif findings:
        level = "warning"
    else:
        level = "ok"

    return {
        "fonts": {
            "total": len(fonts),
            "brand": len(brand_fonts),
            "allowed": len(fonts) - len(off_fonts),
            "off": off_fonts,
            "compliance": font_compliance,
        },
        "colors": {
            "total": len(chromatic),
            "palette": len(chromatic) - len(off_palette),
            "off": off_palette,
            "has_accent": has_accent,
            "unresolved": unresolved,
            "compliance": color_compliance,
        },
        "score": score,
        "level": level,
        "findings": findings,
    }


def visual_brand_metrics(visual: dict, cfg=None) -> dict:
    """Fast brand metric of one visual (element).

    Unlike :func:`page_brand_metrics`, it does not build `findings` (for an
    element "has violation / not" is enough), so it is cheaper to call per visual.
    Returns ``{"fonts": {...}, "colors": {...}, "off": [...],
    "level": "ok"|"warning"|"error"|"unknown"}``.

    Args:
        visual: an element of `pages[].visuals[]` from `PbiLineage.to_json()`
            (`colors[]`, `fonts[]` keys).
        cfg: :class:`BrandConfig`; defaults to `brand_config.yaml`/`brand.py`.
    """
    if cfg is None:
        cfg = _load_config()

    raw_colors, unresolved = _split_colors(visual.get("colors"))
    chromatic = sorted(c for c in raw_colors if not _is_neutral(c))
    off_palette = sorted(
        c for c in chromatic if cfg.match(c) is None and c not in _allow_extra(cfg)
    )
    has_accent = any((m := cfg.match(c)) and m.mandatory for c in chromatic)

    fonts = _clean_fonts(visual.get("fonts"))
    allowed = [f.lower() for f in cfg.fonts_allowed]
    fallback = [f.lower() for f in cfg.fonts_fallback]
    off_fonts = [
        f
        for f in fonts
        if not any(a in f.lower() for a in allowed)
        and not any(fb in f.lower() for fb in fallback)
    ]

    off = [f"color {c}" for c in off_palette] + [f"font {f}" for f in off_fonts]
    if not chromatic and not fonts:
        level = "unknown"
    elif not chromatic and unresolved:
        level = "unknown"
    elif chromatic and not has_accent:
        level = "error"
    elif off:
        level = "warning"
    else:
        level = "ok"
    return {
        "fonts": {
            "total": len(fonts),
            "off": off_fonts,
            "compliance": _pct(len(fonts) - len(off_fonts), len(fonts)),
        },
        "colors": {
            "total": len(chromatic),
            "off": off_palette,
            "has_accent": has_accent,
            "unresolved": unresolved,
            "compliance": _pct(len(chromatic) - len(off_palette), len(chromatic)),
        },
        "off": off,
        "level": level,
    }


def brand_audit_pages(pages: list[dict], cfg=None) -> dict:
    """Compute metrics across all pages and an aggregated summary."""
    if cfg is None:
        cfg = _load_config()
    result = []
    font_scores: list[int] = []
    color_scores: list[int] = []
    off_pages: list[str] = []
    errors: list[str] = []
    for p in pages:
        m = page_brand_metrics(p, cfg)
        name = p.get("name", "?")
        result.append({"name": name, "metrics": m})
        if m["fonts"]["compliance"] is not None:
            font_scores.append(m["fonts"]["compliance"])
        if m["colors"]["compliance"] is not None:
            color_scores.append(m["colors"]["compliance"])
        if m["colors"]["off"] or m["fonts"]["off"]:
            off_pages.append(name)
        if m["level"] == "error":
            errors.append(name)

    def _avg(vals: list[int]) -> int | None:
        return round(sum(vals) / len(vals)) if vals else None

    summary = {
        "pages": len(pages),
        "ok": sum(1 for r in result if r["metrics"]["level"] == "ok"),
        "warnings": sum(1 for r in result if r["metrics"]["level"] == "warning"),
        "errors": len(errors),
        "unknown": sum(1 for r in result if r["metrics"]["level"] == "unknown"),
        "fonts_compliance": _avg(font_scores),
        "colors_compliance": _avg(color_scores),
        "off_brand_pages": off_pages,
        "error_pages": errors,
    }
    return {"summary": summary, "pages": result}


def brand_label(metrics: dict) -> str:
    """A short brand label for PlantUML/report (lines separated by '\\n')."""
    if not metrics:
        return "Brand: n/a"
    f = metrics.get("fonts", {})
    c = metrics.get("colors", {})
    fc = f.get("compliance")
    cc = c.get("compliance")

    def _pct(value: object) -> str:
        return "n/a" if value is None else f"{value}%"

    lines = [f"Brand: fonts {_pct(fc)}"]
    accent = "yes" if c.get("has_accent") else "no"
    lines.append(f"colors {_pct(cc)} · accent: {accent}")
    unresolved = c.get("unresolved") or 0
    if unresolved:
        lines.append(f"theme colours unresolved: {unresolved}")
    return "\n".join(lines)


_LEVEL_ORDER = {"error": 3, "warning": 2, "ok": 1, "unknown": 0}
