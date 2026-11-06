"""CLI: build an annotated board guide (screenshot + visual hotspots).

Usage:
    agentic-bi-board-guide --pbix board.pbix --out-dir output_files/board_guide \\
        [--shots DIR] [--src-prefix PREFIX] [--capture-url URL] \\
        [--geometry-json FILE] [--dax]

Two independent inputs, both optional:

* `--shots DIR` — a directory with `page_<stem>.png` screenshots (a Desktop
  capture, a CI artifact, a manual set): the guide annotates them;
* `--capture-url URL` — capture the screenshots from a rendered report first
  (needs Playwright and a Chromium binary; see `guide_capture`).

`--dax` reads measure expressions via `pbixray` and attaches them to the
panel. Without a screenshot for a page, that page is skipped (a partial guide is
still usable); `--src-prefix` emits every page against an external image prefix.

Exit codes: 0 on success, 2 on a bad input or an unreadable `.pbix`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from agentic_bi.board_guide.guide_build import build_guide
from agentic_bi.board_guide.guide_geometry import (
    extract_page_geometry,
    load_measure_expressions,
)
from agentic_bi.cli_support import run_boundary


def _rel(path: str | Path) -> str:
    """A path for the console: always relative to the CWD, never absolute."""
    try:
        return Path(os.path.relpath(Path(path), Path.cwd())).as_posix()
    except ValueError:  # different drives (Windows): keep the path as given
        return Path(path).as_posix()


def _build(args: argparse.Namespace) -> int:
    measures = load_measure_expressions(args.pbix) if args.dax else {}
    geometry = extract_page_geometry(args.pbix, measures=measures or None)
    print(
        f"pages={len(geometry.pages)} visuals={geometry.visual_count} "
        f"dax_measures={len(measures)}"
    )

    if args.geometry_json:
        # `allow_nan=False`: a non-finite coordinate must fail loudly (exit 2 via
        # the boundary) instead of writing a `NaN`/`Infinity` token that a strict
        # JSON reader downstream rejects.
        payload = json.dumps(
            geometry.to_dict(), ensure_ascii=False, indent=2, allow_nan=False
        )
        Path(args.geometry_json).write_text(payload, encoding="utf-8")
        print(f"geometry -> {_rel(args.geometry_json)}")

    shots = args.shots
    capture_areas: dict[str, tuple[float, float]] = {}
    if args.capture_url:
        from agentic_bi.board_guide.guide_capture import capture_pages

        result = capture_pages(
            args.capture_url,
            shots,
            geometry,
            browser_executable=args.browser,
            page_names=args.pages,
            max_pages=args.max_pages,
            headless=not args.headful,
        )
        capture_areas = {
            str(page["stem"]): (
                float(page["area"]["width"]),
                float(page["area"]["height"]),
            )
            for page in result["pages"]
        }
        print(f"captured={len(result['pages'])} -> {_rel(shots)}")

    skipped: list[tuple[str, str]] = []
    saved = build_guide(
        geometry,
        args.out_dir,
        screenshots=shots,
        src_prefix=args.src_prefix,
        title=args.title,
        on_skip=lambda name, reason: skipped.append((name, reason)),
        capture_areas=capture_areas,
    )
    page_files = [p for p in saved if p.name != "index.html"]
    print(
        f"guide: {len(page_files)} лист(ов) записано, "
        f"{len(skipped)} пропущено -> {_rel(args.out_dir)}"
    )
    print(f"index: {_rel(saved[-1])}")
    for name, reason in skipped[:3]:
        print(f"warning: лист '{name}' пропущен: {reason}", file=sys.stderr)
    if len(skipped) > 3:
        print(
            f"warning: ещё {len(skipped) - 3} лист(ов) пропущено — см. index.html",
            file=sys.stderr,
        )
    if not page_files:
        print(
            "warning: no page had a screenshot; pass --shots/--capture-url or "
            "--src-prefix",
            file=sys.stderr,
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: build the annotated guide."""
    ap = argparse.ArgumentParser(
        prog="agentic-bi-board-guide",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--pbix", required=True, help="source .pbix")
    ap.add_argument(
        "--out-dir",
        default="output_files/board_guide",
        help="output directory for the HTML guide",
    )
    ap.add_argument(
        "--shots",
        default="output_files/board_guide/shots",
        help="directory with page_<stem>.png screenshots (also the capture target)",
    )
    ap.add_argument(
        "--src-prefix",
        default=None,
        help="emit every page against this image prefix instead of local files",
    )
    ap.add_argument(
        "--capture-url",
        default=None,
        help="capture the screenshots from this rendered report URL first",
    )
    ap.add_argument(
        "--browser",
        default=None,
        help="explicit Chromium executable for capture",
    )
    ap.add_argument("--headful", action="store_true", help="run the browser headed")
    ap.add_argument(
        "--dax",
        action="store_true",
        help="attach measure DAX via pbixray",
    )
    ap.add_argument(
        "--geometry-json",
        default=None,
        help="write the extracted geometry to this JSON file",
    )
    ap.add_argument("--title", default="Board guide")
    ap.add_argument("--pages", nargs="*", default=None, help="restrict captured pages")
    ap.add_argument("--max-pages", type=int, default=None)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return run_boundary(lambda: _build(args), prog="agentic-bi-board-guide")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
