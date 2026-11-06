"""The replace step must never leave the target absent, nor create `C:`.

The old fallback was `catch { Delete(path); Move(tmp,path) }`: it ran for *any*
`Replace` failure, including a missing temp file (a concurrent writer already
moved it), so a perfectly good target was deleted and the following `Move` then
failed — the target was absent, which the docstring explicitly denied. These
tests pin the backup-rename chain (move the old file aside, move the new one in,
restore and rethrow on failure) and the parent-directory derivation, which used a
plain `\\` split and produced `CreateDirectory('C:')` for `C:\\file.ps1`.

The module is exercised as generated PowerShell text; nothing here talks to a
real guest.
"""

from __future__ import annotations

import pytest

from agentic_bi.guest_transport import GuestConfig, WinRMTransport
from agentic_bi.guest_winrm_commands import parent_dir, replace_script

_PATH = r"C:\pbi\out\task.ps1"


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


class TestTheTargetIsNeverAbsent:
    def test_an_existing_target_is_replaced_atomically(self) -> None:
        script = replace_script(_PATH)
        assert "if ([IO.File]::Exists($d))" in script
        assert "[IO.File]::Replace($s,$d,$null)" in script

    def test_a_missing_target_is_moved_into_place(self) -> None:
        script = replace_script(_PATH)
        assert "} else { [IO.File]::Move($s,$d) }" in script

    def test_the_target_is_never_deleted_before_the_new_file_is_in_place(self) -> None:
        script = replace_script(_PATH)
        assert "[IO.File]::Delete($d)" not in script
        assert "Remove-Item -LiteralPath $d" not in script

    def test_a_missing_temp_file_cannot_remove_the_target(self) -> None:
        script = replace_script(_PATH)
        removals = [line for line in script.splitlines() if "Remove-Item" in line]
        assert removals, "the fallback still clears a stale backup"
        assert all("$b" in line for line in removals), (
            "the only removal is the stale backup; a FileNotFoundException for the "
            "temp file must leave the target untouched"
        )


class TestTheFallbackRenamesAndRestores:
    def test_the_old_file_is_renamed_to_a_backup_first(self) -> None:
        script = replace_script(_PATH)
        assert "[IO.File]::Move($d,$b)" in script

    def test_the_new_file_is_moved_in_after_the_backup_rename(self) -> None:
        script = replace_script(_PATH)
        assert script.index("[IO.File]::Move($d,$b)") < script.index(
            "try { [IO.File]::Move($s,$d) }"
        )

    def test_a_failed_second_move_restores_the_backup_and_rethrows(self) -> None:
        script = replace_script(_PATH)
        assert "catch { [IO.File]::Move($b,$d); throw }" in script

    def test_the_original_replace_failure_is_not_swallowed(self) -> None:
        script = replace_script(_PATH)
        assert "throw" in script, "the fallback rethrows instead of reporting success"

    def test_a_successful_fallback_clears_the_backup(self) -> None:
        script = replace_script(_PATH)
        assert script.count("Remove-Item -LiteralPath $b") == 2

    def test_the_whole_replace_is_one_command_built_from_variables(self) -> None:
        script = replace_script(_PATH)
        assert "$d='C:\\pbi\\out\\task.ps1'" in script
        assert "$s='C:\\pbi\\out\\task.ps1.tmp'" in script
        assert "$b='C:\\pbi\\out\\task.ps1.bak'" in script


class TestTheParentDirectoryComesFromNtpath:
    def test_a_drive_root_file_does_not_become_the_drive_relative_c(self) -> None:
        transport, calls = _transport()
        transport.write_text(r"C:\file.ps1", "body")
        created = [call for call in calls if "CreateDirectory" in call]
        assert created, "the drive root is created (idempotently), not `C:`"
        assert r"CreateDirectory('C:\')" in created[0]
        assert "CreateDirectory('C:')" not in created[0]

    def test_a_forward_slash_path_creates_its_directory(self) -> None:
        transport, calls = _transport()
        transport.write_text("C:/pbi/out/task.ps1", "body")
        created = [call for call in calls if "CreateDirectory" in call]
        assert created, "a forward-slash path must still create its parent"
        assert r"CreateDirectory('C:\pbi\out')" in created[0]

    def test_a_bare_filename_has_no_directory_to_create(self) -> None:
        assert parent_dir("task.ps1") is None

    def test_a_drive_relative_file_has_no_directory_to_create(self) -> None:
        assert parent_dir("C:task.ps1") is None

    def test_a_drive_root_is_the_drive_root(self) -> None:
        assert parent_dir(r"C:\file.ps1") == "C:\\"

    def test_a_relative_subdirectory_is_kept(self) -> None:
        assert parent_dir(r"sub\task.ps1") == "sub"

    def test_an_empty_path_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            parent_dir("")
