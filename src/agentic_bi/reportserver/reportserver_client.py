"""Report Server client glue: config loading and a Negotiate HTTP session.

Optional dependencies (`requests`/`spnego`) are imported lazily so this module can
be imported for configuration/introspection without the `server` extra installed.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

logger = logging.getLogger(__name__)

# Optional dependencies (the `server` extra). `TYPE_CHECKING` keeps the real
# module types for the checker while the runtime binding stays `None` until
# `_require_server_deps` imports them on first use.
if TYPE_CHECKING:
    import requests
    import spnego
    import urllib3
else:  # pragma: no cover - exercised through `_require_server_deps`
    requests = None
    spnego = None
    urllib3 = None


def _require_server_deps() -> None:
    """Import the Report Server HTTP/auth dependencies on first use."""
    global requests, spnego, urllib3
    if requests is not None:
        return
    try:
        import requests
        import spnego
        import urllib3
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Report Server access needs the 'server' extra: "
            "pip install 'agentic-bi-framework[server]'"
        ) from exc
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _bad_config(key: str, expected: str, value: object) -> ValueError:
    return ValueError(
        f"reportserver: config field '{key}': expected {expected}, "
        f"got {type(value).__name__}"
    )


def config_str(cfg: Mapping[str, object], key: str, default: str) -> str:
    """Read a string config value; a mistyped value is a `ValueError`, not a crash."""
    value = cfg.get(key, default)
    if not isinstance(value, str):
        raise _bad_config(key, "string", value)
    return value


def config_float(cfg: Mapping[str, object], key: str, default: float) -> float:
    """Read a numeric config value (a bool is not a number here)."""
    value = cfg.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad_config(key, "number", value)
    return float(value)


def config_bool(cfg: Mapping[str, object], key: str, default: bool) -> bool:
    """Read a boolean config value."""
    value = cfg.get(key, default)
    if not isinstance(value, bool):
        raise _bad_config(key, "boolean", value)
    return value


def config_str_list(cfg: Mapping[str, object], key: str) -> list[str]:
    """Read a list-of-strings config value (an empty list when absent)."""
    value = cfg.get(key, [])
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise _bad_config(key, "a list of strings", value)
    return list(value)


CONFIG_FILE = Path(__file__).resolve().parent / "reportserver_diagnostics_config.json"

# catalog type -> diagnosed entity sets (OData REST API v2.0)
ITEM_DETAILS = {
    "PowerBIReport": ["PowerBIReports", "Reports"],
    "Report": ["Reports"],
    "Folder": ["Folders", "PowerBIReports", "Reports", "Resources"],
    "Resource": ["Resources"],
    "DataSource": ["DataSources"],
    "DataSet": ["DataSets"],
    "LinkedReport": ["LinkedReports"],
}


def load_config() -> dict[str, object]:
    """Load the configuration; on absence/error use defaults."""
    defaults: dict[str, object] = {
        "server": "",
        "base_path": "/reportserver",
        "api_prefix": "/api/v2.0",
        "roots": ["/Reports"],
        "include_hidden": True,
        "deep_links": [
            "PowerBIReports",
            "Reports",
            "Folders",
            "Resources",
            "DataSources",
            "DataSets",
            "Subscriptions",
            "Schedules",
            "FavoriteItems",
        ],
        "output_dir": "output_files/rs_diagnostics",
        "json_prefix": "pbi_rs",
        "include_root_in_name": True,
        "timeout": 60,
    }
    if not CONFIG_FILE.exists():
        logger.warning("Config not found: %s, using defaults", CONFIG_FILE)
        return defaults
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning(
                "Config %s is not a JSON object (%s), using defaults",
                CONFIG_FILE,
                type(data).__name__,
            )
            return defaults
        merged = dict(defaults)
        merged.update({k: v for k, v in data.items() if v is not None})
        return merged
    except json.JSONDecodeError as e:
        logger.warning("Invalid config %s: %s, using defaults", CONFIG_FILE, e)
        return defaults


def _sanitize(name: str, limit: int = 60) -> str:
    s = "".join(c if c.isalnum() or c in "-_." else "_" for c in name).strip("_")
    return s[:limit].rstrip(".") or "root"


def build_json_name(root_path: str, cfg: Mapping[str, object] | None = None) -> str:
    """JSON name: <prefix>_[<root>]_<YYYYMMDD_HHMMSS>.json."""
    config = cfg if cfg is not None else load_config()
    prefix = config_str(config, "json_prefix", "pbi_rs")
    parts = [prefix]
    if config.get("include_root_in_name", True) and root_path:
        parts.append(_sanitize(root_path))
    parts.append(datetime.now().strftime("%Y%m%d_%H%M%S"))
    return "_".join(parts) + ".json"


def result_out_path(root_path: str) -> Path:
    cfg = load_config()
    out_dir = Path(config_str(cfg, "output_dir", "output_files/rs_diagnostics"))
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / build_json_name(root_path, cfg)


class SpnegoContext(Protocol):
    """The slice of `spnego` context this client uses."""

    def step(self, in_token: bytes | None = None) -> bytes | None: ...


class NegotiateSession:
    """A requests.Session authenticating via Negotiate (Windows-integrated).

    Recreates the spnego context on each call with a challenge (the context is
    consumed after the handshake completes in Windows SSPI).
    """

    def __init__(self, host: str, verify: bool = False, timeout: float = 60.0) -> None:
        _require_server_deps()
        self.host = host
        self.session = requests.Session()
        self.session.verify = verify
        self.session.headers.update({"Accept": "application/json"})
        self.timeout = timeout

    def _new_ctx(self) -> SpnegoContext:
        return spnego.client(host=self.host, service="HTTP", protocol="negotiate")

    def request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> requests.Response:
        ctx = self._new_ctx()
        in_token: bytes | None = None
        resp: requests.Response | None = None
        for _ in range(4):
            try:
                out = ctx.step(in_token)
            except Exception:  # noqa: BLE001 - context already finished/broken
                ctx = self._new_ctx()
                _in = None
                out = ctx.step(_in)
                in_token = _in
            headers: dict[str, str] = {}
            if out:
                headers["Authorization"] = "Negotiate " + base64.b64encode(out).decode()
            resp = self.session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201, 202, 204, 301, 302):
                return resp
            challenge = resp.headers.get("WWW-Authenticate", "")
            if resp.status_code == 401 and challenge.lower().startswith("negotiate"):
                try:
                    in_token = base64.b64decode(challenge.split(" ", 1)[1])
                except Exception:  # noqa: BLE001 - a malformed token is not fatal
                    return resp
            else:
                return resp
        if resp is None or not bool(resp):
            # An error response is falsy (requests.Response.__bool__ == ok); the
            # historical behavior is to close the handshake with a HEAD probe.
            return self.session.head(url)
        return resp

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        return self.request("GET", url, params=params)

    def post(self, url: str, json_body: dict | None = None) -> requests.Response:
        return self.request("POST", url, json_body=json_body)
