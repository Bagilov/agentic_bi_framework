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
    brand_audit_pages(pages, cfg=None)  -> dict  - metrics of all pages + summary
    brand_label(metrics)                -> str   - a string for PlantUML/report
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# Font placeholders in the visual config (not real fonts).
_PLACEHOLDER_FONTS = {"+mn-lt", "+mj-lt", "+mn-ea", "+mj-ea", "themefont", ""}


def _load_config():
    """Lazy import of `BrandConfig` (no hard dependency) + YAML load."""
    pkg_dir = Path(__file__).resolve().parents[1]
    from agentic_bi.brand.config import BrandConfig  # type: ignore

    yaml_path = pkg_dir / "brand_config.yaml"
    if yaml_path.exists():
        try:
            return BrandConfig.load(yaml_path)
        except Exception as exc:  # noqa: BLE001 - config optional, default() exists
            _log.debug("brand_config.yaml load failed: %s", exc)
    return BrandConfig.default()


def _hex_from(token: str) -> str:
    """Extract '#rrggbb' from a lineage token ('hex#D32F2F', 'theme#0')."""
    if not token or not isinstance(token, str):
        return ""
    i = token.find("#")
    if i < 0:
        return ""
    v = token[i + 1 :].strip()
    if len(v) >= 6:
        v = v[:6]
    if len(v) != 6:
        return ""
    try:
        int(v, 16)
    except ValueError:
        return ""
    return "#" + v.lower()


def _is_neutral(hex_color: str) -> bool:
    h = hex_color.lstrip("#")
    return h[0:2] == h[2:4] == h[4:6]


def _clean_fonts(fonts: list[str] | None) -> list[str]:
    seen: list[str] = []
    for f in fonts or []:
        name = str(f).replace("\ufffd", "").strip()
        if name.lower() in _PLACEHOLDER_FONTS:
            continue
        if name and name not in seen:
            seen.append(name)
    return seen


def _pct(part: int, total: int) -> int | None:
    if total <= 0:
        return None
    return round(100 * part / total)


def _allow_extra(cfg) -> set[str]:
    """Normalize the config's `allow_extra` to lowercase '#rrggbb' (case-insensitive)."""
    out = set()
    for c in getattr(cfg, "allow_extra", []) or []:
        h = _hex_from(str(c)) or (str(c) if str(c).startswith("#") else "")
        if h:
            out.add(h.lower())
    return out


def _finding(
    rule_id: str, level: str, category: str, message: str, detail: str = ""
) -> dict:
    return {
        "rule_id": rule_id,
        "level": level,
        "category": category,
        "message": message,
        "detail": detail,
    }


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

    raw_colors = {_hex_from(c) for c in page.get("colors", [])}
    raw_colors.discard("")
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

    raw_colors = {_hex_from(c) for c in visual.get("colors", [])}
    raw_colors.discard("")
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
    lines = [f"Brand: fonts {fc if fc is not None else 'n/a'}%"]
    accent = "yes" if c.get("has_accent") else "no"
    lines.append(f"colors {cc if cc is not None else 'n/a'}% · accent: {accent}")
    return "\n".join(lines)


_LEVEL_ORDER = {"error": 3, "warning": 2, "ok": 1, "unknown": 0}
