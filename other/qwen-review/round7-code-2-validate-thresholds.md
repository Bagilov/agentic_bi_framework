# Bundle 2: validation and thresholds

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/validate_pbix.py ====================

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
        "columns": [
            "as_of_date",
            "metric",
            "entity_id",
            "segment",
            "category",
            "period",
            "period_start",
        ],
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
                f"({bucket}: {ent.get(bucket) or 'empty'})"
            )

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
                        col.get("Expression", {}).get("SourceRef"), {}
                    )
                    check_ref(ent, col.get("Property"), "column", f"{vwhere} filter")

            # query / prototype query
            cfg = _as_obj(vc.get("config")) or {}
            sv = cfg.get("singleVisual") or {}
            pq = sv.get("prototypeQuery") or _as_obj(vc.get("query")) or {}
            alias2ent = {f.get("Name"): f.get("Entity") for f in (pq.get("From") or [])}
            for sel in pq.get("Select") or []:
                if not isinstance(sel, dict):
                    continue
                if "Measure" in sel:
                    m = sel["Measure"]
                    ent = _resolve_entity(
                        m.get("Expression", {}).get("SourceRef"), alias2ent
                    )
                    check_ref(ent, m.get("Property"), "measure", vwhere)
                elif "Column" in sel:
                    c = sel["Column"]
                    ent = _resolve_entity(
                        c.get("Expression", {}).get("SourceRef"), alias2ent
                    )
                    check_ref(ent, c.get("Property"), "column", vwhere)
                elif "Aggregation" in sel:
                    spec = sel["Aggregation"]
                    ex = spec.get("Expression") or {}
                    col = ex.get("Column") if isinstance(ex, dict) else None
                    if col:
                        ent = _resolve_entity(
                            col.get("Expression", {}).get("SourceRef"), alias2ent
                        )
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

    p = (
        sys.argv[1]
        if len(sys.argv) > 1
        else (Path(__file__).parent / "output_files" / "sample.pbix")
    )
    reg = load_registry(sys.argv[2]) if len(sys.argv) > 2 else None
    problems = validate_pbix(Path(p), reg)
    if problems:
        print(f"{len(problems)} problems: ", " ; ".join(problems))
        sys.exit(1)
    print("OK: layout matches the donor model")

==================== FILE: src/agentic_bi/thresholds.py ====================

