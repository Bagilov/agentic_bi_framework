"""Generator of a "report skeleton for a query" — a PBIP project with visuals and filters.

Idea: a binary VertiPaq DataModel cannot be written from scratch, so the skeleton
is described config-driven in a textual PBIP (report.json + model.bim) and built
programmatically FOR A SPECIFIC QUERY. Folding into a binary .pbix and publishing
are separate steps (rebuild_pbix/publish_pbix).

This module is a **facade** over focused submodules:
    skeleton_visuals.py  - filters + visual builders (format verified on real .pbix)
    skeleton_assembly.py - report.json / model.bim / project files + build_skeleton

Scenario: KPI card (measure), chart (line/column: X axis + value), table
(columns/measures), page-level Categorical filters.
"""

from __future__ import annotations

from agentic_bi.skeleton_assembly import (  # noqa: F401
    build_model,
    build_report,
    build_skeleton,
    layout_from_report,
    main,
)
from agentic_bi.skeleton_visuals import (  # noqa: F401
    COL_AGG_FUNCTION,
    card_visual,
    chart_visual,
    page_filter,
    table_visual,
)
from agentic_bi.skeleton_visuals_extra import (  # noqa: F401
    kpi_band,
    scatter_visual,
    stacked_visual,
    treemap_visual,
)

__all__ = [
    "COL_AGG_FUNCTION",
    "card_visual",
    "chart_visual",
    "kpi_band",
    "page_filter",
    "scatter_visual",
    "stacked_visual",
    "table_visual",
    "treemap_visual",
    "build_model",
    "build_report",
    "build_skeleton",
    "layout_from_report",
    "main",
]
