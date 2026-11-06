"""Every command the guest channel emits must fit the encoded-command cap.

The guest truncates a `powershell -EncodedCommand <base64>` line that is too
long, and the old code only checked the *chunk* commands against a 2048-character
payload budget: the final `Replace`/`Move` repeated an 85-character path seven
times and reached ~2360 encoded characters unchecked. These tests pin the one
central guard in `WinRMChannel.ps`, the cap constant and the per-path chunk
budget derived from the real command template.
"""

from __future__ import annotations

import base64

import pytest

from agentic_bi.guest_transport import (
    GuestConfig,
    StageError,
    WinRMTransport,
    ps_quote,
)
from agentic_bi.guest_winrm import WinRMChannel
from agentic_bi.guest_winrm_commands import (
    MAX_ENCODED_COMMAND,
    chunk_budget,
    encoded_size,
    replace_script,
    split_payload,
    write_chunk_script,
)

_SHORT = r"C:\pbi\out\task.ps1"
_LONG = "C:\\" + ("deep\\directory\\" * 4) + ("a" * 40) + ".ps1"


def _config() -> GuestConfig:
    return GuestConfig(winrm="http://127.0.0.1:5985/wsman", user="u", password="p")


def _transport() -> tuple[WinRMTransport, list[str]]:
    transport = WinRMTransport.__new__(WinRMTransport)
    transport.config = _config()
    calls: list[str] = []

    def ps(script: str, **kw: object) -> str:
        calls.append(script)
        return ""

    transport.ps = ps  # type: ignore[method-assign]
    return transport, calls


def _sizes(calls: list[str]) -> list[int]:
    return [encoded_size(call) for call in calls]


class TestTheCapIsDocumentedAndConservative:
    def test_the_cap_leaves_headroom_under_the_windows_command_line(self) -> None:
        assert MAX_ENCODED_COMMAND == 6000
        assert MAX_ENCODED_COMMAND < 8191, "the Windows command line tops out here"

    def test_the_encoded_size_is_the_utf16_base64_payload(self) -> None:
        script = "Write-Output 'ok'"
        expected = len(base64.b64encode(script.encode("utf-16-le")))
        assert encoded_size(script) == expected


class TestTheChannelRefusesAnOversizedCommand:
    def test_ps_raises_stage_error_over_the_cap(self) -> None:
        channel = WinRMChannel(_config())
        with pytest.raises(StageError) as raised:
            channel.ps("x" * 20000)
        assert str(MAX_ENCODED_COMMAND) in str(raised.value)

    def test_the_guard_runs_before_the_session_is_opened(self) -> None:
        channel = WinRMChannel(_config())
        with pytest.raises(StageError):
            channel.ps("x" * 20000)
        assert channel._session is None, "an oversized script must not reach the guest"

    def test_a_command_at_the_budget_is_accepted(self) -> None:
        budget = chunk_budget(_SHORT)
        script = write_chunk_script("'t'", b"a" * budget, offset=9_999_999)
        assert encoded_size(script) <= MAX_ENCODED_COMMAND


class TestTheChunkBudgetFollowsTheRealTemplate:
    def test_a_longer_path_leaves_a_smaller_payload_budget(self) -> None:
        assert chunk_budget(_LONG) < chunk_budget(_SHORT)

    def test_a_path_too_long_for_any_command_is_refused(self) -> None:
        with pytest.raises(StageError, match="too long"):
            chunk_budget("C:\\" + "p" * 4000 + ".ps1")

    def test_a_budget_too_small_to_progress_is_refused(self) -> None:
        with pytest.raises(ValueError, match="too small"):
            split_payload(b"abcd", 3)

    def test_a_piece_is_never_empty_even_for_invalid_utf8(self) -> None:
        with pytest.raises(ValueError, match="no progress"):
            split_payload(b"\x80" * 5, 4)

    def test_the_class_helper_refuses_a_budget_below_four(self) -> None:
        with pytest.raises(ValueError, match="too small"):
            WinRMTransport._chunks(b"abcd", 3)

    def test_an_empty_payload_yields_no_pieces(self) -> None:
        assert split_payload(b"", 4) == []

    def test_no_piece_is_ever_empty(self) -> None:
        pieces = split_payload("😀".encode() * 8, 5)
        assert pieces
        assert all(pieces)
        assert b"".join(pieces) == "😀".encode() * 8


class TestNoEmittedCommandExceedsTheCap:
    def test_a_long_path_write_stays_under_the_cap_everywhere(self) -> None:
        transport, calls = _transport()
        transport.write_text(_LONG, "Write-Output 'start'\n" * 200)
        assert calls
        assert max(_sizes(calls)) <= MAX_ENCODED_COMMAND

    def test_the_final_replace_command_fits_for_a_long_path(self) -> None:
        assert encoded_size(replace_script(_LONG)) <= MAX_ENCODED_COMMAND

    def test_the_path_is_not_repeated_seven_times_costlessly(self) -> None:
        script = replace_script(_LONG)
        assert script.count(_LONG) == 3, (
            "one literal each for $p, $t and $bak; the old version embedded the "
            "path seven times, which is what overflowed the cap"
        )

    def test_a_multi_path_removal_command_fits(self) -> None:
        paths = [_LONG, f"{_LONG}.log", f"{_LONG}.marker"]
        removal = "".join(
            f"if (Test-Path -LiteralPath {ps_quote(path)}) "
            f"{{ Remove-Item -LiteralPath {ps_quote(path)} -Recurse -Force }}\n"
            for path in paths
        )
        assert encoded_size(removal) <= MAX_ENCODED_COMMAND

    def test_read_text_stays_under_the_cap_for_a_realistic_path(self) -> None:
        transport, calls = _transport()
        transport.read_text(_LONG)
        assert max(_sizes(calls)) <= MAX_ENCODED_COMMAND
