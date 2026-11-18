"""Type inference helpers for the engine data pipeline."""

from __future__ import annotations

import datetime as _dt

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M:%S",
    "%Y/%m/%d",
)


def coerce(v):
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v).strip()
    if s == "" or s.lower() in ("na", "nan", "null", "none"):
        return None
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s.replace(",", "") if low.count(",") == 1 else s)
    except ValueError:
        return v


def is_date(v) -> bool:
    if isinstance(v, (_dt.date, _dt.datetime)):
        return True
    if not isinstance(v, str):
        return False
    return any(try_fmt(v, f) for f in _DATE_FORMATS)


def try_fmt(v: str, fmt: str) -> bool:
    try:
        _dt.datetime.strptime(v.strip(), fmt)
        return True
    except ValueError:
        return False


def to_iso(v) -> str:
    if isinstance(v, _dt.datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(v, _dt.date):
        return v.strftime("%Y-%m-%d")
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(str(v).strip(), fmt).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        except ValueError:
            continue
    return str(v)


def parse_date(v: object) -> str | None:
    """Normalize one date value to ISO seconds, or `None` when unparseable.

    A single pass over `_DATE_FORMATS` (no validate-then-convert double scan).
    `datetime`/`date` objects and strings normalize identically — truncated to
    seconds, no sub-second part or tz offset — so every input channel reaches
    the engine as the same literal the DAX `DATE()+TIME()` build will store.
    """
    if isinstance(v, _dt.datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(v, _dt.date):
        return v.strftime("%Y-%m-%dT00:00:00")
    if not isinstance(v, str):
        return None
    text = v.strip()
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(text, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return None


def typed_column(name: str, vals: list) -> dict:
    """Return {name,type,values} with a normalized type."""
    nn = [v for v in vals if v is not None]
    if nn and all(isinstance(v, bool) for v in nn):
        return {
            "name": name,
            "type": "int64",
            "values": [None if v is None else int(v) for v in vals],
        }
    if nn and all(isinstance(v, int) for v in nn):
        return {"name": name, "type": "int64", "values": vals}
    if (
        nn
        and all(isinstance(v, (int, float)) for v in nn)
        and not all(is_date(v) for v in nn)
    ):
        return {"name": name, "type": "double", "values": vals}
    if nn and all(is_date(v) for v in nn):
        return {
            "name": name,
            "type": "date",
            "values": [None if v is None else to_iso(v) for v in vals],
        }
    return {
        "name": name,
        "type": "string",
        "values": [None if v is None else str(v) for v in vals],
    }
