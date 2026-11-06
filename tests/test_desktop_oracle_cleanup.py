"""The oracle removes its uploaded `.pbix`; a whole file leaked per run.

`run_oracle` uploads the local board to a per-run guest path and never deleted
it, so every oracle run left a full `.pbix` in the guest's output directory. The
log is still kept by `run_task`, and cleanup runs even when the task failed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from agentic_bi import desktop_oracle_guest
from agentic_bi.desktop_oracle_guest import GuestConfig, run_oracle


class _Transport:
    def __init__(self, *, fail: bool = False, cleanup_fail: bool = False) -> None:
        self.calls: list[str] = []
        self.pushed: list[str] = []
        self.closed = False
        self.fail = fail
        self.cleanup_fail = cleanup_fail

    def ps(self, script: str, **kwargs: object) -> str:
        self.calls.append(script)
        if self.cleanup_fail and "Remove-Item -LiteralPath" in script:
            raise RuntimeError("cleanup failed")
        return ""

    def push_file(self, local: Path, dest: str, deadline: Any) -> None:
        self.pushed.append(dest)

    def run_task(self, **kwargs: object) -> tuple[str, int]:
        if self.fail:
            raise RuntimeError("task failed")
        return "RESULT [MODEL_LOADED]", 0

    def close(self) -> None:
        self.closed = True


def _config() -> GuestConfig:
    return GuestConfig(
        winrm="http://guest:5985/wsman", user="u", password="p", out=r"C:\pbi\out"
    )


def _install(monkeypatch: pytest.MonkeyPatch, transport: _Transport) -> None:
    monkeypatch.setattr(
        desktop_oracle_guest, "WinRMTransport", lambda *args, **kwargs: transport
    )


def test_the_uploaded_copy_is_removed_after_a_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "board.pbix"
    local.write_bytes(b"pbix")
    transport = _Transport()
    _install(monkeypatch, transport)
    result = run_oracle(local, config=_config(), hold=1, open_timeout=1, timeout=5)
    assert result.verdict == "MODEL_LOADED"
    dest = transport.pushed[0]
    assert re.search(r"C:\\pbi\\out\\board\.[0-9a-f]{8}\.pbix$", dest)
    cleanup = transport.calls[-1]
    assert "Remove-Item -LiteralPath" in cleanup
    assert f"'{dest}'" in cleanup
    assert transport.closed


def test_the_uploaded_copy_is_removed_after_a_failed_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "board.pbix"
    local.write_bytes(b"pbix")
    transport = _Transport(fail=True)
    _install(monkeypatch, transport)
    with pytest.raises(RuntimeError):
        run_oracle(local, config=_config(), hold=1, open_timeout=1, timeout=5)
    assert "Remove-Item -LiteralPath" in transport.calls[-1]
    assert transport.closed


def test_a_failing_cleanup_does_not_mask_a_good_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "board.pbix"
    local.write_bytes(b"pbix")
    transport = _Transport(cleanup_fail=True)
    _install(monkeypatch, transport)
    result = run_oracle(local, config=_config(), hold=1, open_timeout=1, timeout=5)
    assert result.verdict == "MODEL_LOADED"
    assert transport.closed


def test_a_failing_cleanup_does_not_mask_the_task_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "board.pbix"
    local.write_bytes(b"pbix")
    transport = _Transport(fail=True, cleanup_fail=True)
    _install(monkeypatch, transport)
    with pytest.raises(RuntimeError, match="task failed"):
        run_oracle(local, config=_config(), hold=1, open_timeout=1, timeout=5)
    assert transport.closed
