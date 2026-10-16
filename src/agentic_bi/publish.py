"""Publish a `.pbix` to a Power BI Report Server (PBIRS) via REST API v2.0.

Authentication notes:
    - A custom `NegotiateSession` only allowed reads; writes failed with 500.
    - `HttpNegotiateAuth` (requests-negotiate-sspi) grants full authorization:
      POST /api/v2.0/CatalogItems with base64 content returns 201.

Create/update endpoint:
    POST /api/v2.0/CatalogItems
        {"@odata.type":"#Model.PowerBIReport","Name":..., "Path":...,
         "Type":"PowerBIReport","Content":<base64 bytes>,"ContentType":...}

Server host, base path and target folder are NOT hardcoded: pass them via the
`cfg` dict (server/base_path/api_prefix/timeout).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _client(server: str, verify: bool = False):
    """Create a requests session with Negotiate authentication (HttpNegotiateAuth)."""
    import requests
    import urllib3
    from requests_negotiate_sspi import HttpNegotiateAuth

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
    session.verify = verify
    session.auth = HttpNegotiateAuth()
    session.headers.update({"Accept": "application/json"})
    return session, server


def _server_name(report_name: str) -> str:
    """Server-side name: PBIRS stores .pbix without the extension."""
    name = report_name.strip()
    if name.lower().endswith(".pbix"):
        name = name[:-5]
    return name


def publish_pbix(
    pbix_path: Path,
    report_name: str,
    folder_path: str,
    cfg: dict | None = None,
) -> dict:
    """Publish a .pbix into a folder on the Report Server.

    Args:
        pbix_path: path to the .pbix.
        report_name: report name on the server (without the .pbix extension).
        folder_path: target folder path, e.g. `/Target/Folder`.
        cfg: config (server/base_path/api_prefix/timeout). Otherwise defaults.

    Returns:
        A dict from the response (Id, Name, Path, ...).
    """
    _cfg_defaults = {
        "server": "",
        "base_path": "/reportserver",
        "api_prefix": "/api/v2.0",
        "timeout": 300,
    }
    if cfg:
        _cfg_defaults.update({k: v for k, v in cfg.items() if v is not None})
    cfg = _cfg_defaults

    server = cfg["server"]
    if not server:
        raise ValueError("publish_pbix: 'server' is required in cfg")
    base = cfg["base_path"]
    api = cfg["api_prefix"]
    timeout = cfg.get("timeout", 300)

    session, host = _client(server, verify=False)
    base_url = f"https://{host}{base}{api}/CatalogItems"

    data_bytes = pbix_path.read_bytes()
    server_name = _server_name(report_name)
    server_path = f"{folder_path.rstrip('/')}/{server_name}"

    payload = {
        "@odata.type": "#Model.PowerBIReport",
        "Name": server_name,
        "Path": server_path,
        "Type": "PowerBIReport",
        "Content": base64.b64encode(data_bytes).decode(),
        "ContentType": "application/octet-stream",
    }

    # If the item already exists, overwrite via PUT (otherwise 409).
    existing = None
    try:
        r_get = session.get(f"{base_url}(Path='{server_path}')", timeout=timeout)
        if r_get.status_code == 200:
            existing = r_get.json()
    except Exception:  # noqa: BLE001
        existing = None

    if existing and existing.get("Id"):
        item_id = existing["Id"]
        logger.info("PUT %s(%s) (name='%s')", base_url, item_id, server_name)
        resp = session.put(f"{base_url}({item_id})", json=payload, timeout=timeout)
    else:
        logger.info("POST %s (name='%s')", base_url, server_name)
        resp = session.post(base_url, json=payload, timeout=timeout)

    if resp.status_code in (200, 201, 202, 204):
        logger.info(
            "Published '%s' to '%s' (HTTP %s)",
            server_name,
            folder_path,
            resp.status_code,
        )
        stripped = resp.text.strip()
        if resp.status_code == 204 or not stripped:
            return {"status": resp.status_code, "path": server_path}
        try:
            data = resp.json()
            # Do not return the base64 content (huge output).
            if isinstance(data, dict):
                data.pop("Content", None)
                data.pop("ContentType", None)
            return data
        except Exception:  # noqa: BLE001
            return {"status": resp.status_code, "text": resp.text[:500]}
    logger.error("Publish failed: HTTP %s %s", resp.status_code, resp.text[:500])
    return {"status": resp.status_code, "text": resp.text[:500]}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    import argparse

    parser = argparse.ArgumentParser(description="Publish a .pbix to a Report Server")
    parser.add_argument("pbix", help="path to the .pbix file")
    parser.add_argument("--name", required=True, help="report name on the server")
    parser.add_argument("--folder", required=True, help="target folder path")
    parser.add_argument("--server", default="", help="server host (required)")
    parser.add_argument("--base-path", default="/reportserver", help="base path")
    parser.add_argument("--api-prefix", default="/api/v2.0", help="API prefix")
    args = parser.parse_args()

    res = publish_pbix(
        Path(args.pbix),
        args.name,
        args.folder,
        cfg={
            "server": args.server,
            "base_path": args.base_path,
            "api_prefix": args.api_prefix,
        },
    )
    print(res)


if __name__ == "__main__":
    main()
