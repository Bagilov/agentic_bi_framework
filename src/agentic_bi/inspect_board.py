"""Inspect a dashboard on a Power BI Report Server: download the .pbix and break it down.

Process: find the report by path -> download the .pbix (Negotiate) -> lineage via PbiLineage.

Reuses the existing orchestrator `agentic_bi.reportserver.pbix_analysis.PbiRsBulk`
(download + analysis) instead of duplicating its logic.

CLI:
    python -m agentic_bi.inspect_board --path "/Shared Reports/Self-service"
    python -m agentic_bi.inspect_board --path "/Reports/MyReport" --keep-pbix

The server host is read from the report-server config (see
`agentic_bi.reportserver.diagnostics`); no host is hardcoded here.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from agentic_bi.reportserver.odata import odata_quote
from agentic_bi.reportserver.pbix_analysis import PbiRsBulk

logger = logging.getLogger(__name__)

OUT_DIR = Path(__file__).resolve().parent / "output_files"


class PbirsPathError(RuntimeError):
    """The report was not found at the given path."""


class PbirsAccessError(RuntimeError):
    """No permission to download the .pbix content (403 on Content/$value)."""


def find_by_path(bulk: PbiRsBulk, path: str) -> dict:
    """Find a Power BI report by its exact path on the server.

    Args:
        bulk: the PbiRsBulk orchestrator (network + catalog).
        path: full report path, e.g. `/Shared Reports/Self-service`.

    Returns:
        The catalog item (dict with Id, Name, Path, Type...).

    Raises:
        PbirsPathError: if the report is not found at this path.
    """
    params = {
        "$filter": f"Path eq '{odata_quote(path)}' and Type eq 'PowerBIReport'",
        "$select": "*",
    }
    r = bulk.net.get(f"https://{bulk.server}{bulk.base}{bulk.api}/CatalogItems", params)
    if r.status_code != 200:
        raise PbirsAccessError(f"Catalog {path} -> HTTP {r.status_code}")
    items = r.json().get("value", [])
    if not items:
        raise PbirsPathError(f"Report not found at path: {path}")
    return items[0]


def download_report(bulk: PbiRsBulk, item: dict, dest: Path) -> Path:
    """Download the report .pbix; raises PbirsAccessError on 403."""
    iid = item.get("Id")
    if not iid:
        raise PbirsAccessError(
            f"Catalog item without an Id ({item.get('Path') or item.get('Name') or '?'})"
        )
    name = item.get("Name") or "report"
    url = (
        f"https://{bulk.server}{bulk.base}{bulk.api}"
        f"/catalogitems({odata_quote(iid)})/Content/$value"
    )
    r = bulk.net.request("GET", url)
    if r.status_code == 403:
        raise PbirsAccessError(
            f"No permission to download '{name}' (HTTP 403). "
            f"Content/$value is closed for the current user on {bulk.server}."
        )
    if r.status_code != 200 or not r.content:
        raise PbirsAccessError(f"Download '{name}' -> HTTP {r.status_code}")
    dest.write_bytes(r.content)
    return dest


def _thesis(lineage: dict, item: dict) -> dict:
    """Assemble the dashboard's thesis structure from lineage (PbiLineage.to_json())."""
    summary = lineage.get("summary", {})
    theses = {
        "name": item.get("Name"),
        "path": item.get("Path"),
        "analyzed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "pages": summary.get("pages", 0),
            "visuals": summary.get("visuals", 0),
            "tables": summary.get("tables", 0),
            "business_tables": summary.get("business_tables", 0),
            "technical_tables": summary.get("technical_tables", 0),
            "measures": summary.get("measures", 0),
            "calc_columns": summary.get("calc_columns", 0),
            "power_queries": summary.get("power_queries", 0),
            "sources_with_data": summary.get("sources_with_data", 0),
            "sources_access_error": summary.get("sources_access_error", 0),
            "sources_unresolved": summary.get("sources_unresolved", 0),
            "relationships": summary.get("relationships", 0),
        },
    }
    pages = lineage.get("pages", [])
    theses["pages"] = [
        {
            "index": p.get("index"),
            "name": p.get("name"),
            "n_visuals": p.get("n_visuals", 0),
            "n_bindings": p.get("n_bindings", 0),
            "tables": sorted(p.get("tables", [])),
            "visual_types": [v.get("type") for v in p.get("visuals", [])],
        }
        for p in pages
    ]
    theses["sources"] = lineage.get("sources", {})
    return theses


def inspect_board(path: str, keep_pbix: bool = False) -> dict:
    """Download a dashboard .pbix by path and return its elements (as a thesis).

    Args:
        path: full report path on the Report Server.
        keep_pbix: whether to keep the .pbix in output_files (otherwise a temp file).

    Returns:
        Dict: summary + pages + sources (the dashboard's thesis structure).

    Raises:
        PbirsPathError: path not found.
        PbirsAccessError: no permission / network error while downloading.
    """
    bulk = PbiRsBulk()
    item = find_by_path(bulk, path)

    out_dir = OUT_DIR / "inspect"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(str(item.get("Name") or "report")).stem
    pbix = out_dir / f"{stem}.pbix"

    logger.info("Downloading: %s (%s)", item.get("Name"), item.get("Path"))
    download_report(bulk, item, pbix)
    logger.info("Downloaded: %s (%.2f MB)", pbix.name, pbix.stat().st_size / 1e6)

    try:
        res = bulk.analyze(pbix)
    finally:
        if not keep_pbix and pbix.exists():
            pbix.unlink()

    return _thesis(res.get("lineage", {}), item)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(
        description="Inspect a Report Server dashboard: elements by path"
    )
    p.add_argument("--path", required=True, help="full report path on the server")
    p.add_argument(
        "--keep-pbix",
        action="store_true",
        help="keep the downloaded .pbix in output_files/inspect",
    )
    args = p.parse_args(argv)

    try:
        thesis = inspect_board(args.path, keep_pbix=args.keep_pbix)
    except (PbirsPathError, PbirsAccessError) as e:
        logger.error("%s", e)
        return 1

    print(json.dumps(thesis, ensure_ascii=False, indent=2))
    report = OUT_DIR / "inspect" / f"{Path(args.path).name}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(thesis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Saved: %s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
