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
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agentic_bi import settings
from agentic_bi.board import Board, col, measure

logger = logging.getLogger(__name__)

# element type tags the board builder understands
_ELEMENT_TYPES = {"kpi", "chart", "table"}


def _field_dict(f: dict) -> dict:
    """Normalize a field dict into the board.col()/measure() format.

    The spec is untrusted input, so a malformed field fails here with a message
    naming the offending value, instead of a bare `KeyError`/`AttributeError`
    much later in `spec_to_board`.
    """
    if not isinstance(f, dict):
        raise ValueError(f"a field must be a mapping, got {type(f).__name__}: {f!r}")
    prop = f.get("property")
    if not prop:
        raise ValueError(f"a field must have a 'property' key: {f!r}")
    kind = f.get("kind", "column")
    if kind == "measure":
        return measure(prop, f.get("display"))
    return col(prop, f.get("display"), agg=f.get("agg"))


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
    quality: dict = field(default_factory=dict)  # {thresholds: {...}}
    deploy: dict = field(default_factory=dict)  # {pbirs_sync_config, ...}
    control: dict = field(default_factory=dict)  # {verify, expected}
    support: dict = field(default_factory=dict)  # {agents, enable_ids, disable_ids}


# ─── parsing ───────────────────────────────────────────────


def _parse_element(e: dict) -> ElementSpec:
    if not isinstance(e, dict):
        raise ValueError(f"an element must be a mapping, got {type(e).__name__}: {e!r}")
    etype = e.get("type", "table")
    if etype not in _ELEMENT_TYPES:
        raise ValueError(
            f"Unknown element type '{etype}'; allowed: {sorted(_ELEMENT_TYPES)}"
        )
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
    if not isinstance(p, dict):
        raise ValueError(f"a page must be a mapping, got {type(p).__name__}: {p!r}")
    elements = p.get("elements", []) or []
    if not isinstance(elements, list):
        raise ValueError(f"page '{p.get('name')}': elements must be a list")
    return PageSpec(
        name=p.get("name"),
        title=p.get("title"),
        header=p.get("header"),
        filters=p.get("filters", []) or [],
        elements=[_parse_element(e) for e in elements],
    )


def from_dict(d: dict) -> DashboardSpec:
    """Build a spec from a dict (after YAML/JSON).

    A missing `name` is defaulted to an empty string so `validate_spec` reports
    it as a problem (untrusted input must not crash on a bare `KeyError`).
    """
    dash = d.get("dashboard", d)
    pages = [_parse_page(p) for p in dash.get("pages", []) or []]
    return DashboardSpec(
        name=dash.get("name", ""),
        table=settings.resolve_model(table=dash.get("table")).table,
        measure_table=dash.get("measure_table"),
        pages=pages,
        quality=d.get("quality", {}) or {},
        deploy=d.get("deploy", {}) or {},
        control=d.get("control", {}) or {},
        support=d.get("support", {}) or {},
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
            raise RuntimeError(
                "YAML specs need PyYAML: uv pip install pyyaml"
            ) from None
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

        return yaml.safe_dump(to_dict(spec), allow_unicode=True, sort_keys=False)
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
            page.header(ps.header)
        for el in ps.elements:
            pos = tuple(el.pos) if el.pos else None
            if el.type == "kpi":
                page.kpi(_field_dict(el.field), pos=pos)
            elif el.type == "chart":
                page.chart(
                    el.visual_type, _field_dict(el.axis), _field_dict(el.value), pos=pos
                )
            elif el.type == "table":
                page.table([_field_dict(f) for f in el.fields], pos=pos)
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
