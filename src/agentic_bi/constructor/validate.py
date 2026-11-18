"""Design validation: the gate that runs before any `.pbix` is written.

An agent gets a located list of problems (page, block, field) instead of
"something did not render" after launching Desktop. Two layers:

* field rules - what a block kind requires and which fields it ignores;
* model rules - whether the referenced table/column/measure exists, and whether
  an aggregation is valid for the column type.

Cross-page rules (duplicates, ids) and relationships are checked here too;
geometry lives in `validate_geometry`.

Public API:
    validate_design(design) -> list[Issue]
"""

from __future__ import annotations

from agentic_bi.constructor.blocks import AGGREGATIONS, BLOCKS, resolve_kind
from agentic_bi.constructor.design import (
    MIN_HEIGHT,
    MIN_WIDTH,
    Design,
    ModelContext,
    PageDesign,
    VisualDesign,
)
from agentic_bi.constructor.issues import Issue
from agentic_bi.constructor.model import as_bool
from agentic_bi.constructor.validate_geometry import check_page_geometry
from agentic_bi.constructor.validate_model import (
    check_model_refs,
    check_name_collisions,
)

_NUMERIC_AGGS = frozenset({"sum", "avg", "average", "median", "stddev", "var"})
_CHART_KINDS = frozenset({"column", "bar", "line", "pie", "donut"})
_REFERENCE_FIELDS = ("columns", "axis", "value", "measure", "extra_values")


def _err(code: str, message: str, path: str = "") -> Issue:
    return Issue("error", code, message, path)


def _warn(code: str, message: str, path: str = "") -> Issue:
    return Issue("warning", code, message, path)


def _check_fields(block: VisualDesign, path: str, issues: list[Issue]) -> None:
    """Check the field rules of one block against its catalogue entry."""
    spec = BLOCKS[block.kind]
    for name in spec.required:
        if getattr(block, name, None) in (None, "", []):
            issues.append(
                _err("missing_field", f"block {block.kind!r} requires {name!r}", path)
            )
    needs_value = block.kind == "card" or block.kind in _CHART_KINDS
    if block.kind == "matrix" or needs_value:
        if not (block.measure or block.value):
            issues.append(
                _err(
                    "missing_field",
                    f"{block.kind} requires 'measure' or 'value'",
                    path,
                )
            )
    if block.kind == "table" and not block.columns:
        issues.append(_err("empty_columns", "table needs at least one column", path))
    if block.kind == "matrix" and not block.columns:
        issues.append(
            _err("empty_columns", "matrix needs at least one row column", path)
        )
    if block.measure and block.value:
        issues.append(
            _err(
                "measure_value_conflict",
                "set either 'measure' or 'value', not both",
                path,
            )
        )
    allowed = set(spec.required) | set(spec.optional)
    for name in _REFERENCE_FIELDS:
        if getattr(block, name) and name not in allowed:
            issues.append(
                _warn("unused_field", f"block {block.kind!r} ignores {name!r}", path)
            )
    if block.agg != "sum" and "agg" not in allowed:
        issues.append(
            _warn("unused_field", f"block {block.kind!r} ignores 'agg'", path)
        )
    if block.measure and block.agg != "sum" and "agg" in allowed:
        issues.append(
            _err(
                "measure_agg_conflict",
                "aggregation is ignored for a measure; remove 'agg' or 'measure'",
                path,
            )
        )
    if block.agg not in AGGREGATIONS:
        issues.append(
            _err(
                "bad_agg",
                f"unsupported agg {block.agg!r}; allowed: {list(AGGREGATIONS)}",
                path,
            )
        )
    if block.pos is not None:
        x, y, w, h = block.pos
        if min(w, h) <= 0 or min(x, y) < 0:
            issues.append(_err("bad_pos", f"invalid pos {block.pos}", path))
    if block.span is not None and block.span < 1:
        issues.append(_err("bad_span", f"span must be >= 1: {block.span}", path))
    if block.filters:
        issues.append(
            _err(
                "unsupported_filters",
                "visual filters are not supported; use a 'slicer' block instead",
                path,
            )
        )


