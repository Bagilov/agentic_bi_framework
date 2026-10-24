# Bundle 2: skeleton visuals + build + agents

==================== FILE: src/agentic_bi/skeleton_visuals.py ====================

"""Visual and filter builders for the PBIP skeleton (format verified on real .pbix)."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Function in Select for columns (from a real layout): 0=None, 4=min (donor uses 4)
COL_AGG_FUNCTION = 4


def _source_ref(source: str, entity: str) -> dict:
    return {"SourceRef": {"Source": source, "Entity": entity}}


def page_filter(column: str, table: str, source: str = "m") -> dict:
    """Page-level Categorical filter on a column (a slicer in the filter pane).

    howCreated=1 -> "added manually" (visible as a filter on the page).
    """
    filtered = f"FilterAuto_{hash(column) & 0xFFFFFFFF:08x}"
    return {
        "name": filtered,
        "expression": {
            "Column": {
                "Expression": _source_ref(source, table),
                "Property": column,
            }
        },
        "type": "Categorical",
        "howCreated": 1,
        "isHiddenInViewMode": False,
        "objects": {},
    }


# ─── visuals ───────────────────────────────────────────────


def _query_item(
    pq_query,
    table: str,
    source: str,
    measure_table: str | None = None,
    measure_alias: str | None = None,
):
    """Build the Select item and queryRef for a prototypeQuery.

    measure_table/measure_alias: if set, measures reference ANOTHER table (e.g. a
    dedicated measures table in the donor) while columns reference the main one.
    By default measures come from the same table as columns.

    pq_query — a field description: {"kind":"measure"|"column","property":...,
                                      "agg":bool, "display":"..."}
    Returns (select_item, query_ref, is_measure).

    Format verified against a real .pbix (donor):
      - measure                 -> {"Measure": {"Property": prop}}
      - column with aggregation -> {"Aggregation": {"Column":{...}, "Function": N}}
      - column WITHOUT agg      -> {"Column": {"Property": prop}}
    queryRef: "table.prop" for a column, "Sum(table.prop)" for Aggregation.
    """
    prop = pq_query["property"]
    display = pq_query.get("display", prop)
    kind = pq_query.get("kind", "column")
    agg = bool(pq_query.get("agg", False))

    m_table = measure_table if kind == "measure" and measure_table else table
    m_source = measure_alias if kind == "measure" and measure_alias else source

    if kind == "measure":
        item = {
            "Measure": {"Expression": _source_ref(m_source, m_table)},
            "Name": f"{m_table}.{prop}",
            "NativeReferenceName": display,
        }
        item["Measure"]["Property"] = prop
        return item, f"{m_table}.{prop}", True

    if agg:
        # value column with aggregation (as in the donor: Function=0)
        item = {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": _source_ref(source, table),
                        "Property": prop,
                    }
                },
                "Function": pq_query.get("aggFunction", COL_AGG_FUNCTION),
            },
            "Name": f"Sum({table}.{prop})",
            "NativeReferenceName": display,
        }
        return item, f"Sum({table}.{prop})", False

    # column without aggregation (category/date axis, series)
    item = {
        "Column": {"Expression": _source_ref(source, table)},
        "Name": f"{table}.{prop}",
        "NativeReferenceName": display,
    }
    item["Column"]["Property"] = prop
    return item, f"{table}.{prop}", False


def card_visual(
    query: dict,
    table: str,
    source: str = "m",
    x: int = 20,
    y: int = 20,
    w: int = 240,
    h: int = 120,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """KPI card: a single measure."""
    item, qref, _ = _query_item(query, table, source, measure_table, measure_alias)
    _from = [{"Name": source, "Entity": table, "Type": 0}]
    if measure_alias:
        _from.append({"Name": measure_alias, "Entity": measure_table, "Type": 0})
    single = {
        "visualType": "card",
        "projections": {"Values": [{"queryRef": qref}]},
        "prototypeQuery": {
            "Version": 2,
            "From": _from,
            "Select": [item],
            "OrderBy": [
                {
                    "Direction": 1,
                    "Expression": {
                        "Measure"
                        if query.get("kind") == "measure"
                        else "Aggregation": item.get("Measure")
                        or item.get("Aggregation")
                    },
                }
            ],
        },
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "objects": {
            "labels": [
                {
                    "properties": {
                        "fontSize": {"expr": {"Literal": {"Value": "1A"}}},
                        "fontFamily": {
                            "expr": {
                                "Literal": {
                                    "Value": "''Segoe UI'', wf_segoe-ui_normal, helvetica, arial, sans-serif'"
                                }
                            }
                        },
                    }
                }
            ]
        },
    }
    return {
        "config": json.dumps(
            {
                "name": f"KPI_{query['property']}",
                "layouts": [
                    {
                        "id": 0,
                        "position": {"x": x, "y": y, "width": w, "height": h, "z": 0},
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def chart_visual(
    visual_type: str,
    axis: dict,
    value: dict,
    table: str,
    source: str = "m",
    x: int = 20,
    y: int = 160,
    w: int = 620,
    h: int = 320,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """Chart (lineChart/clusteredColumnChart): axis (column) + value (measure or agg column)."""
    ax_item, ax_ref, _ = _query_item(axis, table, source, measure_table, measure_alias)
    val_item, val_ref, _ = _query_item(
        value, table, source, measure_table, measure_alias
    )
    _from = [{"Name": source, "Entity": table, "Type": 0}]
    if measure_alias:
        _from.append({"Name": measure_alias, "Entity": measure_table, "Type": 0})
    single = {
        "visualType": visual_type,
        "projections": {
            "Values": [{"queryRef": val_ref}],
            "Category": [{"queryRef": ax_ref}],
        },
        "prototypeQuery": {
            "Version": 2,
            "From": _from,
            "Select": [ax_item, val_item],
        },
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "objects": {},
    }
    return {
        "config": json.dumps(
            {
                "name": f"Chart_{visual_type}",
                "layouts": [
                    {
                        "id": 0,
                        "position": {"x": x, "y": y, "width": w, "height": h, "z": 0},
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def table_visual(
    fields: list[dict],
    table: str,
    source: str = "m",
    x: int = 20,
    y: int = 520,
    w: int = 1240,
    h: int = 240,
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """Table: a list of fields (column/measure)."""
    selects = []
    qrefs = []
    for f in fields:
        it, qref, _ = _query_item(f, table, source, measure_table, measure_alias)
        selects.append(it)
        qrefs.append({"queryRef": qref})
    _from = [{"Name": source, "Entity": table, "Type": 0}]
    if measure_alias:
        _from.append({"Name": measure_alias, "Entity": measure_table, "Type": 0})
    single = {
        "visualType": "tableEx",
        "projections": {"Values": qrefs},
        "prototypeQuery": {"Version": 2, "From": _from, "Select": selects},
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "objects": {},
    }
    return {
        "config": json.dumps(
            {
                "name": "Table_main",
                "layouts": [
                    {
                        "id": 0,
                        "position": {"x": x, "y": y, "width": w, "height": h, "z": 0},
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def _query_layout(name: str, single: dict, x: int, y: int, w: int, h: int) -> dict:
    """Wrap a singleVisual into a visual container with a position."""
    return {
        "config": json.dumps(
            {
                "name": name,
                "layouts": [
                    {
                        "id": 0,
                        "position": {"x": x, "y": y, "width": w, "height": h, "z": 0},
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def _full_query(
    table: str,
    source: str,
    selects: list[dict],
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """prototypeQuery From + Select (a shared wrapper)."""
    _from = [{"Name": source, "Entity": table, "Type": 0}]
    if measure_alias:
        _from.append({"Name": measure_alias, "Entity": measure_table, "Type": 0})
    return {"Version": 2, "From": _from, "Select": selects}

==================== FILE: src/agentic_bi/skeleton_visuals_extra.py ====================

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

==================== FILE: src/agentic_bi/build.py ====================

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

==================== FILE: src/agentic_bi/agents.py ====================

"""Agent-assisted support for the "dashboard -> quality -> deploy" pipeline.

