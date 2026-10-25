"""Build and publish a sample board over real objects of the donor model.

The board is built config-driven (skeleton) and references EXISTING objects of
the donor's binary model (table fact_table, measures in kpi_measures,
columns period_start/metric/...), so it renders real data.

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
from agentic_bi.automate import verify_published
from agentic_bi.publish import publish_pbix
from agentic_bi.rebuild import _extract_layout, rebuild_pbix
from agentic_bi.skeleton import build_skeleton
from agentic_bi.validate_pbix import validate_pbix

logger = logging.getLogger(__name__)

BOARD_NAME = "sample_board"
TARGET_FOLDER = "/Target/Dev"
DONOR = "data/donor.pbix"

# Real objects of the donor model (table columns, measures).
TABLE = "fact_table"
MEASURE_TABLE = "kpi_measures"
MEASURES = [
    {"name": "metric_a", "expression": ""},
    {"name": "metric_b", "expression": ""},
]


def build_and_publish(
    src: str | Path = DONOR,
    server: str = "",
    folder: str = TARGET_FOLDER,
    dry_run: bool = False,
) -> dict:
    src = Path(src)
    out = paths.output_dir(f"{BOARD_NAME}.pbix")

    # These measures/columns already exist in the donor's binary model.
    columns = [
        {"name": "metric", "dataType": "string"},
        {"name": "period_start", "dataType": "datetime"},
        {"name": "segment", "dataType": "string"},
        {"name": "category", "dataType": "string"},
    ]

    skel_dir = out.parent / "skel_fake"
    _, layout = build_skeleton(
        out=skel_dir,
        report_name="skel_fake",
        display_name=BOARD_NAME,
        table=TABLE,
        columns=columns,
        measures=MEASURES,
        measure_table=MEASURE_TABLE,
        kpi={"kind": "measure", "property": "metric_a", "display": "Metric A"},
        chart_type="lineChart",
        chart_axis={"kind": "column", "property": "period_start", "display": "Period"},
        chart_value={"kind": "measure", "property": "metric_b", "display": "Metric B"},
        table_fields=[
            {"kind": "column", "property": "metric", "display": "Metric"},
            {"kind": "measure", "property": "metric_a", "display": "Metric A"},
            {"kind": "measure", "property": "metric_b", "display": "Metric B"},
        ],
        filter_columns=["category", "metric"],
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

    # Validate the produced .pbix against the donor model BEFORE publishing.
    problems = validate_pbix(out)
    result["validate"] = {"ok": not problems, "problems": problems}
    if problems:
        logger.error(
            "%d layout problems (not publishing):\n- %s",
            len(problems),
            "\n- ".join(problems),
        )
        raise RuntimeError(f"layout does not match the donor model: {problems}")

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
    p = argparse.ArgumentParser(description="Board over real donor-model objects")
    p.add_argument("--src", default=DONOR, help="donor .pbix")
    p.add_argument("--server", default="", help="Report Server host (for publishing)")
    p.add_argument("--folder", default=TARGET_FOLDER, help="target folder")
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
        src=a.src, server=a.server, folder=a.folder, dry_run=a.dry_run
    )
    print("\n=== RESULT ===")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