def _check_page(
    page: PageDesign,
    seen_pages: set[str],
    seen_titles: set[str],
    issues: list[Issue],
) -> None:
    """Check page-level rules (name, title, size, duplicates, filters)."""
    path = f"pages[{page.name}]"
    if not str(page.name).strip():
        issues.append(_err("empty_name", "page name is empty", path))
    if not str(page.title).strip():
        issues.append(_err("empty_title", "page title is empty", path))
    if not page.visuals:
        issues.append(_err("empty_page", "page has no visuals", path))
    if page.name in seen_pages:
        issues.append(_err("duplicate_page", f"duplicate page {page.name!r}", path))
    seen_pages.add(page.name)
    if page.title in seen_titles:
        issues.append(
            _err("duplicate_title", f"duplicate page title {page.title!r}", path)
        )
    seen_titles.add(page.title)
    if page.width < MIN_WIDTH or page.height < MIN_HEIGHT:
        issues.append(
            _err(
                "small_page",
                f"page size {page.width}x{page.height} is too small",
                path,
            )
        )
    if page.filters:
        issues.append(
            _err(
                "unsupported_filters",
                "page filters are not supported; use a 'slicer' block instead",
                path,
            )
        )
    check_page_geometry(page, issues)


def _check_relationships(model: ModelContext, issues: list[Issue]) -> None:
    """Check that each relationship names existing columns and one active link."""
    active_pairs: set[tuple[str, str]] = set()
    for index, rel in enumerate(model.relationships):
        path = f"model.relationships[{index}]"
        for key in ("fromTable", "fromColumn", "toTable", "toColumn"):
            if not rel.get(key):
                issues.append(_err("bad_relationship", f"missing {key}", path))
        from_name = str(rel.get("fromTable") or "")
        to_name = str(rel.get("toTable") or "")
        from_table = model.tables.get(from_name)
        to_table = model.tables.get(to_name)
        if from_name and from_table is None:
            issues.append(
                _err("bad_relationship", f"unknown fromTable {from_name!r}", path)
            )
        if to_name and to_table is None:
            issues.append(
                _err("bad_relationship", f"unknown toTable {to_name!r}", path)
            )
        if from_table and rel.get("fromColumn") not in from_table.columns:
            issues.append(
                _err(
                    "bad_relationship",
                    f"{from_table.name}.{rel.get('fromColumn')} not found",
                    path,
                )
            )
        if to_table and rel.get("toColumn") not in to_table.columns:
            issues.append(
                _err(
                    "bad_relationship",
                    f"{to_table.name}.{rel.get('toColumn')} not found",
                    path,
                )
            )
        active = as_bool(rel.get("isActive", True))
        if active is None:
            issues.append(
                _err(
                    "bad_relationship",
                    f"isActive must be boolean, got {rel.get('isActive')!r}",
                    path,
                )
            )
        elif active:
            pair: tuple[str, str] = (min(from_name, to_name), max(from_name, to_name))
            if pair in active_pairs:
                issues.append(
                    _err(
                        "duplicate_active_relationship",
                        "more than one active relationship between "
                        f"{pair[0]!r} and {pair[1]!r}",
                        path,
                    )
                )
            active_pairs.add(pair)


def validate_design(design: Design) -> list[Issue]:
    """Return every problem of `design` (an empty list means it is usable)."""
    issues: list[Issue] = []
    if not design.pages:
        issues.append(_err("no_pages", "design has no pages"))
    seen_pages: set[str] = set()
    seen_titles: set[str] = set()
    seen_blocks: set[str] = set()
    for page in design.pages:
        _check_page(page, seen_pages, seen_titles, issues)
        for index, block in enumerate(page.visuals):
            path = f"pages[{page.name}].visuals[{index}]"
            if not block.block_id:
                issues.append(_err("missing_id", "block id is empty", path))
            elif block.block_id in seen_blocks:
                issues.append(
                    _err(
                        "duplicate_id",
                        f"duplicate block id {block.block_id!r}",
                        path,
                    )
                )
            seen_blocks.add(block.block_id)
            try:
                resolve_kind(block.kind)
            except ValueError as exc:
                issues.append(_err("unknown_kind", str(exc), path))
                continue
            _check_fields(block, path, issues)
            if design.model.tables:
                check_model_refs(block, design.model, path, issues)
    if not design.model.tables:
        issues.append(
            _warn("no_model", "model context is empty; references are not checked")
        )
    _check_relationships(design.model, issues)
    check_name_collisions(design.model, issues)
    return issues


__all__ = ["validate_design"]
