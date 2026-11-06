"""Boundary parsing/validation for the declarative dashboard spec.

`spec.py` owns the dataclasses and the translation into a `board.Board`; this
module owns the *untrusted-input* side. A spec arrives as JSON/YAML, so every
field is checked before it is turned into a typed record:

    spec: field 'pages[0].elements[2].kind': expected string, got int

Every message names the exact path to the offending field, and every failure is
a `ValueError` — `cli_support.run_boundary` maps it to exit code 2 (bad input)
instead of letting a bare `KeyError`/`AttributeError` escape deep in the builder.

The leaf checks (field-path messages and scalar coercions) live in
`agentic_bi.spec_boundary_values` and are re-exported here; this module walks the
document (dashboard → pages → elements) and normalizes fields into board shapes.

Public API:
    from_dict(document) -> DashboardSpec
    load(path) -> DashboardSpec
    field_dict(field, where) -> dict            (board.col()/measure() shape)
    pos_tuple(pos, where) -> tuple | None
    required_mapping(value, where) -> Mapping
    required_mapping_list(value, where) -> Sequence[Mapping]
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from agentic_bi.spec_boundary_values import (
    ELEMENT_TYPES,
    FIELD_KINDS,
    _bad,
    _field,
    _index,
    _join,
    _opt_field,
    _pos,
    _str_list,
    as_mapping,
    as_sequence,
    opt_str,
    req_str,
)

if TYPE_CHECKING:
    from agentic_bi.spec import DashboardSpec, ElementSpec, PageSpec

# ─── spec records ─────────────────────────────────────────


def _parse_element(value: object, where: str) -> ElementSpec:
    from agentic_bi.spec import ElementSpec

    e = as_mapping(value, where)
    etype = req_str(e, "type", where, default="table")
    if etype not in ELEMENT_TYPES:
        raise ValueError(
            f"Unknown element type '{etype}'; allowed: {sorted(ELEMENT_TYPES)}"
        )
    fields_path = _join(where, "fields")
    raw_fields = e.get("fields")
    fields: list[dict[str, object]] | None = None
    if raw_fields is not None:
        fields = []
        for i, item in enumerate(as_sequence(raw_fields, fields_path)):
            at = _index(fields_path, i)
            entry = _field(item, at)
            if entry is None:
                _bad(at, "mapping", item)
            fields.append(entry)
    return ElementSpec(
        type=etype,
        field=_opt_field(e, "field", where),
        fields=fields,
        visual_type=req_str(e, "visual_type", where, default="lineChart"),
        axis=_opt_field(e, "axis", where),
        value=_opt_field(e, "value", where),
        pos=_pos(e, where),
        text=opt_str(e, "text", where),
    )


def _parse_page(value: object, where: str) -> PageSpec:
    from agentic_bi.spec import PageSpec

    p = as_mapping(value, where)
    elements_path = _join(where, "elements")
    raw = p.get("elements")
    elements = (
        []
        if raw is None
        else [
            _parse_element(item, _index(elements_path, i))
            for i, item in enumerate(as_sequence(raw, elements_path))
        ]
    )
    return PageSpec(
        name=req_str(p, "name", where),
        title=opt_str(p, "title", where),
        header=opt_str(p, "header", where),
        filters=_str_list(p, "filters", where),
        elements=elements,
    )


def _container(doc: Mapping[str, object], key: str) -> dict[str, object]:
    value = doc.get(key)
    if value is None:
        return {}
    return dict(as_mapping(value, key))


def from_dict(document: object) -> DashboardSpec:
    """Build a spec from a parsed JSON/YAML document (validated, `ValueError`)."""
    from agentic_bi import settings
    from agentic_bi.spec import DashboardSpec

    doc = as_mapping(document, "document")
    raw_dashboard = doc.get("dashboard")
    if raw_dashboard is None:
        dash = doc
        where = ""
    else:
        dash = as_mapping(raw_dashboard, "dashboard")
        where = "dashboard"

    pages_path = _join(where, "pages")
    raw_pages = dash.get("pages")
    pages = (
        []
        if raw_pages is None
        else [
            _parse_page(page, _index(pages_path, i))
            for i, page in enumerate(as_sequence(raw_pages, pages_path))
        ]
    )
    return DashboardSpec(
        name=req_str(dash, "name", where),
        table=settings.resolve_model(table=opt_str(dash, "table", where)).table,
        measure_table=opt_str(dash, "measure_table", where),
        pages=pages,
        quality=_container(doc, "quality"),
        deploy=_container(doc, "deploy"),
        control=_container(doc, "control"),
        support=_container(doc, "support"),
    )


def load(path: Path) -> DashboardSpec:
    """Load a spec from a YAML/JSON file; a malformed document raises `ValueError`."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml

            data = yaml.safe_load(text)
        except ImportError:  # pragma: no cover - depends on the `spec` extra
            raise RuntimeError(
                "YAML specs need PyYAML: uv pip install pyyaml"
            ) from None
    else:
        data = json.loads(text)
    return from_dict(data)


# ─── translation helpers ──────────────────────────────────


def required_mapping(
    value: Mapping[str, object] | None, where: str
) -> Mapping[str, object]:
    """Assert a required mapping field is present (used by `spec_to_board`)."""
    if value is None:
        _bad(where, "mapping", None)
    return value


def required_mapping_list(
    value: Sequence[Mapping[str, object]] | None, where: str
) -> Sequence[Mapping[str, object]]:
    """Assert a required list-of-mappings field is present."""
    if value is None:
        _bad(where, "list", None)
    return value


def field_dict(field: Mapping[str, object], where: str) -> dict:
    """Normalize a field mapping into the `board.col()`/`board.measure()` shape."""
    from agentic_bi.board import col, measure

    prop = field.get("property")
    if not isinstance(prop, str) or not prop:
        _bad(_join(where, "property"), "non-empty string", prop)
    kind = field.get("kind", "column")
    if kind not in FIELD_KINDS:
        _bad(_join(where, "kind"), f"one of {list(FIELD_KINDS)}", kind)
    display = opt_str(field, "display", where)
    if kind == "measure":
        return measure(prop, display)
    return col(prop, display, agg=opt_str(field, "agg", where))


def pos_tuple(pos: list[int] | None, where: str) -> tuple[int, int, int, int] | None:
    """Validate `[x, y, w, h]` and return it as a typed tuple (`None` stays `None`)."""
    if pos is None:
        return None
    if len(pos) != 4:
        _bad(where, "[x, y, w, h]", pos)
    return (pos[0], pos[1], pos[2], pos[3])


__all__ = [
    "ELEMENT_TYPES",
    "FIELD_KINDS",
    "as_mapping",
    "as_sequence",
    "field_dict",
    "from_dict",
    "load",
    "opt_str",
    "pos_tuple",
    "req_str",
    "required_mapping",
    "required_mapping_list",
]
