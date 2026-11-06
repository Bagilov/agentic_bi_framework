"""`write_text` must survive a script far larger than one encoded command line.

The Windows guest truncates a long `powershell -encodedcommand` invocation
("The command line is too long"), which is what a single base64 blob produced for
any script above ~1 KiB — so the real build/oracle task bodies could never be
written. `write_text` streams the payload in short chunks; these tests pin the
chunking, the exact round trip and the quoting of the destination path.

The limit is measured on the **encoded command** (`base64(script.encode(
"utf-16-le"))`), not on the character count of the script: that encoded string is
what the guest actually receives and truncates.
"""

from __future__ import annotations

import base64
import math

import pytest

from agentic_bi.guest_transport import GuestConfig, StageError, WinRMTransport
from agentic_bi.guest_winrm_commands import (
    MAX_ENCODED_COMMAND,
    chunk_budget,
    encoded_size,
    replace_script,
)

_LIMIT = MAX_ENCODED_COMMAND


def _transport() -> tuple[WinRMTransport, list[str]]:
    transport = WinRMTransport.__new__(WinRMTransport)
    transport.config = GuestConfig(
        winrm="http://127.0.0.1:5985/wsman", user="u", password="p"
    )

    def ps(script: str, **kw: object) -> str:
        encoded = base64.b64encode(script.encode("utf-16-le"))
        assert len(encoded) <= _LIMIT, (
            f"one encoded command is too long: {len(encoded)}"
        )
        calls.append(script)
        return ""

    calls: list[str] = []
    transport.ps = ps  # type: ignore[method-assign]
    return transport, calls


def _pieces(calls: list[str]) -> list[bytes]:
    """The decoded chunk payloads, one per chunked write call, in order."""
    pieces = []
    for call in calls:
        if "FromBase64String(" not in call:
            continue
        b64 = call.split("FromBase64String('", 1)[1].split("')", 1)[0]
        pieces.append(base64.b64decode(b64))
    return pieces


def _reassemble(calls: list[str]) -> str:
    """Decode the base64 chunk from every chunked write call, in order."""
    out = []
    for call in calls:
        if "FromBase64String(" not in call:
            continue
        b64 = call.split("FromBase64String('", 1)[1].split("')", 1)[0]
        out.append(base64.b64decode(b64))
    return b"".join(out).decode("utf-8-sig")


class TestWriteTextStreamsThePayload:
    """A multi-kilobyte script is written correctly and in small commands."""

    def test_long_script_round_trips_exactly(self) -> None:
        transport, calls = _transport()
        body = "Write-Output 'start'\n" + ("# a comment line\n" * 400) + "exit 0\n"
        transport.write_text(r"C:\pbi\out\task.ps1", body)
        assert _reassemble(calls) == body

    def test_payload_is_split_into_several_commands(self) -> None:
        transport, calls = _transport()
        transport.write_text(r"C:\pbi\out\task.ps1", "x" * 4000)
        chunks = [c for c in calls if "FromBase64String(" in c]
        assert len(chunks) > 1

    def test_every_encoded_command_stays_under_the_guest_limit(self) -> None:
        transport, calls = _transport()
        # Cyrillic: three UTF-8 bytes per character in the worst case.
        transport.write_text(r"C:\pbi\out\task.ps1", "шаг завершён\r\n" * 200)
        longest = max(len(base64.b64encode(c.encode("utf-16-le"))) for c in calls)
        assert longest <= _LIMIT

    def test_the_write_goes_through_a_temporary_file(self) -> None:
        transport, calls = _transport()
        transport.write_text(r"C:\pbi\out\task.ps1", "body")
        write = next(call for call in calls if "FromBase64String(" in call)
        assert r"C:\pbi\out\task.ps1.tmp" in write
        assert r"C:\pbi\out\task.ps1'" not in write
        assert "[IO.File]::Move(" in calls[-1]

    def test_the_parent_directory_is_created(self) -> None:
        transport, calls = _transport()
        transport.write_text(r"C:\pbi\out\deep\task.ps1", "body")
        assert any(
            "[IO.Directory]::CreateDirectory(" in c and r"C:\pbi\out\deep" in c
            for c in calls
        )
        assert not any("New-Item" in c for c in calls)

    def test_chunk_sizes_consume_the_path_dependent_budget(self) -> None:
        """A chunk fills `chunk_budget(path)`; a fixed small size is a regression.

        A constant (measured: 360 bytes) still passes a one-sided "commands fit"
        test but multiplies the number of round trips for every write, and it
        ignores that the budget shrinks as the path grows.
        """
        body = "x" * 20000
        short = r"C:\pbi\out\task.ps1"
        long = "C:\\pbi\\out\\" + "d" * 120 + "\\task.ps1"
        counts = []
        for path in (short, long):
            transport, calls = _transport()
            transport.write_text(path, body)
            payloads = _pieces(calls)
            assert payloads[0].startswith(b"\xef\xbb\xbf")
            sizes = [len(piece) for piece in payloads]
            budget = chunk_budget(path)
            assert max(sizes[1:]) <= budget or len(sizes) == 1
            assert len(sizes) == math.ceil((len(body) + 3) / budget)
            counts.append(len(sizes))
        assert counts[1] > counts[0], "a longer path must yield a smaller budget"

    def test_non_ascii_text_survives(self) -> None:
        transport, calls = _transport()
        body = "Write-Host 'шаг завершён'\n"
        transport.write_text(r"C:\pbi\out\task.ps1", body)
        assert "шаг завершён" in _reassemble(calls)

    def test_a_path_that_only_overflows_the_move_is_refused_before_upload(self) -> None:
        """`chunk_budget` sizes the chunk command, not the final `Replace`/`Move`.

        Measured: at 655 characters the replace command is 6304 encoded chars
        (over the 6000 cap) while `chunk_budget` still returns 876, so the write
        used to upload every chunk and only then fail on the move.
        """
        path = "C:\\pbi\\out\\" + "d" * 639 + ".pbix"
        assert len(path) == 655
        assert encoded_size(replace_script(path)) > MAX_ENCODED_COMMAND
        assert chunk_budget(path) >= 4
        transport, calls = _transport()
        with pytest.raises(StageError, match="encoded characters"):
            transport.write_text(path, "x" * 4000)
        assert calls == []

    def test_the_preamble_is_counted_in_the_move_guard(self) -> None:
        """The guard must measure the command as sent, preamble included.

        Measured: at 612 characters the bare replace command is 5960 encoded
        chars, but the command actually sent starts with the 30-character
        `$ErrorActionPreference` preamble and is 6040 — over the cap. The old
        guard passed, uploaded every chunk, and the guest truncated the move.
        """
        path = "C:\\pbi\\out\\" + "d" * 597 + ".ps1"
        assert len(path) == 612
        preamble = "$ErrorActionPreference='Stop'\n"
        assert encoded_size(replace_script(path)) <= MAX_ENCODED_COMMAND
        assert encoded_size(preamble + replace_script(path)) > MAX_ENCODED_COMMAND
        transport, calls = _transport()
        with pytest.raises(StageError, match="encoded characters"):
            transport.write_text(path, "x" * 4000)
        assert calls == []
