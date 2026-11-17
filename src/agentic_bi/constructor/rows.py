"""Row normalization: untrusted CSV/JSON/DataFrame rows -> typed model rows.

Rows arrive from a CSV/JSON file, a DataFrame or a caller's list, so every value
is checked against the declared column type before it reaches the engine. A
non-integer in an `int64` column, an out-of-range integer or a row that names a
column the model does not have is a `ValueError` with its exact location
(`Sales[3].amount`), not a silently missing value in the artifact.

Public API:
    Rows
    coerce_value(value, type, where) -> object
    normalize_rows(design, data, table=None) -> {table: rows}
"""

from __future__ import annotations

from datetime import date, datetime

from agentic_bi.constructor.design import Design

Rows = dict[str, list[dict[str, object]]]


def _is_missing(value: object) -> bool:
    """True for None/NaN/NaT/Decimal('NaN'): such values become NULL."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    if type(value).__name__ == "Decimal" and str(value) == "NaN":
        return True
    return type(value).__name__ in ("NaTType", "NAType")


def coerce_value(value: object, typ: str, where: str) -> object:
    """Coerce one value to the declared column type (CSV/JSON arrive as text).

    Raises:
        ValueError: the value cannot be represented as `typ` (a non-integer for
            `int64`, an out-of-range integer, a non-number for `double`).
    """
    if _is_missing(value):
        return None
    if typ == "string":
        if isinstance(value, bool):
            return "true" if value else "false"
        return value if isinstance(value, str) else str(value)
    if isinstance(value, str) and not value.strip():
        return None
    if typ == "int64":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            if not -(2**63) <= value <= 2**63 - 1:
                raise ValueError(f"{where}: int64 out of range: {value!r}")
            return value
        try:
            number = float(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{where}: expected int64, got {value!r}") from exc
        if not number.is_integer():
            raise ValueError(f"{where}: expected int64, got {value!r}")
        result = int(number)
        if not -(2**63) <= result <= 2**63 - 1:
            raise ValueError(f"{where}: int64 out of range: {value!r}")
        return result
    if typ == "double":
        try:
            return float(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{where}: expected double, got {value!r}") from exc
    if typ == "date":
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)
    return value


def normalize_rows(design: Design, data: object, table: str | None = None) -> Rows:
    """Check rows and coerce their values to the model column types.

    Args:
        design: the design whose `model` defines tables and column types.
        data: `{table: rows}`, or a pandas DataFrame together with `table`.
        table: the table name for a DataFrame input.

    Raises:
        ValueError: the input is not rows, names an unknown table or column, or
            a value cannot be coerced to its column type.
    """
    if isinstance(data, dict):
        values: Rows = {}
        for key, rows in data.items():
            if isinstance(rows, (str, bytes, dict)) or not isinstance(
                rows, (list, tuple)
            ):
                raise ValueError(f"data for table {key!r} must be a list of rows")
            values[str(key)] = list(rows)
    else:
        to_dict = getattr(data, "to_dict", None)
        if not callable(to_dict):
            raise ValueError("data must be {table: rows} or a pandas DataFrame")
        if not table:
            raise ValueError("table= is required for a DataFrame input")
        records = to_dict(orient="records")
        if not isinstance(records, list):
            raise ValueError("DataFrame.to_dict(orient='records') must return a list")
        values = {table: records}
    known = design.model.tables
    unknown = set(values) - set(known)
    if unknown:
        raise ValueError(f"data tables are not in model context: {sorted(unknown)}")
    normalized: Rows = {}
    for name, rows in values.items():
        columns = known[name].columns
        out_rows: list[dict[str, object]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(
                    f"{name}[{index}] must be an object, got {type(row).__name__}"
                )
            extra = {str(column) for column in row} - set(columns)
            if extra:
                raise ValueError(
                    f"data columns are not in model context: {name}.{sorted(extra)}"
                )
            out_rows.append(
                {
                    str(column): coerce_value(
                        value, columns[str(column)], f"{name}[{index}].{column}"
                    )
                    for column, value in row.items()
                }
            )
        normalized[name] = out_rows
    return normalized


__all__ = ["Rows", "coerce_value", "normalize_rows"]
