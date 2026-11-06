"""The screenshot wait must require a whole PNG, not just a stable size.

The browser is polled, not waited on, so the file is the only signal that a
render finished. A size unchanged for a few probes is not proof: the browser can
pause mid-write, and hashing a truncated PNG would put a hash of a broken image
into the manifest — exactly the reproducibility claim the module makes. A
complete PNG ends with the fixed IEND chunk, so the probe checks the signature
and that trailer as well.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from agentic_bi.shots.shots_render import (
    _PNG_IEND,
    _PNG_SIGNATURE,
    _complete_png,
    _wait_for_stable_file,
)


class _Running:
    """The piece of a browser process the wait actually looks at."""

    returncode: int | None = None

    def poll(self) -> int | None:
        return None


def _whole_image() -> bytes:
    return _PNG_SIGNATURE + b"\x00" * 64 + _PNG_IEND


def test_complete_png_accepts_only_a_whole_image(tmp_path: Path) -> None:
    full = tmp_path / "full.png"
    full.write_bytes(_whole_image())
    assert _complete_png(full)

    truncated = tmp_path / "cut.png"
    truncated.write_bytes(_whole_image()[:-12])
    assert not _complete_png(truncated)

    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    assert not _complete_png(empty)

    assert not _complete_png(tmp_path / "missing.png")


def test_wait_does_not_return_while_the_png_is_partial(tmp_path: Path) -> None:
    """Measured mechanism: a stable size while the write is still paused."""
    path = tmp_path / "slow.png"
    path.write_bytes(_PNG_SIGNATURE + b"\x00" * 4096)
    finished = threading.Event()

    def finish() -> None:
        time.sleep(0.5)
        with path.open("ab") as handle:
            handle.write(_PNG_IEND)
        finished.set()

    writer = threading.Thread(target=finish)
    writer.start()
    try:
        _wait_for_stable_file(path, _Running())
        complete_at_return = finished.is_set()
    finally:
        writer.join(timeout=5)

    assert complete_at_return, "the wait returned before the PNG was complete"
    assert _complete_png(path)
