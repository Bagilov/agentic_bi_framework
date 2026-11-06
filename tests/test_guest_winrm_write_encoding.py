"""`write_text` must write the UTF-8 BOM exactly once, in the first chunk.

Windows PowerShell 5.1 reads a `-File` script in the current ANSI code page
unless it starts with EF BB BF, so a Cyrillic payload (`--title 'Продажи'`) was
turned into mojibake silently: the `.pbix` was still produced and the run was
reported BUILT with a mangled title. Removing the BOM altogether fixed the
mid-file U+FEFF and broke every non-ASCII payload. These tests pin both halves:
the preamble is on the first chunk **only**, later chunks append without one, and
the reassembled file decodes as the original text — ASCII, Cyrillic and astral.

The content is written to `<path>.tmp` and moved onto `<path>` at the end, so a
write that dies half-way leaves no truncated `.ps1` for the guest to run.
"""

from __future__ import annotations

import base64

import pytest

from agentic_bi.guest_transport import GuestConfig, StageError, WinRMTransport
from agentic_bi.guest_winrm_commands import MAX_ENCODED_COMMAND, chunk_budget

_LIMIT = MAX_ENCODED_COMMAND
_PATH = r"C:\pbi\out\task.ps1"
_TMP = _PATH + ".tmp"
_BOM = b"\xef\xbb\xbf"


def _transport() -> tuple[WinRMTransport, list[str]]:
    transport = WinRMTransport.__new__(WinRMTransport)
    transport.config = GuestConfig(
        winrm="http://127.0.0.1:5985/wsman", user="u", password="p"
    )
    calls: list[str] = []

    def ps(script: str, **kw: object) -> str:
        # The guest truncates `powershell -encodedcommand`, which is the script
        # encoded as UTF-16LE and base64'd — not a character count.
        encoded = base64.b64encode(script.encode("utf-16-le"))
        assert len(encoded) <= _LIMIT, (
            f"one encoded command is too long: {len(encoded)}"
        )
        calls.append(script)
        return ""

    transport.ps = ps  # type: ignore[method-assign]
    return transport, calls


def _writes(calls: list[str]) -> list[str]:
    return [call for call in calls if "FromBase64String(" in call]


def _pieces(calls: list[str]) -> list[bytes]:
    out: list[bytes] = []
    for call in _writes(calls):
        b64 = call.split("FromBase64String('", 1)[1].split("')", 1)[0]
        out.append(base64.b64decode(b64))
    return out


def _file(calls: list[str]) -> bytes:
    """The bytes the guest ends up with: every piece written at its offset.

    The preamble travels inside the first piece, so the model simply concatenates
    the pieces in command order.
    """
    return b"".join(_pieces(calls))


class TestTheBomIsWrittenExactlyOnce:
    def test_the_file_starts_with_the_utf8_preamble(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "Write-Output 'a'\r\n" * 100)
        assert _file(calls).startswith(_BOM)

    def test_only_the_first_piece_carries_a_preamble(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "x" * 2000)
        pieces = _pieces(calls)
        assert len(pieces) > 1, "a 2 KiB payload must be split into several chunks"
        assert pieces[0].startswith(_BOM)
        for piece in pieces[1:]:
            assert not piece.startswith(_BOM)
            assert _BOM not in piece

    def test_the_file_holds_exactly_one_preamble(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "Write-Output 'a'\r\n" * 100)
        data = _file(calls)
        assert data.count(_BOM) == 1
        assert data == _BOM + ("Write-Output 'a'\r\n" * 100).encode("utf-8")

    def test_every_chunk_is_written_at_its_own_offset(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "x" * 2000)
        writes = _writes(calls)
        offsets = [
            int(c.split("$fs.SetLength(", 1)[1].split(")", 1)[0]) for c in writes
        ]
        assert offsets[0] == 0
        assert offsets == sorted(offsets)
        assert len(set(offsets)) == len(offsets), "two chunks must not share an offset"
        assert all("$fs.Seek(" in call for call in writes)

    def test_add_content_is_not_used_at_all(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "Write-Output 'a'\r\n" * 100)
        assert not any("Add-Content" in call for call in calls)


class TestNonAsciiPayloadsSurvive:
    def test_cyrillic_round_trips_bit_for_bit(self) -> None:
        transport, calls = _transport()
        body = "$t = 'Продажи'\r\n" + ("# шаг завершён\r\n" * 40)
        transport.write_text(_PATH, body)
        data = _file(calls)
        assert data.decode("utf-8-sig") == body, "the file decodes as UTF-8 with a BOM"

    def test_an_astral_character_is_never_split(self) -> None:
        transport, calls = _transport()
        body = "😀" * 400
        transport.write_text(_PATH, body)
        assert _file(calls).decode("utf-8-sig") == body

    def test_chunks_are_sized_in_bytes_not_characters(self) -> None:
        transport, calls = _transport()
        body = "шаг завершён\r\n" * 100
        transport.write_text(_PATH, body)
        pieces = _pieces(calls)
        assert len(pieces) > 1
        # The first piece additionally carries the 3-byte preamble.
        assert all(len(piece) <= chunk_budget(_PATH) + len(_BOM) for piece in pieces)
        assert _file(calls).decode("utf-8-sig") == body
        for piece in pieces[1:]:
            piece.decode("utf-8")


