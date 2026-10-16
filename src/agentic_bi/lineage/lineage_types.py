"""Lineage value types and small helpers (no heavy dependencies)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_brand_config(path: str | Path | None):
    """Load brand rules (`brand_config.yaml`) for sheet metrics.

    Defaults to `agentic_bi/brand_config.yaml`; if missing or on error returns
    ``None`` (the metrics module then uses defaults from brand.py).
    """
    from pathlib import Path as _Path

    pkg_dir = _Path(__file__).resolve().parents[1]
    try:
        from agentic_bi.brand_config import BrandConfig
    except ImportError:
        return None
    cfg_path = _Path(path) if path else pkg_dir / "brand_config.yaml"
    if not cfg_path.exists():
        return None
    try:
        return BrandConfig.load(cfg_path)
    except Exception as exc:  # noqa: BLE001 — config is optional
        logger.warning("brand config load failed (%s): %s", cfg_path, exc)
        return None


# --------------------------------------------------------------------------- #
#  Utilities
# --------------------------------------------------------------------------- #
def _brand_level_ru(level: str | None) -> str:
    return {
        "ok": "compliant",
        "warning": "warnings",
        "error": "violation",
        "unknown": "no data",
    }.get(level or "", "")


def _split_table_col(query_ref: str) -> tuple[str, str | None]:
    """Split a queryRef 'Table.Column' into (table, column)."""
    if "." not in query_ref:
        return query_ref, None
    tbl, col = query_ref.split(".", 1)
    return tbl, col


def _strip_agg(token: str) -> str:
    """Strip aggregation wrappers like 'Min(Table.column)' -> 'Table'."""
    m = re.match(r"^(\w+)\(", token)
    if m:
        inner = token[m.end() :]
        if inner.endswith(")"):
            return inner[:-1].split(".", 1)[0]
    return token


# --------------------------------------------------------------------------- #
#  Lineage layers
# --------------------------------------------------------------------------- #
@dataclass
class Source:
    """A data source (top lineage layer).

    Fields:
        type: source type (Excel/CSV/ODBC/...).
        detail: details (path/DSN/table).
        status: access status ('ok'/'access_error'/'unresolved'/'no_power_query').
        error: error text if the source is unavailable/undetermined.
    """

    type: str
    detail: str | None = None
    status: str = "ok"
    error: str | None = None
    path: str | None = None


class SourceAccessError(Exception):
    """An explicit data-source access/unavailability error.

    Raised when a source cannot be read/resolved: the local file does not exist
    or is inaccessible, the model does not open, M code does not determine the
    source. Always accompanied by a clear message (never a silent failure).
    """


@dataclass
class VisualBinding:
    """A single visual-to-data binding (queryRef)."""

    role: str
    query_ref: str
    table: str | None = None
    column: str | None = None


@dataclass
class Visual:
    """A visual from a dashboard page."""

    page: str
    page_idx: int
    visual_type: str
    z_index: str
    bindings: list[VisualBinding] = field(default_factory=list)
    colors: set[str] = field(default_factory=set)
    fonts: set[str] = field(default_factory=set)

    @property
    def tables(self) -> set[str]:
        return {b.table for b in self.bindings if b.table}


@dataclass
class Page:
    """A dashboard page with visuals."""

    index: int
    name: str
    visuals: list[Visual] = field(default_factory=list)

    @property
    def tables(self) -> set[str]:
        out = set()
        for v in self.visuals:
            out |= v.tables
        return out


# --------------------------------------------------------------------------- #
#  Main class
# --------------------------------------------------------------------------- #
