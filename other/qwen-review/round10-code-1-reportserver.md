# Bundle 1: reportserver

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/reportserver/__init__.py ====================

"""Vendored Power BI Report Server access (generic, configurable)."""

==================== FILE: src/agentic_bi/reportserver/reportserver_client.py ====================

"""Report Server client glue: config loading and a Negotiate HTTP session.

Optional dependencies (`requests`/`spnego`) are imported lazily so this module can
be imported for configuration/introspection without the `server` extra installed.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Optional dependencies (the `server` extra). Imported lazily.
requests = None  # type: ignore
spnego = None  # type: ignore
urllib3 = None  # type: ignore


def _require_server_deps() -> None:
    """Import the Report Server HTTP/auth dependencies on first use."""
    global requests, spnego, urllib3
    if requests is not None:
        return
    try:
        import requests  # type: ignore
        import spnego  # type: ignore
        import urllib3  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Report Server access needs the 'server' extra: "
            "pip install 'agentic-bi-framework[server]'"
        ) from exc
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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


def load_config() -> dict:
    """Load the configuration; on absence/error use defaults."""
    defaults = {
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
        merged = dict(defaults)
        merged.update({k: v for k, v in data.items() if v is not None})
        return merged
    except json.JSONDecodeError as e:
        logger.warning("Invalid config %s: %s, using defaults", CONFIG_FILE, e)
        return defaults


def _sanitize(name: str, limit: int = 60) -> str:
    s = "".join(c if c.isalnum() or c in "-_." else "_" for c in name).strip("_")
    return s[:limit].rstrip(".") or "root"


def build_json_name(root_path: str, cfg: dict | None = None) -> str:
    """JSON name: <prefix>_[<root>]_<YYYYMMDD_HHMMSS>.json."""
    cfg = cfg or load_config()
    prefix = cfg.get("json_prefix", "pbi_rs")
    parts = [prefix]
    if cfg.get("include_root_in_name", True) and root_path:
        parts.append(_sanitize(root_path))
    parts.append(datetime.now().strftime("%Y%m%d_%H%M%S"))
    return "_".join(parts) + ".json"


def result_out_path(root_path: str) -> Path:
    cfg = load_config()
    out_dir = Path(cfg.get("output_dir"))
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / build_json_name(root_path, cfg)


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

    def _new_ctx(self):
        return spnego.client(host=self.host, service="HTTP", protocol="negotiate")

    def request(
        self, method: str, url: str, params: dict | None = None, **kwargs
    ) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        ctx = self._new_ctx()
        in_token = None
        resp = None
        for _ in range(4):
            try:
                out = ctx.step(in_token)
            except Exception:  # context already finished/broken - restart
                ctx = self._new_ctx()
                _in = None
                out = ctx.step(_in)
                in_token = _in
            headers = dict(kwargs.pop("headers", {}))
            if out:
                headers["Authorization"] = "Negotiate " + base64.b64encode(out).decode()
            resp = self.session.request(
                method, url, headers=headers, params=params, **kwargs
            )
            if resp.status_code in (200, 201, 202, 204, 301, 302):
                return resp
            challenge = resp.headers.get("WWW-Authenticate", "")
            if resp.status_code == 401 and challenge.lower().startswith("negotiate"):
                try:
                    in_token = base64.b64decode(challenge.split(" ", 1)[1])
                except Exception:
                    return resp
            else:
                return resp
        return resp or resp if resp else self.session.head(url)

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        return self.request("GET", url, params=params)

    def post(self, url: str, json_body: dict | None = None) -> requests.Response:
        return self.request("POST", url, json=json_body)

==================== FILE: src/agentic_bi/reportserver/diagnostics.py ====================

"""Diagnostics for Power BI Report Server dashboards via the OData REST API.

Runs diagnostics over all dashboards on a Power BI Report Server: it walks the
configured root catalogs (including hidden items) and collects per catalog item
the metadata, data sources and configured server objects (subscriptions,
schedules, favorites).

Authentication is Windows-integrated (Negotiate/NTLM via spnego + the current
Windows login; the host comes from the config).

