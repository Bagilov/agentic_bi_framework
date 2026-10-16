"""Static validation of a `.pbix` / `Report/Layout` for structural errors.

Checks, per visual container:
  - config JSON parses and `singleVisual` is present
  - `visualType` is known and its projection role keys are allowed
  - required roles for the visual type are present
  - every projection `queryRef` matches a `prototypeQuery.Select` Name
  - every Select references a table/column/measure that exists in the model
  - no unsafe `Condition.In` filters

The role tables follow real Power BI samples (see module docs of
`engine_layout_visual`). Public API:
    layout_from_pbix(pbix) -> dict
    check_layout(layout, registry) -> list[str]
    check_pbix(pbix, registry) -> list[str]
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

# allowed projection roles per visualType (derived from real Power BI files)
ALLOWED = {
    "tableEx": {"Values", "Tooltips"},
    "pivotTable": {"Rows", "Columns", "Values", "Tooltips"},
    "matrix": {"Rows", "Columns", "Values"},
    "card": {"Values", "Tooltips"},
    "cardVisual": {"Data"},
    "multiRowCard": {"Values"},
    "slicer": {"Values"},
    "columnChart": {"Category", "Series", "Y", "Tooltips"},
    "clusteredColumnChart": {"Category", "Series", "Y", "Tooltips"},
    "barChart": {"Category", "Series", "Rows", "Y", "Tooltips"},
    "lineChart": {"Category", "Series", "Y", "Tooltips"},
    "areaChart": {"Category", "Series", "Y", "Tooltips"},
    "pieChart": {"Category", "Series", "Y", "Tooltips"},
    "donutChart": {"Category", "Series", "Y", "Tooltips"},
    "treemap": {"Group", "Values", "Details", "Tooltips"},
    "funnel": {"Category", "Y", "Tooltips"},
    "waterfallChart": {"Category", "Y", "Tooltips"},
    "stackedColumnChart": {"Category", "Series", "Y", "Tooltips"},
    "stackedBarChart": {"Category", "Series", "Y", "Tooltips"},
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
    "lineChart": ["Category", "Y"],
    "areaChart": ["Category", "Y"],
    "pieChart": ["Y"],
    "donutChart": ["Y"],
    "funnel": ["Category", "Y"],
    "waterfallChart": ["Category", "Y"],
    "stackedColumnChart": ["Category", "Y"],
    "stackedBarChart": ["Category", "Y"],
}


def layout_from_pbix(pbix: str | Path) -> dict:
    """Decode `Report/Layout` from a `.pbix` archive."""
    raw = zipfile.ZipFile(pbix).read("Report/Layout")
    for enc in ("utf-16-le", "utf-8-sig", "utf-8"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:  # noqa: BLE001
            continue
    raise ValueError("cannot decode Report/Layout")


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
                errs.append(f"{w}: no visualType")
                continue
            proj = sv.get("projections") or {}
            if not proj:
                errs.append(f"{w}: {vt} has no projections (renders empty)")
            allowed = ALLOWED.get(vt)
            if allowed is None:
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
            for f in json.loads(vc.get("filters", "[]") or "[]") or []:
                if isinstance(f, dict) and "In" in json.dumps(f):
                    errs.append(f"{w}: unsafe Condition.In filter")
    return errs


def check_pbix(pbix: str | Path, registry: dict) -> list[str]:
    """Validate a `.pbix`; convenience wrapper around `check_layout`."""
    return check_layout(layout_from_pbix(pbix), registry)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Validate a .pbix Report/Layout.")
    ap.add_argument("pbix")
    ap.add_argument("registry", help="JSON file {table:{columns,measures}}")
    args = ap.parse_args()
    reg = json.loads(Path(args.registry).read_text())
    errs = check_pbix(args.pbix, reg)
    print(f"ERRORS: {len(errs)}")
    for e in errs:
        print("  -", e)
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
