"""Static validation of a `.pbix` / `Report/Layout` for structural errors.

Checks, per visual container:
  - config JSON parses and `singleVisual` is present
  - `visualType` is known and its projection role keys are allowed
  - required roles for the visual type are present
  - every projection `queryRef` matches a `prototypeQuery.Select` Name
  - every Select references a table/column/measure that exists in the model
  - no unsafe `Condition.In` filters

Known composite/custom visual types (combo, ribbon, AI and imported custom
visuals) have roles outside the built-in catalogue: they are logged at info
level instead of failing, while an unknown built-in type is still an error.

`unsafe Condition.In` is decided structurally, not textually. The first version
serialized the whole filter with `json.dumps` and searched for the substring
`"In"`, which fires on any word containing it (`Include`, `Income`, `Index`,
table/column names) - 69 false errors on `templates/template.pbix`. A filter is
an object graph, so the check walks the tree and looks only at the `Condition`
mapping and the `In` key inside it.

Desktop itself writes two legitimate `Condition.In` shapes (inline `Values` and
a Top-N `Table` subquery), so an `In` is reported only when it cannot be
resolved: a `Table`/expression `SourceRef.Source` that the filter's own `From`
does not declare, or an `In` with neither `Values` nor `Table`. That keeps real
report filters certifiable while a hand-built dangling `IN` (the construct that
crashes the pivot on drill) still fails.

The role tables follow real Power BI samples (see module docs of
`engine_layout_visual`). Public API:
    layout_from_pbix(pbix) -> dict
    check_layout(layout, registry) -> list[str]
    check_pbix(pbix, registry) -> list[str]

CLI exit codes: 0 when no errors, 1 when errors are found, 2 on a bad input.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from agentic_bi.layout_meta import DECORATIVE_VISUAL_TYPES, decode_layout
from agentic_bi.visual_check_filters import (
    filters_of,
    find_unsafe_in,
    source_aliases,
)

logger = logging.getLogger(__name__)

# allowed projection roles per visualType (derived from real Power BI files).
# `pivotTable` is the only matrix visual type in the QOM; there is no `matrix`.
ALLOWED = {
    "tableEx": {"Values", "Tooltips"},
    "pivotTable": {"Rows", "Columns", "Values", "Tooltips"},
    "card": {"Values", "Tooltips"},
    "cardVisual": {"Data"},
    "multiRowCard": {"Values"},
    "slicer": {"Values"},
    "columnChart": {"Category", "Series", "Y", "Tooltips"},
    "clusteredColumnChart": {"Category", "Series", "Y", "Tooltips"},
    # Real samples (templates/template.pbix page "Pipeline Trends" sec4/vis1,
    # other/e2e-verification/*.pbix) carry `Rows` on a horizontal bar next to
    # Category + Y, so it is a legitimate role, not an invention.
    "barChart": {"Category", "Series", "Rows", "Y", "Tooltips"},
    "clusteredBarChart": {"Category", "Series", "Y", "Tooltips"},
    "lineChart": {"Category", "Series", "Y", "Tooltips"},
    "areaChart": {"Category", "Series", "Y", "Tooltips"},
    "pieChart": {"Category", "Series", "Y", "Tooltips"},
    "donutChart": {"Category", "Series", "Y", "Tooltips"},
    "treemap": {"Group", "Values", "Details", "Tooltips"},
    "funnel": {"Category", "Y", "Tooltips"},
    "waterfallChart": {"Category", "Y", "Tooltips"},
    # Power BI has no `stackedColumnChart`/`stackedBarChart` type: a stacked
    # column is `columnChart` and a stacked bar is `barChart`. Desktop renders the
    # invented names as a missing custom visual (measured on the guest), so they
    # are not accepted here either.
    "scatterChart": {"Category", "Series", "Size", "X", "Y", "Play"},
    "gauge": {"Y", "MinValue", "MaxValue", "TargetValue"},
    "kpi": {"Indicator", "TrendLine", "Tooltips"},
}
REQUIRED = {
    "tableEx": ["Values"],
    "pivotTable": ["Rows"],
    "card": ["Values"],
    "slicer": ["Values"],
    "treemap": ["Group", "Values"],
    "scatterChart": ["X", "Y"],
    "gauge": ["Y"],
    "kpi": ["Indicator"],
    "columnChart": ["Category", "Y"],
    "clusteredColumnChart": ["Category", "Y"],
    "barChart": ["Category", "Y"],
    "clusteredBarChart": ["Category", "Y"],
    "lineChart": ["Category", "Y"],
    "areaChart": ["Category", "Y"],
    "pieChart": ["Y"],
    "donutChart": ["Y"],
    "funnel": ["Category", "Y"],
    "waterfallChart": ["Category", "Y"],
}


# Known composite/custom visual types. Their data roles are not part of the
# built-in catalogue (`lineStackedColumnComboChart` adds `Y2`, `keyDriversVisual`
# uses Target/ExplainBy, ...), so role tables cannot describe them. They are
# reported at info level and only their prototypeQuery is validated; an unknown
# *built-in* type stays an error. All of them occur in templates/template.pbix.
COMPOSITE_VISUAL_TYPES = frozenset(
    {
        "lineStackedColumnComboChart",
        "ribbonChart",
        "keyDriversVisual",
        "decompositionTreeVisual",
    }
)
CUSTOM_VISUAL_PREFIXES = ("FlowVisual_",)


def is_composite_visual(visual_type: str) -> bool:
    """True for known composite/custom visual types (their roles are not checked)."""
    return visual_type in COMPOSITE_VISUAL_TYPES or visual_type.startswith(
        CUSTOM_VISUAL_PREFIXES
    )


def layout_from_pbix(pbix: str | Path) -> dict:
    """Decode `Report/Layout` from a `.pbix` archive (encoding is sniffed).

    Raises `ValueError` when the archive is not a Power BI `.pbix` (no
    `Report/Layout` member); a non-zip file raises `zipfile.BadZipFile`.
    """
    with zipfile.ZipFile(pbix) as zf:
        try:
            raw = zf.read("Report/Layout")
        except KeyError as e:
            raise ValueError(
                f"{pbix}: not a Power BI .pbix: Report/Layout is missing"
            ) from e
    return decode_layout(raw)


def _resolve(sr: dict, alias2ent: dict) -> str | None:
    if not sr:
        return None
    return alias2ent.get(sr.get("Source")) or sr.get("Entity") or sr.get("Source")


def check_layout(layout: dict, registry: dict) -> list[str]:
    """Return a list of human-readable error strings (empty == valid).

    registry: {table: {"columns": [...], "measures": [...]}}.
    """
    errs: list[str] = []
    for si, sec in enumerate(layout.get("sections", [])):
        for vi, vc in enumerate(sec.get("visualContainers", [])):
            w = f"sec{si}/vis{vi}"
            try:
                cfg = json.loads(vc.get("config", "") or "{}")
            except Exception as e:  # noqa: BLE001
                errs.append(f"{w}: config JSON invalid: {e}")
                continue
            sv = cfg.get("singleVisual") or {}
            vt = sv.get("visualType")
            if not vt:
                # `singleVisualGroup` - a structural grouping container, not a visual.
                if cfg.get("singleVisualGroup"):
                    continue
                errs.append(f"{w}: no visualType")
                continue
            proj = sv.get("projections") or {}
            if not proj and vt not in DECORATIVE_VISUAL_TYPES:
                errs.append(f"{w}: {vt} has no projections (renders empty)")
            allowed = ALLOWED.get(vt)
            if allowed is None and vt in DECORATIVE_VISUAL_TYPES:
                continue  # decorative visual: no data roles to validate
            if allowed is None and is_composite_visual(vt):
                # Known composite/custom visual: roles are not in the catalogue.
                logger.info("%s: composite visual '%s', role checks skipped", w, vt)
            elif allowed is None:
                errs.append(f"{w}: unknown visualType '{vt}'")
            else:
                for role in proj:
                    if role not in allowed:
                        errs.append(
                            f"{w}: {vt} role '{role}' not allowed "
                            f"(allowed: {sorted(allowed)})"
                        )
                for role in REQUIRED.get(vt, []):
                    if role not in proj:
                        errs.append(f"{w}: {vt} missing required role '{role}'")
            pq = sv.get("prototypeQuery") or {}
            alias2ent = {f.get("Name"): f.get("Entity") for f in (pq.get("From") or [])}
            names = {
                s.get("Name") for s in (pq.get("Select") or []) if isinstance(s, dict)
            }
            for role, refs in proj.items():
                for r in refs:
                    qr = r.get("queryRef")
                    if qr not in names:
                        errs.append(
                            f"{w}: {vt} projection {role} queryRef "
                            f"'{qr}' has no matching Select"
                        )
            for sel in pq.get("Select") or []:
                if not isinstance(sel, dict):
                    continue
                for kind in ("Column", "Measure"):
                    if kind in sel:
                        spec = sel[kind]
                        ent = _resolve(
                            spec.get("Expression", {}).get("SourceRef"), alias2ent
                        )
                        prop = spec.get("Property")
                        bucket = "measures" if kind == "Measure" else "columns"
                        if ent not in registry:
                            errs.append(f"{w}: {vt} {kind} table '{ent}' not in model")
                        elif prop not in registry[ent].get(bucket, []):
                            errs.append(f"{w}: {vt} {kind} {ent}.{prop} not in model")
                if "Aggregation" in sel:
                    col = (sel["Aggregation"].get("Expression") or {}).get("Column")
                    if col:
                        ent = _resolve(
                            col.get("Expression", {}).get("SourceRef"), alias2ent
                        )
                        prop = col.get("Property")
                        if ent not in registry:
                            errs.append(f"{w}: {vt} agg table '{ent}' not in model")
                        elif prop not in registry[ent].get("columns", []):
                            errs.append(f"{w}: {vt} agg {ent}.{prop} not in model")
            filters, filters_error = filters_of(vc)
            if filters_error is not None:
                errs.append(f"{w}: {filters_error}")
                continue
            for f in filters:
                if isinstance(f, dict) and find_unsafe_in(f, source_aliases(f)):
                    errs.append(f"{w}: unsafe Condition.In filter")
    return errs


def check_pbix(pbix: str | Path, registry: dict) -> list[str]:
    """Validate a `.pbix`; convenience wrapper around `check_layout`."""
    return check_layout(layout_from_pbix(pbix), registry)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from agentic_bi.cli_support import run_boundary

    ap = argparse.ArgumentParser(
        prog="agentic-bi-visual-check",
        description="Validate a .pbix Report/Layout.",
    )
    ap.add_argument("pbix")
    ap.add_argument("registry", help="JSON file {table:{columns,measures}}")
    args = ap.parse_args(argv)

    def body() -> int:
        reg = json.loads(Path(args.registry).read_text(encoding="utf-8"))
        errs = check_pbix(args.pbix, reg)
        print(f"ERRORS: {len(errs)}")
        for e in errs:
            print("  -", e)
        return 1 if errs else 0

    return run_boundary(body, prog="agentic-bi-visual-check")


if __name__ == "__main__":
    raise SystemExit(main())
