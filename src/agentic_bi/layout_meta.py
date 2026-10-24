"""Shared knowledge about a Power BI `Report/Layout`.

Two facts are needed by every consumer of a layout (verification, static
validation, web clone, rebuild) and must not drift apart:

1. `Report/Layout` is UTF-16LE **without BOM** in files written by Desktop, but a
   layout that was re-exported by another tool or hand-edited may be UTF-8. A
   decoder must sniff the bytes instead of assuming one encoding.
2. Some visuals are decorative: `textbox`, `shape`, `image`, `pageNavigator` and
   friends legitimately carry no data projections. Treating "no projections" as
   an error for them makes every real report look broken.

Public API:
    DECORATIVE_VISUAL_TYPES               - visual types that need no projections
    decode_layout(raw)                    -> dict
    decode_layout_with_encoding(raw)      -> (dict, encoding)
    iter_layout_visuals(layout)           -> (page, singleVisual, container)
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Decorative/static visuals that legitimately carry no data projections. Kept
# here (not in a checks module) so the static validator, the `.pbix` verifier and
# the web clone agree on one list.
DECORATIVE_VISUAL_TYPES = frozenset(
    {
        "textbox",
        "image",
        "shape",
        "basicShape",
        "rectangle",
        "actionButton",
        "bookmarkNavigator",
        "pageNavigator",
        "qnaVisual",
        "groupContainer",
        "shapeMap",
        "aiNarratives",
    }
)

_ENCODINGS = ("utf-8-sig", "utf-8")


def decode_layout_with_encoding(raw: bytes) -> tuple[dict, str]:
    """Decode `Report/Layout` bytes by sniffing the encoding.

    Returns the parsed layout and the encoding name it was read as, so a caller
    that re-writes the member can preserve the original encoding. Raises
    `ValueError` when no candidate decodes to JSON.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "utf-16be" if raw.startswith(b"\xfe\xff") else "utf-16le"
        return json.loads(raw.decode("utf-16")), enc
    if len(raw) > 1 and raw[1] == 0:  # UTF-16LE without BOM
        return json.loads(raw.decode("utf-16-le")), "utf-16le"
    for enc in _ENCODINGS:
        try:
            return json.loads(raw.decode(enc)), enc
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError("cannot decode Report/Layout")


def decode_layout(raw: bytes) -> dict:
    """Decode `Report/Layout` bytes to a dict (encoding is sniffed)."""
    return decode_layout_with_encoding(raw)[0]


def iter_layout_visuals(layout: dict):
    """Yield `(page_name, singleVisual, container)` over the layout's containers.

    The layout is untrusted: a container without `config`, a `config` that is not
    JSON, or a `singleVisualGroup` (no `singleVisual`) must not raise. Such
    containers are skipped, the rest are yielded with an empty `singleVisual`.
    """
    for section in layout.get("sections", []) or []:
        page = section.get("displayName")
        for container in section.get("visualContainers", []) or []:
            raw = container.get("config")
            if not raw:
                continue
            try:
                cfg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            except (ValueError, TypeError) as exc:
                logger.debug("container config invalid on %s: %s", page, exc)
                continue
            if not isinstance(cfg, dict):
                continue
            yield page, cfg.get("singleVisual") or {}, container


__all__ = [
    "DECORATIVE_VISUAL_TYPES",
    "decode_layout",
    "decode_layout_with_encoding",
    "iter_layout_visuals",
]
