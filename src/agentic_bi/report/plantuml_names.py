"""Stem sanitizing and ``@startuml`` header analysis for PlantUML artifacts.

PlantUML names every produced image after its ``@startuml <name>`` header, so
the header is the only link between a source block and its file. Two blocks can
declare the same header (the second image overwrites the first) and a header may
contain path separators or characters PlantUML renames on its own. This module
therefore rewrites unsafe or duplicate headers to unique markers in source
order, keeping the result stable and collision-free.

Public API:
    - :func:`safe_stem` - a filesystem-safe, bounded artifact stem
    - :func:`prepare_source` - unique headers plus the names to expect
    - :func:`order_produced` - produced files in source order, nothing dropped
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Windows refuses these device names, with or without an extension.
#: ``COM0``/``LPT0`` are deliberately absent: Windows documents ``COM1`` -
#: ``COM9`` and ``LPT1`` - ``LPT9`` as reserved, while port zero is not a
#: standard device name and the OS accepts it as a regular file name.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_MAX_STEM = 100
_HASH_LEN = 8

_SAFE_HEADER = re.compile(r"^[A-Za-z0-9_]+$")
_START_LINE = re.compile(r"^(\s*)@startuml\b(.*)$")
_LITERAL_OPEN = re.compile(r"^\s*(note|legend|header|footer)\b", re.IGNORECASE)
_LITERAL_CLOSE = re.compile(r"^\s*end\s*(note|legend|header|footer)\b", re.IGNORECASE)
_NOTE_AS = re.compile(r"\bas\b", re.IGNORECASE)


@dataclass(frozen=True)
class PreparedSource:
    """Rewritten PlantUML source and one expected image name per block."""

    text: str
    names: tuple[str, ...]


def safe_stem(name: str, fallback: str = "diagram") -> str:
    """Reduce `name` to a bare file stem that cannot escape an output directory.

    A path separator or ``..`` would otherwise let a caller write outside
    `out_dir`. The rule is: keep the last path component and replace every
    character that is not a Unicode word character, a dot or a hyphen with
    ``_``, so ``"Отчёт 2024"`` becomes ``"Отчёт_2024"`` instead of losing its
    non-ASCII part. The stem is bounded to ``_MAX_STEM`` characters (a short
    content hash keeps truncated names unique), Windows device names (``CON``,
    ``NUL``, ``COM1`` ...) get a logged ``_`` prefix, and an empty result falls
    back to `fallback`, then to ``"diagram"``.
    """
    stem = re.sub(r"[^\w.-]", "_", Path(name).name).strip("._")
    if not stem:
        stem = re.sub(r"[^\w.-]", "_", fallback).strip("._")
    if not stem:
        return "diagram"
    if len(stem) > _MAX_STEM:
        digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:_HASH_LEN]
        stem = f"{stem[: _MAX_STEM - _HASH_LEN - 1]}-{digest}"
    if stem.split(".", 1)[0].upper() in _RESERVED_NAMES:
        logger.warning(
            "Diagram name %r is a reserved Windows device; using %r", stem, f"_{stem}"
        )
        stem = f"_{stem}"
    return stem


def _opens_literal_block(line: str) -> bool:
    """True when `line` starts a multi-line note/legend/header/footer block."""
    match = _LITERAL_OPEN.match(line)
    if match is None:
        return False
    if match.group(1).lower() != "note":
        return True
    if ":" in line:
        return False
    return not ('"' in line and _NOTE_AS.search(line))


def _scan_headers(lines: list[str]) -> list[tuple[int, str, str]]:
    """``(line index, indent, header)`` for real ``@startuml`` lines only."""
    occurrences: list[tuple[int, str, str]] = []
    inside = False
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if inside:
            if _LITERAL_CLOSE.match(body):
                inside = False
            continue
        if _opens_literal_block(body):
            inside = True
            continue
        match = _START_LINE.match(body)
        if match is not None:
            occurrences.append((index, match.group(1), match.group(2).strip()))
    return occurrences


def _unique_marker(position: int, known: set[str]) -> str:
    """A marker name that no declared header already uses."""
    candidate = f"__dg_{position}"
    while candidate in known:
        candidate = f"_{candidate}"
    return candidate


def prepare_source(puml_text: str) -> PreparedSource:
    """Rewrite every ``@startuml`` header to a unique, safe output name.

    A header is rewritten when it is unnamed, when it contains anything outside
    ``[A-Za-z0-9_]``, or when an earlier block already declared it. Rewriting a
    duplicate is what keeps the second diagram from silently overwriting the
    first: PlantUML 1.2025.4 writes one file per unique header. The returned
    ``names`` tuple keeps source order, so the caller always binds the primary
    image to the first block.
    """
    lines = puml_text.splitlines(keepends=True)
    occurrences = _scan_headers(lines)
    known = {header for _, _, header in occurrences if header}
    seen: set[str] = set()
    names: list[str] = []
    for position, (index, indent, header) in enumerate(occurrences, start=1):
        name = header
        reason = ""
        if not name:
            reason = "empty"
        elif _SAFE_HEADER.match(name) is None:
            reason = "unsafe"
        elif name in seen:
            reason = "duplicate"
        if reason:
            name = _unique_marker(position, known)
            known.add(name)
            if reason == "duplicate":
                logger.warning(
                    "Duplicate @startuml header %r; block %d renders as %r",
                    header,
                    position,
                    name,
                )
            else:
                logger.debug(
                    "@startuml header %r is %s; block %d renders as %r",
                    header,
                    reason,
                    position,
                    name,
                )
        seen.add(name)
        names.append(name)
        ending = lines[index][len(lines[index].rstrip("\r\n")) :]
        lines[index] = f"{indent}@startuml {name}{ending}"
    return PreparedSource("".join(lines), tuple(names))


def order_produced(
    produced: list[Path], names: tuple[str, ...], work: Path
) -> list[Path]:
    """Order `produced` by source order, appending anything no header named.

    Matching is by the path relative to `work` (not by stem), so ``a/b.png`` and
    ``b.png`` are distinct. Every produced file is returned: a file that matches
    no header is appended alphabetically after a warning instead of being
    dropped, and the accounting invariant is checked explicitly.
    """
    root = work.resolve()
    remaining = list(produced)
    ordered: list[Path] = []
    for name in names:
        wanted = f"{name}.png"
        for position, path in enumerate(remaining):
            try:
                relative = path.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            if relative == wanted:
                ordered.append(remaining.pop(position))
                break
    if remaining:
        leftovers = sorted(remaining, key=lambda item: item.name)
        logger.warning(
            "PlantUML produced %d file(s) that no @startuml header names: %s",
            len(leftovers),
            ", ".join(item.name for item in leftovers),
        )
        ordered.extend(leftovers)
    if len(ordered) != len(produced):
        logger.error(
            "PlantUML output accounting mismatch: %d ordered vs %d produced",
            len(ordered),
            len(produced),
        )
    return ordered
