"""Validate a produced layout/.pbix against the donor model.

Before publishing we check that every object referenced by the skeleton's
visuals and filters (tables, columns, measures) actually exists in the donor
model. The problem with such skeletons: the layout is built config-driven and
may reference non-existent objects (e.g. a measure that is not in the model),
which on a Report Server causes a render error ("Could not load data...").

The donor model can be supplied as a registry dict or loaded from a JSON file.
If none is given, `EXAMPLE_REGISTRY` (a neutral sample) is used so the validator
and tests run without a donor or network. Build a registry for your own donor
with `build_registry(alias_to_entity)` or by inspecting the donor layout.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Neutral example model (shape: table -> {"columns": [...], "measures": [...]}) ──
EXAMPLE_REGISTRY: dict = {
    "Filters": {
        "columns": ["entity_id", "version", "segment", "category", "period"],
        "measures": [],
    },
    "fact_table": {
        "columns": ["as_of_date", "metric", "entity_id", "segment",
                    "category", "period", "period_start"],
        "measures": [],
    },
    "dim_type": {"columns": ["category"], "measures": []},
    "kpi_measures": {
        "columns": ["dt_period_start"],
        "measures": ["metric_a", "metric_b", "rank_metric", "total_metric"],
    },
}

# Backwards-compatible alias.
DONOR_REGISTRY = EXAMPLE_REGISTRY


def load_registry(path: str | Path) -> dict:
    """Load a donor model registry from a JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _as_obj(x):
    """Parse a JSON string into an object, if it is a string."""
    if isinstance(x, str):
        try:
            return json.loads(x)
        except (json.JSONDecodeError, ValueError):
            return None
    return x


def _resolve_entity(src_ref: dict, alias2ent: dict) -> str | None:
    """Turn a SourceRef (Source='alias'|'Entity') into a donor table name."""
    if not src_ref:
        return None
    src = src_ref.get("Source")
    ent = src_ref.get("Entity")
    if src in alias2ent:
        return alias2ent[src]
    return ent or src


def validate_layout(layout: dict, registry: dict | None = None) -> list[str]:
    """Return the list of layout problems (empty list = valid).

    Checks all model references: sections->filters, visualContainers->filters,
    and prototypeQuery.Select (Column/Measure/Aggregation) against the registry.
    """
    registry = registry or EXAMPLE_REGISTRY
    problems: list[str] = []

    def check_ref(entity: str | None, prop: str | None, kind: str, where: str) -> None:
        if not entity or not prop:
            return
        ent = registry.get(entity)
        if ent is None:
            problems.append(f"{where}: table '{entity}' is not in the donor model")
            return
        bucket = "measures" if kind == "measure" else "columns"
        if prop not in ent.get(bucket, []):
            problems.append(
                f"{where}: {entity}.{prop} is not in the donor "
                f"({bucket}: {ent.get(bucket) or 'empty'})")

    for si, sec in enumerate(layout.get("sections", [])):
        where = f"section[{si}]"

        # page-level filters
        for f in _as_obj(sec.get("filters")) or []:
            col = (f.get("expression") or {}).get("Column")
            if col:
                ent = _resolve_entity(col.get("Expression", {}).get("SourceRef"), {})
                check_ref(ent, col.get("Property"), "column", f"{where} filter")

        for vi, vc in enumerate(sec.get("visualContainers", [])):
            vwhere = f"{where}/visual[{vi}]"

            # visual filters
            for f in _as_obj(vc.get("filters")) or []:
                col = (f.get("expression") or {}).get("Column")
                if col:
                    ent = _resolve_entity(
                        col.get("Expression", {}).get("SourceRef"), {})
                    check_ref(ent, col.get("Property"), "column", f"{vwhere} filter")

            # query / prototype query
            cfg = _as_obj(vc.get("config")) or {}
            sv = cfg.get("singleVisual") or {}
            pq = sv.get("prototypeQuery") or _as_obj(vc.get("query")) or {}
            alias2ent = {f.get("Name"): f.get("Entity")
                         for f in (pq.get("From") or [])}
            for sel in pq.get("Select") or []:
                if not isinstance(sel, dict):
                    continue
                if "Measure" in sel:
                    m = sel["Measure"]
                    ent = _resolve_entity(m.get("Expression", {}).get("SourceRef"),
                                          alias2ent)
                    check_ref(ent, m.get("Property"), "measure", vwhere)
                elif "Column" in sel:
                    c = sel["Column"]
                    ent = _resolve_entity(c.get("Expression", {}).get("SourceRef"),
                                          alias2ent)
                    check_ref(ent, c.get("Property"), "column", vwhere)
                elif "Aggregation" in sel:
                    spec = sel["Aggregation"]
                    ex = spec.get("Expression") or {}
                    col = ex.get("Column") if isinstance(ex, dict) else None
                    if col:
                        ent = _resolve_entity(
                            col.get("Expression", {}).get("SourceRef"), alias2ent)
                        check_ref(ent, col.get("Property"), "column", vwhere)
    return problems


def validate_pbix(path: Path, registry: dict | None = None) -> list[str]:
    """Extract the layout from a produced .pbix and validate it."""
    from agentic_bi.rebuild import _extract_layout
    layout, _ = _extract_layout(Path(path))
    return validate_layout(layout, registry)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else (
        Path(__file__).parent / "output_files" / "sample.pbix")
    reg = load_registry(sys.argv[2]) if len(sys.argv) > 2 else None
    problems = validate_pbix(Path(p), reg)
    if problems:
        print(f"{len(problems)} problems: ", " ; ".join(problems))
        sys.exit(1)
    print("OK: layout matches the donor model")