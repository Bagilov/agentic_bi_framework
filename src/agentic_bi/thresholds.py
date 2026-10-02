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
from dataclasses import dataclass, asdict
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
                "a broken visual on the portal (\"Could not load data\"). Zero is a hard "
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
        key, THRESHOLDS[key].value if key in THRESHOLDS else None)


def validate_override(key: str, value: Any) -> bool:
    """Check that a threshold override type matches the default."""
    t = THRESHOLDS.get(key)
    if t is None:
        return True  # project threshold — type not checked
    return isinstance(value, type(t.value))


__all__ = [
    "Threshold", "THRESHOLDS", "all_thresholds", "describe", "resolve_thresholds",
    "get_threshold", "validate_override",
]