"""CLI boundary and unconfigured-guest tests for the dashboard chain.

`agentic-bi-guest-dashboard` must end every user-fixable failure on exit 2 and one
line of stderr, and `--json` must carry the verdict whenever there is a verdict.
These live in their own module so the chain tests stay within the file-size rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.guest_chain import build_dashboard
from agentic_bi.guest_chain_cli import _emit, main

_GUEST_VARS = (
    "AGENTIC_BI_GUEST_WINRM",
    "AGENTIC_BI_GUEST_USER",
    "AGENTIC_BI_GUEST_PASSWORD",
)


@pytest.fixture
def no_guest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the guest is unconfigured, whatever the developer's shell has."""
    for name in _GUEST_VARS:
        monkeypatch.delenv(name, raising=False)


class TestUnconfiguredChain:
    def test_build_dashboard_fails_fast_without_a_guest(self, no_guest) -> None:
        with pytest.raises(RuntimeError, match="guest not configured"):
            build_dashboard()

    def test_main_returns_exit_two_and_reports_not_configured(
        self, no_guest, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([]) == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["verdict"] == "NOT_CONFIGURED"
        assert payload["ok"] is False


class TestEmitIsBoundarySafe:
    """An unwritable --json path warns and still prints the verdict; no traceback."""

    def test_unwritable_json_path_warns_without_raising(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory\n", encoding="utf-8")
        target = blocker / "verdict.json"
        _emit({"verdict": "NOT_CONFIGURED", "ok": False}, str(target))
        captured = capsys.readouterr()
        assert json.loads(captured.out)["verdict"] == "NOT_CONFIGURED"
        assert "could not write the verdict" in captured.err


class TestChainCliBoundary:
    """A configuration the user can fix ends on one line and exit 2.

    Measured before: `--timeout -5` raised `ValueError: deadline must be positive`
    and `AGENTIC_BI_CHAIN_TIMEOUT=abc` raised `ValueError: invalid literal for
    int()`, both as tracebacks out of `main` (exit 1), and `--json` was ignored on
    the NOT_CONFIGURED path, so a CI job reading the verdict file got nothing.
    """

    @pytest.fixture
    def configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTIC_BI_GUEST_WINRM", "http://127.0.0.1:5985/wsman")
        monkeypatch.setenv("AGENTIC_BI_GUEST_USER", "u")
        monkeypatch.setenv("AGENTIC_BI_GUEST_PASSWORD", "p")
        monkeypatch.delenv("AGENTIC_BI_CHAIN_TIMEOUT", raising=False)

    def test_json_is_written_when_the_guest_is_not_configured(
        self, no_guest, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "verdict.json"
        assert main(["--json", str(target)]) == 2
        assert json.loads(target.read_text(encoding="utf-8"))["verdict"] == (
            "NOT_CONFIGURED"
        )
        assert json.loads(capsys.readouterr().out)["ok"] is False

    def test_a_non_positive_cli_timeout_is_bad_input(
        self,
        configured: None,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(["--timeout", "-5"]) == 2
        captured = capsys.readouterr()
        assert "--timeout must be a positive" in captured.err
        assert "Traceback" not in captured.err
        assert captured.out == ""

    def test_a_garbage_env_timeout_is_bad_input(
        self,
        configured: None,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("AGENTIC_BI_CHAIN_TIMEOUT", "abc")
        assert main([]) == 2
        captured = capsys.readouterr()
        assert "AGENTIC_BI_CHAIN_TIMEOUT" in captured.err
        assert "abc" in captured.err
        assert "Traceback" not in captured.err

    def test_a_zero_env_timeout_is_bad_input(
        self,
        configured: None,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("AGENTIC_BI_CHAIN_TIMEOUT", "0")
        assert main([]) == 2
        assert "must be positive" in capsys.readouterr().err