Concept: each stage of the dashboard lifecycle (develop, test, deploy, control,
support) gets a *support agent* — a declaratively described entity with a role,
purpose, activation trigger and a set of tools. An agent description is a
manifest (JSON/YAML) that can be:

- stored in the dashboard declarative spec (section ``support.agents``);
- materialized into a Kilo agent file (``.kilo/agent/<id>.md``) without code;
- used as a contract for Agent Manager / expert subtasks.

Lifecycle stages (domains) the agents correspond to:

- ``develop`` — development (build the board from a spec, layout, rebuild);
- ``test``    — testing (validate_pbix, structural checks, thresholds);
- ``deploy``  — deploy (git-deploy via a sync client, guardrails);
- ``control`` — control/monitoring (compare the published artifact with expected);
- ``support`` — support (answer questions, triage incidents, recommendations).

An agent is NOT an executor and NOT a mandatory step: the pipeline runs without
agents too. Agents are a "smart support" layer that helps a human (and/or Agent
Manager) go through the stages: generate a plan, check the result, explain the
thresholds, highlight risks.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

# lifecycle stages the agents support
STAGES = ("develop", "test", "deploy", "control", "support")


@dataclass(frozen=True)
class SupportAgent:
    """Manifest of a support agent for one lifecycle stage."""

    id: str  # unique id (e.g. "agent.build")
    role: str  # short role name ("Builder")
    stage: str  # one of STAGES
    purpose: str = ""  # what the agent is for
    triggers: tuple[str, ...] = ()  # conditions/events that invoke the agent
    tools: tuple[str, ...] = ()  # tools available to the agent
    prompt: str = ""  # start-instruction template for Agent Manager
    enabled: bool = True  # whether to enable by default