"""Threshold catalog for the "dashboard -> quality -> deploy" pipeline.

A single registry of ALL thresholds encountered in the Management/PBI pipeline,
explaining WHY each is needed and HOW to manage it. Thresholds are grouped by
domain:

- ``quality`` — layout quality checks before publishing (validate_pbix);
- ``deploy``  — guardrails of a git-deploy via a sync client (planner);
- ``build``   — structural build limits.

By default every threshold comes from ``THRESHOLDS``, but it can be overridden
in the declarative dashboard spec (``quality``/``deploy`` sections). Priority:
spec value > default value.

How to manage/change:
- globally — here, in ``THRESHOLDS`` (the default value);
- per project — in YAML ``quality.thresholds.*`` / ``deploy.guardrails.*``;
- programmatically — ``resolve_thresholds(spec)`` returns effective values.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Threshold:
    """A description of one threshold."""

    key: str
    value: Any
    unit: str = ""
    domain: str = ""
    why: str = ""
    source: str = ""


# ─── default threshold registry ────────────────────────────


def _quality_thresholds() -> dict[str, Threshold]:
    return {
        # ── quality (validate_pbix) ─────────────────────────
        "quality.max_layout_problems": Threshold(
            key="quality.max_layout_problems",
            value=0,
            unit="problems",
            domain="quality",
            why="validate_pbix compares the layout with the donor model: every problem "
            "is a reference to a non-existent table/column/measure. Any problem => "
            'a broken visual on the portal ("Could not load data"). Zero is a hard '
            "gate: do not publish until the layout matches the model.",
            source="agentic_bi.validate_pbix.validate_layout",
        ),
        "quality.min_sections": Threshold(
            key="quality.min_sections",
            value=1,
            unit="pages",
            domain="quality",
            why="A board must have at least one page; an empty report (0 sections) is "
            "pointless and may be rejected by the portal.",
            source="agentic_bi.spec",
        ),
        "quality.min_visuals_per_section": Threshold(
            key="quality.min_visuals_per_section",
            value=0,
            unit="visuals",
            domain="quality",
            why="0 = allowed (a placeholder page). Above zero controls the minimum board "
            "fill. Configured to the customer's requirements.",
            source="agentic_bi.quality",
        ),
    }


def _deploy_thresholds() -> dict[str, Threshold]:
    return {
        # ── deploy (sync-client guardrails) ─────────────────
        "deploy.max_deletion_pct": Threshold(
            key="deploy.max_deletion_pct",
            value=50,
            unit="%",
            domain="deploy",
            why="Guarantee: a deploy must not mass-delete published reports. >50% "
            "deletions versus the previous state is almost certainly a config/"
            "branch error. Override only deliberately (--force).",
            source="sync_client.planner.MAX_DELETION_PCT",
        ),
        "deploy.max_change_pct": Threshold(
            key="deploy.max_change_pct",
            value=100,
            unit="%",
            domain="deploy",
            why="Limit of total changes (upload+delete) versus the previous state. "
            "100% = a full resync is allowed; make it stricter if change volume "
            "must be controlled.",
            source="sync_client.planner.MAX_CHANGE_PCT",
        ),
        "deploy.lock_ttl_seconds": Threshold(
            key="deploy.lock_ttl_seconds",
            value=600,
            unit="sec",
            domain="deploy",
            why="Lifetime of the deploy lock resource. 600s = 10 minutes is enough for "
            "a typical deploy; parallel deploys from another process will wait or "
            "time out.",
            source="git-deploy.yaml (sync.lock_ttl_seconds)",
        ),
        "deploy.timeout_seconds": Threshold(
            key="deploy.timeout_seconds",
            value=180,
            unit="sec",
            domain="deploy",
            why="HTTP request timeout to the Report Server (server.timeout) — protects "
            "against a hung deploy on a large set of .pbix files.",
            source="git-deploy.yaml (server.timeout)",
        ),
    }


def _build_thresholds() -> dict[str, Threshold]:
    return {
        # ── build ───────────────────────────────────────────
        "build.max_pbix_size_mb": Threshold(
            key="build.max_pbix_size_mb",
            value=1000,
            unit="MB",
            domain="build",
            why="Upper limit on the built .pbix size. Data lives entirely in the donor's "
            "VertiPaq model; exceeding the limit indicates a build anomaly "
            "(duplicates, layout bloat).",
            source="agentic_bi.framework",
        ),
        "build.donor_required": Threshold(
            key="build.donor_required",
            value=True,
            unit="bool",
            domain="build",
            why="The build pattern does not generate VertiPaq from scratch — the binary "
            "DataModel is taken from a donor. Without a donor you cannot build a "
            "valid .pbix.",
            source="agentic_bi.rebuild.rebuild_pbix",
        ),
    }


def _registry() -> dict[str, Threshold]:
    """Assemble the full threshold catalog from the domain groups."""
    return {**_quality_thresholds(), **_deploy_thresholds(), **_build_thresholds()}


THRESHOLDS: dict[str, Threshold] = _registry()


# ─── catalog API ───────────────────────────────────────────


def all_thresholds() -> list[dict]:
    """The full threshold catalog (for documentation/display)."""
    return [asdict(t) for t in THRESHOLDS.values()]


def describe(domain: str | None = None) -> str:
    """Human-readable threshold description (for a CLI --thresholds)."""
    lines: list[str] = []
    for key, t in THRESHOLDS.items():
        if domain and t.domain != domain:
            continue
        lines.append(f"- {key} = {t.value!r} {t.unit}")
        lines.append(f"    why: {t.why}")
        lines.append(f"    source: {t.source}")
    return "\n".join(lines)


def resolve_thresholds(overrides: dict | None = None) -> dict[str, Any]:
    """Return effective threshold values, honoring spec overrides.

    ``overrides`` — a flat dict (e.g. ``{"quality.max_layout_problems": 1}``) or a
    nested one ``{"quality": {"max_layout_problems": 1}}`` (flattened).
    """
    flat: dict[str, Any] = {}
    for k, v in (overrides or {}).items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                flat[f"{k}.{kk}"] = vv
        else:
            flat[k] = v
    out = {}
    for key, t in THRESHOLDS.items():
        out[key] = flat.get(key, t.value)
    # also pass through unknown keys (project extensions)
    for k, v in flat.items():
        out.setdefault(k, v)
    return out


def get_threshold(key: str, overrides: dict | None = None):
    """Return the effective value of a single threshold."""
    return resolve_thresholds(overrides).get(
        key, THRESHOLDS[key].value if key in THRESHOLDS else None
    )


def validate_override(key: str, value: Any) -> bool:
    """Check that a threshold override type matches the default."""
    t = THRESHOLDS.get(key)
    if t is None:
        return True  # project threshold — type not checked
    return isinstance(value, type(t.value))


__all__ = [
    "Threshold",
    "THRESHOLDS",
    "all_thresholds",
    "describe",
    "resolve_thresholds",
    "get_threshold",
    "validate_override",
]