class TestEmptyText:
    def test_an_empty_payload_creates_an_empty_file(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "")
        assert _writes(calls) == [], "no chunk for an empty payload"
        write = next(call for call in calls if "WriteAllBytes" in call)
        assert "New-Object byte[] 0" in write, "an empty file, zero bytes"
        assert "UTF8Encoding" not in write, "no content, so no preamble either"

    def test_the_empty_file_is_moved_into_place(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "")
        assert "[IO.File]::Move($s,$d)" in calls[-1]


class TestTheWriteIsAtomic:
    def test_every_chunk_goes_to_the_temporary_file(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "x" * 2000)
        for call in _writes(calls):
            assert f"('{_TMP}'," in call
            assert f"('{_PATH}'," not in call

    def test_the_final_step_moves_the_temporary_file_into_place(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "x" * 2000)
        last = calls[-1]
        assert f"$d='{_PATH}'" in last
        assert f"$s='{_TMP}'" in last
        assert "if ([IO.File]::Exists($d))" in last
        assert "[IO.File]::Replace($s,$d,$null)" in last, (
            "the 3-argument File.Move overload is .NET Core only; PowerShell 5.1 "
            "runs on .NET Framework, where Replace is the atomic overwrite"
        )
        assert "[IO.File]::Move($s,$d)" in last
        assert ", $true)" not in last, (
            "no move may use the .NET Core-only 3-argument overload"
        )

    def test_the_target_is_never_removed_up_front(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "x" * 2000)
        last = calls[-1]
        assert "[IO.File]::Delete($p)" not in last
        assert "Remove-Item -LiteralPath $p" not in last, (
            "the old file must be replaced atomically, not deleted first"
        )


class TestAFailedWriteLeavesNothingBehind:
    def test_a_broken_chunk_discards_the_temporary_file(self) -> None:
        calls: list[str] = []
        transport = WinRMTransport.__new__(WinRMTransport)
        transport.config = GuestConfig(
            winrm="http://127.0.0.1:5985/wsman", user="u", password="p"
        )

        def ps(script: str, **kw: object) -> str:
            calls.append(script)
            if "FromBase64String" in script and "FromBase64String" in "".join(
                calls[:-1]
            ):
                raise StageError("the guest dropped the connection")
            return ""

        transport.ps = ps  # type: ignore[method-assign]
        with pytest.raises(StageError, match="dropped the connection"):
            transport.write_text(_PATH, "x" * 2000)
        discarded = [call for call in calls if "Remove-Item" in call]
        assert discarded, "a half-written temp file must not be left on the guest"
        assert f"Remove-Item -LiteralPath '{_TMP}'" in discarded[-1]

    def test_the_original_error_is_what_propagates(self) -> None:
        transport = WinRMTransport.__new__(WinRMTransport)
        transport.config = GuestConfig(
            winrm="http://127.0.0.1:5985/wsman", user="u", password="p"
        )

        def ps(script: str, **kw: object) -> str:
            raise StageError("the guest dropped the connection")

        transport.ps = ps  # type: ignore[method-assign]
        with pytest.raises(StageError, match="dropped the connection"):
            transport.write_text(_PATH, "body")


class TestOnlyUtf8TextIsAccepted:
    def test_a_lone_surrogate_is_refused_with_a_clear_message(self) -> None:
        transport, calls = _transport()
        with pytest.raises(StageError, match="not UTF-8 encodable"):
            transport.write_text(_PATH, 'Write-Output "\ud800"')
        assert calls == [], "nothing may be written before the text is validated"

    def test_the_error_names_the_offending_text(self) -> None:
        transport, _ = _transport()
        with pytest.raises(StageError) as raised:
            transport.write_text(_PATH, "a\ud800b")
        assert _PATH in str(raised.value)
        assert "surrogate" in str(raised.value)

    def test_valid_astral_text_is_not_refused(self) -> None:
        transport, calls = _transport()
        transport.write_text(_PATH, "😀")
        assert _file(calls).decode("utf-8-sig") == "😀"


class TestTheDestinationPathIsLiteral:
    def test_wildcards_in_the_path_are_not_expanded(self) -> None:
        transport, calls = _transport()
        transport.write_text(r"C:\pbi\out\board[1]*.ps1", "body")
        tmp = r"C:\pbi\out\board[1]*.ps1.tmp"
        assert any(f"('{tmp}'," in call for call in calls)
        assert f"$s='{tmp}'" in calls[-1]
        assert "[IO.File]::Move($s,$d)" in calls[-1]

    def test_the_parent_directory_is_created_without_new_item(self) -> None:
        transport, calls = _transport()
        transport.write_text(r"C:\pbi\out\deep\task.ps1", "body")
        created = [call for call in calls if "CreateDirectory" in call]
        assert created, "the parent directory must be created first"
        assert r"[IO.Directory]::CreateDirectory('C:\pbi\out\deep')" in created[0]
        assert not any("New-Item" in call for call in calls)
