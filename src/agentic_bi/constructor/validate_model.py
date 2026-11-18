"""Model-reference checks for one block: do its objects exist and fit the type?

Separated from the structural rules in `validate` because these checks need the
whole model context: a table, a column or a measure a block names may simply not
exist, and an aggregation may be meaningless for the column type (a `sum` over a
string or a date). Every finding is a `Issue` located at the block.

Public API:
    check_model_refs(block, model, path, issues) -> None
    check_name_collisions(model, issues) -> None
"""

from __future__ import annotations

from agentic_bi.constructor.design import ModelContext, VisualDesign
from agentic_bi.constructor.issues import Issue

_NUMERIC_AGGS = frozenset({"sum", "avg", "average", "median", "stddev", "var"})


def _err(code: str, message: str, path: str) -> Issue:
    return Issue("error", code, message, path)


def check_model_refs(
    block: VisualDesign, model: ModelContext, path: str, issues: list[Issue]
) -> None:
    """Check that every model object a block names exists, with a usable type."""
    table = model.tables.get(block.table)
    if table is None:
        issues.append(
            _err(
                "unknown_table", f"table {block.table!r} is not in model context", path
            )
        )
        return
    for column in block.columns:
        if column not in table.columns:
            issues.append(
                _err(
                    "unknown_column",
                    f"{block.table}.{column} is not in model context",
                    path,
                )
            )
    for name in ("axis", "value"):
        column = getattr(block, name)
        if column and column not in table.columns:
            issues.append(
                _err(
                    "unknown_column",
                    f"{block.table}.{column} is not in model context",
                    path,
                )
            )
    for column in block.extra_values:
        if column not in table.columns:
            issues.append(
                _err(
                    "unknown_column",
                    f"{block.table}.{column} is not in model context",
                    path,
                )
            )
    if block.measure and block.measure not in table.measures:
        issues.append(
            _err(
                "unknown_measure",
                f"{block.table}.{block.measure} is not a measure",
                path,
            )
        )
    if (
        block.kind == "slicer"
        and block.axis in table.measures
        and block.axis not in table.columns
    ):
        issues.append(
            _err(
                "slicer_by_measure",
                "slicer by a measure is not supported; use a column",
                path,
            )
        )
    candidates: list[str | None] = [block.value, *block.extra_values]
    if not block.measure:
        for candidate in candidates:
            column_type = table.columns.get(str(candidate or ""))
            if column_type in ("string", "date") and block.agg in _NUMERIC_AGGS:
                issues.append(
                    _err(
                        "bad_agg_type",
                        f"agg {block.agg!r} is not valid for "
                        f"{block.table}.{candidate} ({column_type})",
                        path,
                    )
                )


def check_name_collisions(model: ModelContext, issues: list[Issue]) -> None:
    """Reject a measure whose name is also a column of the same table.

    TOM refuses such a measure and the build script skips it with a log line,
    so the build would succeed while the visual renders blank. The gate catches
    it before any artifact, whether or not a visual uses the measure. Tabular
    names are case-insensitive, so `Amount` over `amount` collides too.
    """
    for name, table in model.tables.items():
        columns_low = {column.lower() for column in table.columns}
        for measure in table.measures:
            if measure.lower() in columns_low:
                issues.append(
                    _err(
                        "measure_column_collision",
                        f"measure {name}.{measure} has the same name as a column; "
                        "the engine would drop the measure",
                        f"model.tables[{name}]",
                    )
                )


__all__ = ["check_model_refs", "check_name_collisions"]
