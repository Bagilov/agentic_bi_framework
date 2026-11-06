"""Validation of the OData catalog responses (untrusted HTTP/JSON).

The Report Server returns whatever the deployment has: a normal
`{"value": [...]}` page, a single entity, an error body or a truncated document.
The bulk analysis dereferences every item (`Id`, `Type`, `Path`), so the shape is
checked once here — a malformed response is a `ValueError` naming the catalog
root, never an `AttributeError` on a list or a `KeyError` on an item.

Public API:
    catalog_values(payload, root) -> list[dict]
    item_str(item, key) -> str
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def catalog_values(payload: object, root: str) -> list[dict]:
    """The `value` list of an OData catalog response, validated before use.

    Args:
        payload: the decoded JSON body (`dict` for a collection page).
        root: the catalog root, used in the error message.

    Returns:
        The object items of the page (non-object entries are skipped with a
        warning, they cannot be catalog items).

    Raises:
        ValueError: the body is not an object, or `value` is not a list.
    """
    if not isinstance(payload, dict):
        raise ValueError(
            f"catalog {root}: expected a JSON object, got {type(payload).__name__}"
        )
    value = payload.get("value")
    if not isinstance(value, list):
        raise ValueError(
            f"catalog {root}: expected a 'value' list, got {type(value).__name__}"
        )
    items: list[dict] = []
    for raw in value:
        if not isinstance(raw, dict):
            logger.warning(
                "Catalog %s: skipping a non-object item (%s)",
                root,
                type(raw).__name__,
            )
            continue
        items.append(raw)
    return items


def item_str(item: dict, key: str) -> str:
    """Read a catalog item field as a string (`""` when absent or mistyped)."""
    value = item.get(key)
    return value if isinstance(value, str) else ""


def slug(path: str) -> str:
    """A filesystem-safe stem from a server path/name (`board` when empty)."""
    s = path.replace("\\", "/").rsplit("/", 1)[-1]
    s = re.sub(r"[^\w\-.]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:80].rstrip(".") or "board"


__all__ = ["catalog_values", "item_str", "slug"]
