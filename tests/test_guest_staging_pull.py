"""A pull of a missing or empty guest file must not overwrite a local artifact.

`pull_file` measured the guest file with a bare `Get-Item`: on a missing path
Windows PowerShell wrote a non-terminating error to stderr, stdout stayed empty,
the total became 0, the chunk loop was skipped and `write_bytes(b"")` replaced the
caller's previous good `.pbix` with 0 bytes — while the stage reported success.
The size probe now runs under `$ErrorActionPreference='Stop'` and an empty answer
is refused before the local file is touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi.guest_staging import StagingMixin
from agentic_bi.guest_types import Deadline, StageError


class _Guest(StagingMixin):
    """Only `ps` is exercised: a pull never opens a staging server."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[str] = []

    def ps(self, script: str, **kwargs: object) -> str:
        self.calls.append(script)
        return self.answer


def test_a_missing_guest_file_is_refused_before_the_local_write(
    tmp_path: Path,
) -> None:
    local = tmp_path / "board.pbix"
    local.write_bytes(b"previous good build")
    guest = _Guest("")
    with pytest.raises(StageError, match="missing or empty"):
        guest.pull_file(r"C:\pbi\out\board.pbix", local, Deadline(30))
    assert local.read_bytes() == b"previous good build"


def test_an_empty_guest_file_is_refused_before_the_local_write(tmp_path: Path) -> None:
    local = tmp_path / "board.pbix"
    local.write_bytes(b"previous good build")
    guest = _Guest("0")
    with pytest.raises(StageError, match="missing or empty"):
        guest.pull_file(r"C:\pbi\out\board.pbix", local, Deadline(30))
    assert local.read_bytes() == b"previous good build"


def test_the_size_probe_is_terminating(tmp_path: Path) -> None:
    guest = _Guest("")
    with pytest.raises(StageError):
        guest.pull_file(r"C:\pbi\out\board.pbix", tmp_path / "b.pbix", Deadline(30))
    assert guest.calls[0].startswith("$ErrorActionPreference='Stop'")
    assert "-LiteralPath" in guest.calls[0]


def test_a_short_read_is_refused_instead_of_writing_a_truncated_file(
    tmp_path: Path,
) -> None:
    local = tmp_path / "board.pbix"
    local.write_bytes(b"previous good build")

    class _Short(_Guest):
        def ps(self, script: str, **kwargs: object) -> str:
            self.calls.append(script)
            return "42" if "Get-Item" in script else ""

    guest = _Short("")
    with pytest.raises(StageError, match="pulled 0 of 42 B"):
        guest.pull_file(r"C:\pbi\out\board.pbix", local, Deadline(30))
    assert local.read_bytes() == b"previous good build"


def test_a_size_answer_with_no_number_is_a_stage_error(tmp_path: Path) -> None:
    """A warning line instead of the length must not escape as a bare `ValueError`.

    Measured before: the probe parsed `int(last line)` unconditionally, so a
    non-terminating error on stdout surfaced as
    `error: ValueError: invalid literal for int() with base 10: ...` — the file
    was not named and the chain log carried a message about a parser, not about
    the guest file.
    """
    local = tmp_path / "board.pbix"
    local.write_bytes(b"previous good build")
    guest = _Guest("WARNING: something odd\n")
    with pytest.raises(StageError, match=r"board\.pbix.*missing or empty"):
        guest.pull_file(r"C:\pbi\out\board.pbix", local, Deadline(30))
    assert local.read_bytes() == b"previous good build"


def test_the_size_answer_is_the_last_all_digit_line(tmp_path: Path) -> None:
    """A numeric line mixed with noise is still read; noise alone is refused."""
    local = tmp_path / "board.pbix"

    class _Noisy(_Guest):
        def ps(self, script: str, **kwargs: object) -> str:
            self.calls.append(script)
            if "Get-Item" in script:
                return "WARNING: retrying\n42\n"
            return ""

    guest = _Noisy("")
    with pytest.raises(StageError, match="pulled 0 of 42 B"):
        guest.pull_file(r"C:\pbi\out\board.pbix", local, Deadline(30))
