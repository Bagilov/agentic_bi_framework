"""Taxonomy of data-source origins (lineage layer 0).

Answers "where did the initial layer of sources come from": every top-level
source (a warehouse mart, an Excel file, an inline M-code table) is mapped to the
**generating process/repository** and an origin category.

A data source does not "start" lineage by itself: it has an upstream - an
industrial pipeline, an operator's manual Excel, or a constant inside the model.

Origin categories (fixed layer order):

    origin-pipeline    - pipeline - marts, Readme
    origin-manual      - manual source
    origin-reference   - inline reference table
    origin-etl         - ETL (legacy)
    origin-unknown     - other

The map can be managed via a YAML config (``origins.yaml``) when provided;
otherwise the built-in DEFAULT_ORIGINS is used. This lets you adapt lineage to
any dashboard without changing code. The built-in default is a NEUTRAL sample -
override it with your own map.

The constants and the default map live in ``lineage_origins_data.py``; this
module re-exports them and provides the lookup/assembly helpers.
"""

from __future__ import annotations

import re
from pathlib import Path

try:  # PyYAML is optional: the source map has a built-in default
    import yaml
except ImportError:  # pragma: no cover - without PyYAML we use the default
    yaml = None

from agentic_bi.lineage.lineage_origins_data import (  # noqa: F401
    DEFAULT_ORIGINS,
    ORIGIN_COLORS,
    ORIGIN_LABEL,
    ORIGIN_LEVEL,
    ORIGIN_LEVEL_LABEL,
    ORIGIN_ORDER,
    ORIGIN_STAGE_COLORS,
    ORIGIN_STAGE_LABEL,
    ORIGIN_STAGE_ORDER,
    Origin,
)


def _norm(name: str) -> str:
    """Normalize a table name for matching (case/whitespace)."""
    return re.sub(r"\s+", " ", str(name).strip()).lower()


def load_origins(config: dict | str | Path | None = None) -> list[Origin]:
    """Load the origin map: from a dict/YAML path or the built-in default.

    Args:
        config: a dict with an `origins` list, a YAML file path, or None.

    Returns:
        list[Origin] - the origin map.
    """
    raw: list[dict] = DEFAULT_ORIGINS

    if isinstance(config, (str, Path)):
        p = Path(config)
        if p.exists() and yaml is not None:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and "origins" in data:
                raw = data["origins"]
            elif isinstance(data, list):
                raw = data
    elif isinstance(config, dict) and "origins" in config:
        raw = config["origins"]

    out: list[Origin] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            Origin(
                key=str(item.get("key") or "origin-unknown"),
                category=str(item.get("category") or "origin-unknown"),
                label=str(item.get("label") or item.get("key") or "?"),
                detail=item.get("detail"),
                tables=list(item.get("tables") or []),
                stages=_norm_stages(item.get("stages")),
            )
        )
    return out


def _norm_stages(raw) -> list[dict]:
    """Normalize sub-stages: keep only known stages in a fixed order."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "").strip().lower()
        if stage not in ORIGIN_STAGE_ORDER:
            continue
        out.append({
            "stage": stage,
            "label": str(item.get("label") or ""),
            "detail": str(item.get("detail") or ""),
        })
    out.sort(key=lambda s: ORIGIN_STAGE_ORDER.index(s["stage"]))
    return out


def classify_origin(table: str, origins: list[Origin]) -> Origin | None:
    """Find the origin of a source table by its name."""
    t = _norm(table)
    for o in origins:
        for name in o.tables:
            if _norm(name) == t:
                return o
    return None


def origin_json_block(origins: list[Origin], source_tables: list[str]) -> dict:
    """The `origin` JSON block for `PbiLineage.to_json()`.

    Every origin contains the list of source tables it generates; tables without
    an explicit mapping fall into the `origin-unknown` category.
    """
    known = {_norm(n) for o in origins for n in o.tables}
    unknown = [t for t in source_tables if _norm(t) not in known]

    items = []
    for sort_idx, o in enumerate(sorted(origins, key=lambda x: _cat_rank(x.category))):
        if not o.tables:
            continue
        items.append({
            "key": o.key,
            "category": o.category,
            "label": o.label,
            "detail": o.detail,
            "tables": list(o.tables),
            "stages": list(o.stages),
            "sort": sort_idx,
        })

    if unknown:
        items.append({
            "key": "origin-unknown",
            "category": "origin-unknown",
            "label": ORIGIN_LABEL["origin-unknown"],
            "detail": None,
            "tables": sorted(unknown),
            "stages": [],
            "sort": len(items),
        })

    return {
        "level": ORIGIN_LEVEL,
        "label": ORIGIN_LEVEL_LABEL,
        "categories": ORIGIN_ORDER,
        "stage_order": ORIGIN_STAGE_ORDER,
        "stage_label": ORIGIN_STAGE_LABEL,
        "items": items,
    }


def _cat_rank(category: str) -> int:
    try:
        return ORIGIN_ORDER.index(category)
    except ValueError:
        return len(ORIGIN_ORDER)


__all__ = [
    "Origin",
    "DEFAULT_ORIGINS",
    "ORIGIN_COLORS",
    "ORIGIN_LABEL",
    "ORIGIN_LEVEL",
    "ORIGIN_LEVEL_LABEL",
    "ORIGIN_ORDER",
    "ORIGIN_STAGE_COLORS",
    "ORIGIN_STAGE_LABEL",
    "ORIGIN_STAGE_ORDER",
    "load_origins",
    "classify_origin",
    "origin_json_block",
]