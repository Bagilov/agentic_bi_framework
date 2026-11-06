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

CLI:
    python -m agentic_bi.rebuild donor.pbix --out output_files/rebuilt.pbix

CLI exit codes (see :mod:`agentic_bi.cli_support`): 0 when the new `.pbix` is
written, 2 on a bad input (missing donor, not a `.pbix` zip, unreadable layout).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import zipfile
from pathlib import Path

from agentic_bi import settings
from agentic_bi.layout_meta import decode_layout_with_encoding

logger = logging.getLogger(__name__)

PROG = "agentic_bi.rebuild"


def _extract_layout(src: Path) -> tuple[dict, str]:
    """Extract Report/Layout from a ready .pbix (sample of model references).

    Returns the layout and the encoding to write it back as: Desktop uses plain
    UTF-16LE without BOM, so any UTF-16 source is normalized to that; UTF-8
    sources are preserved as UTF-8.

    Raises:
        ValueError: when `src` is not a zip container or its layout is unreadable.
        KeyError: when the container has no ``Report/Layout`` part.
    """
    try:
        with zipfile.ZipFile(src) as z:
            raw = z.read("Report/Layout")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"not a .pbix zip container: {src}") from exc
    try:
        layout, enc = decode_layout_with_encoding(raw)
    except ValueError as exc:
        raise ValueError(f"Could not decode the source Report/Layout: {src}") from exc
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
    table: str | None = None,
    col: str | None = None,
    measure: str | None = None,
    layout: dict | None = None,
) -> Path:
    """Rebuild a .pbix: take the DataModel and binary parts from src, embed our
    layout and re-save the zip.

    Args:
        src: an existing working .pbix (source of truth for the DataModel).
        out: where to save the new .pbix.
        display_name: page name in the new layout.
        table/col/measure: model objects from the DataModel referenced by the new
            visual (must exist in the src model). Each ``None`` resolves from
            ``agentic_bi.settings`` (environment or neutral default).
        layout: a ready layout dict (e.g. from skeleton). Contains `sections`
            and `id`. If given, it is used as-is instead of `_new_layout`.
    """
    out.parent.mkdir(parents=True, exist_ok=True)

    # source base layout, to preserve resourcePackages/config
    base_layout, layout_enc = _extract_layout(src)
    if layout is None:
        model = settings.resolve_model(table=table, column=col, measure=measure)
        new_layout = _new_layout(
            display_name, model.table, model.column, model.measure, base_layout
        )
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

    logger.debug(
        "Rebuilt .pbix: %s (%d parts, %.1f KB)",
        _shown(out),
        len(names),
        out.stat().st_size / 1024,
    )
    return out


def _shown(path: str | Path) -> str:
    """Return `path` for a message: relative to CWD, never an absolute path."""
    p = Path(path)
    return str(p) if not p.is_absolute() else os.path.relpath(p, Path.cwd())


def _console_safe() -> None:
    """Keep a non-UTF-8 console (Windows cp1251/cp866) from raising on output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, ValueError):  # a closed/replaced stream is not fatal
            pass


def _layout_counts(layout: dict) -> tuple[int, int]:
    """Return (pages, visuals) for the summary line."""
    sections = layout.get("sections") or []
    pages = len(sections) if isinstance(sections, list) else 0
    visuals = sum(
        len(s.get("visualContainers") or []) for s in sections if isinstance(s, dict)
    )
    return pages, visuals


def main(argv: list[str] | None = None) -> int:
    from agentic_bi.cli_support import EXIT_BAD_INPUT, EXIT_OK, fail, run_boundary

    _console_safe()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Rebuild a .pbix from a donor (its DataModel is reused as-is).",
    )
    parser.add_argument("src", help="donor .pbix whose DataModel and parts are reused")
    parser.add_argument(
        "--out",
        default="output_files/rebuilt.pbix",
        metavar="PBIX",
        help="output .pbix path (default: output_files/rebuilt.pbix)",
    )
    parser.add_argument(
        "--display",
        default="Rebuilt report",
        help="page display name (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    def body() -> int:
        src = Path(args.src)
        if not src.is_file():
            return fail(PROG, f"donor pbix not found: {_shown(src)}", EXIT_BAD_INPUT)
        out = Path(args.out)
        try:
            rebuild_pbix(src, out, display_name=args.display)
            layout, _encoding = _extract_layout(out)
        except KeyError as exc:
            return fail(
                PROG,
                f"{_shown(src)}: no Report/Layout part in the container ({exc})",
                EXIT_BAD_INPUT,
            )
        pages, visuals = _layout_counts(layout)
        print(f"{PROG}: {pages} page(s), {visuals} visual(s) -> OK")
        print(f"Saved: {_shown(out)}")
        return EXIT_OK

    return run_boundary(body, prog=PROG)


if __name__ == "__main__":
    raise SystemExit(main())
