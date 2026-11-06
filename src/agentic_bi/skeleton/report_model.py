"""Spec assembly for the PBIP skeleton project: report.json, model.bim, layout.

Owns the config→spec conversions: :func:`build_report` (report.json sections),
:func:`build_model` (model.bim tables/partitions) and
:func:`layout_from_report` (the .pbix layout used by ``rebuild_pbix``). Writing
the project files and the query-driven entry point stay in
:mod:`agentic_bi.skeleton.assembly`.
"""

from __future__ import annotations

import json


def build_report(sections: list[dict]) -> dict:
    """Assemble report.json from lists of sections.

    sections: [{name, displayName, width, height, filters:[page_filter], containers:[visual]}]
    """
    out_sections = []
    for s in sections:
        out_sections.append(
            {
                "name": s["name"],
                "displayName": s["displayName"],
                "filters": json.dumps(s.get("filters", []), ensure_ascii=False),
                "config": json.dumps(
                    {
                        "width": s.get("width", 1280),
                        "height": s.get("height", 800),
                        "background": {"color": "#FFFFFF"},
                    },
                    ensure_ascii=False,
                ),
                "visualContainers": s.get("containers", []),
            }
        )
    return {
        "version": "1.0",
        "config": json.dumps({"theme": "default", "filter": {"filter": None}}),
        "sections": out_sections,
    }


# ─── model ─────────────────────────────────────────────────


def build_model(tables: list[dict]) -> dict:
    """Assemble model.bim (like build._model_bim, but without empty DATATABLE
    partitions when an external source is set; the skeleton uses DATATABLE-empty)."""
    norm = []
    for t in tables or []:
        nt = dict(t)
        if "partitions" not in nt:
            cols = nt.get("columns", [])
            args = ", ".join(
                f'"{c["name"]}", STRING'
                if c.get("dataType") == "string"
                else f'"{c["name"]}", DOUBLE'
                for c in cols
            )
            nt["partitions"] = [
                {
                    "name": f"{t['name']}-1",
                    "mode": "import",
                    "source": {
                        "type": "calculated",
                        "expression": f"DATATABLE({args}, {{}})",
                    },
                }
            ]
        norm.append(nt)
    return {
        "name": "SemanticModel",
        "compatibilityLevel": 1606,
        "model": {
            "culture": "en-US",
            "annotations": [
                {
                    "name": "DefaultMeasureTable",
                    "value": (norm[0]["name"] if norm else "Data"),
                },
                {"name": "defaultPowerBIDataSourceVersion", "value": "powerBI_V3"},
            ],
            "tables": norm,
            "relationships": [],
        },
    }


def layout_from_report(report: dict, base_layout: dict | None = None) -> dict:
    """Convert report.json (PBIP) into the .pbix layout format.

    report: a dict from `build_report`.
    base_layout: the donor layout (for id/filters/resourcePackages/config), from
        rebuild._extract_layout. If None - defaults are used.

    .pbix layout format (verified against a donor): top-level has `id`, `filters`,
    `resourcePackages`, `sections`, `config`, `layoutOptimization`; a section has
    `id`, `name`, `displayName`, `filters`, `ordinal`, `visualContainers`,
    `config`, `displayOption`, `width`, `height`.
    """
    base = base_layout or {}
    layout = {
        "id": base.get("id", 0),
        "filters": "[]",
        "resourcePackages": base.get("resourcePackages", []),
        "config": base.get(
            "config",
            '{"version":"5.54","themeCollection":{"baseTheme":{"name":"CY24SU05","version":"5.38","compatVersion":5}}}',
        ),
        "layoutOptimization": base.get("layoutOptimization", 0),
    }
    sections = []
    for i, sec in enumerate(report.get("sections", [])):
        sections.append(
            {
                "id": sec.get("id", f"ReportSection{i}"),
                "name": sec.get("name", f"ReportSection{i}"),
                "displayName": sec.get("displayName", "Page"),
                "filters": sec.get("filters", "[]"),
                "ordinal": i,
                "visualContainers": sec.get(
                    "containers", sec.get("visualContainers", [])
                ),
                "config": sec.get("config", ""),
                "displayOption": 1,
                "width": sec.get("width", 1280),
                "height": sec.get("height", 800),
            }
        )
    layout["sections"] = sections
    return layout
