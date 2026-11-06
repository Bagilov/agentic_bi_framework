"""The build's artifact probe must parse a number, or fail as a stage error.

`run_build` took the last line of the size probe response and passed it to
`int()`. A non-terminating PowerShell warning printed before the number
(`WARNING: ...` then `1234`) made that a bare `ValueError`: the chain reported
`STAGE_FAILED` through the generic handler instead of naming the stage, and an
`exit 0` build that produced nothing was indistinguishable from a broken probe.

The size is now read like the file count in `extract_zip`: the last all-digit
line wins, and no digit line is a `StageError` naming the artifact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi.guest_chain import ChainConfig, ChainResult
from agentic_bi.guest_chain_build import run_build
from agentic_bi.guest_types import Deadline, GuestConfig, StageError


class _FakeTransport:
    """Answers the size probes with scripted responses, in order."""

    def __init__(self, sizes: list[str]) -> None:
        self.scripts: list[str] = []
        self.sizes = list(sizes)
        self.task: dict[str, object] = {}

    def ps(self, script: str, **kwargs: object) -> str:
        self.scripts.append(script)
        if "Get-Item -LiteralPath" in script and ").Length" in script:
            return self.sizes.pop(0) if self.sizes else ""
        return ""

    def push_file(self, local: Path, dest: str, deadline: Deadline) -> None:
        return None

    def extract_zip(self, zip_path: str, dest_dir: str, *, expected: int) -> int:
        return expected

    def run_task(self, **kwargs: object) -> tuple[str, int]:
        self.task = kwargs
        return "builder output", 0


def _config(tmp_path: Path) -> ChainConfig:
    data = tmp_path / "sales.csv"
    data.write_text("a,b\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    return ChainConfig(
        guest=GuestConfig(
            winrm="http://guest:5985/wsman",
            user="u",
            password="p",
            root=r"C:\pbi\abf",
            out=r"C:\pbi\out",
        ),
        data=data,
        table="Sales",
        out=Path("output_files/board.pbix"),
        repo=repo,
    )


def _run(transport: _FakeTransport, tmp_path: Path) -> bool:
    return run_build(
        transport,  # type: ignore[arg-type]
        _config(tmp_path),
        Deadline(30),
        ChainResult(verdict="NOT_BUILT"),
    )


class TestTheSizeProbeIsParsedSafely:
    def test_a_warning_line_before_the_number_is_not_a_value_error(
        self, tmp_path: Path
    ) -> None:
        transport = _FakeTransport(["WARNING: something\n1234", "12"])
        assert _run(transport, tmp_path)

    def test_a_response_without_a_number_is_a_stage_error(self, tmp_path: Path) -> None:
        transport = _FakeTransport(["WARNING: access denied", ""])
        with pytest.raises(StageError, match="could not read the size"):
            _run(transport, tmp_path)

    def test_an_empty_response_is_a_stage_error(self, tmp_path: Path) -> None:
        transport = _FakeTransport(["", ""])
        with pytest.raises(StageError, match="could not read the size"):
            _run(transport, tmp_path)

    def test_a_zero_size_is_a_build_failure_not_a_stage_error(
        self, tmp_path: Path
    ) -> None:
        transport = _FakeTransport(["WARNING: none\n0", "1"])
        result = ChainResult(verdict="NOT_BUILT")
        assert not run_build(
            transport,  # type: ignore[arg-type]
            _config(tmp_path),
            Deadline(30),
            result,
        )
        assert "no .pbix produced" in result.log[-1]

    def test_a_publish_that_consumed_the_build_is_a_stage_error(
        self, tmp_path: Path
    ) -> None:
        """The probe watches this run's own file, the one the chain pulls."""
        transport = _FakeTransport(["1234", "WARNING: not found\n0"])
        with pytest.raises(StageError, match="consumed this run's build"):
            _run(transport, tmp_path)

    def test_the_builder_runs_before_the_size_is_read(self, tmp_path: Path) -> None:
        transport = _FakeTransport(["1234", "12"])
        _run(transport, tmp_path)
        assert transport.task, "the task must have been started"
        probes = [
            s
            for s in transport.scripts
            if "Get-Item -LiteralPath" in s and ").Length" in s
        ]
        assert len(probes) == 2
