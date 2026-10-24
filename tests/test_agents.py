"""Tests for the support-agent manifest contract.

Covers the boundary rules a manifest must obey: a known lifecycle `stage`, the
required keys, and the `all_agents`/`agents_for_stage` behaviour on an unknown
stage. All of these fail loudly rather than returning an empty list, so a typo
cannot silently orphan an agent.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agentic_bi.agents import (
    AGENT_REGISTRY,
    STAGES,
    SupportAgent,
    agents_for_stage,
    all_agents,
    from_manifest,
    render_kilo_agent,
    resolve_agents,
)


class TestFromManifest:
    def test_accepts_a_complete_manifest(self) -> None:
        agent = from_manifest(
            {"id": "agent.x", "role": "X", "stage": "develop", "purpose": "p"}
        )
        assert agent.id == "agent.x"
        assert agent.stage == "develop"
        assert agent.enabled is True

    def test_defaults_optional_fields(self) -> None:
        agent = from_manifest({"id": "a", "role": "R", "stage": "test"})
        assert agent.triggers == ()
        assert agent.tools == ()
        assert agent.prompt == ""

    def test_rejects_a_missing_required_key(self) -> None:
        with pytest.raises(ValueError, match="must contain id, role, stage"):
            from_manifest({"id": "a", "role": "R"})

    def test_rejects_an_unknown_stage(self) -> None:
        with pytest.raises(ValueError, match="Unknown stage 'develp'"):
            from_manifest({"id": "a", "role": "R", "stage": "develp"})

    def test_every_default_stage_is_accepted(self) -> None:
        for stage in STAGES:
            agent = from_manifest({"id": "a", "role": "R", "stage": stage})
            assert agent.stage == stage


class TestAllAgents:
    def test_no_stage_returns_the_whole_registry(self) -> None:
        assert all_agents() == list(AGENT_REGISTRY.values())

    def test_filters_by_a_known_stage(self) -> None:
        for agent in all_agents("develop"):
            assert agent.stage == "develop"

    def test_unknown_stage_raises_instead_of_returning_empty(self) -> None:
        with pytest.raises(ValueError, match="Unknown stage 'WRONG'"):
            all_agents("WRONG")

    def test_agents_for_stage_delegates_the_same_contract(self) -> None:
        assert agents_for_stage("test") == all_agents("test")
        with pytest.raises(ValueError, match="Unknown stage"):
            agents_for_stage("nope")


class TestResolveAgents:
    def _spec(self, support: dict) -> object:
        return type("S", (), {"support": support})()

    def test_a_manifest_override_wins(self) -> None:
        spec = self._spec(
            {"agents": [{"id": "agent.builder", "role": "R", "stage": "develop"}]}
        )
        resolved = {a.id: a for a in resolve_agents(spec, enabled_only=False)}
        assert resolved["agent.builder"].role == "R"

    def test_disable_ids_removes_an_agent(self) -> None:
        spec = self._spec({"disable_ids": ["agent.tester"]})
        ids = {a.id for a in resolve_agents(spec, enabled_only=False)}
        assert "agent.tester" not in ids

    def test_enable_ids_forces_an_agent_on(self) -> None:
        spec = self._spec({"enable_ids": ["agent.tester"]})
        resolved = {a.id: a for a in resolve_agents(spec)}
        assert resolved["agent.tester"].enabled is True

    def test_enabled_only_filters_disabled_agents(self) -> None:
        plain = resolve_agents(None, enabled_only=True)
        assert all(a.enabled for a in plain)


class TestRenderKiloAgent:
    def test_renders_the_stage_and_instruction(self) -> None:
        agent = SupportAgent(
            id="agent.x",
            role="X",
            stage="develop",
            purpose="build",
            tools=("t1", "t2"),
            triggers=("on_build",),
            prompt="do it",
        )
        markdown = render_kilo_agent(agent)
        assert "# X (agent.x)" in markdown
        assert "**Stage:** develop" in markdown
        assert "**Tools:** t1, t2" in markdown
        assert "do it" in markdown

    def test_empty_tools_and_triggers_render_a_dash(self) -> None:
        markdown = render_kilo_agent(
            replace(AGENT_REGISTRY["agent.builder"], tools=(), triggers=())
        )
        assert "**Tools:** -" in markdown
        assert "**Triggers:** -" in markdown
