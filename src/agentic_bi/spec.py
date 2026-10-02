"""Declarative dashboard model (spec).

Lets you describe a dashboard and its lifecycle USING DATA ONLY (YAML/JSON),
without code: page/element composition, model fields, and — at the pipeline
level — which quality thresholds to apply and how to deploy via a git client.

Format (YAML/JSON):

    dashboard:
      name: "Overview board"
      table: fact_table
      measure_table: kpi_measures   # optional
      pages:
        - name: p1
          title: "Main"
          header: "Dashboard · Overview"       # optional
          filters: [category, metric]  # page-level Categorical filters
          elements:
            - type: kpi
              field: {kind: measure, property: metric_a, display: "Metric A"}
            - type: chart
              visual_type: lineChart           # lineChart | clusteredColumnChart
              axis:   {kind: column,  property: period_start, display: "Period"}
              value:  {kind: measure, property: metric_b,    display: "Metric B"}
            - type: table
              fields:
                - {kind: column,  property: metric, display: "Metric"}
                - {kind: measure, property: metric_a,    display: "Metric A"}
    quality:
      thresholds: {}                           # threshold overrides (see thresholds.py)
    deploy:
      pbirs_sync_config: "git-deploy.yaml"   # git-deploy config
      target_folder: "/Target/Dev"
      branch: "dev"
      dry_run: false
    support:
      agents: []                               # support-agent manifests (see agents.py)
      enable_ids: []                           # enable agents from the registry
      disable_ids: []                          # disable agents from the registry

``spec_to_board()`` translates a spec into a ``Board`` object from ``board.py``;
``to_dict/from_dict``/``load`` provide serialization and structural validation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

from agentic_bi.board import Board, col, measure

logger = logging.getLogger(__name__)

# element type tags the board builder understands
_ELEMENT_TYPES = {"kpi", "chart", "table"}


def _field_dict(f: dict) -> dict:
    """Normalize a field dict into the board.col()/measure() format."""
    kind = f.get("kind", "column")
    if kind == "measure":
        return measure(f["property"], f.get("display"))
    return col(f["property"], f.get("display"), agg=f.get("agg"))


@dataclass
class ElementSpec:
    """A single visual/element of a page."""
    type: str
    field: dict | None = None
    fields: list[dict] | None = None
    visual_type: str = "lineChart"
    axis: dict | None = None
    value: dict | None = None
    pos: list[int] | None = None  # [x, y, w, h]
    text: str | None = None


@dataclass
class PageSpec:
    """A board page."""
    name: str
    title: str | None = None
    header: str | None = None
    filters: list[str] = field(default_factory=list)
    elements: list[ElementSpec] = field(default_factory=list)


@dataclass
class DashboardSpec:
    """A declarative dashboard specification."""
    name: str
    table: str
    measure_table: str | None = None
    pages: list[PageSpec] = field(default_factory=list)
    quality: dict = field(default_factory=dict)   # {thresholds: {...}}
    deploy: dict = field(default_factory=dict)    # {pbirs_sync_config, ...}
    control: dict = field(default_factory=dict)   # {verify, expected}
    support: dict = field(default_factory=dict)   # {agents, enable_ids, disable_ids}


# ─── parsing ───────────────────────────────────────────────


def _parse_element(e: dict) -> ElementSpec:
    etype = e.get("type", "table")
    if etype not in _ELEMENT_TYPES:
        raise ValueError(f"Unknown element type '{etype}'; allowed: "
                         f"{sorted(_ELEMENT_TYPES)}")
    return ElementSpec(
        type=etype,
        field=e.get("field"),
        fields=e.get("fields"),
        visual_type=e.get("visual_type", "lineChart"),
        axis=e.get("axis"),
        value=e.get("value"),
        pos=e.get("pos"),
        text=e.get("text"),
    )


def _parse_page(p: dict) -> PageSpec:
    return PageSpec(
        name=p.get("name"),
        title=p.get("title"),
        header=p.get("header"),
        filters=p.get("filters", []),
        elements=[_parse_element(e) for e in p.get("elements", [])],
    )


def from_dict(d: dict) -> DashboardSpec:
    """Build a spec from a dict (after YAML/JSON)."""
    dash = d.get("dashboard", d)
    pages = [_parse_page(p) for p in dash.get("pages", [])]
    return DashboardSpec(
        name=dash["name"],
        table=dash.get("table", "fact_table"),
        measure_table=dash.get("measure_table"),
        pages=pages,
        quality=d.get("quality", {}),
        deploy=d.get("deploy", {}),
        control=d.get("control", {}),
        support=d.get("support", {}),
    )


def load(path: Path) -> DashboardSpec:
    """Load a spec from a YAML/JSON file (depends on the extension)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(text)
        except ImportError:  # pragma: no cover
            raise RuntimeError("YAML specs need PyYAML: uv pip install pyyaml")
    else:
        data = json.loads(text)
    return from_dict(data)


def to_dict(spec: DashboardSpec) -> dict:
    """Back to a dict (for saving/tests)."""
    return {
        "dashboard": {
            "name": spec.name,
            "table": spec.table,
            "measure_table": spec.measure_table,
            "pages": [asdict(p) for p in spec.pages],
        },
        "quality": spec.quality,
        "deploy": spec.deploy,
        "control": spec.control,
        "support": spec.support,
    }


def to_yaml(spec: DashboardSpec) -> str:
    """Serialize a spec to a YAML string."""
    try:
        import yaml  # type: ignore
        return yaml.safe_dump(to_dict(spec), allow_unicode=True,
                              sort_keys=False)
    except ImportError:  # pragma: no cover
        return json.dumps(to_dict(spec), ensure_ascii=False, indent=2)


# ─── translation to a board ────────────────────────────────


def spec_to_board(spec: DashboardSpec) -> Board:
    """Translate a spec into a ready ``Board`` builder (agentic_bi.board)."""
    board = Board(table=spec.table, measure_table=spec.measure_table)
    for ps in spec.pages:
        page = board.add_page(ps.name, title=ps.title)
        page.filters(ps.filters)
        if ps.header:
            page.header(ps.header, pos=ps.header and None)
        for el in ps.elements:
            pos = tuple(el.pos) if el.pos else None
            if el.type == "kpi":
                page.kpi(_field_dict(el.field), pos=pos)
            elif el.type == "chart":
                page.chart(el.visual_type, _field_dict(el.axis),
                           _field_dict(el.value), pos=pos)
            elif el.type == "table":
                page.table([_field_dict(f) for f in el.fields], pos=pos)
    return board


def validate_spec(spec: DashboardSpec) -> list[str]:
    """Structural validation of a spec; returns problems (empty = ok)."""
    problems: list[str] = []
    if not spec.name:
        problems.append("Missing dashboard.name")
    if not spec.table:
        problems.append("Missing dashboard.table")
    if not spec.pages:
        problems.append("No pages (dashboard.pages) — the board is empty")
    for p in spec.pages:
        if not p.name:
            problems.append("Page without name")
        for el in p.elements:
            if el.type == "kpi" and not el.field:
                problems.append(f"{p.name}/kpi: missing field")
            if el.type == "chart" and (not el.axis or not el.value):
                problems.append(f"{p.name}/chart: axis and value are required")
            if el.type == "table" and not el.fields:
                problems.append(f"{p.name}/table: missing fields")
    return problems


__all__ = [
    "DashboardSpec", "PageSpec", "ElementSpec", "from_dict", "load", "to_dict",
    "to_yaml", "spec_to_board", "validate_spec",
]