# ─── default support-agent registry ────────────────────────


def _develop_agent() -> SupportAgent:
    """Agent for the "develop" stage: build a board from a spec."""
    return SupportAgent(
        id="agent.builder",
        role="Builder",
        stage="develop",
        purpose="Builds a board from a declarative spec: translates spec -> Board, "
        "prepares the layout and folds it into a .pbix via rebuild "
        "(donor DataModel).",
        triggers=("on_build", "on_spec_change"),
        tools=("spec_to_board", "board.layout", "rebuild_pbix"),
        prompt=(
            "Build the dashboard from spec <spec> via spec_to_board, get the "
            "layout board.layout(...) and fold into a .pbix "
            "rebuild_pbix(donor, out, layout=...)."
        ),
    )


def _test_agent() -> SupportAgent:
    """Agent for the "test" stage: quality checks before publishing."""
    return SupportAgent(
        id="agent.tester",
        role="Tester",
        stage="test",
        purpose="Checks the built .pbix before publishing: validate_pbix, "
        "structural spec checks, layout-vs-donor-model and threshold checks.",
        triggers=("before_publish", "after_build"),
        tools=("validate_pbix", "validate_spec", "thresholds.resolve_thresholds"),
        prompt=(
            "Run quality checks on the built .pbix: validate_pbix(path). If there "
            "are problems — stop the publish and return the list of errors."
        ),
    )


def _deploy_agent() -> SupportAgent:
    """Agent for the "deploy" stage: git-deploy a .pbix to a Report Server."""
    return SupportAgent(
        id="agent.deployer",
        role="Deployer",
        stage="deploy",
        purpose="Performs a git-deploy of a .pbix to a Report Server via a sync "
        "client, honoring guardrails (max_deletion_pct/max_change_pct) and "
        "a dry-run plan.",
        triggers=("on_deploy", "on_dry_run"),
        tools=("git-deploy deploy", "git-deploy status", "guardrails"),
        prompt=(
            "Deploy using config <cfg>; first the --dry-run plan, check the "
            "guardrails (deploy.max_deletion_pct), then the real deploy."
        ),
    )


def _control_agent() -> SupportAgent:
    """Agent for the "control" stage: compare the published artifact with expected."""
    return SupportAgent(
        id="agent.watchdog",
        role="Watchdog",
        stage="control",
        purpose="Monitors the published dashboard: compares presence/size/version on "
        "the Report Server with expected, flags mismatches and regression risks.",
        triggers=("on_publish", "on_schedule"),
        tools=("verify_published", "deploy status", "thresholds"),
        prompt=(
            "Check that the published dashboard <name> in <folder> matches the "
            "expected one (Id/Size/version). Return a summary of mismatches."
        ),
    )


def _support_agent() -> SupportAgent:
    """Agent for the "support" stage: explain thresholds and triage incidents."""
    return SupportAgent(
        id="agent.supporter",
        role="Supporter",
        stage="support",
        purpose="Supports the user/team on the dashboard: explains thresholds from "
        "the catalog, triages incidents (broken visual, 409/deploy-state), "
        "and gives recommendations on refining the spec.",
        triggers=("on_question", "on_incident"),
        tools=("thresholds.describe", "troubleshooting", "spec docs"),
        prompt=(
            "Answer the user's question about the dashboard: explain the "
            "thresholds from the catalog, triage the incident and give "
            "recommendations."
        ),
    )