This module is a **facade** over:
    reportserver_client.py - config loading + the Negotiate HTTP session

CLI:
    python -m agentic_bi.reportserver.diagnostics --roots /Reports /Shared
    python -m agentic_bi.reportserver.diagnostics --no-json

Results are written to `output_dir` from the config
(`reportserver_diagnostics_config.json`); if absent, use the CLI/config.
No host or network path is hardcoded.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from agentic_bi.reportserver.reportserver_client import (  # noqa: F401
    CONFIG_FILE,
    ITEM_DETAILS,
    NegotiateSession,
    _require_server_deps,
    _sanitize,
    build_json_name,
    load_config,
    result_out_path,
)

logger = logging.getLogger(__name__)


class ReportServerDiagnostics:
    """Diagnostics of the Power BI Report Server dashboard catalog via the OData API."""

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or load_config()
        self.base = self.cfg.get("base_path", "/reportserver")
        self.api = self.cfg.get("api_prefix", "/api/v2.0")
        self.net = NegotiateSession(
            host=self.cfg.get("server", ""), timeout=self.cfg.get("timeout", 60)
        )
        self.include_hidden = bool(self.cfg.get("include_hidden", True))

    def _api_url(
        self, entity: str, item_id: str | None = None, action: str | None = None
    ) -> str:
        path = f"{self.api}/{entity}"
        if item_id:
            path += f"('{item_id}')"
        if action:
            path += f"/{action}"
        return f"https://{self.cfg.get('server')}{self.base}{path}"

    def _get_json(self, url: str, params: dict | None = None) -> dict:
        r = self.net.get(url, params)
        if r.status_code == 200 and "json" in r.headers.get("Content-Type", ""):
            try:
                return r.json()
            except json.JSONDecodeError:
                return {}
        if r.status_code != 200:
            logger.debug("HTTP %s %s", r.status_code, url)
        return {}

    def _get_values(self, url: str, params: dict | None = None) -> list[dict]:
        j = self._get_json(url, params)
        if isinstance(j, dict):
            v = j.get("value")
            if isinstance(v, list):
                return v
            return [j]
        return []

    # --- catalog ----------------------------------------------------------
    def list_root_items(self, root: str) -> list[dict]:
        """All items under root (recursively, including nested folders)."""
        items: list[dict] = []
        params = {
            "$filter": f"startswith(Path,'{root}')",
            "$top": 1000,
            "$select": "*",
        }
        for it in self._get_values(self._api_url("CatalogItems"), params):
            if it.get("Hidden") and not self.include_hidden:
                continue
            items.append(it)
        return items

    def list_all_catalog(self) -> list[dict]:
        """The whole catalog (for entity-set summaries)."""
        return self._get_values(
            self._api_url("CatalogItems"), {"$top": 1000, "$select": "*"}
        )

    # --- detail by type ---------------------------------------------------
    def item_detail(self, item: dict) -> list[dict]:
        """Detailed objects by catalog type (PowerBIReports/Reports/Folders/...)."""
        out: list[dict] = []
        itype = item.get("Type") or ""
        entities = (ITEM_DETAILS.get(itype) or [])[:1]
        if not entities:
            return out
        iid = item.get("Id")
        if not iid:
            return out
        for ent in entities:
            vals = self._get_values(self._api_url(ent, iid))
            if vals:
                out.extend(vals)
        return out

    def entity_samples(self, entity: str, limit: int = 5) -> list[dict]:
        """Sample records of an entity set (for the type reference/summaries)."""
        return self._get_values(self._api_url(entity), {"$top": limit, "$select": "*"})

    # --- entity-set summaries ---------------------------------------------
    def entity_summary(self) -> dict:
        """Summary of configured server objects: subscriptions, schedules, favorites."""
        out: dict = {}
        for ent in self.cfg.get("deep_links", []):
            try:
                vals = self._get_values(
                    self._api_url(ent), {"$top": 500, "$select": "*"}
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Entity %s error: %s", ent, e)
                vals = []
            out[ent] = {"count": len(vals), "items": vals}
        return out

    # --- catalog summaries ------------------------------------------------
    @staticmethod
    def _summarize_items(root: str, items: list[dict]) -> dict:
        by_type = Counter(it.get("Type") or "Unknown" for it in items)
        hidden = [it for it in items if it.get("Hidden")]
        folders = [it for it in items if it.get("Type") == "Folder"]
        reports = [it for it in items if it.get("Type") in ("PowerBIReport", "Report")]
        return {
            "root": root,
            "total": len(items),
            "folders": len(folders),
            "reports_powerbi": sum(
                1 for it in items if it.get("Type") == "PowerBIReport"
            ),
            "reports_ssrs": sum(1 for it in items if it.get("Type") == "Report"),
            "hidden": len(hidden),
            "hidden_items": [
                {k: it.get(k) for k in ("Name", "Path", "Type", "Hidden")}
                for it in hidden
            ],
            "by_type": dict(by_type),
            "reports": [
                {
                    k: it.get(k)
                    for k in (
                        "Name",
                        "Path",
                        "Type",
                        "Hidden",
                        "Size",
                        "ModifiedDate",
                        "CreatedDate",
                    )
                }
                for it in reports
            ],
        }

    # --- run --------------------------------------------------------------
    def run(self, roots: list[str] | None = None) -> list[dict]:
        """Run diagnostics for each root. Returns results per root."""
        roots = roots or self.cfg.get("roots", [])
        results: list[dict] = []
        for root in roots:
            items = self.list_root_items(root)
            summary = self._summarize_items(root, items)
            details_by_type: dict[str, list[dict]] = defaultdict(list)
            for it in items:
                det = self.item_detail(it)
                if det:
                    details_by_type[it.get("Type") or "Unknown"].extend(det)
            entity_summary = self.entity_summary()
            result = {
                "root": root,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "config": {
                    "server": self.cfg.get("server"),
                    "base_url": f"https://{self.cfg.get('server')}{self.base}{self.api}",
                    "include_hidden": self.include_hidden,
                },
                "summary": summary,
                "items": items,
                "details_by_type": {k: v for k, v in details_by_type.items()},
                "server_objects": entity_summary,
            }
            results.append(result)
        return results

    def save(self, root: str, result: dict) -> Path:
        out = result_out_path(root)
        payload = {
            "generated_at": result["generated_at"],
            "root": root,
            **{k: v for k, v in result.items() if k != "root"},
        }
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("JSON saved: %s", out)
        return out


_diag: ReportServerDiagnostics | None = None


def diag() -> ReportServerDiagnostics:
    global _diag
    if _diag is None:
        _diag = ReportServerDiagnostics()
    return _diag


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    p = argparse.ArgumentParser(
        description="Diagnostics of Power BI Report Server dashboards"
    )
    p.add_argument(
        "--roots", nargs="*", default=None, help="root catalogs (default from config)"
    )
    p.add_argument("--no-json", action="store_true", help="do not save JSON results")
    p.add_argument("--filter", default=None, help="filter by catalog name (substring)")
    args = p.parse_args(argv)

    d = diag()
    roots = args.roots or None
    cfg_roots = d.cfg.get("roots", [])
    if roots:
        cfg_roots = roots
    if args.filter:
        cfg_roots = [r for r in cfg_roots if args.filter.lower() in r.lower()]

    try:
        results = d.run(cfg_roots)
        for res in results:
            root = res["root"]
            s = res["summary"]
            print(f"\n=== {root} ===")
            print(
                f"items: {s['total']} | folders: {s['folders']} | "
                f"Power BI: {s['reports_powerbi']} | SSRS: {s['reports_ssrs']} | "
                f"hidden: {s['hidden']}"
            )
            print("by type:", dict(s["by_type"]))
            if s["hidden_items"]:
                print("hidden items:")
                for h in s["hidden_items"]:
                    print("   ", h.get("Path"), f"[{h.get('Type')}]")
            if not args.no_json:
                path = d.save(root, res)
                print("JSON result:", path)
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error("Diagnostics failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

==================== FILE: src/agentic_bi/reportserver/pbix_analysis.py ====================

"""Bulk analysis of .pbix from a Power BI Report Server (download + lineage + antipatterns).

Downloads all Power BI reports from the configured Report Server roots (including
hidden ones) and runs analysis on each:
  - data lineage via `PbiLineage` (pages, visuals, tables, sources, JSON),
  - calculation antipatterns via `pbi_antipatterns.analyze_pbix`.

Results:
  - locally in `output_files/pbi_rs_pbix/<root>/` (lineage JSON + antipatterns + Excel),
  - a summary registry across ALL boards -> `<output_dir>/pbix_analysis/index.json`,
    where `output_dir` comes from `reportserver_diagnostics_config.json`.

Authentication is Windows-integrated Negotiate (spnego), no password.

CLI:
    python -m agentic_bi.reportserver.pbix_analysis --roots /Reports /Shared
    python -m agentic_bi.reportserver.pbix_analysis --only Report --skip-antipatterns
    python -m agentic_bi.reportserver.pbix_analysis --pbix-local "path.pbix"  # analyze a local file
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from agentic_bi.reportserver.diagnostics import NegotiateSession, load_config
from agentic_bi.reportserver.pbix_index import IndexMixin

logger = logging.getLogger(__name__)


def _slug(path: str) -> str:
    s = path.replace("\\", "/").rsplit("/", 1)[-1]
    s = re.sub(r"[^\w\-.]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:80].rstrip(".") or "board"


class PbiRsBulk(IndexMixin):
    """Orchestrator: catalog -> download .pbix -> lineage + antipatterns."""

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or load_config()
        self.server = self.cfg.get("server", "")
        self.base = self.cfg.get("base_path", "/reportserver")
        self.api = self.cfg.get("api_prefix", "/api/v2.0")
        self.net = NegotiateSession(host=self.server, timeout=300)
        self.report_out = Path(self.cfg.get("output_dir")) / "pbix_analysis"
        self.skip_ap = False
        self.keep_pbix = False
        self.only_filter: list[str] | None = None

    # --- catalog ----------------------------------------------------------
    def list_powerbi(self, roots: list[str]) -> list[dict]:
        items: list[dict] = []
        for root in roots:
            params = {
                "$filter": f"startswith(Path,'{root}')",
                "$top": 1000,
                "$select": "*",
            }
            r = self.net.get(
                f"https://{self.server}{self.base}{self.api}/CatalogItems", params
            )
            if r.status_code != 200:
                logger.warning("Catalog %s -> HTTP %s", root, r.status_code)
                continue
            for it in r.json().get("value", []):
                if it.get("Type") == "PowerBIReport":
                    if it.get("Hidden") and not self.cfg.get("include_hidden", True):
                        continue
                    items.append({"root": root, **it})
        return items

    # --- download ---------------------------------------------------------
    def download(self, item: dict, dest: Path) -> Path | None:
        """Download the .pbix via catalogitems(id)/Content/$value."""
        iid = item["Id"]
        url = f"https://{self.server}{self.base}{self.api}/catalogitems({iid})/Content/$value"
        r = self.net.request("GET", url)
        if r.status_code != 200 or not r.content:
            logger.warning("Download %s -> HTTP %s", item["Name"], r.status_code)
            return None
        dest.write_bytes(r.content)
        return dest

    # --- analyze one file -------------------------------------------------
    def analyze(self, pbix: Path) -> dict:
        from agentic_bi.lineage.pbi_lineage import PbiLineage

        with PbiLineage(str(pbix)) as lg:
            lineage = lg.to_json()

        result = {
            "file": pbix.name,
            "path": str(pbix),
            "analyzed_at": datetime.now().isoformat(timespec="seconds"),
            "lineage": lineage,
        }
        if not self.skip_ap:
            try:
                from agentic_bi.antipatterns.pbi_antipatterns import analyze_pbix

                ap = analyze_pbix(str(pbix))
                result["antipatterns"] = ap
            except Exception as e:  # noqa: BLE001
                logger.warning("Antipatterns %s: %s", pbix.name, e)
        return result

    # --- aggregation ------------------------------------------------------
    def run(self, roots: list[str], limit: int | None = None) -> list[dict]:
        self.report_out.mkdir(parents=True, exist_ok=True)
        reports = self.list_powerbi(roots)
        if self.only_filter:
            keep = [
                it
                for it in reports
                if any(k.lower() in it["Name"].lower() for k in self.only_filter)
            ]
            dropped = len(reports) - len(keep)
            logger.info(
                "Batch --only filter: %d of %d left (%d dropped)",
                len(keep),
                len(reports),
                dropped,
            )
            reports = keep
        if limit:
            reports = reports[:limit]
        logger.info("Power BI reports found: %d", len(reports))

        results: list[dict] = []
        done = self.already_done()
        for i, item in enumerate(reports, 1):
            stem = f"{_slug(item['Name'])}_{item['Id'][:8]}"
            per = self.report_out / _slug(item["root"]) / f"{stem}.json"
            if stem in done:
                try:
                    results.append(json.loads(per.read_text(encoding="utf-8")))
                except Exception:  # noqa: BLE001
                    pass
                continue
            if self.keep_pbix:
                pbix_dir = self.report_out / "sources_pbix" / _slug(item["root"])
                pbix_dir.mkdir(parents=True, exist_ok=True)
                pbix = pbix_dir / f"{stem}.pbix"
            else:
                pbix = self.report_out / "pbix_tmp" / f"{stem}.pbix"
                pbix.parent.mkdir(parents=True, exist_ok=True)
            dest = self.download(item, pbix)
            if not dest:
                results.append(
                    {
                        "root": item["root"],
                        "name": item["Name"],
                        "path": item["Path"],
                        "error": "download_failed",
                    }
                )
                continue
            logger.info(
                "[%d/%d] %s %.1f MB",
                i,
                len(reports),
                item["Name"],
                dest.stat().st_size / 1e6,
            )
            try:
                res = self.analyze(dest)
                res.update(
                    {"root": item["root"], "path": item["Path"], "name": item["Name"]}
                )
                per.parent.mkdir(parents=True, exist_ok=True)
                per.write_text(
                    json.dumps(res, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                results.append(res)
            except Exception as e:  # noqa: BLE001
                logger.error("analysis %s: %s", item["Name"], e)
                results.append(
                    {
                        "root": item["root"],
                        "name": item["Name"],
                        "path": item["Path"],
                        "error": str(e),
                    }
                )
            finally:
                if not self.keep_pbix and dest.exists():
                    dest.unlink()
        return results

    def already_done(self) -> set[str]:
        """Names of already-analyzed boards (to resume an interrupted run)."""
        done: set[str] = set()
        if self.report_out.exists():
            for json_file in self.report_out.glob("*/[!_]*.json"):
                done.add(json_file.stem)
        return done

    def reanalyze_local(self, keep_dir: Path) -> tuple[int, list[dict]]:
        """Re-analyze local .pbix files (without a server), rewriting the board JSON.

        Useful after a schema change (`to_json`) - to refresh source fields
        (path/type) and rebuild a fresh drill index without re-downloading.

        Args:
            keep_dir: the saved-sources directory (sources_pbix/<root>).

        Returns:
            (number of successes, results)
        """
        ok = 0
        results: list[dict] = []
        # maps id(8) -> displayed name and server path from the catalog
        id2name: dict[str, str] = {}
        id2path: dict[str, str] = {}
        for item in self.list_powerbi(self.cfg.get("roots", [])):
            id2name[item["Id"][:8]] = item["Name"]
            id2path[item["Id"][:8]] = item.get("Path")
        for root_dir in sorted(keep_dir.iterdir()) if keep_dir.exists() else []:
            if not root_dir.is_dir():
                continue
            root_key = (
                "/" + root_dir.name
                if not root_dir.name.startswith("/")
                else root_dir.name
            )
            for pbix in sorted(root_dir.glob("*.pbix")):
                stem = pbix.stem
                try:
                    res = self.analyze(pbix)
                    res["root"] = root_key
                    id8 = stem.split("_")[-1]
                    res["name"] = id2name.get(id8) or (
                        stem.rsplit("_", 1)[0] if "_" in stem else stem
                    )
                    # the server path (Report Server folder) matters more than the file name
                    res["path"] = id2path.get(id8) or pbix.name
                    per = self.report_out / _slug(root_key) / f"{stem}.json"
                    per.parent.mkdir(parents=True, exist_ok=True)
                    per.write_text(
                        json.dumps(res, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                    results.append(res)
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    logger.error("reanalyze %s: %s", pbix.name, e)
                    results.append(
                        {"root": root_key, "name": pbix.stem, "error": str(e)}
                    )
        return ok, results


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    p = argparse.ArgumentParser(
        description="Analyze .pbix from a Power BI Report Server"
    )
    p.add_argument("--roots", nargs="*", default=None)
    p.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="download/analyze only boards whose name contains any of the strings (batch filter)",
    )
    p.add_argument(
        "--limit", type=int, default=None, help="limit the number of reports (test)"
    )
    p.add_argument(
        "--skip-antipatterns", action="store_true", help="do not compute antipatterns"
    )
    p.add_argument(
        "--keep-pbix",
        action="store_true",
        help="keep downloaded .pbix in <out>/sources_pbix/<root>/ (otherwise delete)",
    )
    p.add_argument(
        "--reanalyze-local",
        action="store_true",
        help="re-analyze saved local .pbix (without a server) and refresh indexes",
    )
    p.add_argument(
        "--rebuild-index",
        action="store_true",
        help="rebuild indexes (index.json + drill_index.json) from ready board JSONs",
    )
    args = p.parse_args(argv)

    b = PbiRsBulk()
    b.skip_ap = args.skip_antipatterns
    b.keep_pbix = args.keep_pbix
    b.only_filter = args.only

    if args.rebuild_index:
        results = b.load_board_results()
        b.save_drill(results)
        idx = b.finalize(results)
        print(
            f"Indexes rebuilt from {len(results)} boards:\n  {idx}\n  {b.drill_path()}"
        )
        return 0

    if args.reanalyze_local:
        keep_dir = b.report_out / "sources_pbix"
        ok, results = b.reanalyze_local(keep_dir)
        b.save_drill(results)
        idx = b.finalize(results)
        print(f"Re-analyzed locally: {ok} boards\n  {idx}\n  {b.drill_path()}")
        return 0

    roots = args.roots or b.cfg.get("roots", [])
    results = b.run(roots, args.limit)
    b.save_drill(results)
    idx = b.finalize(results)
    print(f"\nSummary index: {idx}")
    print(f"Drill index: {b.drill_path()}")
    print(
        f"Total analyzed: {sum(1 for r in results if 'error' not in r)} of {len(results)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

==================== FILE: src/agentic_bi/reportserver/pbix_index.py ====================

"""Summary/index building mixin for the Report Server bulk analysis."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class IndexMixin:
    def build_index(self, results: list[dict]) -> dict:
        """Summary registry across all boards (for index.json)."""
        rows = []
        for res in results:
            if "error" in res:
                rows.append(
                    {
                        "root": res.get("root"),
                        "name": res.get("name"),
                        "path": res.get("path"),
                        "error": res.get("error"),
                    }
                )
                continue
            lin = res.get("lineage", {})
            summary = lin.get("summary", {})
            ap = res.get("antipatterns", {})
            ap_summary = ap.get("summary", {})
            brand = lin.get("brand", {}).get("summary", {}) or {}
            rows.append(
                {
                    "root": res.get("root", ""),
                    "name": res.get("name"),
                    "path": res.get("path"),
                    "pages": summary.get("pages", 0),
                    "visuals": summary.get("visuals", 0),
                    "tables_total": summary.get("tables", 0),
                    "tables_business": summary.get("business_tables", 0),
                    "measures": summary.get("measures", 0),
                    "calc_columns": summary.get("calc_columns", 0),
                    "power_queries": summary.get("power_queries", 0),
                    "sources": summary.get("sources", 0),
                    "sources_with_data": summary.get("sources_with_data", 0),
                    "antipatterns_total": ap_summary.get("total_findings", 0),
                    "antipatterns_critical": ap_summary.get("critical", 0),
                    "brand_fonts_pct": brand.get("fonts_compliance"),
                    "brand_colors_pct": brand.get("colors_compliance"),
                    "brand_ok_pages": brand.get("ok", 0),
                    "brand_warning_pages": brand.get("warnings", 0),
                    "brand_error_pages": brand.get("errors", 0),
                    "analyzed_at": res.get("analyzed_at"),
                }
            )
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "boards": rows,
            "n": len(rows),
        }

    # --- main run ---------------------------------------------------------
    def finalize(self, results: list[dict]) -> Path:
        idx = self.report_out / "index.json"
        idx.write_text(
            json.dumps(self.build_index(results), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return idx

    def drill_path(self) -> Path:
        return self.report_out / "drill_index.parquet"

    def save_drill(self, results: list[dict]) -> Path:
        """Save a flat drill index to Parquet (one row per element).
        Extraction from ready boards: for each element (source/table/measure/
        page/finding) a separate row is generated, enriched with board values.
        Reads well in Power BI."""
        try:
            import pandas as pd
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as e:  # noqa: BLE001
            logger.error("pyarrow is not installed - parquet unavailable (%s)", e)
            raise

        rows = self._drill_rows(results)
        out = self.drill_path()
        if rows:
            df = pd.DataFrame(rows)
            for col in df.columns:
                try:
                    df[col] = pd.to_numeric(df[col], errors="ignore")
                except Exception:  # noqa: BLE001
                    pass
            table = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_table(table, out, compression="snappy")
        else:
            pd.DataFrame().to_parquet(out, engine="pyarrow")
        logger.info("Drill parquet saved: %s (rows %d)", out, len(rows))
        return out

    def _drill_rows(self, results: list[dict]) -> list[dict]:
        """Flat drill rows: one row per board element."""
        rows: list[dict] = []
        run_at = datetime.now().isoformat(timespec="seconds")

        # a single set of all antipatterns - so has_* flags exist on EVERY board
        # (0 when absent, not NaN) and the dashboard can filter by one metric.
        all_ids: set[str] = set()
        for res in results:
            if "error" in res:
                continue
            all_ids.update(
                (res.get("antipatterns", {}).get("summary", {}) or {}).get("by_id", {})
                or {}
            )

        def base(res: dict) -> dict:
            lin = res.get("lineage", {})
            summary = lin.get("summary", {})
            ap = res.get("antipatterns", {})
            asum = ap.get("summary", {})
            bsum = lin.get("brand", {}).get("summary", {}) or {}
            by_id = asum.get("by_id", {}) or {}
            # server placement path on the Report Server: /<root>/<folder...>/<Name>
            srv = res.get("path") or ""
            is_server = srv.startswith("/")
            folder = srv.rsplit("/", 1)[0] if is_server else None
            depth = srv.count("/") if is_server else 0
            d = {
                "board": res.get("name"),
                "root": res.get("root"),
                "board_path": res.get("path"),
                "board_server_path": srv if is_server else None,  # full server path
                "board_folder": folder,  # placement folder (without the report name)
                "board_folder_depth": depth,  # folder nesting depth
                "analyzed_at": res.get(
                    "analyzed_at"
                ),  # when the board itself was analyzed
                "index_built_at": run_at,  # when this drill index was built
                "board_pages": summary.get("pages", 0),
                "board_visuals": summary.get("visuals", 0),
                "board_tables_total": summary.get("tables", 0),
                "board_tables_business": summary.get("business_tables", 0),
                "board_measures": summary.get("measures", 0),
                "board_calc_columns": summary.get("calc_columns", 0),
                "board_sources": summary.get("sources_with_data", 0),
                "board_ap_total": asum.get("total_findings", 0),
                "board_ap_critical": asum.get("critical", 0),
                "board_brand_fonts": bsum.get("fonts_compliance"),
                "board_brand_colors": bsum.get("colors_compliance"),
                "board_brand_errors": bsum.get("errors", 0),
            }
            # presence flags of specific antipatterns on the board (0/1).
            # set for ALL known ap_id - 0 if the pattern is absent.
            for aid in all_ids:
                d[f"has_{aid}"] = 1 if by_id.get(aid, 0) > 0 else 0
            return d

        for res in results:
            if "error" in res:
                rows.append(
                    {
                        "board": res.get("name"),
                        "root": res.get("root"),
                        "level": "board",
                        "error": res.get("error"),
                        "analyzed_at": res.get("analyzed_at"),
                        "index_built_at": run_at,
                    }
                )
                continue
            b = base(res)
            lin = res.get("lineage", {})
            ap = res.get("antipatterns", {})
            # --- sources ---
            for t, s in lin.get("sources", {}).get("by_table", {}).items():
                rows.append(
                    {
                        **b,
                        "level": "source",
                        "element": t,
                        "source_type": s.get("type"),
                        "source_path": s.get("path"),
                        "source_detail": s.get("detail"),
                        "status": s.get("status"),
                    }
                )
            # --- tables ---
            for t, tb in lin.get("tables", {}).items():
                rows.append(
                    {
                        **b,
                        "level": "table",
                        "element": t,
                        "technical": tb.get("technical"),
                        "columns": tb.get("columns_count", 0),
                        "measures": tb.get("measures_count", 0),
                        "source_type": (tb.get("source") or {}).get("type"),
                        "source_path": (tb.get("source") or {}).get("path"),
                        "table_refs": tb.get("refs", 0),
                    }
                )
            # --- measures ---
            for t, sem in lin.get("semantics", {}).items():
                for m in sem.get("measures", []):
                    mname = m.get("name") if isinstance(m, dict) else m
                    rows.append(
                        {
                            **b,
                            "level": "measure",
                            "element": mname,
                            "table": t,
                            "measure_refs": m.get("refs")
                            if isinstance(m, dict)
                            else None,
                        }
                    )
            # --- pages ---
            for pg in lin.get("pages", []):
                bm = pg.get("brand") or {}
                rows.append(
                    {
                        **b,
                        "level": "page",
                        "element": pg.get("name"),
                        "page_index": pg.get("index"),
                        "page_visuals": pg.get("n_visuals", 0),
                        "page_refs": pg.get("refs", 0),
                        "page_tables": ", ".join(pg.get("tables", [])),
                        "page_brand_fonts": (bm.get("fonts") or {}).get("compliance"),
                        "page_brand_colors": (bm.get("colors") or {}).get("compliance"),
                        "page_brand_status": bm.get("level"),
                        "page_brand_has_red": (bm.get("colors") or {}).get("has_red"),
                    }
                )
            # --- antipattern findings ---
            for lvl, findings in ap.get("findings", {}).items():
                for f in findings:
                    rows.append(
                        {
                            **b,
                            "level": f"ap_{f.get('level', lvl)}",
                            "element": f.get("scope"),
                            "ap_id": f.get("id"),
                            "ap_name": f.get("name"),
                            "ap_critical": f.get("critical"),
                            "ap_detail": f.get("detail"),
                            "ap_fix": f.get("fix"),
                        }
                    )
        return rows

    # --- drill-down index -------------------------------------------------

    def load_board_results(self) -> list[dict]:
        """Load ready board JSONs from report_out (to rebuild indexes)."""
        results = []
        for sub in self.report_out.iterdir():
            if not sub.is_dir() or sub.name in ("pbix_tmp", "sources_pbix"):
                continue
            for jf in sub.glob("*.json"):
                try:
                    results.append(json.loads(jf.read_text(encoding="utf-8")))
                except json.JSONDecodeError as e:  # noqa: BLE001
                    logger.warning("skip %s: %s", jf, e)
        return results

