"""Structural validation of a declarative dashboard spec.

Split out of `spec.py` (which owns parsing/translation and stays within the
file-size budget). The validator reports the defects that would otherwise surface
as a late `KeyError`/`TypeError` in `spec_to_board`, as a silently dead visual, or
as a broken layout.

Public API:
    validate_spec(spec) -> list[str]      (empty list = ok)
"""

from __future__ import annotations

from agentic_bi.spec import DashboardSpec

# chart visual types the skeleton can build (see skeleton_visuals.chart_visual).
# An unknown one is not rejected by Power BI's parser until the report is opened,
# so it must be caught here or the .pbix ships with a dead visual.
CHART_TYPES = frozenset({"lineChart", "clusteredColumnChart"})


def _validate_field(f: dict, where: str, problems: list[str]) -> None:
    """Check one field mapping has a `property` and a sane `kind`."""
    if not isinstance(f, dict):
        problems.append(f"{where}: field must be a mapping, got {type(f).__name__}")
        return
    if not f.get("property"):
        problems.append(f"{where}: field is missing 'property'")
    if f.get("kind", "column") not in ("column", "measure"):
        problems.append(f"{where}: unknown field kind {f.get('kind')!r}")


def _validate_pos(pos: object, where: str, problems: list[str]) -> None:
    """Check `pos` is four integers (a length-2 or string pos breaks the layout)."""
    if pos is None:
        return
    if not isinstance(pos, (list, tuple)) or len(pos) != 4:
        problems.append(f"{where}: pos must be [x, y, w, h], got {pos!r}")
        return
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in pos):
        problems.append(f"{where}: pos values must be integers, got {pos!r}")


def validate_spec(spec: DashboardSpec) -> list[str]:
    """Structural validation of a spec; returns problems (empty = ok).

    Catches the defects that would otherwise surface as a late `KeyError`/
    `TypeError` in `spec_to_board` or as a silently wrong layout: a page or
    element missing a key, a field without `property`, a malformed `pos`, an
    unknown chart `visual_type`, a non-string page filter, and duplicate page
    names (whose sections collide in the built layout).
    """
    problems: list[str] = []
    if not spec.name:
        problems.append("Missing dashboard.name")
    if not spec.table:
        problems.append("Missing dashboard.table")
    if not spec.pages:
        problems.append("No pages (dashboard.pages) — the board is empty")
    seen_pages: set[str] = set()
    for p in spec.pages:
        if not p.name:
            problems.append("Page without name")
        elif p.name in seen_pages:
            problems.append(f"Duplicate page name '{p.name}'")
        else:
            seen_pages.add(p.name)
        for el in p.elements:
            where = f"{p.name}/{el.type}"
            _validate_pos(el.pos, where, problems)
            if el.type == "kpi":
                if not el.field:
                    problems.append(f"{where}: missing field")
                else:
                    _validate_field(el.field, where, problems)
            elif el.type == "chart":
                if el.visual_type not in CHART_TYPES:
                    problems.append(
                        f"{where}: unknown visual_type {el.visual_type!r}; "
                        f"allowed: {sorted(CHART_TYPES)}"
                    )
                if not el.axis or not el.value:
                    problems.append(f"{where}: axis and value are required")
                else:
                    _validate_field(el.axis, f"{where}/axis", problems)
                    _validate_field(el.value, f"{where}/value", problems)
            elif el.type == "table":
                if not el.fields:
                    problems.append(f"{where}: missing fields")
                else:
                    for i, f in enumerate(el.fields):
                        _validate_field(f, f"{where}/field[{i}]", problems)
        for i, flt in enumerate(p.filters):
            if not isinstance(flt, str) or not flt.strip():
                problems.append(
                    f"page '{p.name}': filters[{i}] must be a non-empty string "
                    f"(a column name), got {flt!r}"
                )
    return problems


__all__ = ["CHART_TYPES", "validate_spec"]
