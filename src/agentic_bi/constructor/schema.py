"""Machine-readable JSON Schemas for the constructor's inputs and report.

The schemas exist for agents: they make it possible to write a design or a
model context without reading the sources. They are a top-level contract, not a
replacement for validation - cross-references and semantics are checked by
`validate_design`, which the schema cannot express.
"""

from __future__ import annotations

from agentic_bi.constructor.blocks import catalog
from agentic_bi.constructor.model import ALLOWED_TYPES
from agentic_bi.constructor.report import SCHEMA_VERSION

_JSON_SCHEMA = "https://json-schema.org/draft/2020-12/schema"
_TYPE_ENUM = sorted(ALLOWED_TYPES)


def _block_schema() -> dict[str, object]:
    return {
        "type": "object",
        "required": ["kind"],
        "properties": {
            "id": {"type": "string"},
            "kind": {
                "type": "string",
                "enum": sorted(str(block["kind"]) for block in catalog()),
            },
            "table": {"type": "string"},
            "columns": {"type": "array", "items": {"type": "string"}},
            "axis": {"type": "string"},
            "value": {"type": "string"},
            "measure": {"type": "string"},
            "agg": {"type": "string"},
            "extra_values": {"type": "array", "items": {"type": "string"}},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "tooltip": {"type": "string"},
            "pos": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": {"type": "integer", "minimum": 0},
            },
            "span": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": False,
    }


def _model_schema() -> dict[str, object]:
    column = {
        "oneOf": [
            {"type": "string", "description": "column name (type string)"},
            {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": _TYPE_ENUM},
                },
            },
            {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {"type": "string"},
            },
        ]
    }
    table = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "columns": {
                "oneOf": [
                    {
                        "type": "object",
                        "additionalProperties": {"type": "string", "enum": _TYPE_ENUM},
                    },
                    {"type": "array", "items": column},
                ]
            },
            "measures": {
                "oneOf": [
                    {"type": "object", "additionalProperties": {"type": "string"}},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
        },
    }
    relationship = {
        "type": "object",
        "required": ["fromTable", "fromColumn", "toTable", "toColumn"],
        "properties": {
            "fromTable": {"type": "string"},
            "fromColumn": {"type": "string"},
            "toTable": {"type": "string"},
            "toColumn": {"type": "string"},
            "isActive": {"type": "boolean"},
        },
    }
    return {
        "type": "object",
        "properties": {
            "database": {"type": "string"},
            "tables": {
                "oneOf": [
                    {"type": "object", "additionalProperties": table},
                    {"type": "array", "items": table},
                ]
            },
            "relationships": {"type": "array", "items": relationship},
        },
    }


def design_schema() -> dict[str, object]:
    """Return the JSON Schema of a design (pages, blocks and the model context)."""
    return {
        "$schema": _JSON_SCHEMA,
        "title": "constructor.design/1",
        "type": "object",
        "required": ["pages"],
        "properties": {
            "name": {"type": "string"},
            "database": {"type": "string"},
            "model": _model_schema(),
            "pages": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["visuals"],
                    "properties": {
                        "name": {"type": "string"},
                        "title": {"type": "string"},
                        "width": {"type": "integer", "minimum": 320},
                        "height": {"type": "integer", "minimum": 240},
                        "visuals": {
                            "type": "array",
                            "minItems": 1,
                            "items": _block_schema(),
                        },
                    },
                },
            },
        },
        "additionalProperties": False,
        "x-blocks": catalog(),
        "x-column-types": _TYPE_ENUM,
    }


def context_schema() -> dict[str, object]:
    """Return the JSON Schema of a model context."""
    return {
        "$schema": _JSON_SCHEMA,
        "title": "constructor.context/1",
        "allOf": [_model_schema()],
        "x-column-types": _TYPE_ENUM,
    }


def report_schema() -> dict[str, object]:
    """Return the JSON Schema of the machine report (`TestReport.as_dict`)."""
    return {
        "$schema": _JSON_SCHEMA,
        "title": SCHEMA_VERSION,
        "type": "object",
        "required": [
            "schema",
            "ok",
            "critical_ok",
            "passed",
            "failed",
            "warnings",
            "checks",
        ],
        "properties": {
            "schema": {"const": SCHEMA_VERSION},
            "title": {"type": "string"},
            "ok": {"type": "boolean"},
            "critical_ok": {"type": "boolean"},
            "passed": {"type": "integer"},
            "failed": {"type": "integer"},
            "warnings": {"type": "integer"},
            "meta": {"type": "object"},
            "checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["group", "name", "ok"],
                    "properties": {
                        "group": {"type": "string"},
                        "name": {"type": "string"},
                        "ok": {"type": "boolean"},
                        "critical": {"type": "boolean"},
                        "level": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                },
            },
        },
    }


_SCHEMAS = {"design": design_schema, "context": context_schema, "report": report_schema}


def get_schema(name: str) -> dict[str, object]:
    """Return the schema called `name` (`design`, `context` or `report`).

    Raises:
        ValueError: the name is unknown; the message lists the available ones.
    """
    try:
        return _SCHEMAS[name]()
    except KeyError as exc:
        raise ValueError(
            f"unknown schema {name!r}; available: {sorted(_SCHEMAS)}"
        ) from exc


__all__ = [
    "SCHEMA_VERSION",
    "context_schema",
    "design_schema",
    "get_schema",
    "report_schema",
]
