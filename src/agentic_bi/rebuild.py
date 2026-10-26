"""Iteration 3+4: rebuild a binary `.pbix` from an existing working file.

Strategy (verified against real files):
- A `.pbix` is an ordinary zip: binary VertiPaq `DataModel` + `Report/Layout` (JSON).
- The binary `DataModel` CANNOT be generated from scratch by hand (closed
  xpress/ABF format).
- The reliable path: take the `DataModel` from a ready working `.pbix` as-is
  (byte-for-byte), replace `[Content_Types].xml` with a full one, and embed our
  `Report/Layout` whose visuals reference EXISTING model objects (table/measure/
  column names from the taken DataModel). Rebuild the zip.

Layout and DataModel are independent — the layout references the model by name,
so as long as object names match, the visuals work in Desktop and on a Report
Server.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from agentic_bi.layout_meta import decode_layout_with_encoding

logger = logging.getLogger(__name__)


def _extract_layout(src: Path) -> tuple[dict, str]:
    """Extract Report/Layout from a ready .pbix (sample of model references).

    Returns the layout and the encoding to write it back as: Desktop uses plain
    UTF-16LE without BOM, so any UTF-16 source is normalized to that; UTF-8
    sources are preserved as UTF-8.
    """
    with zipfile.ZipFile(src) as z:
        raw = z.read("Report/Layout")
    try:
        layout, enc = decode_layout_with_encoding(raw)
    except ValueError as exc:
        raise ValueError("Could not decode the source Report/Layout") from exc
    return layout, "utf-16le" if enc.startswith("utf-16") else enc


def _new_layout(
    display_name: str, table: str, col: str, measure: str, base_layout: dict
) -> dict:
    """Build a layout with a single visual referencing the source model."""
    layout = dict(base_layout)
    layout["sections"] = [
        {
            "name": "ReportSectionCustom",
            "displayName": display_name,
            "filters": "[]",
            "ordinal": 0,
            "visualContainers": [
                {
                    "x": 20,
                    "y": 20,
                    "z": 0,
                    "width": 400,
                    "height": 300,
                    "config": json.dumps(
                        {
                            "name": "visual1",
                            "layouts": [
                                {
                                    "id": 0,
                                    "position": {
                                        "x": 20,
                                        "y": 20,
                                        "width": 400,
                                        "height": 300,
                                        "z": 0,
                                    },
                                }
                            ],
                            "singleVisual": {
                                "visualType": "clusteredColumnChart",
                                "objects": {},
                                "prototypeQuery": {
                                    "Version": 2,
                                    "From": [{"Name": "e", "Entity": table}],
                                    "Select": [
                                        {
                                            "Column": {
                                                "Expression": {
                                                    "SourceRef": {"Source": "e"}
                                                },
                                                "Property": col,
                                            },
                                            "Name": col,
                                        },
                                        {
                                            "Measure": {
                                                "Expression": {
                                                    "MeasureRef": {"Property": measure}
                                                }
                                            },
                                            "Name": measure,
                                        },
                                    ],
                                },
                            },
                        },
                        ensure_ascii=False,
                    ),
                    "filters": "[]",
                    "tabOrder": 0,
                }
            ],
        }
    ]
    layout["id"] = base_layout.get("id", 0)
    return layout


def rebuild_pbix(
    src: Path,
    out: Path,
    display_name: str = "Rebuilt report",
    table: str = "fact_table",
    col: str = "metric",
    measure: str = "score",
    layout: dict | None = None,
) -> Path:
    """Rebuild a .pbix: take the DataModel and binary parts from src, embed our
    layout and re-save the zip.

    Args:
        src: an existing working .pbix (source of truth for the DataModel).
        out: where to save the new .pbix.
        display_name: page name in the new layout.
        table/col/measure: model objects from the DataModel referenced by the new
            visual (must exist in the src model).
        layout: a ready layout dict (e.g. from skeleton). Contains `sections`
            and `id`. If given, it is used as-is instead of `_new_layout`.
    """
    out.parent.mkdir(parents=True, exist_ok=True)

    # source base layout, to preserve resourcePackages/config
    base_layout, layout_enc = _extract_layout(src)
    if layout is None:
        new_layout = _new_layout(display_name, table, col, measure, base_layout)
    else:
        new_layout = layout

    # read all parts of the source zip, replacing Report/Layout
    with zipfile.ZipFile(src) as zin:
        names = zin.namelist()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in names:
                data = zin.read(name)
                if name == "Report/Layout":
                    # Keep the same encoding as the source — plain UTF-16LE
                    # without BOM (otherwise Desktop/analyzers cannot decode the
                    # layout; the source has no BOM).
                    text = json.dumps(new_layout, ensure_ascii=False)
                    data = (
                        text.encode("utf-16-le")
                        if layout_enc == "utf-16le"
                        else text.encode(layout_enc)
                    )
                zout.writestr(name, data)

    logger.info(
        "Rebuilt .pbix: %s (%d parts, %.1f KB)",
        out,
        len(names),
        out.stat().st_size / 1024,
    )
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    import argparse

    parser = argparse.ArgumentParser(description="Rebuild a .pbix from a donor")
    parser.add_argument("src", help="donor .pbix (DataModel source)")
    parser.add_argument("--out", default="output_files/rebuilt.pbix")
    parser.add_argument("--display", default="Rebuilt report")
    args = parser.parse_args()
    rebuild_pbix(Path(args.src), Path(args.out), display_name=args.display)


if __name__ == "__main__":
    main()
