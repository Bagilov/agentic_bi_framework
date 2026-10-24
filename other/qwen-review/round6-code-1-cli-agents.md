# Bundle 1: CLI boundary + agent manifests (new code)

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/cli_support.py ====================

"""Shared boundary handling for the console entry points.

Every ``agentic-bi-*`` command must end on a documented exit code, never on an
unhandled traceback:

* ``0`` — success;
* ``1`` — a runtime failure (the work ran and its own result was negative);
* ``2`` — a bad input or configuration (missing/unreadable file, unsupported
  format, invalid spec).

`run_boundary` wraps a command body so an expected, user-facing failure becomes a
short message on stderr plus a code. An unexpected error is **not** swallowed:
it stays a traceback, because it is a bug in the framework, not a user mistake.

Public API:
    EXIT_OK, EXIT_FAILED, EXIT_BAD_INPUT
    run_boundary(body, prog) -> int
"""

from __future__ import annotations

import sys
from collections.abc import Callable

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BAD_INPUT = 2

# Failures that mean "the input was wrong", not "the framework is broken": a
# missing/unreadable path, a value the parser rejects, or an unsupported format.
_INPUT_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    NotImplementedError,
)


def run_boundary(body: Callable[[], int], *, prog: str) -> int:
    """Run a command body, mapping an input failure to exit code 2.

    Args:
        body: the command's real work; returns its exit code (0 or 1).
        prog: the program name, used to prefix the error message.

    Returns:
        The body's code on success, or ``EXIT_BAD_INPUT`` (2) when the input is
        missing, unreadable or unsupported.
    """
    try:
        return body()
    except _INPUT_ERRORS as exc:
        print(f"{prog}: error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT


def fail(prog: str, message: str, code: int = EXIT_BAD_INPUT) -> int:
    """Print `message` to stderr and return `code` (for pre-flight checks)."""
    print(f"{prog}: error: {message}", file=sys.stderr)
    return code


__all__ = ["EXIT_OK", "EXIT_FAILED", "EXIT_BAD_INPUT", "fail", "run_boundary"]

==================== FILE: src/agentic_bi/agents.py ====================

"""Agent-assisted support for the "dashboard -> quality -> deploy" pipeline.

Concept: each stage of the dashboard lifecycle (develop, test, deploy, control,
support) gets a *support agent* — a declaratively described entity with a role,
purpose, activation trigger and a set of tools. An agent description is a
manifest (JSON/YAML) that can be:

- stored in the dashboard declarative spec (section ``support.agents``);
- materialized into a Kilo agent file (``.kilo/agent/<id>.md``) without code;
- used as a contract for Agent Manager / expert subtasks.

Lifecycle stages (domains) the agents correspond to:

- ``develop`` — development (build the board from a spec, layout, rebuild);
- ``test``    — testing (validate_pbix, structural checks, thresholds);
- ``deploy``  — deploy (git-deploy via a sync client, guardrails);
- ``control`` — control/monitoring (compare the published artifact with expected);
- ``support`` — support (answer questions, triage incidents, recommendations).

An agent is NOT an executor and NOT a mandatory step: the pipeline runs without
agents too. Agents are a "smart support" layer that helps a human (and/or Agent
Manager) go through the stages: generate a plan, check the result, explain the
thresholds, highlight risks.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

# lifecycle stages the agents support
STAGES = ("develop", "test", "deploy", "control", "support")


@dataclass(frozen=True)
class SupportAgent:
    """Manifest of a support agent for one lifecycle stage."""

    id: str  # unique id (e.g. "agent.build")
    role: str  # short role name ("Builder")
    stage: str  # one of STAGES
    purpose: str = ""  # what the agent is for
    triggers: tuple[str, ...] = ()  # conditions/events that invoke the agent
    tools: tuple[str, ...] = ()  # tools available to the agent
    prompt: str = ""  # start-instruction template for Agent Manager
    enabled: bool = True  # whether to enable by default


# ─── default support-agent registry ────────────────────────


def _develop_agent() -> SupportAgent:
    """Agent for the "develop" stage: build a board from a spec."""
    return SupportAgent(
        id="agent.builder",
        role="Builder",
        stage="develop",
        purpose="Builds a board from a declarative spec: translates spec -> Board, "
        "prepares the layout and folds it into a .pbix via rebuild "
        "(donor DataModel).",
        triggers=("on_build", "on_spec_change"),
        tools=("spec_to_board", "board.layout", "rebuild_pbix"),
        prompt=(
            "Build the dashboard from spec <spec> via spec_to_board, get the "
            "layout board.layout(...) and fold into a .pbix "
            "rebuild_pbix(donor, out, layout=...)."
        ),
    )


def _test_agent() -> SupportAgent:
    """Agent for the "test" stage: quality checks before publishing."""
    return SupportAgent(
        id="agent.tester",
        role="Tester",
        stage="test",
        purpose="Checks the built .pbix before publishing: validate_pbix, "
        "structural spec checks, layout-vs-donor-model and threshold checks.",
        triggers=("before_publish", "after_build"),
        tools=("validate_pbix", "validate_spec", "thresholds.resolve_thresholds"),
        prompt=(
            "Run quality checks on the built .pbix: validate_pbix(path). If there "
            "are problems — stop the publish and return the list of errors."
        ),
    )


def _deploy_agent() -> SupportAgent:
    """Agent for the "deploy" stage: git-deploy a .pbix to a Report Server."""
    return SupportAgent(
        id="agent.deployer",
        role="Deployer",
        stage="deploy",
        purpose="Performs a git-deploy of a .pbix to a Report Server via a sync "
        "client, honoring guardrails (max_deletion_pct/max_change_pct) and "
        "a dry-run plan.",
        triggers=("on_deploy", "on_dry_run"),
        tools=("git-deploy deploy", "git-deploy status", "guardrails"),
        prompt=(
            "Deploy using config <cfg>; first the --dry-run plan, check the "
            "guardrails (deploy.max_deletion_pct), then the real deploy."
        ),
    )


def _control_agent() -> SupportAgent:
    """Agent for the "control" stage: compare the published artifact with expected."""
    return SupportAgent(
        id="agent.watchdog",
        role="Watchdog",
        stage="control",
        purpose="Monitors the published dashboard: compares presence/size/version on "
        "the Report Server with expected, flags mismatches and regression risks.",
        triggers=("on_publish", "on_schedule"),
        tools=("verify_published", "deploy status", "thresholds"),
        prompt=(
            "Check that the published dashboard <name> in <folder> matches the "
            "expected one (Id/Size/version). Return a summary of mismatches."
        ),
    )


def _support_agent() -> SupportAgent:
    """Agent for the "support" stage: explain thresholds and triage incidents."""
    return SupportAgent(
        id="agent.supporter",
        role="Supporter",
        stage="support",
        purpose="Supports the user/team on the dashboard: explains thresholds from "
        "the catalog, triages incidents (broken visual, 409/deploy-state), "
        "and gives recommendations on refining the spec.",
        triggers=("on_question", "on_incident"),
        tools=("thresholds.describe", "troubleshooting", "spec docs"),
        prompt=(
            "Answer the user's question about the dashboard: explain the "
            "thresholds from the catalog, triage the incident and give "
            "recommendations."
        ),
    )


def _default_agents() -> tuple[SupportAgent, ...]:
    return (
        _develop_agent(),
        _test_agent(),
        _deploy_agent(),
        _control_agent(),
        _support_agent(),
    )


AGENT_REGISTRY: dict[str, SupportAgent] = {a.id: a for a in _default_agents()}


# ─── manifest API ──────────────────────────────────────────


def all_agents(stage: str | None = None) -> list[SupportAgent]:
    """All support agents, optionally only for one stage.

    An unknown stage raises rather than returning `[]`: a typo would otherwise
    look like "this stage has no agents" and silently orphan every agent.
    """
    if stage is None:
        return list(AGENT_REGISTRY.values())
    if stage not in STAGES:
        raise ValueError(f"Unknown stage '{stage}'; allowed: {STAGES}")
    return [a for a in AGENT_REGISTRY.values() if a.stage == stage]


def agents_for_stage(stage: str) -> list[SupportAgent]:
    """Agents supporting a particular lifecycle stage."""
    return all_agents(stage)


def to_manifest(agent: SupportAgent) -> dict:
    """Serialize an agent into a dict (manifest for a spec/file)."""
    return asdict(agent)


def from_manifest(d: dict) -> SupportAgent:
    """Build a SupportAgent from a manifest (dict).

    The `stage` is validated here: a manifest may only name a known lifecycle
    stage, so a typo fails loudly instead of producing an agent that no stage
    resolves (which would silently disappear from every stage view).
    """
    if "id" not in d or "role" not in d or "stage" not in d:
        raise ValueError("An agent manifest must contain id, role, stage")
    if d["stage"] not in STAGES:
        raise ValueError(
            f"Unknown stage '{d['stage']}' in agent '{d['id']}'; allowed: {STAGES}"
        )
    return SupportAgent(
        id=d["id"],
        role=d["role"],
        stage=d["stage"],
        purpose=d.get("purpose", ""),
        triggers=tuple(d.get("triggers", []) or []),
        tools=tuple(d.get("tools", []) or []),
        prompt=d.get("prompt", ""),
        enabled=d.get("enabled", True),
    )


def resolve_agents(
    spec: Any | None = None, enabled_only: bool = True
) -> list[SupportAgent]:
    """The effective set of agents, honoring overrides from the spec.

    ``spec`` — a ``DashboardSpec`` object (from spec.py) that may have a
    ``support = {"agents": [manifest, ...], "enable_ids": [...],
    "disable_ids": [...]}`` section.

    Priority:
    1. If an agent is overridden by a manifest in the spec — the manifest wins;
    2. ``disable_ids`` disables an agent; ``enable_ids`` enables it (on by default);
    3. otherwise — the value from ``AGENT_REGISTRY`` (+ the ``enabled_only`` filter).

    Returns agents in registry order (stable order).
    """
    overrides: list[SupportAgent] = []
    enable_ids: set[str] = set()
    disable_ids: set[str] = set()
    if spec is not None:
        support = getattr(spec, "support", None) or {}
        overrides = [from_manifest(m) for m in support.get("agents", [])]
        enable_ids = set(support.get("enable_ids", []) or [])
        disable_ids = set(support.get("disable_ids", []) or [])

    by_id = {a.id: a for a in overrides}
    result: list[SupportAgent] = []
    for aid, default in AGENT_REGISTRY.items():
        agent = by_id.get(aid, default)
        if aid in disable_ids:
            continue
        if aid in enable_ids:
            effective = SupportAgent(
                id=agent.id,
                role=agent.role,
                stage=agent.stage,
                purpose=agent.purpose,
                triggers=agent.triggers,
                tools=agent.tools,
                prompt=agent.prompt,
                enabled=True,
            )
            result.append(effective)
        elif agent.enabled or not enabled_only:
            result.append(agent)
    # project (registry-unknown) agents — include them too
    for aid, agent in by_id.items():
        if aid not in AGENT_REGISTRY and aid not in disable_ids:
            result.append(agent)
    return result


def render_kilo_agent(agent: SupportAgent) -> str:
    """Render a Kilo agent markdown (body of ``.kilo/agent/<id>.md``).

    Returns the file's text; writing it is the caller's job. The `agent.id` is
    **not** sanitised here, so a writer must treat it as a filename and reject
    separators/traversal (the returned body itself is inert).
    """
    tools = ", ".join(agent.tools) or "-"
    triggers = ", ".join(agent.triggers) or "-"
    return (
        f"# {agent.role} ({agent.id})\n\n"
        f"**Stage:** {agent.stage}\n\n"
        f"**Purpose:** {agent.purpose}\n\n"
        f"**Triggers:** {triggers}\n\n"
        f"**Tools:** {tools}\n\n"
        f"## Start instruction\n\n{agent.prompt}\n"
    )


__all__ = [
    "SupportAgent",
    "STAGES",
    "AGENT_REGISTRY",
    "all_agents",
    "agents_for_stage",
    "to_manifest",
    "from_manifest",
    "resolve_agents",
    "render_kilo_agent",
]

==================== FILE: src/agentic_bi/visual_check.py ====================

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

CLI exit codes: 0 when no errors, 1 when errors are found, 2 on a bad input.
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

==================== FILE: src/agentic_bi/brand_audit.py ====================

"""Audit a document for compliance with the brand style.

Quickly locate places that deviate from the style guide: colors (text/fill/line/
background), fonts (family/weight/size) and rules (mandatory accent, at least 2
primary-range colors, "2 of 3" base elements). Driven by a
:class:`brand_config.BrandConfig` (defaults from :mod:`brand`).

This module is a thin facade + public entry points; the work lives in:
    brand_audit_types.py   - AuditFinding / AuditReport
    brand_audit_extract.py - ThemeResolver + observation extraction from .pptx
    brand_audit_eval.py    - evaluation of observations against the rules

Supported:
    - direct RGB colors and **theme (scheme) colors** (resolved via theme1.xml);
    - nested group shapes (recursively);
    - tables (cell -> paragraph -> run);
    - font weights and sizes.

Example:
    from agentic_bi.brand_audit import audit_pptx
    rep = audit_pptx("Presentation.pptx")
    print(rep.format())            # a readable report with locations
    rep.to_json("audit.json")      # a machine-readable result

CLI:
    python -m agentic_bi.brand_audit deck.pptx --config brand_config.yaml
    python -m agentic_bi.brand_audit deck.pptx --json report.json --fail-on error

Public API:
    AuditFinding   - a single non-compliance (rule/level/location/value)
    AuditReport    - the finding set + summary/format/to_json
    ThemeResolver  - resolves theme (scheme) colors to HEX
    audit_pptx(path, cfg=None)      -> AuditReport
    audit_document(path, cfg=None)  -> AuditReport   (pptx/docx/xlsx)

CLI exit codes: 0 normally (findings are reported, not fatal), 1 when `--fail-on`
is set and matched, 2 on a bad input (unreadable config / unsupported format).
"""

from __future__ import annotations

import logging
from pathlib import Path

from agentic_bi.brand_audit_eval import (  # noqa: F401
    evaluate_observations,
    limit_findings,
)
from agentic_bi.brand_audit_extract import (  # noqa: F401
    ThemeResolver,
    iter_pptx_observations,
)
from agentic_bi.brand_audit_types import (  # noqa: F401
    AuditFinding,
    AuditReport,
)
from agentic_bi.brand_config import BrandConfig
from agentic_bi.brand_eval import is_brand_font  # noqa: F401 (public re-export)

logger = logging.getLogger(__name__)


def audit_pptx(path: str | Path, cfg: BrandConfig | None = None) -> AuditReport:
    """Check a `.pptx` presentation for brand compliance."""
    cfg = cfg or BrandConfig.default()
    rep = AuditReport(path=str(path))
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "python-pptx is required: uv pip install python-pptx"
        ) from exc
    try:
        prs = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001 - corrupted/non-pptx file
        logger.warning("could not open %s: %s", path, exc)
        rep.add(
            AuditFinding(
                "DOC-UNREADABLE",
                "error",
                "document",
                str(path),
                f"File does not open as .pptx: {exc}",
                str(path),
            )
        )
        return rep
    theme = (
        ThemeResolver.from_presentation(prs)
        if cfg.audit.get("resolve_theme_colors", True)
        else ThemeResolver()
    )
    obs = iter_pptx_observations(prs, cfg, theme)
    rep.theme = theme.as_dict()
    rep.stats = {
        "slides": len(prs.slides),
        "color_observations": sum(1 for o in obs if o.kind != "font"),
        "font_observations": sum(1 for o in obs if o.kind == "font"),
        "theme_slots": len(theme.slots),
    }
    rep.stats["theme_colors_resolved"] = sum(1 for o in obs if o.from_theme)
    evaluate_observations(obs, cfg, rep)
    limit_findings(rep, cfg)
    return rep


def audit_document(path: str | Path, cfg: BrandConfig | None = None) -> AuditReport:
    """Check a document by extension (.pptx/.docx/.xlsx)."""
    ext = Path(path).suffix.lower()
    if ext == ".pptx":
        return audit_pptx(path, cfg)
    raise NotImplementedError(f"format {ext!r} is not supported yet (.pptx only)")


def main(argv: list[str] | None = None) -> int:
    import argparse

    from agentic_bi.cli_support import run_boundary

    ap = argparse.ArgumentParser(
        prog="agentic-bi-brand-audit",
        description="Audit a document for brand-style compliance",
    )
    ap.add_argument("document", help="path to a .pptx")
    ap.add_argument("--config", default=None, help="brand_config.yaml/json")
    ap.add_argument("--json", dest="json_out", default=None, help="save JSON")
    ap.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="never",
        help="exit code 1 on findings of this level",
    )
    args = ap.parse_args(argv)

    def body() -> int:
        cfg = BrandConfig.load(args.config) if args.config else BrandConfig.default()
        rep = audit_document(args.document, cfg)
        print(rep.format(max_findings=int(cfg.audit.get("max_findings", 0) or 0)))
        if args.json_out:
            rep.to_json(args.json_out)
            print(f"\nJSON: {args.json_out}")

        if args.fail_on == "error" and rep.errors:
            return 1
        if args.fail_on == "warning" and (rep.errors or rep.warnings):
            return 1
        return 0

    return run_boundary(body, prog="agentic-bi-brand-audit")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuditFinding",
    "AuditReport",
    "ThemeResolver",
    "audit_document",
    "audit_pptx",
    "is_brand_font",
]

==================== FILE: src/agentic_bi/engine_cli.py ====================

"""CLI: build a `.pbix` via the Desktop RS AS engine.

Examples:
    python -m agentic_bi.engine_cli --data sales.csv --table Sales --out out.pbix
    python engine_cli.py --data mix.csv --table Mix --out mix.pbix --oracle
    python engine_cli.py --data mix.csv --table Mix --out mix.pbix --verify

By default the build ends with a reverse self-test (--verify), including a check
of the report theme against the brand style guide (--verify-brand). Disable
with `--no-verify` / `--no-brand-verify`. `--verify-strict` (default) fails the
build on a failed check; `--brand-strict` also makes brand errors critical.

Exit codes: 0 on success, 1 when the build/verify/oracle fails, 2 on a bad input.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from agentic_bi.engine import DEFAULT_TEMPLATE, PBI_RS, EnginePipeline


def _parse_pages(raw: str | None) -> dict[str, int] | None:
    """Parse page expectations: 'Overview=8,Issues=3' -> dict."""
    if not raw:
        return None
    pages: dict[str, int] = {}
    for part in raw.split(","):
        name, _, n = part.rpartition("=")
        if not name:
            continue
        pages[name.strip()] = int(n)
    return pages or None


def main(argv: list[str] | None = None) -> int:
    from agentic_bi.cli_support import run_boundary

    ap = argparse.ArgumentParser(
        prog="agentic-bi-engine",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--data", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--database", default=None)
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--desktop", default=PBI_RS)
    ap.add_argument("--oracle", action="store_true")
    ap.add_argument("--hold", type=int, default=70)
    ap.add_argument(
        "--keep-donor-layout",
        action="store_true",
        help="keep the donor layout instead of a clean one",
    )
    ap.add_argument(
        "--verify",
        dest="verify",
        action="store_true",
        default=True,
        help="reverse self-test of the built .pbix (on by default)",
    )
    ap.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        help="disable the reverse self-test",
    )
    ap.add_argument(
        "--no-verify-strict",
        dest="strict_verify",
        action="store_false",
        default=True,
        help="do not fail on a failed critical check (report only)",
    )
    ap.add_argument(
        "--strict-soft",
        action="store_true",
        default=False,
        help="treat a model read-back failure (pbixray) as a failure too",
    )
    ap.add_argument(
        "--assert-pages",
        default=None,
        help="expected pages 'Name=N,Name2=M' for the structure check",
    )
    ap.add_argument(
        "--sample",
        type=int,
        default=50,
        help="how many model rows to compare in the read-back",
    )
    ap.add_argument(
        "--no-model-verify",
        dest="model_verify",
        action="store_false",
        default=True,
        help="do not read the model via pbixray (layout only)",
    )
    ap.add_argument(
        "--verify-brand",
        dest="brand_verify",
        action="store_true",
        default=True,
        help="check the report theme against the style guide (on by default)",
    )
    ap.add_argument(
        "--no-brand-verify",
        dest="brand_verify",
        action="store_false",
        help="disable the brand-book check",
    )
    ap.add_argument(
        "--brand-strict",
        action="store_true",
        default=False,
        help="treat brand errors as build failures (e.g. BRAND-ACCENT-MANDATORY)",
    )
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)

    def body() -> int:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        db = args.database or (Path(args.out).stem + "_db")
        pipe = EnginePipeline(template=Path(args.template), desktop=args.desktop)
        pages = _parse_pages(args.assert_pages)
        result = pipe.run(
            Path(args.data),
            args.table,
            db,
            Path(args.out),
            check_oracle=args.oracle,
            hold=args.hold,
            clean_layout=not args.keep_donor_layout,
            verify=args.verify,
            strict_verify=args.strict_verify,
            pages=pages,
            sample=args.sample,
            model_verify=args.model_verify,
            strict_soft=args.strict_soft,
            brand_verify=args.brand_verify,
            brand_strict=args.brand_strict,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.report:
            Path(args.report).write_text(
                f"# engine pbix\n\n- data: `{args.data}`\n- rows: {result['rows']}\n"
                f"- layout: {result['layout']}\n- out: `{result['out']}` "
                f"({result['pbix_bytes']} B)\n- verify: {result.get('verify', 'n/a')}\n"
                f"- oracle: {result['oracle']}\n",
                encoding="utf-8",
            )
        if result.get("verify") == "FAILED":
            return 1
        return 0 if result["oracle"] in ("MODEL_LOADED", "SKIPPED") else 1

    return run_boundary(body, prog="agentic-bi-engine")


if __name__ == "__main__":
    raise SystemExit(main())

