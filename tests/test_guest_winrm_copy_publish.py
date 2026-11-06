"""Publishing a finished build must not consume the file the chain pulls.

`publish_script` is an atomic **move** (`[IO.File]::Replace`/`Move` delete the
source), which is right for `<path>.tmp` staging. The build stage used it for a
finished `.pbix`, so the per-run file was gone before `build_dashboard` pulled
it: a missing path read as size 0, a 0-byte local file replaced the previous good
artifact, and the verdict stayed `BUILT`.

`publish_copy_script` copies first and then applies the same atomic replace, so
the source survives. These tests pin the generated PowerShell text; nothing here
talks to a real guest.
"""

from __future__ import annotations

import pytest

from agentic_bi.guest_types import StageError
from agentic_bi.guest_winrm_commands import (
    MAX_ENCODED_COMMAND,
    check_size,
    encoded_size,
    publish_copy_script,
    publish_script,
)

_SRC = r"C:\pbi\out\board.0badc0de.pbix"
_DST = r"C:\pbi\out\board.pbix"


class TestPublishCopyKeepsTheSource:
    def test_the_source_is_copied_not_moved(self) -> None:
        script = publish_copy_script(_SRC, _DST)
        assert "$src='C:\\pbi\\out\\board.0badc0de.pbix'" in script
        assert "[IO.File]::Copy($src,$stg,$true)" in script
        assert "Move($src,$" not in script

    def test_the_copy_targets_a_staging_name_next_to_the_destination(self) -> None:
        script = publish_copy_script(_SRC, _DST)
        assert "$stg='C:\\pbi\\out\\board.pbix.publish.tmp'" in script

    def test_the_final_step_is_the_same_atomic_replace(self) -> None:
        script = publish_copy_script(_SRC, _DST)
        assert "[IO.File]::Replace($s,$d,$null)" in script
        assert "$s='C:\\pbi\\out\\board.pbix.publish.tmp'" in script
        assert "$d='C:\\pbi\\out\\board.pbix'" in script

    def test_a_failed_copy_removes_its_partial_staging_file(self) -> None:
        script = publish_copy_script(_SRC, _DST)
        assert "catch {" in script
        assert "if ([IO.File]::Exists($stg))" in script
        assert "Remove-Item -LiteralPath $stg -Force" in script
        assert "throw" in script

    def test_the_three_argument_copy_is_net_framework_safe(self) -> None:
        """`Copy(src, dst, overwrite)` exists on .NET Framework; 3-arg Move does not."""
        script = publish_copy_script(_SRC, _DST)
        assert "Copy($src,$stg,$true)" in script
        assert "Move($s,$d,$true)" not in script

    def test_the_command_stays_under_the_encoded_cap(self) -> None:
        assert encoded_size(publish_copy_script(_SRC, _DST)) < MAX_ENCODED_COMMAND

    def test_a_move_based_publish_would_be_caught(self) -> None:
        """The regression guard: `publish_script` must stay a move (staging needs it)."""
        script = publish_script(_SRC, _DST)
        assert "[IO.File]::Move($s,$d)" in script
        assert "[IO.File]::Copy(" not in script

    def test_an_over_long_path_is_refused_by_the_channel(self) -> None:
        long = "C:\\pbi\\out\\" + "a" * 900 + ".pbix"
        with pytest.raises(StageError, match="encoded characters"):
            check_size(publish_copy_script(long, long))


class TestPublishCopyStagingIsPerRun:
    """Two chains publishing one declared name must not share a staging file."""

    def test_a_token_makes_the_staging_name_unique(self) -> None:
        script = publish_copy_script(_SRC, _DST, token="0badc0de")
        assert "$stg='C:\\pbi\\out\\board.pbix.0badc0de.publish.tmp'" in script
        assert "$s='C:\\pbi\\out\\board.pbix.0badc0de.publish.tmp'" in script

    def test_two_tokens_never_produce_the_same_staging_path(self) -> None:
        one = publish_copy_script(_SRC, _DST, token="aaaaaaaa")
        two = publish_copy_script(_SRC, _DST, token="bbbbbbbb")
        one_stg = one.split("$stg=", 1)[1].splitlines()[0]
        two_stg = two.split("$stg=", 1)[1].splitlines()[0]
        assert one_stg != two_stg

    def test_a_token_with_a_path_separator_is_refused(self) -> None:
        with pytest.raises(ValueError, match="ASCII alphanumeric"):
            publish_copy_script(_SRC, _DST, token="../x")

    def test_a_non_ascii_token_is_refused(self) -> None:
        with pytest.raises(ValueError, match="ASCII alphanumeric"):
            publish_copy_script(_SRC, _DST, token="токен")
