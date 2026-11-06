"""Manifest records for figures that were not produced, and portable reasons.

A build's failures and skips are stored in the manifest, so their text must not
carry the run's output directory or the plan's directory: the same plan built
into two different directories has to produce the same bytes, and the documented
rule is that no absolute path appears in the manifest. The output root reaches a
message in several spellings — as the caller wrote it, resolved, or resolved
through a symlink (`/tmp` is `/private/tmp` on macOS) — so every spelling is
stripped, not just the resolved one.

This module owns that normalization and the record shape, so `shots_build` stays
an orchestrator: it decides *what* to render and this file decides what a
non-`ok` figure looks like and leaves behind.

Public API:
    portable(message, out, base) -> str
    discard_stale(out, spec) -> None
    record_unbuilt(spec, base, status, reason) -> RenderRecord
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from agentic_bi.shots.shots_manifest import RenderRecord
from agentic_bi.shots.shots_types import FigureSpec

logger = logging.getLogger(__name__)


def _resolved(path: Path) -> Path | None:
    """`path.resolve()`, or None when the filesystem cannot answer."""
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - defensive, resolve rarely fails
        return None


def _prefixes(out: Path, base: Path) -> list[str]:
    """Every spelling of both roots, longest first.

    Longest first so a nested root is not half-replaced by its parent prefix.
    A bare `.` is skipped: stripping it would eat every sentence period.
    """
    found: set[str] = set()
    for root in (out, base):
        for candidate in (root, _resolved(root)):
            if candidate is None:
                continue
            text = str(candidate)
            if text and text not in {".", os.sep}:
                found.add(text)
    return sorted(found, key=len, reverse=True)


def portable(message: str, out: Path, base: Path) -> str:
    """Strip every known spelling of the output and plan roots from `message`.

    Args:
        message: the text a renderer or the OS produced.
        out: the output directory of the run.
        base: the directory the plan's sources resolve against.

    Returns:
        The message with the run's own directories removed, so it is identical
        for two runs of the same plan into different directories. Anything
        outside the two roots is left as the tool reported it.
    """
    text = message
    for prefix in _prefixes(out, base):
        text = text.replace(prefix + os.sep, "")
        text = re.sub(re.escape(prefix) + r"(?=$|[\\/])", ".", text)
    return text


def source_label(spec: FigureSpec, base: Path) -> str:
    """The source as the plan wrote it (relative to `base`), never absolute."""
    try:
        return Path(spec.source).resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(spec.source).name


def record_unbuilt(
    spec: FigureSpec, base: Path, status: str, reason: str
) -> RenderRecord:
    """A manifest entry for a figure that was not produced.

    Args:
        spec: the figure that was requested.
        base: the directory the plan's sources resolve against.
        status: `skipped` or `failed`.
        reason: why, already normalized by `portable`.
    """
    return RenderRecord(
        name=spec.name,
        kind=spec.kind,
        source=source_label(spec, base),
        png="",
        width=0,
        height=0,
        scale=spec.scale,
        sha256="",
        bytes=0,
        status=status,
        reason=reason,
    )


def discard_stale(out: Path, spec: FigureSpec) -> None:
    """Delete a figure's PNG so a non-`ok` record cannot ship an older image.

    A failure before the renderer runs (missing source, `--no-strict`) or a
    render that dies half-way used to leave the previous run's PNG in the output
    directory: anything staging `out/*.png` would then publish a picture the
    manifest does not describe, and only an explicit `verify` caught it.
    """
    target = out / spec.output_name()
    try:
        target.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - defensive, unlink rarely fails
        logger.warning(
            "figure '%s': cannot remove stale %s (%s)", spec.name, target.name, exc
        )


__all__ = ["discard_stale", "portable", "record_unbuilt", "source_label"]
