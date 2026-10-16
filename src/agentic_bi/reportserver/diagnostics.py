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
