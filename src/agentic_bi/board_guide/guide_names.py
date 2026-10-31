"""Page names -> safe, unique file stems (stdlib only).

`Report/Layout` page names are untrusted text: they may contain path
separators, punctuation, non-Latin letters, be absurdly long, or differ only by
case. This module turns them into stems that are safe on any filesystem and
still unique per page, so `guide_<stem>.html` and `page_<stem>.png` never
silently overwrite each other.

Public API:
    safe_name(name) -> str
    unique_stems_for_names(names) -> list[str]
    unique_stems(pages) -> list[str]
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

_UNSAFE_RE = re.compile(r"[^\w-]+", re.UNICODE)
# A filename component is capped at 255 bytes on the common filesystems; keep a
# generous margin for the `page_`/`guide_` prefix and the `.png`/`.html` suffix.
_MAX_STEM_BYTES = 120


@runtime_checkable
class HasStem(Protocol):
    """Anything that can name the file stem of a page (a `GuidePage`)."""

    @property
    def stem(self) -> str:  # pragma: no cover - structural protocol
        ...


def safe_name(name: str) -> str:
    """A filesystem-safe stem for a page name.

    Letters and digits of any script are kept (a Cyrillic page keeps a readable
    stem instead of collapsing to a constant), while every path separator and
    punctuation character becomes `_`. An empty result becomes `page`.

    A very long name is truncated on a character boundary and gets a short
    content hash, so the stem stays well under the 255-byte filename limit
    instead of making the final `guide_<stem>.html` path fail with `OSError`.

    Note that this mapping is not injective: `"A/B"`, `"A B"` and `"A_B"` all
    give `"A_B"`. Use `unique_stems` when two pages must not share a file name.
    """
    cleaned = _UNSAFE_RE.sub("_", name.strip()).strip("_") or "page"
    if len(cleaned.encode("utf-8")) > _MAX_STEM_BYTES:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        room = _MAX_STEM_BYTES - len(digest) - 1
        head = cleaned.encode("utf-8")[:room].decode("utf-8", "ignore")
        cleaned = f"{head}-{digest}"
    return cleaned


def unique_stems_for_names(names: Iterable[str]) -> list[str]:
    """One unique stem per name, in order.

    Two names that sanitize alike get a `-2`, `-3`, ... suffix. Every candidate
    is checked against every stem already emitted, so a suffix can never collide
    with a page that was itself named like the suffix (`"A_B"` next to
    `"A_B-2"`), and the check is case-insensitive so `"Sales"` and `"sales"` do
    not map to one file on a case-insensitive filesystem (the macOS default).
    """
    used: set[str] = set()
    out: list[str] = []
    for name in names:
        base = safe_name(name)
        stem = base
        count = 1
        while stem.casefold() in used:
            count += 1
            stem = f"{base}-{count}"
        used.add(stem.casefold())
        out.append(stem)
    return out


def unique_stems(pages: Sequence[HasStem]) -> list[str]:
    """One unique file stem per page, in page order.

    `safe_name` may map two different page names to the same stem, which would
    make `page_<stem>.png` and `guide_<stem>.html` overwrite each other. Every
    consumer of the stem (`build_guide`, `capture_pages`) must derive it from the
    **full** page list, so the screenshot lookup and the emitted file names
    cannot drift apart.
    """
    return unique_stems_for_names([page.stem for page in pages])


__all__ = ["HasStem", "safe_name", "unique_stems", "unique_stems_for_names"]