def _default_agents() -> tuple[SupportAgent, ...]:
    return (
        _develop_agent(),
        _test_agent(),
        _deploy_agent(),
        _control_agent(),
        _support_agent(),
    )


AGENT_REGISTRY: dict[str, SupportAgent] = {a.id: a for a in _default_agents()}


# ─── manifest API ──────────────────────────────────────────


def all_agents(stage: str | None = None) -> list[SupportAgent]:
    """All support agents, optionally only for one stage.

    An unknown stage raises rather than returning `[]`: a typo would otherwise
    look like "this stage has no agents" and silently orphan every agent.
    """
    if stage is None:
        return list(AGENT_REGISTRY.values())
    if stage not in STAGES:
        raise ValueError(f"Unknown stage '{stage}'; allowed: {STAGES}")
    return [a for a in AGENT_REGISTRY.values() if a.stage == stage]


def agents_for_stage(stage: str) -> list[SupportAgent]:
    """Agents supporting a particular lifecycle stage."""
    return all_agents(stage)


def to_manifest(agent: SupportAgent) -> dict:
    """Serialize an agent into a dict (manifest for a spec/file)."""
    return asdict(agent)


def from_manifest(d: dict) -> SupportAgent:
    """Build a SupportAgent from a manifest (dict).

    The `stage` is validated here: a manifest may only name a known lifecycle
    stage, so a typo fails loudly instead of producing an agent that no stage
    resolves (which would silently disappear from every stage view).
    """
    if "id" not in d or "role" not in d or "stage" not in d:
        raise ValueError("An agent manifest must contain id, role, stage")
    if d["stage"] not in STAGES:
        raise ValueError(
            f"Unknown stage '{d['stage']}' in agent '{d['id']}'; allowed: {STAGES}"
        )
    return SupportAgent(
        id=d["id"],
        role=d["role"],
        stage=d["stage"],
        purpose=d.get("purpose", ""),
        triggers=tuple(d.get("triggers", []) or []),
        tools=tuple(d.get("tools", []) or []),
        prompt=d.get("prompt", ""),
        enabled=d.get("enabled", True),
    )


def resolve_agents(
    spec: Any | None = None, enabled_only: bool = True
) -> list[SupportAgent]:
    """The effective set of agents, honoring overrides from the spec.

    ``spec`` — a ``DashboardSpec`` object (from spec.py) that may have a
    ``support = {"agents": [manifest, ...], "enable_ids": [...],
    "disable_ids": [...]}`` section.

    Priority:
    1. If an agent is overridden by a manifest in the spec — the manifest wins;
    2. ``disable_ids`` disables an agent; ``enable_ids`` enables it (on by default);
    3. otherwise — the value from ``AGENT_REGISTRY`` (+ the ``enabled_only`` filter).

    Returns agents in registry order (stable order).
    """
    overrides: list[SupportAgent] = []
    enable_ids: set[str] = set()
    disable_ids: set[str] = set()
    if spec is not None:
        support = getattr(spec, "support", None) or {}
        overrides = [from_manifest(m) for m in support.get("agents", [])]
        enable_ids = set(support.get("enable_ids", []) or [])
        disable_ids = set(support.get("disable_ids", []) or [])

    by_id = {a.id: a for a in overrides}
    result: list[SupportAgent] = []
    for aid, default in AGENT_REGISTRY.items():
        agent = by_id.get(aid, default)
        if aid in disable_ids:
            continue
        if aid in enable_ids:
            effective = SupportAgent(
                id=agent.id,
                role=agent.role,
                stage=agent.stage,
                purpose=agent.purpose,
                triggers=agent.triggers,
                tools=agent.tools,
                prompt=agent.prompt,
                enabled=True,
            )
            result.append(effective)
        elif agent.enabled or not enabled_only:
            result.append(agent)
    # project (registry-unknown) agents — include them too
    for aid, agent in by_id.items():
        if aid not in AGENT_REGISTRY and aid not in disable_ids:
            result.append(agent)
    return result


