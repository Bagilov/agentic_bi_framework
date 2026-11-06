"""`push_file` must report the real failure, and only its own timeout.

The budget check sat in the `finally` that closes the staging server, so a fetch
that failed for a concrete reason (an unreachable URL, a refused write to the
guest path) was replaced by a generic `push: exceeded the Ns budget` whenever the
clock had run out as well. The cause the user needs is the fetch error.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from agentic_bi.guest_staging import StagingMixin
from agentic_bi.guest_types import ChainTimeout, Deadline, GuestConfig, StageError

_DEST = r"C:\pbi\out\abf.zip"


class _Guest(StagingMixin):
    """A transport whose `ps` answer is supplied per test."""

    def __init__(self) -> None:
        self.config = GuestConfig(
            winrm="http://127.0.0.1:5985/wsman", user="u", password="p"
        )
        self._init_staging()

    def ps(self, script: str, **kwargs: object) -> str:
        raise StageError("guest refused the fetch")


def _local(tmp_path: Path) -> Path:
    local = tmp_path / "abf.zip"
    local.write_bytes(b"payload")
    return local


def _expired() -> Deadline:
    """A budget that has already elapsed, without waiting inside the test."""
    deadline = Deadline(0.001)
    time.sleep(0.01)
    return deadline


def test_a_fetch_failure_is_not_replaced_by_the_budget(tmp_path: Path) -> None:
    guest = _Guest()
    with pytest.raises(StageError, match="guest refused the fetch"):
        guest.push_file(_local(tmp_path), _DEST, _expired())
    assert guest._servers == []


def test_an_expired_budget_still_fails_a_successful_fetch(tmp_path: Path) -> None:
    guest = _Guest()

    def ps(script: str, **kwargs: object) -> str:
        return ""

    guest.ps = ps  # type: ignore[method-assign]
    with pytest.raises(ChainTimeout, match="push"):
        guest.push_file(_local(tmp_path), _DEST, _expired())
    assert guest._servers == []


def test_a_verified_fetch_returns_normally(tmp_path: Path) -> None:
    guest = _Guest()
    digest = hashlib.sha256(b"payload").hexdigest().upper()

    def ps(script: str, **kwargs: object) -> str:
        return digest if "Get-FileHash" in script else ""

    guest.ps = ps  # type: ignore[method-assign]
    guest.push_file(_local(tmp_path), _DEST, Deadline(30))
    assert guest._servers == []


def test_a_checksum_mismatch_is_a_stage_error(tmp_path: Path) -> None:
    guest = _Guest()

    def ps(script: str, **kwargs: object) -> str:
        return "0" * 64 if "Get-FileHash" in script else ""

    guest.ps = ps  # type: ignore[method-assign]
    with pytest.raises(StageError, match="failed SHA-256 verification"):
        guest.push_file(_local(tmp_path), _DEST, Deadline(30))
