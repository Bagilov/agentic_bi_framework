"""Model context: the tables, columns, measures and relationships a design uses.

The design is checked against this context before any artifact is written, and
the same context becomes the engine build spec. Keeping the model description in
one place is what makes a design portable: the constructor never guesses column
types or measure expressions.

The context is untrusted input (JSON/YAML) or a read-back `.pbix`, so every
field is normalized here and a bad declaration raises `ValueError` naming the
offending name.

Public API:
    TableContext(name, columns={col: type}, measures={name: dax})
    load_mapping(path) -> dict
    norm_type(value) -> str
    relationship_record(row) -> dict | None
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DATABASE = "Dashboard"

_TYPE_ALIASES = {
    "str": "string",
    "text": "string",
    "object": "string",
    "guid": "string",
    "varchar": "string",
    "nvarchar": "string",
    "char": "string",
    "int": "int64",
    "integer": "int64",
    "int32": "int64",
    "int16": "int64",
    "int8": "int64",
    "uint64": "int64",
    "uint32": "int64",
    "uint16": "int64",
    "uint8": "int64",
    "bool": "int64",
    "boolean": "int64",
    "bit": "int64",
    "float": "double",
    "float64": "double",
    "float32": "double",
    "number": "double",
    "decimal": "double",
    "datetime": "date",
    "datetime64": "date",
    "timestamp": "date",
}
ALLOWED_TYPES = frozenset({"string", "int64", "double", "date"})

# Tables Desktop generates for its own date handling; they are not part of a
# user model, so reading a donor must not put them into the context.
TECH_TABLE_PREFIXES = ("DateTableTemplate_", "LocalDateTable_")
_PBIXRAY_TYPE_HINTS = (
    ("datetime", "date"),
    ("date", "date"),
    ("int", "int64"),
    ("uint", "int64"),
    ("bool", "int64"),
    ("float", "double"),
    ("double", "double"),
    ("decimal", "double"),
)


def load_mapping(path: str | Path) -> dict[str, object]:
    """Read a JSON/YAML object from `path`.

    Raises:
        ValueError: the file is not an object, or PyYAML is missing for YAML.
        OSError: the file cannot be read.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    raw: object
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("PyYAML is required for YAML files") from exc
        raw = yaml.safe_load(text)
    else:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name}: JSON/YAML object expected")
    return raw


def norm_type(value: object) -> str:
    """Return the canonical column type for `value` or raise `ValueError`."""
    token = str(value or "string").strip().lower()
    token = _TYPE_ALIASES.get(token, token)
    if token not in ALLOWED_TYPES:
        raise ValueError(
            f"unsupported column type {value!r}; allowed: {sorted(ALLOWED_TYPES)}"
        )
    return token


def pbixray_type(dtype: object) -> str:
    """Map a pandas/pbixray dtype to a constructor column type."""
    token = str(dtype or "").strip().lower()
    for hint, typ in _PBIXRAY_TYPE_HINTS:
        if hint in token:
            return typ
    return "string"


def str_or_none(raw: object) -> str | None:
    """A string field without surrounding spaces; empty becomes `None`."""
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def norm_columns(raw: object) -> dict[str, str]:
    if not raw:
        return {}
    if isinstance(raw, str) or not isinstance(raw, (dict, list, tuple)):
        raise ValueError("columns must be an object or a list")
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            column = str(key).strip()
            if not column:
                raise ValueError("column name is empty")
            if column in out:
                raise ValueError(f"duplicate column name {column!r}")
            out[column] = norm_type(value)
        return out
    for item in raw:
        name: object
        typ: object
        if isinstance(item, str):
            name, typ = item, "string"
        elif isinstance(item, dict) and item.get("name"):
            name, typ = item["name"], item.get("type")
        elif isinstance(item, (list, tuple)) and len(item) == 2 and item[0]:
            name, typ = item[0], item[1]
        else:
            raise ValueError(f"bad column declaration: {item!r}")
        name = str(name).strip()
        if not name:
            raise ValueError("column name is empty")
        if name in out:
            raise ValueError(f"duplicate column name {name!r}")
        out[str(name)] = norm_type(typ)
    return out


def norm_measures(raw: object) -> dict[str, str]:
    if not raw:
        return {}
    if isinstance(raw, str) or not isinstance(raw, (dict, list, tuple)):
        raise ValueError("measures must be an object or a list")
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            measure = str(key).strip()
            if not measure:
                raise ValueError("measure name is empty")
            if measure in out:
                raise ValueError(f"duplicate measure name {measure!r}")
            out[measure] = str(value or "")
        return out
    for item in raw:
        name: object
        expression: object
        if isinstance(item, str):
            name, expression = item, ""
        elif isinstance(item, dict) and item.get("name"):
            name, expression = item["name"], item.get("expression")
        else:
            raise ValueError(f"bad measure declaration: {item!r}")
        name = str(name).strip()
        if not name:
            raise ValueError("measure name is empty")
        if name in out:
            raise ValueError(f"duplicate measure name {name!r}")
        out[str(name)] = str(expression or "")
    return out


def as_bool(value: object) -> bool | None:
    """Parse a boolean field from JSON without inventing truthy values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    return None


def relationship_record(row: dict[str, object]) -> dict[str, object] | None:
    """Map one read-back relationship row to a context record (or `None`)."""
    table_keys = ("FromTableName", "FromTable")
    from_column_keys = ("FromColumnName", "FromColumn")
    to_table_keys = ("ToTableName", "ToTable")
    to_column_keys = ("ToColumnName", "ToColumn")

    def pick(*names: str) -> object:
        for name in names:
            value = row.get(name)
            if value not in (None, ""):
                return value
        return None

    from_table = pick(*table_keys)
    from_column = pick(*from_column_keys)
    to_table = pick(*to_table_keys)
    to_column = pick(*to_column_keys)
    if not all((from_table, from_column, to_table, to_column)):
        return None
    record: dict[str, object] = {
        "fromTable": str(from_table).strip(),
        "fromColumn": str(from_column).strip(),
        "toTable": str(to_table).strip(),
        "toColumn": str(to_column).strip(),
    }
    active = as_bool(pick("IsActive", "isActive"))
    if active is not None:
        record["isActive"] = active
    return record


@dataclass
class TableContext:
    """One table of the model: columns (name -> type) and measures (name -> DAX)."""

    name: str
    columns: dict[str, str] = field(default_factory=dict)
    measures: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, raw: object) -> TableContext:
        """Build a table from its JSON/YAML declaration."""
        if raw is None:
            return cls(name=name)
        if not isinstance(raw, dict):
            raise ValueError(f"table {name!r} declaration must be an object")
        return cls(
            name=name,
            columns=norm_columns(raw.get("columns")),
            measures=norm_measures(raw.get("measures")),
        )


__all__ = [
    "ALLOWED_TYPES",
    "DEFAULT_DATABASE",
    "TECH_TABLE_PREFIXES",
    "TableContext",
    "load_mapping",
    "norm_columns",
    "norm_measures",
    "norm_type",
    "pbixray_type",
    "relationship_record",
    "str_or_none",
]