def render_kilo_agent(agent: SupportAgent) -> str:
    """Render a Kilo agent markdown (body of ``.kilo/agent/<id>.md``).

    Returns the file's text; writing it is the caller's job. The `agent.id` is
    **not** sanitised here, so a writer must treat it as a filename and reject
    separators/traversal (the returned body itself is inert).
    """
    tools = ", ".join(agent.tools) or "-"
    triggers = ", ".join(agent.triggers) or "-"
    return (
        f"# {agent.role} ({agent.id})\n\n"
        f"**Stage:** {agent.stage}\n\n"
        f"**Purpose:** {agent.purpose}\n\n"
        f"**Triggers:** {triggers}\n\n"
        f"**Tools:** {tools}\n\n"
        f"## Start instruction\n\n{agent.prompt}\n"
    )


__all__ = [
    "SupportAgent",
    "STAGES",
    "AGENT_REGISTRY",
    "all_agents",
    "agents_for_stage",
    "to_manifest",
    "from_manifest",
    "resolve_agents",
    "render_kilo_agent",
]

==================== FILE: src/agentic_bi/inspect_board.py ====================

"""Inspect a dashboard on a Power BI Report Server: download the .pbix and break it down.

Process: find the report by path -> download the .pbix (Negotiate) -> lineage via PbiLineage.

Reuses the existing orchestrator `agentic_bi.reportserver.pbix_analysis.PbiRsBulk`
(download + analysis) instead of duplicating its logic.

CLI:
    python -m agentic_bi.inspect_board --path "/Shared Reports/Self-service"
    python -m agentic_bi.inspect_board --path "/Reports/MyReport" --keep-pbix

The server host is read from the report-server config (see
`agentic_bi.reportserver.diagnostics`); no host is hardcoded here.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from agentic_bi.reportserver.pbix_analysis import PbiRsBulk

logger = logging.getLogger(__name__)

OUT_DIR = Path(__file__).resolve().parent / "output_files"


class PbirsPathError(RuntimeError):
    """The report was not found at the given path."""


class PbirsAccessError(RuntimeError):
    """No permission to download the .pbix content (403 on Content/$value)."""


def find_by_path(bulk: PbiRsBulk, path: str) -> dict:
    """Find a Power BI report by its exact path on the server.

    Args:
        bulk: the PbiRsBulk orchestrator (network + catalog).
        path: full report path, e.g. `/Shared Reports/Self-service`.

    Returns:
        The catalog item (dict with Id, Name, Path, Type...).

    Raises:
        PbirsPathError: if the report is not found at this path.
    """
    params = {
        "$filter": f"Path eq '{path}' and Type eq 'PowerBIReport'",
        "$select": "*",
    }
    r = bulk.net.get(f"https://{bulk.server}{bulk.base}{bulk.api}/CatalogItems", params)
    if r.status_code != 200:
        raise PbirsAccessError(f"Catalog {path} -> HTTP {r.status_code}")
    items = r.json().get("value", [])
    if not items:
        raise PbirsPathError(f"Report not found at path: {path}")
    return items[0]


def download_report(bulk: PbiRsBulk, item: dict, dest: Path) -> Path:
    """Download the report .pbix; raises PbirsAccessError on 403."""
    iid = item["Id"]
    url = (
        f"https://{bulk.server}{bulk.base}{bulk.api}/catalogitems({iid})/Content/$value"
    )
    r = bulk.net.request("GET", url)
    if r.status_code == 403:
        raise PbirsAccessError(
            f"No permission to download '{item['Name']}' (HTTP 403). "
            f"Content/$value is closed for the current user on {bulk.server}."
        )
    if r.status_code != 200 or not r.content:
        raise PbirsAccessError(f"Download '{item['Name']}' -> HTTP {r.status_code}")
    dest.write_bytes(r.content)
    return dest


def _thesis(lineage: dict, item: dict) -> dict:
    """Assemble the dashboard's thesis structure from lineage (PbiLineage.to_json())."""
    summary = lineage.get("summary", {})
    theses = {
        "name": item.get("Name"),
        "path": item.get("Path"),
        "analyzed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "pages": summary.get("pages", 0),
            "visuals": summary.get("visuals", 0),
            "tables": summary.get("tables", 0),
            "business_tables": summary.get("business_tables", 0),
            "technical_tables": summary.get("technical_tables", 0),
            "measures": summary.get("measures", 0),
            "calc_columns": summary.get("calc_columns", 0),
            "power_queries": summary.get("power_queries", 0),
            "sources_with_data": summary.get("sources_with_data", 0),
            "sources_access_error": summary.get("sources_access_error", 0),
            "sources_unresolved": summary.get("sources_unresolved", 0),
            "relationships": summary.get("relationships", 0),
        },
    }
    pages = lineage.get("pages", [])
    theses["pages"] = [
        {
            "index": p.get("index"),
            "name": p.get("name"),
            "n_visuals": p.get("n_visuals", 0),
            "n_bindings": p.get("n_bindings", 0),
            "tables": sorted(p.get("tables", [])),
            "visual_types": [v.get("type") for v in p.get("visuals", [])],
        }
        for p in pages
    ]
    theses["sources"] = lineage.get("sources", {})
    return theses


