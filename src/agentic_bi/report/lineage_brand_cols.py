"""Brand-book columns for the flat lineage matrix.

Unfolds the ``brand`` blocks of ``PbiLineage.to_json()`` into the right-hand
matrix columns (fonts %, colors %, status, notes) for both page-level and
visual-level rows.
"""

from __future__ import annotations

BRAND_LEVEL_LABEL = {
    "ok": "compliant",
    "warning": "warnings",
    "error": "violation",
    "unknown": "no data",
}

_EMPTY = {
    "Brand · fonts, %": "",
    "Brand · colors, %": "",
    "Brand · status": "",
    "Brand · notes": "",
}


def page_brand_index(data: dict) -> dict[str, dict]:
    """Map "page name -> brand metrics" from the lineage JSON."""
    index: dict[str, dict] = {}
    for p in data.get("pages", []) or []:
        if p.get("brand"):
            index[p.get("name", "?")] = p["brand"]
    brand_block = data.get("brand") or {}
    for name, m in (brand_block.get("pages") or {}).items():
        index.setdefault(name, m)
    return index


def brand_row(metrics: dict | None) -> dict:
    """Unfold page-level brand metrics into matrix columns."""
    m = metrics or {}
    fonts = m.get("fonts", {}) or {}
    colors = m.get("colors", {}) or {}
    fc, cc = fonts.get("compliance"), colors.get("compliance")
    notes: list[str] = []
    for f in fonts.get("off", []) or []:
        notes.append(f"font: {f}")
    for c in colors.get("off", []) or []:
        notes.append(f"color: {c}")
    if colors and not colors.get("has_red") and colors.get("total"):
        notes.append("no brand red")
    return {
        "Brand · fonts, %": fc if fc is not None else "",
        "Brand · colors, %": cc if cc is not None else "",
        "Brand · status": BRAND_LEVEL_LABEL.get(m.get("level", ""), ""),
        "Brand · notes": "; ".join(notes[:6]),
    }


def visual_brand_row(visual: dict) -> dict:
    """Unfold visual-level brand metrics (level 7 rows) into matrix columns."""
    m = visual.get("brand") or {}
    if not m:
        return dict(_EMPTY)
    f, c = m.get("fonts", {}) or {}, m.get("colors", {}) or {}
    return {
        "Brand · fonts, %": f.get("compliance")
        if f.get("compliance") is not None
        else "",
        "Brand · colors, %": c.get("compliance")
        if c.get("compliance") is not None
        else "",
        "Brand · status": BRAND_LEVEL_LABEL.get(m.get("level", ""), ""),
        "Brand · notes": "; ".join(m.get("off", []) or [])[:200],
    }
