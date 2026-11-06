"""Value-level validation primitives for the declarative dashboard spec.

Split out of `spec_boundary` (which grew past the file-size budget): this module
owns the leaf checks of untrusted input — the path-qualified error message, the
mapping/list/string/integer coercions and the element vocabulary — without knowing
anything about the spec records built from them.

Every message names the exact path to the offending field, and every failure is a
`ValueError`.

Public API:
    as_mapping(value, where) -> Mapping
    as_sequence(value, where) -> list
    opt_str(mapping, key, where) -> str | None
    req_str(mapping, key, where, *, default="") -> str
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn

# Element type tags the board builder understands.
ELEMENT_TYPES = frozenset({"kpi", "chart", "table"})
FIELD_KINDS = ("column", "measure")


# ─── error reporting ───────────────────────────────────────


def _bad(where: str, expected: str, value: object) -> NoReturn:
    """Raise a path-qualified `ValueError` for an untrusted value."""
    raise ValueError(
        f"spec: field '{where}': expected {expected}, got {type(value).__name__}"
    )


def _join(base: str, key: str) -> str:
    return f"{base}.{key}" if base else key


def _index(base: str, i: int) -> str:
    return f"{base}[{i}]"


# ─── scalar coercion ───────────────────────────────────────


def as_mapping(value: object, where: str) -> Mapping[str, object]:
    """Check `value` is a mapping with string keys (JSON object)."""
    if not isinstance(value, Mapping):
        _bad(where, "mapping", value)
    for key in value:
        if not isinstance(key, str):
            _bad(where, "string keys", key)
    return value


def as_sequence(value: object, where: str) -> list[object]:
    """Check `value` is a list (a JSON/YAML array)."""
    if not isinstance(value, list):
        _bad(where, "list", value)
    return value


def opt_str(m: Mapping[str, object], key: str, where: str) -> str | None:
    """Read an optional string field; `null`/absent become `None`."""
    value = m.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        _bad(_join(where, key), "string", value)
    return value


def req_str(m: Mapping[str, object], key: str, where: str, *, default: str = "") -> str:
    """Read a string field, defaulting when absent (never when mistyped)."""
    value = m.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        _bad(_join(where, key), "string", value)
    return value


def _field(value: object, where: str) -> dict[str, object] | None:
    """Read an optional field mapping and check the *types* of `kind`/`property`.

    Whether a well-typed `kind` is a known one stays a `validate_spec` problem:
    the boundary rejects what cannot become a typed record, not what is merely
    unsupported.
    """
    if value is None:
        return None
    field = dict(as_mapping(value, where))
    for child in ("kind", "property"):
        child_value = field.get(child)
        if child_value is not None and not isinstance(child_value, str):
            _bad(_join(where, child), "string", child_value)
    return field


def _opt_field(
    m: Mapping[str, object], key: str, where: str
) -> dict[str, object] | None:
    return _field(m.get(key), _join(where, key))


def _str_list(m: Mapping[str, object], key: str, where: str) -> list[str]:
    value = m.get(key)
    if value is None:
        return []
    path = _join(where, key)
    out: list[str] = []
    for i, item in enumerate(as_sequence(value, path)):
        if not isinstance(item, str):
            _bad(_index(path, i), "string", item)
        out.append(item)
    return out


def _pos(m: Mapping[str, object], where: str) -> list[int] | None:
    value = m.get("pos")
    if value is None:
        return None
    path = _join(where, "pos")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        _bad(path, "[x, y, w, h]", value)
    out: list[int] = []
    for i, item in enumerate(value):
        if not isinstance(item, int) or isinstance(item, bool):
            _bad(_index(path, i), "integer", item)
        out.append(item)
    return out


__all__ = [
    "ELEMENT_TYPES",
    "FIELD_KINDS",
    "as_mapping",
    "as_sequence",
    "opt_str",
    "req_str",
]
