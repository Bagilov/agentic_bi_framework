"""Declarative dashboard model (spec).

Lets you describe a dashboard and its lifecycle USING DATA ONLY (YAML/JSON),
without code: page/element composition, model fields, and — at the pipeline
level — which quality thresholds to apply and how to deploy via a git client.

Format (YAML/JSON):

    dashboard:
      name: "Overview board"
      table: Data                   # model table (columns/axes/filters)
      measure_table: Measures       # optional; measures come from this table
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
from dataclasses import asdict, dataclass, field

from agentic_bi.board import Board
from agentic_bi.spec_boundary import (
    field_dict,
    from_dict,
    load,
    pos_tuple,
    required_mapping,
    required_mapping_list,
)


@dataclass
class ElementSpec:
    """A single visual/element of a page."""

    type: str
    field: dict[str, object] | None = None
    fields: list[dict[str, object]] | None = None
    visual_type: str = "lineChart"
    axis: dict[str, object] | None = None
    value: dict[str, object] | None = None
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
    quality: dict[str, object] = field(default_factory=dict)  # {thresholds: {...}}
    deploy: dict[str, object] = field(default_factory=dict)  # {pbirs_sync_config, ...}
    control: dict[str, object] = field(default_factory=dict)  # {verify, expected}
    # {agents, enable_ids, disable_ids}
    support: dict[str, object] = field(default_factory=dict)


# ─── parsing ───────────────────────────────────────────────
# Parsing and field-level validation live in `spec_boundary` (untrusted input).


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
        import yaml

        return yaml.safe_dump(to_dict(spec), allow_unicode=True, sort_keys=False)
    except ImportError:  # pragma: no cover
        return json.dumps(to_dict(spec), ensure_ascii=False, indent=2)


# ─── translation to a board ────────────────────────────────


def spec_to_board(spec: DashboardSpec) -> Board:
    """Translate a spec into a ready ``Board`` builder (agentic_bi.board).

    A hand-built ``DashboardSpec`` can still be incomplete; a missing required
    field raises a path-qualified ``ValueError`` instead of a bare ``TypeError``.
    """
    board = Board(table=spec.table, measure_table=spec.measure_table)
    for pi, ps in enumerate(spec.pages):
        page = board.add_page(ps.name, title=ps.title)
        page.filters(ps.filters)
        if ps.header:
            page.header(ps.header)
        for ei, el in enumerate(ps.elements):
            where = f"pages[{pi}].elements[{ei}]"
            pos = pos_tuple(el.pos, f"{where}.pos")
            if el.type == "kpi":
                field_where = f"{where}.field"
                page.kpi(
                    field_dict(required_mapping(el.field, field_where), field_where),
                    pos=pos,
                )
            elif el.type == "chart":
                axis_where = f"{where}.axis"
                value_where = f"{where}.value"
                page.chart(
                    el.visual_type,
                    field_dict(required_mapping(el.axis, axis_where), axis_where),
                    field_dict(required_mapping(el.value, value_where), value_where),
                    pos=pos,
                )
            elif el.type == "table":
                fields_where = f"{where}.fields"
                page.table(
                    [
                        field_dict(field, f"{fields_where}[{i}]")
                        for i, field in enumerate(
                            required_mapping_list(el.fields, fields_where)
                        )
                    ],
                    pos=pos,
                )
    return board


def validate_spec(spec: DashboardSpec) -> list[str]:
    """Structural validation (see `spec_validate.validate_spec`)."""
    from agentic_bi.spec_validate import validate_spec as _validate

    return _validate(spec)


__all__ = [
    "DashboardSpec",
    "PageSpec",
    "ElementSpec",
    "from_dict",
    "load",
    "to_dict",
    "to_yaml",
    "spec_to_board",
    "validate_spec",
]
