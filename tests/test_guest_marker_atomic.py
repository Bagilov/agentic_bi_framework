"""The marker parser must reject a truncated write, like the writer never makes one.

`parse_exitcode` accepted any prefix: a poll that read `EXITCODE=1` of an
unfinished `EXITCODE=10` reported 1, so a build that later failed with 10 could
be reported as a different code — or a success could be reported from a value
that had not even been flushed. The docstring already promised a mid-write read
returns None.

The runner now writes the marker atomically (`Set-Content` to `<marker>.tmp`,
then an overwriting `[IO.File]::Move`) and always terminates the value with a
newline, and the parser accepts exactly that shape. Both halves are pinned here.
"""

from __future__ import annotations

import pytest

from agentic_bi.guest_task import parse_exitcode, runner_script

_MARKER = r"C:\pbi\out\p.done"


class TestTheParserOnlyAcceptsACompleteMarker:
    @pytest.mark.parametrize(
        ("marker", "expected"),
        [
            ("EXITCODE=0\r\n", 0),
            ("EXITCODE=2\r\n", 2),
            ("EXITCODE=10\r\n", 10),
            ("EXITCODE=-1\r\n", -1),
            ("noise\r\nEXITCODE=7\r\n", 7),
            ("EXITCODE=0\n", 0),
            ("EXITCODE=0\r\n\r\n", 0),
        ],
    )
    def test_a_complete_marker_yields_a_code(self, marker: str, expected: int) -> None:
        assert parse_exitcode(marker) == expected

    @pytest.mark.parametrize(
        "marker",
        [
            "EXITCODE=1",
            "EXITCODE=10",
            "EXITCODE=",
            "EXITCODE=\r\n",
            "EXITCODE=abc\r\n",
            "EXITCODE=0\r\nstray",
            "",
            "noise",
        ],
    )
    def test_a_partial_or_dirty_marker_yields_none(self, marker: str) -> None:
        assert parse_exitcode(marker) is None

    def test_the_truncated_prefix_of_a_two_digit_code_is_not_one(self) -> None:
        full = "EXITCODE=10\r\n"
        assert parse_exitcode(full[: len("EXITCODE=1")]) is None


class TestTheWriterEmitsThatShape:
    def _runner(self) -> str:
        return runner_script(
            payload=r"C:\pbi\out\p.payload.ps1",
            log_path=r"C:\pbi\out\p.log",
            marker_path=_MARKER,
        )

    def test_the_value_is_written_to_a_temporary_first(self) -> None:
        runner = self._runner()
        assert f"Set-Content -LiteralPath '{_MARKER}.tmp'" in runner
        assert f"Set-Content -LiteralPath '{_MARKER}'" not in runner

    def test_the_temporary_is_moved_onto_the_marker_atomically(self) -> None:
        runner = self._runner()
        assert f"$s='{_MARKER}.tmp'" in runner
        assert f"$d='{_MARKER}'" in runner
        assert runner.index("Set-Content") < runner.index("[IO.File]::Move")

    def test_the_move_uses_the_two_argument_overload_only(self) -> None:
        runner = self._runner()
        assert ", $true)" not in runner, (
            "the 3-argument File.Move overload is .NET Core only and Windows "
            "PowerShell 5.1 runs on .NET Framework"
        )

    def test_the_marker_token_is_written_exactly_once(self) -> None:
        runner = self._runner()
        assert runner.count('"EXITCODE=" + $abfCode') == 1

    def test_the_parser_accepts_what_the_writer_emits(self) -> None:
        # `Set-Content` terminates the value, so the file on the guest is
        # `EXITCODE=<n>\r\n` — the only shape the parser accepts.
        for code in (0, 4, 10, -1):
            assert parse_exitcode(f"EXITCODE={code}\r\n") == code
