"""OData v2 record walking for the Report Server REST API.

An OData collection response is `{"value": [...]}` and may carry an
`@odata.nextLink` when the result is larger than the requested `$top` page. A
caller that reads only the first page silently truncates a large catalog, so the
walk must follow `nextLink` to the end — with a guard against a server that points
back at a page it already served.

A single-entity response (`CatalogItems(id)`) is the object itself, not wrapped in
`value`; it is returned as one record.

Public API:
    odata_quote(value) -> str
    walk_values(fetch_json, url, params=None, paginate=True) -> list[dict]
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

FetchJson = Callable[..., dict]


def odata_quote(value: object) -> str:
    """Escape a string literal for an OData `'...'` filter/parameter.

    OData escapes an embedded single quote by doubling it; an unescaped quote
    would terminate the literal early, breaking the request or injecting extra
    filter syntax. Used for every `$filter` and path literal.
    """
    return str(value).replace("'", "''")


def walk_values(
    fetch_json: FetchJson,
    url: str,
    params: dict | None = None,
    paginate: bool = True,
) -> list[dict]:
    """Read the records of an OData entity set.

    Args:
        fetch_json: a callable `(url, params) -> dict` returning the parsed JSON
            of one page (an empty dict on any error).
        url: the first page URL.
        params: query parameters for the first request only (the `nextLink`
            already carries the full query string).
        paginate: follow `@odata.nextLink`; pass False for a bounded sample.

    Returns:
        The records in server order (an empty list when nothing was read).
    """
    out: list[dict] = []
    next_url: str | None = url
    next_params: dict | None = params
    seen: set[str] = set()
    while next_url:
        j = fetch_json(next_url, next_params)
        if isinstance(j, dict):
            value = j.get("value")
            # A collection page carries `value`; a single-item response is the
            # object itself.
            out.extend(value if isinstance(value, list) else [j])
            link = j.get("@odata.nextLink")
        else:
            link = None
        if not paginate or not isinstance(link, str) or link in seen:
            break
        seen.add(link)
        next_url, next_params = link, None
    return out


__all__ = ["odata_quote", "walk_values"]
