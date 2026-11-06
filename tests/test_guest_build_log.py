"""Exactly one process owns the task log: the runner, never the payload.

The build payload and the oracle payload each appended to the same log the task
runner redirects its child into. `Out-File` opens the file with
`FileShare.Read`, so the runner's redirect was refused and the payload's own
`Out-File` failed too: for the builder the log lost the child's whole output, and
for the oracle it was fatal — the `RESULT [VERDICT]` line never reached the log,
`_parse_verdict` returned None and `run_oracle` raised "no oracle verdict".

The payloads now print to stdout/stderr only (their `2>&1` still merges native
stderr), and the runner's single UTF-8 append captures everything. This test
fails if a log path reappears in either payload.
"""

from __future__ import annotations

from pathlib import Path

from agentic_bi.desktop_oracle_guest import _oracle_script
from agentic_bi.guest_chain import ChainConfig
from agentic_bi.guest_chain_build import build_script
from agentic_bi.guest_task import runner_script
from agentic_bi.guest_task_script import run_paths
from agentic_bi.guest_types import GuestConfig

_OUT = r"C:\pbi\out[1]"
_PBIX = rf"{_OUT}\board[1].pbix"


def _guest() -> GuestConfig:
    return GuestConfig(
        winrm="http://guest:5985/wsman",
        user="u",
        password="p",
        root=r"C:\pbi\abf",
        out=_OUT,
    )


def _config() -> ChainConfig:
    return ChainConfig(
        guest=_guest(),
        data=Path("examples/engine_sales.csv"),
        table="Sales",
        out=Path("output_files/board.pbix"),
    )


class TestTheBuildPayloadDoesNotWriteTheLog:
    def test_the_payload_never_mentions_the_log_path(self) -> None:
        paths = run_paths(_OUT, "agentic_bi_board")
        script = build_script(_config(), _PBIX)
        assert paths.log not in script
        assert "Out-File" not in script
        assert "Set-Content" not in script

    def test_the_runner_is_the_one_writing_the_log(self) -> None:
        paths = run_paths(_OUT, "agentic_bi_board")
        runner = runner_script(
            payload=paths.payload,
            log_path=paths.log,
            marker_path=paths.marker,
        )
        assert f"Out-File -LiteralPath '{paths.log}' -Append -Encoding utf8" in runner

    def test_the_payload_still_merges_native_stderr(self) -> None:
        script = build_script(_config(), _PBIX)
        assert script.rstrip().endswith("2>&1")
        assert "--out" in script

    def test_the_payload_keeps_continue_for_the_child(self) -> None:
        # A terminating preference would turn the merged native stderr into a
        # `NativeCommandError` and abort the payload before the footer runs.
        script = build_script(_config(), _PBIX)
        assert script.startswith("$ErrorActionPreference='Continue'")

    def test_the_star_redirect_is_still_gone(self) -> None:
        assert "*>" not in build_script(_config(), _PBIX)


class TestTheOraclePayloadDoesNotWriteTheLog:
    def test_the_payload_never_mentions_the_log_path(self) -> None:
        paths = run_paths(_OUT, "agentic_bi_oracle")
        script = _oracle_script(_guest(), _PBIX, 90, 240)
        assert paths.log not in script
        assert "Out-File" not in script
        assert "$log" not in script

    def test_the_runner_is_the_one_writing_the_log(self) -> None:
        paths = run_paths(_OUT, "agentic_bi_oracle")
        runner = runner_script(
            payload=paths.payload,
            log_path=paths.log,
            marker_path=paths.marker,
        )
        assert f"Out-File -LiteralPath '{paths.log}' -Append -Encoding utf8" in runner

    def test_the_oracle_still_merges_native_stderr(self) -> None:
        assert _oracle_script(_guest(), _PBIX, 90, 240).rstrip().endswith("2>&1")
