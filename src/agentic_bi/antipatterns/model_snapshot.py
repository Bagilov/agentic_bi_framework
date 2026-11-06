"""Typed, validated snapshot of a pbixray model for the antipattern analysis.

`pbi_antipatterns.analyze_board_objects` accepts an arbitrary pbixray-like
object. That is untrusted input for this package: a foreign or truncated object
must not reach a detector and fail with a bare `AttributeError`/`KeyError`
halfway through the report.

`snapshot_model` checks the shape once — the four frames, their row keys and the
table list — and returns typed rows. A missing member or column raises
`ValueError("antipatterns: field '<frame>[i].<Key>': ...")`, so the caller sees
which part of the model is wrong.

Public API:
    ModelSnapshot, SourceRow, MeasureRow, ColumnRow
    snapshot_model(model) -> ModelSnapshot
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class _Frame(Protocol):
    """A pandas-like frame: `iterrows()` yields `(index, row)` pairs."""

    def iterrows(self) -> Iterable[tuple[object, object]]: ...


@runtime_checkable
class _Row(Protocol):
    """A pandas-like row (Series) or a mapping: read a cell by column name."""

    def __getitem__(self, key: str) -> object: ...


@dataclass(frozen=True)
class SourceRow:
    """One Power Query (M) expression of a source table."""

    table: str
    expression: str


@dataclass(frozen=True)
class MeasureRow:
    """One DAX measure."""

    table: str
    name: str
    expression: str


@dataclass(frozen=True)
class ColumnRow:
    """One calculated column."""

    table: str
    column: str
    expression: str


@dataclass
class ModelSnapshot:
    """The model parts the antipattern detectors consume."""

    sources: list[SourceRow] = field(default_factory=list)
    measures: list[MeasureRow] = field(default_factory=list)
    columns: list[ColumnRow] = field(default_factory=list)
    schema_tables: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)


def _join(base: str, key: str) -> str:
    return f"{base}.{key}" if base else key


def _bad(where: str, expected: str, value: object) -> ValueError:
    return ValueError(
        f"antipatterns: field '{where}': expected {expected}, "
        f"got {type(value).__name__}"
    )


def _member(model: object, name: str) -> object:
    """Read a required model member, naming it when it is absent."""
    try:
        return getattr(model, name)
    except AttributeError:
        raise ValueError(
            f"antipatterns: model has no '{name}' (pbixray object expected)"
        ) from None


def _frames(value: object, where: str) -> Iterable[tuple[object, object]]:
    if not isinstance(value, _Frame):
        raise _bad(where, "a frame with iterrows()", value)
    return value.iterrows()


def _cell(row: object, key: str, where: str) -> object:
    if not isinstance(row, _Row):
        raise _bad(where, "a row indexable by column name", row)
    try:
        return row[key]
    except KeyError:
        raise ValueError(
            f"antipatterns: field '{_join(where, key)}' is missing"
        ) from None


def _text(value: object) -> str:
    """A non-string expression carries no code (`""` is a no-op for detectors)."""
    return value if isinstance(value, str) else ""


def _name(value: object, where: str, key: str) -> str:
    if not isinstance(value, str):
        raise _bad(_join(where, key), "string", value)
    return value


def _names(value: object, where: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise _bad(where, "a list of names", value)
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise _bad(f"{where}[{i}]", "string", item)
        out.append(item)
    return out


def _sources(value: object) -> list[SourceRow]:
    where = "power_query"
    if isinstance(value, _Frame):
        out: list[SourceRow] = []
        for i, (_idx, row) in enumerate(value.iterrows()):
            at = f"{where}[{i}]"
            out.append(
                SourceRow(
                    table=_name(_cell(row, "TableName", at), at, "TableName"),
                    expression=_text(_cell(row, "Expression", at)),
                )
            )
        return out
    if isinstance(value, Mapping):
        return [
            SourceRow(table=_name(table, where, "key"), expression=_text(expr))
            for table, expr in value.items()
        ]
    raise _bad(where, "a frame with iterrows() or a table -> M code mapping", value)


def _measures(value: object) -> list[MeasureRow]:
    out: list[MeasureRow] = []
    for i, (_idx, row) in enumerate(_frames(value, "dax_measures")):
        where = f"dax_measures[{i}]"
        out.append(
            MeasureRow(
                table=_name(_cell(row, "TableName", where), where, "TableName"),
                name=_name(_cell(row, "Name", where), where, "Name"),
                expression=_text(_cell(row, "Expression", where)),
            )
        )
    return out


def _columns(value: object) -> list[ColumnRow]:
    out: list[ColumnRow] = []
    for i, (_idx, row) in enumerate(_frames(value, "dax_columns")):
        where = f"dax_columns[{i}]"
        out.append(
            ColumnRow(
                table=_name(_cell(row, "TableName", where), where, "TableName"),
                column=_name(_cell(row, "ColumnName", where), where, "ColumnName"),
                expression=_text(_cell(row, "Expression", where)),
            )
        )
    return out


def _schema_tables(value: object) -> list[str]:
    out: list[str] = []
    for i, (_idx, row) in enumerate(_frames(value, "schema")):
        where = f"schema[{i}]"
        out.append(_name(_cell(row, "TableName", where), where, "TableName"))
    return out


def snapshot_model(model: object) -> ModelSnapshot:
    """Validate a pbixray-like model and return its typed snapshot.

    Raises:
        ValueError: the object lacks a member or a row lacks a required column;
            the message names the exact field (`dax_measures[2].TableName`).
    """
    return ModelSnapshot(
        sources=_sources(_member(model, "power_query")),
        measures=_measures(_member(model, "dax_measures")),
        columns=_columns(_member(model, "dax_columns")),
        schema_tables=_schema_tables(_member(model, "schema")),
        tables=_names(_member(model, "tables"), "tables"),
    )


__all__ = [
    "ColumnRow",
    "MeasureRow",
    "ModelSnapshot",
    "SourceRow",
    "snapshot_model",
]
