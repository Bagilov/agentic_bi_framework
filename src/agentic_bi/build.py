"""Iteration 1+2: build a Power BI **PBIP project** (text-based) that opens in
Power BI Desktop.

Output (verified against real files):
- Inside a `.pbix`, Desktop requires a binary VertiPaq `DataModel` — a text
  `model.bim` is NOT recognized in a `.pbix`.
- A textual model definition only works in the **Power BI Project (PBIP)**
  format: a folder with `report.json` + `*.Semantic/model.bim` + `definition.pbism`,
  and a root `.pbir` file. Desktop opens PBIP directly.

So we iteratively build a **PBIP project** generator — fully programmable,
versionable, opens in Desktop. (Folding into a binary `.pbix` is a separate
step handled by the engine path / rebuild.)

Structure (modeled on a PBIP project):
    <name>.pbir                # entry point (version + reportConfig)
    <name>.Report/report.json  # page/visual layout
    <name>.Semantic/model.bim  # data model (tables/columns/measures)
    <name>.Semantic/definition.pbism  # version: 1.0
    <name>/data/...            # source (CSV) — in iteration 4

This module = Iteration 1 (scaffold: empty page) + Iteration 2 (model).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _pbir(display_name: str) -> dict:
    return {
        "version": "1.0",
        "reportConfig": json.dumps(
            {
                "config": json.dumps({"theme": "default", "filter": {"filter": None}}),
                "version": "1.0",
            },
            ensure_ascii=False,
        ),
    }


def _visual_placeholder() -> dict:
    """Placeholder: a card visual with the Count measure (real pbix format)."""
    return {
        "config": json.dumps(
            {
                "name": "CountCard",
                "layouts": [
                    {
                        "id": 0,
                        "position": {
                            "x": 20,
                            "y": 20,
                            "width": 300,
                            "height": 120,
                            "z": 0,
                        },
                    }
                ],
                "singleVisual": {
                    "visualType": "card",
                    "objects": {},
                    "prototypeQuery": {
                        "Version": 2,
                        "From": [{"Name": "e", "Entity": "Events"}],
                        "Select": [
                            {
                                "Measure": {
                                    "Expression": {"MeasureRef": {"Property": "Count"}}
                                },
                                "Name": "Count",
                            }
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def _report_with_visuals(display_name: str, page_name: str = "Page 1") -> dict:
    """report.json with a single visual (placeholder; full set in iteration 3+)."""
    return {
        "version": "1.0",
        "config": json.dumps({"theme": "default", "filter": {"filter": None}}),
        "sections": [
            {
                "name": page_name,
                "displayName": display_name,
                "filters": "[]",
                "config": json.dumps(
                    {"width": 1280, "height": 720, "background": {"color": "#FFFFFF"}}
                ),
                "visualContainers": [_visual_placeholder()],
            }
        ],
    }


def _empty_report(display_name: str, page_name: str = "Page 1") -> dict:
    """report.json: one empty page, 0 visuals (iteration 1)."""
    return {
        "version": "1.0",
        "config": json.dumps({"theme": "default", "filter": {"filter": None}}),
        "sections": [
            {
                "name": page_name,
                "displayName": display_name,
                "filters": "[]",
                "config": json.dumps(
                    {"width": 1280, "height": 720, "background": {"color": "#FFFFFF"}}
                ),
                "visualContainers": [],
            }
        ],
    }


def _model_bim(tables: list[dict] | None = None) -> dict:
    """model.bim: the data model (iteration 2).

    tables — a list of table dicts, each:
      {name, columns:[{name,dataType}], measures:[{name,expression}], partitions:?}
    If a table has no `partitions`, an empty `DATATABLE` calculated partition is
    added automatically (the model opens with no external source and no Refresh).
    A partition is mandatory in TMSL.

    TMSL: compatibilityLevel 1606, culture, annotations
    (DefaultMeasureTable + defaultPowerBIDataSourceVersion).
    """
    norm_tables = []
    for t in tables or []:
        nt = dict(t)
        if "partitions" not in nt:
            cols = nt.get("columns", [])
            datatype_arg = ", ".join(
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
                        "expression": f"DATATABLE({datatype_arg}, {{}})",
                    },
                }
            ]
        norm_tables.append(nt)

    return {
        "name": "SemanticModel",
        "compatibilityLevel": 1606,
        "model": {
            "culture": "en-US",
            "annotations": [
                {"name": "DefaultMeasureTable", "value": norm_tables[0]["name"]}
                if norm_tables
                else {"name": "DefaultMeasureTable", "value": "Events"},
                {"name": "defaultPowerBIDataSourceVersion", "value": "powerBI_V3"},
            ],
            "tables": norm_tables,
            "relationships": [],
        },
    }


def build_pbip(
    out: Path,
    display_name: str = "Report",
    tables: list[dict] | None = None,
    page_name: str = "Page 1",
    with_visuals: bool = False,
) -> Path:
    """Build a PBIP project into the `out` folder and return the `.pbir` path.

    Args:
        out: where to put the project. The .pbir will be `out / "<name>.pbir"`.
        display_name: the display name of the report/page.
        tables: model tables (see `_model_bim`).
        page_name: the page name.
        with_visuals: add a sample visual (Count card) to the report.
    """
    root = out
    root.mkdir(parents=True, exist_ok=True)
    name = root.name

    # root .pbir
    _write_json(root / f"{name}.pbir", _pbir(display_name))

    # report
    report_dir = root / f"{name}.Report"
    report_dir.mkdir(exist_ok=True)
    report = (
        _report_with_visuals(display_name, page_name)
        if with_visuals
        else _empty_report(display_name, page_name)
    )
    _write_json(report_dir / "report.json", report)

    # semantic model
    semantic_dir = root / f"{name}.Semantic"
    semantic_dir.mkdir(exist_ok=True)
    _write_json(semantic_dir / "model.bim", _model_bim(tables))
    _write_json(semantic_dir / "definition.pbism", {"version": "1.0"})

    pbir = root / f"{name}.pbir"
    return pbir


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    out = Path(__file__).parent / "output_files" / "demo_events"
    tables = [
        {
            "name": "Events",
            "columns": [
                {"name": "case", "dataType": "string"},
                {"name": "status", "dataType": "string"},
                {"name": "dur", "dataType": "decimal"},
            ],
            "measures": [
                {"name": "Count", "expression": "COUNTROWS('Events')"},
                {"name": "AvgDur", "expression": "AVERAGE('Events'[dur])"},
            ],
        }
    ]
    pbir = build_pbip(
        out, display_name="Demo: events", tables=tables, with_visuals=True
    )
    logger.info("PBIP project created: %s (open it in Power BI Desktop)", pbir)


if __name__ == "__main__":
    main()
