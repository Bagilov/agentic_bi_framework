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

Known zone outside the perimeter: what the portal reports here is served by the
portal's own metadata database (catalog, access grants, execution logs,
favorites). That database is not part of this solution and is not present in our
environment; which engine backs it, its schema and its credentials are specific
to a concrete installation. This module therefore consumes only the public OData
API and never queries that database directly, and no table, schema, SQL or
connection detail belongs in this codebase.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from agentic_bi.cli_support import run_boundary
from agentic_bi.reportserver.odata import odata_quote, walk_values
from agentic_bi.reportserver.reportserver_client import (  # noqa: F401
    CONFIG_FILE,
    ITEM_DETAILS,
    NegotiateSession,
    _require_server_deps,
    _sanitize,
    build_json_name,
    config_bool,
    config_float,
    config_str,
    config_str_list,
    load_config,
    result_out_path,
)

logger = logging.getLogger(__name__)


# Size exception (>300 lines): the catalog walk, its summary and the CLI are one
# report; the summary fields are derived from the walk and keeping them apart
# hid a "0 items" that meant "the server refused the request".


class ReportServerDiagnostics:
    """Diagnostics of the Power BI Report Server dashboard catalog via the OData API."""

    def __init__(self, cfg: dict[str, object] | None = None) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self.base = config_str(self.cfg, "base_path", "/reportserver")
        self.api = config_str(self.cfg, "api_prefix", "/api/v2.0")
        self.net = NegotiateSession(
            host=config_str(self.cfg, "server", ""),
            timeout=config_float(self.cfg, "timeout", 60.0),
        )
        self.include_hidden = config_bool(self.cfg, "include_hidden", True)
        #: URLs that could not be read during the current `run()`; a non-empty
        #: list means the catalog was only partly visible.
        self.fetch_errors: list[str] = []

    def _api_url(
        self, entity: str, item_id: str | None = None, action: str | None = None
    ) -> str:
        path = f"{self.api}/{entity}"
        if item_id:
            path += f"('{odata_quote(item_id)}')"
        if action:
            path += f"/{action}"
        return f"https://{self.cfg.get('server')}{self.base}{path}"

    def _get_json(self, url: str, params: dict | None = None) -> dict | None:
        """One page of JSON, or None when it cannot be read.

        `None` (not `{}`) is the failure signal: an empty dict is a legitimate
        body shape, so returning it on a 401/500 made `walk_values` report the
        failed root as one item of type `Unknown` and every entity set as
        `count: 1`. The failure is also recorded, so `run()` can report it and
        the CLI can exit non-zero instead of claiming a clean, empty server.
        """
        r = self.net.get(url, params)
        if r.status_code == 200 and "json" in r.headers.get("Content-Type", ""):
            try:
                return r.json()
            except json.JSONDecodeError:
                logger.warning(
                    "HTTP 200 but the body is not JSON (%s): %s",
                    r.headers.get("Content-Type"),
                    url,
                )
                self.fetch_errors.append(f"{url}: body is not JSON")
                return None
        if r.status_code != 200:
            logger.warning("HTTP %s for %s", r.status_code, url)
            self.fetch_errors.append(f"{url}: HTTP {r.status_code}")
        else:
            logger.warning(
                "Non-JSON response (%s) for %s", r.headers.get("Content-Type"), url
            )
            self.fetch_errors.append(f"{url}: non-JSON response")
        return None

    def _get_values(
        self, url: str, params: dict | None = None, paginate: bool = True
    ) -> list[dict]:
        """Records of an entity set, following `@odata.nextLink` (see `odata.py`)."""
        return walk_values(self._get_json, url, params, paginate)

    # --- catalog ----------------------------------------------------------
    def list_root_items(self, root: str) -> list[dict]:
        """All items under root (recursively, including nested folders)."""
        items: list[dict] = []
        params = {
            "$filter": f"startswith(Path,'{odata_quote(root)}')",
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
        return self._get_values(
            self._api_url(entity), {"$top": limit, "$select": "*"}, paginate=False
        )

    # --- entity-set summaries ---------------------------------------------
    def entity_summary(self) -> dict:
        """Summary of configured server objects: subscriptions, schedules, favorites."""
        out: dict = {}
        for ent in config_str_list(self.cfg, "deep_links"):
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
        """Run diagnostics for each root. Returns results per root.

        A root that could not be read carries its failures in `fetch_errors`
        both per result and in the summary count, so "0 items" is never
        indistinguishable from "the server refused the request".
        """
        roots = roots or config_str_list(self.cfg, "roots")
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
            errors = list(self.fetch_errors)
            self.fetch_errors.clear()
            summary = {**summary, "errors": len(errors)}
            result = {
                "root": root,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "config": {
                    "server": self.cfg.get("server"),
                    "base_url": f"https://{self.cfg.get('server')}{self.base}{self.api}",
                    "include_hidden": self.include_hidden,
                },
                "summary": summary,
                "fetch_errors": errors,
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


def _body(args: argparse.Namespace) -> int:
    """Command body: resolve the config, run the diagnostics, print per root."""
    d = diag()
    roots = args.roots or None
    cfg_roots = config_str_list(d.cfg, "roots")
    if roots:
        cfg_roots = roots
    if args.filter:
        cfg_roots = [r for r in cfg_roots if args.filter.lower() in r.lower()]

    try:
        results = d.run(cfg_roots)
    except Exception as e:  # noqa: BLE001 - a server failure is the result
        logger.error("Diagnostics failed: %s", e)
        return 1
    failed = 0
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
        for err in res["fetch_errors"]:
            print(f"read error: {err}", file=sys.stderr)
        if res["fetch_errors"]:
            failed += 1
            print(
                f"warning: {root}: {len(res['fetch_errors'])} request(s) could not "
                "be read; the counts above cover only the visible part",
                file=sys.stderr,
            )
        if s["hidden_items"]:
            print("hidden items:")
            for h in s["hidden_items"]:
                print("   ", h.get("Path"), f"[{h.get('Type')}]")
        if not args.no_json:
            path = d.save(root, res)
            print("JSON result:", path)
    # A partly unreadable server is a negative result, not a clean run: exit 0
    # used to be returned for a 401 as well, with `total: 1` invented by the
    # failure-as-record bug in `walk_values`.
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; a bad configuration is exit 2 with one stderr line."""
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
    return run_boundary(lambda: _body(args), prog="agentic-bi-server")


if __name__ == "__main__":
    sys.exit(main())
