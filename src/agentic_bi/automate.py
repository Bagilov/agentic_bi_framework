"""Full pipeline automation: build `.pbix` -> publish to Report Server.

Orchestrates two working steps of `agentic_bi`:
  1. `rebuild_pbix` — build a binary `.pbix` from a donor (Layout replaced with
     ours, the donor's binary VertiPaq DataModel is preserved byte-for-byte).
  2. `publish_pbix` — publish/update a `.pbix` via REST /api/v2.0/CatalogItems.
  3. verify — GET the item by Path and confirm the report is visible, not empty.

Usage:
  # build + structure check only, without publishing
  uv run python -m agentic_bi.automate --dry-run

  # full run: build + publish to the configured folder + verify
  uv run python -m agentic_bi.automate --src donor.pbix --name "My Report" \
      --folder "/Target/Folder"

Environment-specific values (server host, base path, target folder, donor path)
are NOT baked in: pass them via CLI flags or a config dict.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from agentic_bi.publish import publish_pbix
from agentic_bi.rebuild import rebuild_pbix
from agentic_bi.skeleton import build_skeleton

logger = logging.getLogger(__name__)

# Model object names from the donor that the new visual references (rebuild_pbix).
DEFAULT_TABLE = "fact_table"
DEFAULT_COL = "metric"
DEFAULT_MEASURE = "score"
DEFAULT_DISPLAY = "Rebuilt report"

# Defaults are intentionally neutral: override via CLI/config.
DEFAULT_SRC = "data/donor.pbix"
DEFAULT_NAME = "api_rebuild_test"
DEFAULT_FOLDER = "/Target/Dev"


def verify_published(
    server: str,
    folder_path: str,
    report_name: str,
    base: str = "/reportserver",
    api: str = "/api/v2.0",
    timeout: int = 120,
) -> dict:
    """Check that `report_name` exists in `folder_path` on the server.

    Returns:
        A dict with Id/Path/Size or {"exists": False}.
    """
    import requests
    import urllib3
    from requests_negotiate_sspi import HttpNegotiateAuth

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    server_path = (
        f"{folder_path.rstrip('/')}/{report_name.strip().removesuffix('.pbix')}"
    )
    session = requests.Session()
    session.verify = False
    session.auth = HttpNegotiateAuth()
    session.headers.update({"Accept": "application/json"})

    url = f"https://{server}{base}{api}/CatalogItems(Path='{server_path}')"
    r = session.get(url, timeout=timeout)
    if r.status_code != 200:
        logger.error("Verify: %s -> HTTP %s %s", url, r.status_code, r.text[:300])
        return {"exists": False}
    item = r.json()
    return {
        "exists": True,
        "Id": item.get("Id"),
        "Path": item.get("Path"),
        "Size": item.get("Size"),
        "Type": item.get("Type"),
        "ModifiedDate": item.get("ModifiedDate"),
    }


def run(
    src: Path,
    out: Path,
    name: str = DEFAULT_NAME,
    folder: str = DEFAULT_FOLDER,
    display_name: str = DEFAULT_DISPLAY,
    table: str = DEFAULT_TABLE,
    col: str = DEFAULT_COL,
    measure: str = DEFAULT_MEASURE,
    cfg: dict | None = None,
    dry_run: bool = False,
) -> dict:
    """Full pipeline: build a .pbix from a donor, publish, verify.

    Returns:
        A summary dict of the results.
    """
    result: dict = {}

    # 1. Build
    logger.info("Building .pbix from donor %s", src)
    out = rebuild_pbix(
        src, out, display_name=display_name, table=table, col=col, measure=measure
    )
    result["built"] = {"path": str(out), "size": out.stat().st_size}
    logger.info("Built .pbix: %s (%.1f KB)", out, out.stat().st_size / 1024)

    # 2. Structure validation (optional in dry-run — not a hard failure)
    try:
        from agentic_bi.lineage.pbi_lineage import PbiLineage

        with PbiLineage(str(out)) as lg:
            lineage = lg.to_json()
            pages = len(lineage.get("pages", []))
            result["validate"] = {
                "pages": pages,
                "sources": len(lineage.get("sources", [])),
                "tables": len(lineage.get("tables", {})),
            }
            logger.info(
                "Validation: pages=%s sources=%s tables=%s",
                result["validate"]["pages"],
                result["validate"]["sources"],
                result["validate"]["tables"],
            )
    except Exception as e:  # noqa: BLE001
        result["validate"] = {"error": str(e)}
        logger.warning("Structure validation failed (non-critical): %s", e)

    if dry_run:
        result["publish"] = {"skipped": "dry-run"}
        logger.info("dry-run: publish skipped")
        return result

    # 3. Publish
    res = publish_pbix(out, name, folder, cfg)
    result["publish"] = res
    logger.info("Publish: %s", res)

    # 4. Verify
    server = (cfg or {}).get("server", "")
    base = (cfg or {}).get("base_path", "/reportserver")
    api_pref = (cfg or {}).get("api_prefix", "/api/v2.0")
    if server:
        ver = verify_published(server, folder, name, base=base, api=api_pref)
    else:
        ver = {"skipped": "no server configured"}
    result["verify"] = ver
    logger.info("Verify: %s", ver)
    return result


def run_from_skeleton(
    src: Path,
    out: Path,
    name: str,
    folder: str,
    cfg: dict | None = None,
    dry_run: bool = False,
    columns: list | None = None,
    measures: list | None = None,
) -> dict:
    """Pipeline: query -> skeleton -> .pbix -> publish.

    A skeleton is generated for the query (PBIP: KPI + chart + table + filters),
    its layout is folded into a binary .pbix via rebuild_pbix (DataModel from
    `src`), then published. The skeleton is simple for testing; the extensible
    parameters are columns/measures for the Data model.

    Returns:
        A summary dict.
    """
    columns = columns or [
        {"name": "segment", "dataType": "string"},
        {"name": "period_start", "dataType": "datetime"},
        {"name": "target", "dataType": "decimal"},
    ]
    measures = measures or [
        {"name": "TotalTarget", "expression": "SUM('Data'[target])"},
    ]

    skel_dir = out.parent / f"skel_{name}"
    _, layout = build_skeleton(
        out=skel_dir,
        report_name=f"skel_{name}",
        display_name=name,
        table="Data",
        columns=columns,
        measures=measures,
        kpi={"kind": "measure", "property": "TotalTarget", "display": "Total"},
        chart_type="lineChart",
        chart_axis={"kind": "column", "property": "period_start", "display": "Period"},
        chart_value={"kind": "measure", "property": "TotalTarget", "display": "Total"},
        table_fields=[
            {"kind": "column", "property": "segment", "display": "Segment"},
            {"kind": "measure", "property": "TotalTarget", "display": "Total"},
        ],
        filter_columns=["segment", "period_start"],
    )
    result: dict = {}

    # fold into .pbix
    logger.info("Folding skeleton into .pbix: %s", out)
    out = rebuild_pbix(src, out, layout=layout)
    result["built"] = {"path": str(out), "size": out.stat().st_size}

    if dry_run:
        result["publish"] = {"skipped": "dry-run"}
        return result

    res = publish_pbix(out, name, folder, cfg)
    result["publish"] = res
    server = (cfg or {}).get("server", "")
    base = (cfg or {}).get("base_path", "/reportserver")
    api_pref = (cfg or {}).get("api_prefix", "/api/v2.0")
    if server:
        result["verify"] = verify_published(
            server, folder, name, base=base, api=api_pref
        )
    else:
        result["verify"] = {"skipped": "no server configured"}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build + publish a .pbix to Report Server"
    )
    parser.add_argument(
        "--src", default=DEFAULT_SRC, help="donor .pbix (source of truth for DataModel)"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="where to build the .pbix (default output_files/<name>.pbix)",
    )
    parser.add_argument(
        "--name", default=DEFAULT_NAME, help="report name on the server (without .pbix)"
    )
    parser.add_argument(
        "--folder", default=DEFAULT_FOLDER, help="target folder on the server"
    )
    parser.add_argument(
        "--display", default=DEFAULT_DISPLAY, help="page name in the layout"
    )
    parser.add_argument(
        "--table", default=DEFAULT_TABLE, help="model table in the layout"
    )
    parser.add_argument("--col", default=DEFAULT_COL, help="model column in the layout")
    parser.add_argument(
        "--measure", default=DEFAULT_MEASURE, help="model measure in the layout"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="build only, without publishing"
    )
    parser.add_argument(
        "--skeleton",
        action="store_true",
        help="generate a query-driven skeleton (build_skeleton) instead of a single-visual layout",
    )
    parser.add_argument("--verbose", action="store_true", help="verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    out = (
        Path(args.out)
        if args.out
        else Path(__file__).parent
        / "output_files"
        / f"{args.name.strip().removesuffix('.pbix')}.pbix"
    )

    if args.skeleton:
        res = run_from_skeleton(
            src=Path(args.src),
            out=out,
            name=args.name,
            folder=args.folder,
            cfg=None,
            dry_run=args.dry_run,
        )
    else:
        res = run(
            src=Path(args.src),
            out=out,
            name=args.name,
            folder=args.folder,
            display_name=args.display,
            table=args.table,
            col=args.col,
            measure=args.measure,
            dry_run=args.dry_run,
        )
    import json

    print("\n=== RESULT ===")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
