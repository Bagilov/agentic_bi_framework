# Bundle 3: tests pinning the new contracts

Each section is one test file, path relative to repo root.

==================== FILE: tests/test_cli_boundary.py ====================

"""Tests for the CLI boundary contract and default output locations.

Every console entry point must return a documented code on a bad input instead of
leaking a traceback (BR-7), and no default output may be written inside the
installed package. These pin both: a missing input is exit 2, and the resolved
default paths are CWD-relative.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi import cli_support
from agentic_bi.cli_support import EXIT_BAD_INPUT, EXIT_FAILED, EXIT_OK, run_boundary


class TestRunBoundary:
    def test_passes_the_body_code_through(self) -> None:
        assert run_boundary(lambda: 0, prog="p") == EXIT_OK
        assert run_boundary(lambda: 1, prog="p") == EXIT_FAILED

    def test_maps_a_missing_file_to_bad_input(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def body() -> int:
            raise FileNotFoundError("no such board")

        assert run_boundary(body, prog="agentic-bi-x") == EXIT_BAD_INPUT
        assert "agentic-bi-x: error:" in capsys.readouterr().err

    def test_maps_a_value_error_to_bad_input(self) -> None:
        def body() -> int:
            raise ValueError("bad spec")

        assert run_boundary(body, prog="p") == EXIT_BAD_INPUT

    def test_does_not_swallow_an_unexpected_error(self) -> None:
        def body() -> int:
            raise KeyError("a bug, not a user mistake")

        with pytest.raises(KeyError):
            run_boundary(body, prog="p")

    def test_fail_returns_the_requested_code(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli_support.fail("prog", "nope") == EXIT_BAD_INPUT
        assert "prog: error: nope" in capsys.readouterr().err


class TestEntryPointBadInputIsCodeTwo:
    """A missing input file must be exit 2, not an unhandled exception."""

    def test_visual_check(self, tmp_path: Path) -> None:
        from agentic_bi.visual_check import main

        code = main([str(tmp_path / "missing.pbix"), str(tmp_path / "missing.json")])
        assert code == EXIT_BAD_INPUT

    def test_brand_audit_on_an_unreadable_config(self, tmp_path: Path) -> None:
        from agentic_bi.brand_audit import main

        doc = tmp_path / "deck.pptx"
        doc.write_bytes(b"not a real pptx")
        code = main([str(doc), "--config", str(tmp_path / "missing.yaml")])
        assert code == EXIT_BAD_INPUT

    def test_antipatterns(self, tmp_path: Path) -> None:
        from agentic_bi.antipatterns.pbi_antipatterns import main

        assert main([str(tmp_path / "missing.pbix")]) == EXIT_BAD_INPUT

    def test_pbix_patch_on_a_missing_file(self, tmp_path: Path) -> None:
        from agentic_bi.pbix_binary.patch_cli import main

        code = main(["members", "--pbix", str(tmp_path / "missing.pbix")])
        assert code == EXIT_BAD_INPUT


class TestDefaultOutputsAreCwdRelative:
    """No default output may resolve inside the installed package."""

    def test_antipatterns_default_out_is_relative(self, monkeypatch, tmp_path) -> None:

        from agentic_bi.antipatterns import pbi_antipatterns as mod

        captured: dict[str, Path] = {}

        def fake_analyze(_pbix: str) -> dict:
            return {
                "summary": {"total_findings": 0, "critical": 0, "by_level": {}},
                "findings": {},
                "by_id": {},
            }

        def fake_write(_data: dict, out: Path) -> Path:
            captured["out"] = out
            return out

        monkeypatch.setattr(mod, "analyze_pbix", fake_analyze)
        monkeypatch.setattr(mod, "_write", fake_write)
        monkeypatch.chdir(tmp_path)
        pbix = tmp_path / "board.pbix"
        pbix.write_bytes(b"x")
        assert mod.main([str(pbix)]) == 0
        assert captured["out"].is_relative_to(Path("output_files"))
        assert (
            Path(mod.__file__).resolve().parent not in captured["out"].resolve().parents
        )


def test_cli_support_exports_the_documented_codes() -> None:
    assert (EXIT_OK, EXIT_FAILED, EXIT_BAD_INPUT) == (0, 1, 2)

==================== FILE: tests/test_agents.py ====================

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

