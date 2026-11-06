"""A corrupt `.pbix` is bad input (exit 2), not a traceback.

`agentic-bi-pbix-patch` documents "every user-facing failure is exit 2", but a
non-zip container raises `zipfile.BadZipFile`, which is not an `OSError`, so the
command ended on a traceback while `agentic-bi-rebuild` returned 2 for the same
file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi.pbix_binary.patch_cli import main


def test_members_on_a_non_zip_file_is_bad_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.pbix"
    broken.write_bytes(b"not a zip at all")
    assert main(["members", "--pbix", str(broken)]) == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "zip" in captured.err.lower()
