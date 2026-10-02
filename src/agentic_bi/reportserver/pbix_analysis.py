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

logger = logging.getLogger(__name__)

from agentic_bi.reportserver.diagnostics import NegotiateSession, load_config  # noqa: E402



from agentic_bi.reportserver.diagnostics import NegotiateSession, load_config  # noqa: E402
from agentic_bi.reportserver.pbix_index import IndexMixin  # noqa: E402


def _slug(path: str) -> str:
    s = path.replace("\\", "/").rsplit("/", 1)[-1]
    s = re.sub(r'[^\w\-.]+', "_", s, flags=re.UNICODE).strip("_")
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
            params = {"$filter": f"startswith(Path,'{root}')", "$top": 1000, "$select": "*"}
            r = self.net.get(f"https://{self.server}{self.base}{self.api}/CatalogItems", params)
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
            keep = [it for it in reports
                    if any(k.lower() in it["Name"].lower() for k in self.only_filter)]
            dropped = len(reports) - len(keep)
            logger.info("Batch --only filter: %d of %d left (%d dropped)",
                        len(keep), len(reports), dropped)
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
                results.append({"root": item["root"], "name": item["Name"],
                                "path": item["Path"], "error": "download_failed"})
                continue
            logger.info("[%d/%d] %s %.1f MB", i, len(reports),
                        item["Name"], dest.stat().st_size / 1e6)
            try:
                res = self.analyze(dest)
                res.update({"root": item["root"], "path": item["Path"], "name": item["Name"]})
                per.parent.mkdir(parents=True, exist_ok=True)
                per.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                results.append(res)
            except Exception as e:  # noqa: BLE001
                logger.error("analysis %s: %s", item["Name"], e)
                results.append({"root": item["root"], "name": item["Name"],
                                "path": item["Path"], "error": str(e)})
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
            root_key = "/" + root_dir.name if not root_dir.name.startswith("/") else root_dir.name
            for pbix in sorted(root_dir.glob("*.pbix")):
                stem = pbix.stem
                try:
                    res = self.analyze(pbix)
                    res["root"] = root_key
                    id8 = stem.split("_")[-1]
                    res["name"] = id2name.get(id8) or (stem.rsplit("_", 1)[0] if "_" in stem else stem)
                    # the server path (Report Server folder) matters more than the file name
                    res["path"] = id2path.get(id8) or pbix.name
                    per = self.report_out / _slug(root_key) / f"{stem}.json"
                    per.parent.mkdir(parents=True, exist_ok=True)
                    per.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str),
                                   encoding="utf-8")
                    results.append(res)
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    logger.error("reanalyze %s: %s", pbix.name, e)
                    results.append({"root": root_key, "name": pbix.stem, "error": str(e)})
        return ok, results

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    p = argparse.ArgumentParser(description="Analyze .pbix from a Power BI Report Server")
    p.add_argument("--roots", nargs="*", default=None)
    p.add_argument("--only", nargs="*", default=None,
                   help="download/analyze only boards whose name contains any of the strings (batch filter)")
    p.add_argument("--limit", type=int, default=None, help="limit the number of reports (test)")
    p.add_argument("--skip-antipatterns", action="store_true", help="do not compute antipatterns")
    p.add_argument("--keep-pbix", action="store_true",
                   help="keep downloaded .pbix in <out>/sources_pbix/<root>/ (otherwise delete)")
    p.add_argument("--reanalyze-local", action="store_true",
                   help="re-analyze saved local .pbix (without a server) and refresh indexes")
    p.add_argument("--rebuild-index", action="store_true",
                   help="rebuild indexes (index.json + drill_index.json) from ready board JSONs")
    args = p.parse_args(argv)

    b = PbiRsBulk()
    b.skip_ap = args.skip_antipatterns
    b.keep_pbix = args.keep_pbix
    b.only_filter = args.only

    if args.rebuild_index:
        results = b.load_board_results()
        b.save_drill(results)
        idx = b.finalize(results)
        print(f"Indexes rebuilt from {len(results)} boards:\n  {idx}\n  {b.drill_path()}")
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
    print(f"Total analyzed: {sum(1 for r in results if 'error' not in r)} of {len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())