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
