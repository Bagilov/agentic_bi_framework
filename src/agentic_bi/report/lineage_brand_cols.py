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


def as_mapping(value: object) -> dict:
    """A JSON object from an untrusted lineage document; anything else is empty."""
    return value if isinstance(value, dict) else {}


def as_rows(value: object) -> list[dict]:
    """A JSON array of objects, skipping non-object entries."""
    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def as_list(value: object) -> list:
    """A JSON array; a scalar, string or object counts as absent."""
    return value if isinstance(value, list) else []


_EMPTY = {
    "Brand · fonts, %": "",
    "Brand · colors, %": "",
    "Brand · status": "",
    "Brand · notes": "",
}


def page_brand_index(data: dict) -> dict[str, dict]:
    """Map "page name -> brand metrics" from the lineage JSON."""
    index: dict[str, dict] = {}
    for p in as_rows(data.get("pages")):
        if p.get("brand"):
            index[str(p.get("name", "?"))] = p["brand"]
    brand_block = as_mapping(data.get("brand"))
    for name, m in as_mapping(brand_block.get("pages")).items():
        index.setdefault(name, as_mapping(m))
    return index


def brand_row(metrics: dict | None) -> dict:
    """Unfold page-level brand metrics into matrix columns."""
    m = as_mapping(metrics)
    fonts = as_mapping(m.get("fonts"))
    colors = as_mapping(m.get("colors"))
    fc, cc = fonts.get("compliance"), colors.get("compliance")
    notes: list[str] = []
    for f in as_list(fonts.get("off")):
        notes.append(f"font: {f}")
    for c in as_list(colors.get("off")):
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
    m = as_mapping(visual.get("brand"))
    if not m:
        return dict(_EMPTY)
    f, c = as_mapping(m.get("fonts")), as_mapping(m.get("colors"))
    return {
        "Brand · fonts, %": f.get("compliance")
        if f.get("compliance") is not None
        else "",
        "Brand · colors, %": c.get("compliance")
        if c.get("compliance") is not None
        else "",
        "Brand · status": BRAND_LEVEL_LABEL.get(m.get("level", ""), ""),
        "Brand · notes": "; ".join(str(item) for item in as_list(m.get("off")))[:200],
    }