def inspect_board(path: str, keep_pbix: bool = False) -> dict:
    """Download a dashboard .pbix by path and return its elements (as a thesis).

    Args:
        path: full report path on the Report Server.
        keep_pbix: whether to keep the .pbix in output_files (otherwise a temp file).

    Returns:
        Dict: summary + pages + sources (the dashboard's thesis structure).

    Raises:
        PbirsPathError: path not found.
        PbirsAccessError: no permission / network error while downloading.
    """
    bulk = PbiRsBulk()
    item = find_by_path(bulk, path)

    out_dir = OUT_DIR / "inspect"
    out_dir.mkdir(parents=True, exist_ok=True)
    pbix = out_dir / f"{Path(item['Name']).stem}.pbix"

    logger.info("Downloading: %s (%s)", item["Name"], item["Path"])
    download_report(bulk, item, pbix)
    logger.info("Downloaded: %s (%.2f MB)", pbix.name, pbix.stat().st_size / 1e6)

    try:
        res = bulk.analyze(pbix)
    finally:
        if not keep_pbix and pbix.exists():
            pbix.unlink()

    return _thesis(res.get("lineage", {}), item)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(
        description="Inspect a Report Server dashboard: elements by path"
    )
    p.add_argument("--path", required=True, help="full report path on the server")
    p.add_argument(
        "--keep-pbix",
        action="store_true",
        help="keep the downloaded .pbix in output_files/inspect",
    )
    args = p.parse_args(argv)

    try:
        thesis = inspect_board(args.path, keep_pbix=args.keep_pbix)
    except (PbirsPathError, PbirsAccessError) as e:
        logger.error("%s", e)
        return 1

    print(json.dumps(thesis, ensure_ascii=False, indent=2))
    report = OUT_DIR / "inspect" / f"{Path(args.path).name}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(thesis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Saved: %s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

==================== FILE: src/agentic_bi/dax_markers.py ====================

"""Distortion markers and their scanning for DAX/M analysis."""

from __future__ import annotations

import re

# Markers in DAX indicating a distortion risk.
DAX_DISTORT_MARKERS = {
    "hardcoded_threshold": re.compile(r"<=?\s*0\.\d+|>=\s*0\.\d+|\b\d+\.\d{2,}\b"),
    "filter_all": re.compile(r"FILTER\s*\(\s*ALL"),
    "isblank_default": re.compile(r"ISBLANK\s*\("),
    "switch_const": re.compile(r"SWITCH\s*\("),
    "var_no_return": re.compile(r"VAR\b.+?RETURN\b", re.DOTALL),
    "format_column": re.compile(r"FORMAT\s*\("),
}

# Markers in Power Query M code indicating a risk.
M_DISTORT_MARKERS = {
    "hardcoded_path": re.compile(
        r"(C:|D:|E:|H:)[\\/]Users|File\.Contents\(\s*[\"']([A-Za-z]:|\\\\)"
    ),
    "local_now": re.compile(
        r"DateTime\.LocalNow|DateTime\.FixedLocalNow", re.IGNORECASE
    ),
    "fixed_date": re.compile(r"#date\(\s*\d{4}"),
    "file_share": re.compile(r"\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9_.-]+"),
}


def scan_markers(expr: str, markers: dict) -> list[str]:
    """Return the list of markers that fired for one expression."""
    return [name for name, pat in markers.items() if pat.search(expr)]

