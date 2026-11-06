"""Atomic publishing of PlantUML artifacts into a caller's output directory.

The renderer writes images into a private temporary directory, which may live on
a different filesystem than ``out_dir`` (``/tmp`` on tmpfs is the normal case on
Linux). Nothing is ever copied straight onto a final path: every image is first
staged inside ``out_dir`` itself, so the last rename is same-device and atomic
and a failure mid-copy leaves the previous artifact intact.

A hidden manifest records which files this tool created. A later run removes
only its own stale suffixes, so ``--out-dir .`` can never delete an unrelated
``lineage_2.png`` that the user created.

Public API:
    - :func:`export_puml` - atomic UTF-8/LF ``.puml`` write
    - :func:`publish_artifacts` - stage, rename and clean produced PNGs
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_MANIFEST_VERSION = 1
_FILE_MODE = 0o644


def manifest_path(out_dir: Path, stem: str) -> Path:
    """Hidden manifest that lists the artifacts this tool created for `stem`."""
    return out_dir / f".{stem}-artifacts.json"


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _target_mode(target: Path) -> int:
    """Keep an existing file's mode, otherwise use the documented ``0644``."""
    try:
        return target.stat().st_mode & 0o777
    except OSError:
        return _FILE_MODE


def export_puml(puml_text: str, path: str | Path) -> Path:
    """Write ``puml_text`` to ``path`` atomically and return the written path.

    The source is written to a short-named temporary file in the destination
    directory and renamed over ``path`` with :func:`os.replace`. A failed write
    therefore never leaves a half-written ``.puml`` behind: readers see either
    the previous complete file or the new complete one, never a truncated mix.

    The temporary name is derived from a hash of the target name, so it stays
    under the filesystem name limit even when the target name is maximal. The
    published file keeps the mode of an existing target, or gets ``0644`` for a
    new one; the process umask is never read or changed, so concurrent callers
    cannot race on it. The content is flushed and fsynced, and written with
    ``newline="\\n"``: the bytes are identical on every platform.

    Args:
        puml_text: the PlantUML source to persist.
        path: destination ``.puml`` path; its parent directory is created.

    Returns:
        The destination path, after the atomic rename succeeded.

    Raises:
        OSError: when the text cannot be written or renamed into place. The
            temporary file is removed in that case.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{_short_hash(target.name)}-",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(name)
    open_fd = fd
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(open_fd, _target_mode(target))
        handle = os.fdopen(open_fd, "w", encoding="utf-8", newline="\n")
        open_fd = -1
        with handle:
            handle.write(puml_text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        if open_fd >= 0:
            os.close(open_fd)
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def _stage(source: Path, out_dir: Path, stem: str) -> Path:
    """Copy `source` into a temporary file inside `out_dir`."""
    fd, name = tempfile.mkstemp(
        prefix=f".{stem}-{_short_hash(source.name)}-",
        suffix=".tmp",
        dir=str(out_dir),
    )
    stage = Path(name)
    open_fd = fd
    try:
        with os.fdopen(open_fd, "wb") as handle:
            open_fd = -1
            with source.open("rb") as reader:
                shutil.copyfileobj(reader, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(stage, _FILE_MODE)
        return stage
    except BaseException:
        if open_fd >= 0:
            os.close(open_fd)
        stage.unlink(missing_ok=True)
        raise


def _artifact_pattern(stem: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(stem)}(?:_\d+)?\.png$")


def _write_manifest(out_dir: Path, stem: str, names: list[str]) -> None:
    """Atomically replace the artifact manifest with `names`."""
    target = manifest_path(out_dir, stem)
    payload = {"version": _MANIFEST_VERSION, "artifacts": names}
    fd, name = tempfile.mkstemp(
        prefix=f".{_short_hash(target.name)}-",
        suffix=".tmp",
        dir=str(out_dir),
    )
    temp = Path(name)
    open_fd = fd
    try:
        handle = os.fdopen(open_fd, "w", encoding="utf-8", newline="\n")
        open_fd = -1
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, _FILE_MODE)
        os.replace(temp, target)
    except BaseException:
        if open_fd >= 0:
            os.close(open_fd)
        temp.unlink(missing_ok=True)
        raise


def _read_manifest(out_dir: Path, stem: str) -> list[str] | None:
    """Recorded artifact names, or None when the manifest is absent/unusable."""
    path = manifest_path(out_dir, stem)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable diagram manifest %s: %s", path.name, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("Ignoring malformed diagram manifest %s", path.name)
        return None
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        logger.warning("Ignoring malformed diagram manifest %s", path.name)
        return None
    names: list[str] = []
    for item in artifacts:
        if not isinstance(item, str):
            logger.warning("Ignoring malformed diagram manifest %s", path.name)
            return None
        names.append(item)
    return names


def _stale_candidates(out_dir: Path, stem: str, fresh: set[str]) -> list[str]:
    """``<stem>_<k>.png`` files (k >= 2) that this run did not just write."""
    pattern = re.compile(rf"^{re.escape(stem)}_(\d+)\.png$")
    found: list[str] = []
    try:
        entries = list(out_dir.iterdir())
    except OSError:
        return found
    for candidate in entries:
        match = pattern.match(candidate.name)
        if match is None or int(match.group(1)) < 2 or candidate.name in fresh:
            continue
        found.append(candidate.name)
    return found


def _remove_stale_targets(
    out_dir: Path, stem: str, fresh: set[str], recorded: list[str] | None
) -> None:
    """Remove only artifacts recorded in the manifest and no longer produced."""
    if recorded is None:
        candidates = _stale_candidates(out_dir, stem, fresh)
        if candidates:
            logger.warning(
                "No artifact manifest for %r; leaving %s untouched because they "
                "may belong to the user",
                stem,
                ", ".join(sorted(candidates)),
            )
        return
    pattern = _artifact_pattern(stem)
    for name in recorded:
        if name in fresh or pattern.match(name) is None:
            continue
        if Path(name).name != name:
            continue
        try:
            (out_dir / name).unlink()
        except FileNotFoundError:
            continue
        except OSError:
            logger.debug("Could not remove stale diagram %s", name)


def publish_artifacts(sources: list[Path], out_dir: Path, stem: str) -> list[Path]:
    """Publish `sources` as ``<stem>.png``, ``<stem>_2.png`` ... in order.

    Every source is first copied into a staging file inside `out_dir`; only then
    are the staging files renamed over their targets, with the primary target
    renamed last so a failure cannot replace the primary with a partial set.
    Staging files are removed and stale manifest entries are cleaned in a
    ``finally`` block, whatever the outcome.

    Returns:
        The target paths in source order.

    Raises:
        OSError: when staging, renaming or the manifest write fails. Published
            targets are never truncated: each rename moves a complete stage.
    """
    targets = [
        out_dir / (f"{stem}.png" if index == 0 else f"{stem}_{index + 1}.png")
        for index in range(len(sources))
    ]
    previous = _read_manifest(out_dir, stem)
    staged: list[Path] = []
    try:
        for source in sources:
            staged.append(_stage(source, out_dir, stem))
        for index in [*range(1, len(staged)), 0]:
            os.replace(staged[index], targets[index])
        _write_manifest(out_dir, stem, [target.name for target in targets])
        return targets
    finally:
        for stage in staged:
            stage.unlink(missing_ok=True)
        _remove_stale_targets(
            out_dir, stem, {target.name for target in targets}, previous
        )
