"""Build and publish a sample board over a configured model.

The board is built config-driven (skeleton) and references objects that must
exist in the target model, so it renders real data. Object names come from
``agentic_bi.settings`` (explicit > environment > neutral default), so nothing
donor-specific is baked into the module; the CSV/CSV model below is the neutral
sample the default registry in ``validate_pbix`` describes.

Steps:
  1. build_skeleton -> PBIP skeleton (KPI + chart + table + filters).
  2. layout_from_report -> layout in .pbix format.
  3. rebuild_pbix(src, out, layout=...) -> binary .pbix (DataModel from donor).
  4. publish_pbix -> publish to a Report Server.

Usage:
  uv run python -m agentic_bi.board_fake --src data/donor.pbix
  uv run python -m agentic_bi.board_fake --src data/donor.pbix --dry-run
  uv run python -m agentic_bi.board_fake --src data/donor.pbix --server host --folder /Target/Dev
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import agentic_bi.paths as paths
from agentic_bi import settings
from agentic_bi.automate import verify_published
from agentic_bi.publish import publish_pbix
from agentic_bi.rebuild import _extract_layout, rebuild_pbix
from agentic_bi.skeleton import build_skeleton
from agentic_bi.validate_pbix import validate_pbix

logger = logging.getLogger(__name__)

BOARD_NAME = "sample_board"
TARGET_FOLDER = "/Target/Dev"
DONOR = "data/donor.pbix"


def build_and_publish(
    src: str | Path = DONOR,
    server: str = "",
    folder: str = TARGET_FOLDER,
    dry_run: bool = False,
    table: str | None = None,
) -> dict:
    src = Path(src)
    names = settings.resolve_model(table=table)
    out = paths.output_dir(f"{BOARD_NAME}.pbix")
    tbl = names.table

    # Neutral sample objects: a "behavior by groups" model with a KPI, a time
    # axis and a couple of aggregations. Adapt to your donor via `table`/env.
    columns = [
        {"name": "segment", "dataType": "string"},
        {"name": "period_start", "dataType": "datetime"},
        {"name": "target", "dataType": "decimal"},
        {"name": "score", "dataType": "decimal"},
        {"name": "cnt", "dataType": "integer"},
    ]
    measures = [
        {"name": "TotalTarget", "expression": f"SUM('{tbl}'[target])"},
        {"name": "AvgScore", "expression": f"AVERAGE('{tbl}'[score])"},
        {"name": "Count", "expression": f"COUNTROWS('{tbl}')"},
    ]

    skel_dir = out.parent / "skel_fake"
    _, layout = build_skeleton(
        out=skel_dir,
        report_name="skel_fake",
        display_name=BOARD_NAME,
        table=tbl,
        columns=columns,
        measures=measures,
        kpi={"kind": "measure", "property": "TotalTarget", "display": "Total target"},
        chart_type="lineChart",
        chart_axis={"kind": "column", "property": "period_start", "display": "Period"},
        chart_value={
            "kind": "measure",
            "property": "AvgScore",
            "display": "Average score",
        },
        table_fields=[
            {"kind": "column", "property": "segment", "display": "Segment"},
            {"kind": "measure", "property": "TotalTarget", "display": "Target"},
            {"kind": "measure", "property": "Count", "display": "Records"},
        ],
        filter_columns=["segment", "period_start"],
    )

    # Enrich the layout with real resourcePackages/config from the donor (for
    # correct rendering of charts/tables), keeping our objects.
    base_layout, _ = _extract_layout(src)
    # do not override sections — only packages/config/themes from the donor
    if base_layout.get("resourcePackages"):
        layout["resourcePackages"] = base_layout["resourcePackages"]
    if base_layout.get("config"):
        layout["config"] = base_layout["config"]

    logger.info("Folding into .pbix: %s", out)
    out = rebuild_pbix(src, out, layout=layout)
    result = {"built": {"path": str(out), "size": out.stat().st_size}}

    # Validate the produced .pbix against the target model BEFORE publishing.
    problems = validate_pbix(out)
    result["validate"] = {"ok": not problems, "problems": problems}
    if problems:
        logger.error(
            "%d layout problems (not publishing):\n- %s",
            len(problems),
            "\n- ".join(problems),
        )
        raise RuntimeError(f"layout does not match the target model: {problems}")

    if dry_run:
        result["publish"] = {"skipped": "dry-run"}
        return result

    if not server:
        result["publish"] = {"skipped": "no server configured"}
        return result

    cfg = {
        "server": server,
        "base_path": "/reportserver",
        "api_prefix": "/api/v2.0",
        "timeout": 300,
    }
    res = publish_pbix(out, BOARD_NAME, folder, cfg)
    result["publish"] = res
    result["verify"] = verify_published(
        server, folder, BOARD_NAME, base="/reportserver", api="/api/v2.0"
    )
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Board over the configured model objects")
    p.add_argument("--src", default=DONOR, help="donor .pbix")
    p.add_argument("--server", default="", help="Report Server host (for publishing)")
    p.add_argument("--folder", default=TARGET_FOLDER, help="target folder")
    p.add_argument(
        "--table",
        default=None,
        help=f"model table (default: {settings.DEFAULT_TABLE})",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="build only, without publishing"
    )
    p.add_argument("--verbose", action="store_true")
    a = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    res = build_and_publish(
        src=a.src, server=a.server, folder=a.folder, dry_run=a.dry_run, table=a.table
    )
    print("\n=== RESULT ===")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
