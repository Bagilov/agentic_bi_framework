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

# Spec sections that merely wrap their domain's thresholds (one level deeper than
# the key domain): ``quality: {thresholds: {...}}``, ``deploy: {guardrails: {...}}``.
_CONTAINER_KEYS = {"thresholds", "guardrails"}


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


def _flatten(overrides: dict) -> dict[str, Any]:
    """Flatten spec overrides into `domain.name` keys.

    Accepts both a flat dict (`{"quality.max_layout_problems": 1}`) and the
    documented nested form. The spec nests the values one level deeper than the
    key domain (`quality: {thresholds: {...}}`, `deploy: {guardrails: {...}}`),
    so a second level whose name is a container (`thresholds`/`guardrails`) is
    flattened too rather than producing a key that matches nothing.
    """
    flat: dict[str, Any] = {}
    for k, v in (overrides or {}).items():
        if not isinstance(v, dict):
            flat[k] = v
            continue
        for kk, vv in v.items():
            if isinstance(vv, dict) and kk in _CONTAINER_KEYS:
                for kkk, vvv in vv.items():
                    flat[f"{k}.{kkk}"] = vvv
            else:
                flat[f"{k}.{kk}"] = vv
    return flat


def resolve_thresholds(overrides: dict | None = None) -> dict[str, Any]:
    """Return effective threshold values, honoring spec overrides.

    ``overrides`` — a flat dict (e.g. ``{"quality.max_layout_problems": 1}``) or a
    nested one, either ``{"quality": {"max_layout_problems": 1}}`` or the
    documented ``{"quality": {"thresholds": {"max_layout_problems": 1}}}``.

    An override whose type does not match the threshold's default is ignored (the
    default is kept) and logged, so a bad value cannot reach a comparison as a
    `TypeError` or silently weaken a gate.
    """
    flat = _flatten(overrides or {})
    out: dict[str, Any] = {}
    for key, t in THRESHOLDS.items():
        if key in flat and not validate_override(key, flat[key]):
            logger.warning(
                "threshold %s: override %r has the wrong type (%s expected); "
                "keeping the default %r",
                key,
                flat[key],
                type(t.value).__name__,
                t.value,
            )
            out[key] = t.value
        else:
            out[key] = flat.get(key, t.value)
    # also pass through unknown keys (project extensions), but flag likely typos
    for k, v in flat.items():
        if k not in THRESHOLDS:
            logger.warning(
                "threshold override %r is not in the catalog (typo?); ignored by "
                "the built-in gates",
                k,
            )
            out.setdefault(k, v)
    return out


def get_threshold(key: str, overrides: dict | None = None):
    """Return the effective value of a single threshold.

    An unknown key returns `None` **and is logged**: a typo would otherwise
    silently yield `None`, which then breaks a `value > threshold` comparison
    with a `TypeError` far from the mistake.
    """
    if key not in THRESHOLDS:
        logger.warning("unknown threshold key %r (typo?)", key)
    return resolve_thresholds(overrides).get(
        key, THRESHOLDS[key].value if key in THRESHOLDS else None
    )


def validate_override(key: str, value: Any) -> bool:
    """Check that a threshold override type matches the default.

    A `bool` is rejected for an `int` threshold even though `isinstance(True, int)`
    is `True`: a `True`/`False` where a count is expected is a mistake, and it
    would silently become `1`/`0` in a comparison.
    """
    t = THRESHOLDS.get(key)
    if t is None:
        return True  # project threshold — type not checked
    if isinstance(t.value, bool):
        return isinstance(value, bool)
    if isinstance(t.value, int) and isinstance(value, bool):
        return False
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
