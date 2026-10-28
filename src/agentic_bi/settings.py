"""Overridable defaults for the donor model object names.

The framework builds a report *layout* that references objects (tables,
columns, measures) that must already exist in the donor's binary DataModel. The
caller has always been able to pass those names explicitly, but each entry point
also carried a donor-specific default (``fact_table``, ``kpi_measures``,
``metric``, ``score``) baked into its signature, so the shipped code silently
described one particular model instead of the generic contract.

This module is the single place those names live. Every default is neutral
(``Data``/``Value``) and, more importantly, resolvable without editing code:

* pass the value explicitly (always wins), or
* set an environment variable (``PBI_MODEL_TABLE``, ``PBI_MODEL_MEASURE_TABLE``,
  ``PBI_MODEL_COLUMN``, ``PBI_MODEL_MEASURE``), or
* replace :data:`DEFAULTS` in-process.

Resolution order per field is explicit argument > environment > built-in
neutral default. There is no new runtime dependency; the module is stdlib-only,
like the rest of the package.

Public API:
    ModelNames                 - the four resolved object names (frozen dataclass)
    DEFAULT_TABLE              - neutral table name (``"Data"``)
    DEFAULT_COLUMN             - neutral column name (``"Value"``)
    DEFAULT_MEASURE            - neutral measure name (``"Value"``)
    DEFAULTS                   - the module-level :class:`ModelNames` instance
    default_model()            - resolve a :class:`ModelNames` from the environment
    resolve_model(...)         - apply explicit overrides on top of the defaults
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Neutral names: valid Power BI identifiers that encode no donor. They are the
# fallback only, so a caller that does not configure the model gets a layout
# referencing `Data`/`Value` rather than one team's private fact table.
DEFAULT_TABLE = "Data"
DEFAULT_COLUMN = "Value"
DEFAULT_MEASURE = "Value"

_ENV_TABLE = "PBI_MODEL_TABLE"
_ENV_MEASURE_TABLE = "PBI_MODEL_MEASURE_TABLE"
_ENV_COLUMN = "PBI_MODEL_COLUMN"
_ENV_MEASURE = "PBI_MODEL_MEASURE"


@dataclass(frozen=True)
class ModelNames:
    """The donor model object names a layout may reference.

    Attributes:
        table: table that holds the columns/axes/filters (required).
        measure_table: optional separate table that holds the measures.
        column: default column referenced when none is given.
        measure: default measure referenced when none is given.
    """

    table: str = DEFAULT_TABLE
    measure_table: str | None = None
    column: str = DEFAULT_COLUMN
    measure: str = DEFAULT_MEASURE


DEFAULTS = ModelNames()


def default_model() -> ModelNames:
    """Return the environment-resolved defaults, falling back to :data:`DEFAULTS`.

    A blank environment variable is treated as unset, so ``PBI_MODEL_TABLE=``
    does not turn the table name into an empty string.
    """
    return ModelNames(
        table=os.environ.get(_ENV_TABLE) or DEFAULTS.table,
        measure_table=os.environ.get(_ENV_MEASURE_TABLE) or DEFAULTS.measure_table,
        column=os.environ.get(_ENV_COLUMN) or DEFAULTS.column,
        measure=os.environ.get(_ENV_MEASURE) or DEFAULTS.measure,
    )


def resolve_model(
    table: str | None = None,
    measure_table: str | None = None,
    column: str | None = None,
    measure: str | None = None,
) -> ModelNames:
    """Resolve the effective object names for one call.

    Args:
        table: explicit table name; ``None`` falls through to the defaults.
        measure_table: explicit measures table; ``None`` uses the default.
        column: explicit default column; ``None`` uses the default.
        measure: explicit default measure; ``None`` uses the default.

    Returns:
        A :class:`ModelNames` where each ``None`` argument was replaced by the
        environment/default value.
    """
    base = default_model()
    return ModelNames(
        table=table if table is not None else base.table,
        measure_table=measure_table
        if measure_table is not None
        else base.measure_table,
        column=column if column is not None else base.column,
        measure=measure if measure is not None else base.measure,
    )


__all__ = [
    "DEFAULT_COLUMN",
    "DEFAULT_MEASURE",
    "DEFAULT_TABLE",
    "DEFAULTS",
    "ModelNames",
    "default_model",
    "resolve_model",
]
