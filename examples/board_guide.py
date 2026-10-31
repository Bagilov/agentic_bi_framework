"""Example: build an annotated board guide (screenshot + visual hotspots).

The guide pairs the **real screenshot** of each report page with the page's
`Report/Layout` geometry as transparent hotspots; hovering a visual shows its
type, projected fields, measures, filters and (optionally) the measures' DAX.
See `agentic_bi.board_guide` and docs/IMPLEMENTATION.md §18.

The image is an input, not something this example produces: pass a directory of
`page_<stem>.png` screenshots (`--shots`) or an image prefix (`--src-prefix`).
Without a screenshot the guide still writes `index.html` plus a geometry dump,
which is useful to see the page/visual stems to name the images after.

Run:

    # annotate a directory of page_<stem>.png screenshots
    python examples/board_guide.py --pbix board.pbix --shots shots/ --dax

    # no screenshots: dump the geometry (page stems + visual boxes)
    python examples/board_guide.py --pbix board.pbix --out-dir output_files/guide

By default it uses the shipped donor `templates/template.pbix`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_bi.board_guide import build_guide, extract_page_geometry
from agentic_bi.board_guide.guide_geometry import load_measure_expressions

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
DEFAULT_PBIX = _ROOT / "templates" / "template.pbix"
DEFAULT_OUT = _ROOT / "output_files" / "board_guide"


def _print_geometry(geometry) -> None:
    """Show the page stems (what to name the screenshots) and the visual boxes."""
    print(f"pages={len(geometry.pages)} visuals={geometry.visual_count}")
    for page in geometry.pages:
        print(
            f"  {page.name}  ({page.width:.0f}x{page.height:.0f})  -> page_{page.stem}.png"
        )
        for visual in page.visuals:
            refs = ", ".join(visual.measures or visual.fields)
            print(
                f"    {visual.x:>6.0f},{visual.y:>5.0f} "
                f"{visual.width:>5.0f}x{visual.height:<5.0f} "
                f"{visual.visual_type:<18} {visual.label}"
                + (f"  [{refs}]" if refs else "")
            )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--pbix", default=str(DEFAULT_PBIX), help="source .pbix")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT), help="output directory")
    ap.add_argument(
        "--shots",
        default=None,
        help="directory with page_<stem>.png screenshots to annotate",
    )
    ap.add_argument(
        "--src-prefix",
        default=None,
        help="emit every page against this image prefix (e.g. a URL)",
    )
    ap.add_argument("--dax", action="store_true", help="attach measure DAX via pbixray")
    args = ap.parse_args()

    pbix = Path(args.pbix)
    measures = load_measure_expressions(pbix) if args.dax else {}
    geometry = extract_page_geometry(pbix, measures=measures or None)
    print(f"model measures: {len(measures)}")
    _print_geometry(geometry)

    geom_json = Path(args.out_dir) / "geometry.json"
    geom_json.parent.mkdir(parents=True, exist_ok=True)
    geom_json.write_text(
        json.dumps(geometry.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    saved = build_guide(
        geometry,
        args.out_dir,
        screenshots=args.shots,
        src_prefix=args.src_prefix,
        title=f"Board guide · {pbix.name}",
    )
    for path in saved:
        print(f"wrote {path} ({path.stat().st_size} B)")
    if not args.shots and not args.src_prefix:
        print(
            "no screenshots passed: wrote the index and geometry.json only; "
            "name your images page_<stem>.png and re-run with --shots"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
