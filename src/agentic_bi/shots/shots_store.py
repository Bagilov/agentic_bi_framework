"""Deterministic on-disk form of the shot manifest.

Two runs of the same plan must produce the same bytes, otherwise a manifest
cannot be reviewed, diffed or cached. This module fixes that form: a stable key
order, records in plan order, no timestamp unless the caller supplies one, and
names instead of paths — the manifest must not depend on where the browser or
the plan happens to live on this machine. Reading is the mirror image: every
failure is a `ValueError` naming the file, so `verify` reports it as bad input
(exit code 2) rather than a traceback.

Public API:
    write_manifest(records, path, ...) -> ShotManifest
    read_manifest(path) -> ShotManifest
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agentic_bi.shots.shots_manifest import RenderRecord, ShotManifest


def _name(value: str) -> str:
    """The last component of a path, on either separator style."""
    return re.split(r"[\\/]", value)[-1] if value else ""


def write_manifest(
    records: list[RenderRecord],
    path: str | Path,
    *,
    browser: str,
    plan: str = "",
    generated: str = "",
    root: str | Path | None = None,
) -> ShotManifest:
    """Write a manifest JSON and return it.

    Args:
        records: every requested figure, in plan order (any status).
        path: where to write the manifest JSON.
        browser: the browser executable used; only its name is recorded.
        plan: the source plan file; only its name is recorded.
        generated: an optional ISO-8601 timestamp; empty keeps the file
            byte-identical across runs.
        root: the directory recorded PNG names are relative to; defaults to the
            manifest's own directory, so a set can be verified after a move.

    Returns:
        The written `ShotManifest` (with `root` set, so it can be verified).
    """
    out = Path(path)
    manifest = ShotManifest(
        browser=_name(browser),
        generated=generated,
        figures=list(records),
        plan=_name(plan),
        root=str(out.parent if root is None else root),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def read_manifest(path: str | Path) -> ShotManifest:
    """Read a manifest JSON back into a `ShotManifest`.

    Raises:
        ValueError: when the file cannot be read, is not JSON, or a record is
            malformed. `verify` is a command about user input, so a truncated
            manifest is exit code 2 with the file name, not a traceback.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"manifest '{source}': file not found") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"manifest '{source}': not valid UTF-8") from exc
    except OSError as exc:
        raise ValueError(
            f"manifest '{source}': cannot read ({exc.strerror or exc})"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"manifest '{source}': invalid JSON at line {exc.lineno} "
            f"column {exc.colno}: {exc.msg}"
        ) from exc
    manifest = ShotManifest.from_dict(data)
    manifest.root = str(source.parent)
    return manifest


__all__ = ["read_manifest", "write_manifest"]
