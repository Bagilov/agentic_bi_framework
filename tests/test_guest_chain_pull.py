"""The chain pulls *its own* per-run build, not the shared published copy.

`run_build` publishes a finished build onto the caller's declared output name
(`<out>\\<name>`). Two chains building the same target on one guest therefore
both write that path, and the chain that pulled first could get the other
chain's `.pbix` (last-writer-wins). The build keeps a per-run file, and the chain
pulls that file; the published copy stays a convenience for humans.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentic_bi.guest_chain import ChainConfig, ChainResult, build_dashboard
from agentic_bi.guest_chain_build import run_build
from agentic_bi.guest_transport import Deadline, GuestConfig


def _guest() -> GuestConfig:
    return GuestConfig(
        winrm="http://guest:5985/wsman", user="u", password="p", out=r"C:\pbi\out"
    )


class _Transport:
    """Records the publish/pull paths and answers the size probes."""

    def __init__(self) -> None:
        self.scripts: list[str] = []
        self.pulls: list[tuple[str, Path]] = []
        self.events: list[str] = []
        self.task: dict[str, object] = {}

    def ps(self, script: str, **kwargs: object) -> str:
        self.scripts.append(script)
        if "Remove-Item -LiteralPath '" in script and ".pbix" in script:
            self.events.append("cleanup")
        return "1234" if "Get-Item -LiteralPath" in script else ""

    def push_file(self, local: Path, dest: str, deadline: Deadline) -> None:
        return None

    def extract_zip(self, zip_path: str, dest_dir: str, *, expected: int) -> int:
        return expected

    def run_task(self, **kwargs: object) -> tuple[str, int]:
        self.task = kwargs
        return "builder output", 0

    def ensure_vm(self, deadline: Deadline) -> str:
        return "already running"

    def pull_file(self, guest_path: str, local: Path, deadline: Deadline) -> int:
        self.pulls.append((guest_path, Path(local)))
        self.events.append("pull")
        return 4321

    started_vm = False

    def close(self) -> None:
        return None


def _config(tmp_path: Path) -> ChainConfig:
    repo = tmp_path / "repo"
    repo.mkdir()
    data = tmp_path / "sales.csv"
    data.write_text("a,b\n", encoding="utf-8")
    return ChainConfig(
        guest=_guest(),
        data=data,
        table="Sales",
        out=tmp_path / "out" / "board.pbix",
        repo=repo,
    )


def test_run_build_records_its_own_guest_artifact(tmp_path: Path) -> None:
    transport = _Transport()
    result = ChainResult(verdict="NOT_BUILT")
    assert run_build(
        transport,  # type: ignore[arg-type]
        _config(tmp_path),
        Deadline(30),
        result,
    )
    assert result.guest_build is not None
    assert re.search(r"C:\\pbi\\out\\board\.[0-9a-f]{8}\.pbix$", result.guest_build)
    assert result.guest_build != r"C:\pbi\out\board.pbix"


def test_the_chain_pulls_the_per_run_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _Transport()
    monkeypatch.setattr(
        "agentic_bi.guest_chain.WinRMTransport", lambda *a, **k: transport
    )
    result = build_dashboard(_config(tmp_path))
    assert result.verdict == "BUILT"
    guest_path, local = transport.pulls[0]
    assert guest_path == result.guest_build
    assert re.search(r"board\.[0-9a-f]{8}\.pbix$", guest_path)
    assert local.name == "board.pbix"


def test_the_publish_copies_so_the_pull_source_survives(tmp_path: Path) -> None:
    transport = _Transport()
    result = ChainResult(verdict="NOT_BUILT")
    assert run_build(
        transport,  # type: ignore[arg-type]
        _config(tmp_path),
        Deadline(30),
        result,
    )
    assert result.guest_build is not None
    publish = next(c for c in transport.scripts if "[IO.File]::Copy(" in c)
    # `publish_script` is a move; using it here deleted the file the chain pulls.
    assert f"$src='{result.guest_build}'" in publish
    assert "Copy($src,$stg,$true)" in publish


def test_the_per_run_artifact_is_removed_only_after_the_pull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _Transport()
    monkeypatch.setattr(
        "agentic_bi.guest_chain.WinRMTransport", lambda *a, **k: transport
    )
    result = build_dashboard(_config(tmp_path))
    assert result.verdict == "BUILT"
    assert transport.events == ["pull", "cleanup"]
    cleanup = next(
        c
        for c in transport.scripts
        if "Remove-Item -LiteralPath '" in c and ".pbix" in c
    )
    assert f"'{result.guest_build}'" in cleanup


def test_a_build_without_its_own_path_is_a_stage_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No silent fallback to the shared published name (that was the race)."""
    transport = _Transport()
    monkeypatch.setattr(
        "agentic_bi.guest_chain.WinRMTransport", lambda *a, **k: transport
    )

    def _built_without_path(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr("agentic_bi.guest_chain.run_build", _built_without_path)
    result = build_dashboard(_config(tmp_path))
    assert result.verdict == "STAGE_FAILED"
    assert transport.pulls == []
    assert "without its own path" in result.log[-1]
