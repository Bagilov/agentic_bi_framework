"""Extra visual builders (stacked/treemap/scatter/KPI band)."""

from __future__ import annotations

import logging

from agentic_bi.skeleton_visuals import (
    _full_query,
    _query_item,
    _query_layout,
    card_visual,
)

logger = logging.getLogger(__name__)


def stacked_visual(
    axis: dict,
    value: dict,
    series: dict | None,
    table: str,
    source: str = "m",
    x: int = 20,
    y: int = 160,
    w: int = 620,
    h: int = 320,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """Stacked column/bar: axis (category) + value + optional series."""
    ax_item, ax_ref, _ = _query_item(axis, table, source, measure_table, measure_alias)
    val_item, val_ref, _ = _query_item(
        value, table, source, measure_table, measure_alias
    )
    selects = [ax_item, val_item]
    projections: dict = {
        "Values": [{"queryRef": val_ref}],
        "Category": [{"queryRef": ax_ref}],
    }
    if series:
        s_item, s_ref, _ = _query_item(
            series, table, source, measure_table, measure_alias
        )
        selects.insert(1, s_item)
        projections["Series"] = [{"queryRef": s_ref}]
    single = {
        "visualType": "stackedColumnChart",
        "projections": projections,
        "prototypeQuery": _full_query(
            table, source, selects, measure_table, measure_alias
        ),
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "objects": {},
    }
    return _query_layout(f"Chart_{single['visualType']}", single, x, y, w, h)


def treemap_visual(
    axis: dict,
    value: dict,
    table: str,
    source: str = "m",
    x: int = 20,
    y: int = 480,
    w: int = 500,
    h: int = 320,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """Treemap: category (axis) + size (value agg)."""
    ax_item, ax_ref, _ = _query_item(axis, table, source, measure_table, measure_alias)
    val_item, val_ref, _ = _query_item(
        value, table, source, measure_table, measure_alias
    )
    single = {
        "visualType": "treemap",
        "projections": {
            "Values": [{"queryRef": val_ref}],
            "Category": [{"queryRef": ax_ref}],
        },
        "prototypeQuery": _full_query(
            table, source, [ax_item, val_item], measure_table, measure_alias
        ),
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "objects": {},
    }
    return _query_layout("Treemap_AP", single, x, y, w, h)


def scatter_visual(
    x: dict,
    y: dict,
    size: dict | None,
    table: str,
    source: str = "m",
    x_: int = 660,
    y_: int = 480,
    w: int = 600,
    h: int = 320,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """Scatter (bubble): X, Y measures/agg; size=agg (bubble size)."""
    x_item, x_ref, _ = _query_item(x, table, source, measure_table, measure_alias)
    y_item, y_ref, _ = _query_item(y, table, source, measure_table, measure_alias)
    selects = [x_item, y_item]
    projections: dict = {
        "Values": [{"queryRef": x_ref, "Role": "X"}, {"queryRef": y_ref, "Role": "Y"}]
    }
    if size:
        s_item, s_ref, _ = _query_item(
            size, table, source, measure_table, measure_alias
        )
        selects.append(s_item)
        projections["Values"].append({"queryRef": s_ref, "Role": "Size"})
    single = {
        "visualType": "scatterChart",
        "projections": projections,
        "prototypeQuery": _full_query(
            table, source, selects, measure_table, measure_alias
        ),
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "objects": {},
    }
    return _query_layout("Scatter_Bubble", single, x_, y_, w, h)


def kpi_band(
    cards: list[dict],
    table: str,
    source: str = "m",
    x0: int = 20,
    y0: int = 20,
    cw: int = 200,
    ch: int = 120,
    gap: int = 16,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """A row of KPI cards (one measure/agg each) laid out horizontally."""
    containers = []
    for i, q in enumerate(cards):
        x = x0 + i * (cw + gap)
        c = card_visual(
            q,
            table,
            source,
            x=x,
            y=y0,
            w=cw,
            h=ch,
            measure_table=measure_table,
            measure_alias=measure_alias,
        )
        containers.append(c)
    return containers


# ─── report assembly ───────────────────────────────────────
