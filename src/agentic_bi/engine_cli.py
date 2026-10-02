"""CLI: build a `.pbix` via the Desktop RS AS engine.

Examples:
    python -m agentic_bi.engine_cli --data sales.csv --table Sales --out out.pbix
    python engine_cli.py --data mix.csv --table Mix --out mix.pbix --oracle
    python engine_cli.py --data mix.csv --table Mix --out mix.pbix --verify

By default the build ends with a reverse self-test (--verify), including a check
of the report theme against the brand style guide (--verify-brand). Disable
with `--no-verify` / `--no-brand-verify`. `--verify-strict` (default) fails the
build on a failed check; `--brand-strict` also makes brand errors critical.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from agentic_bi.engine import EnginePipeline, DEFAULT_TEMPLATE, PBI_RS


def _parse_pages(raw: str | None) -> dict[str, int] | None:
    """Parse page expectations: 'Overview=8,Issues=3' -> dict."""
    if not raw:
        return None
    pages: dict[str, int] = {}
    for part in raw.split(","):
        name, _, n = part.rpartition("=")
        if not name:
            continue
        pages[name.strip()] = int(n)
    return pages or None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--database", default=None)
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--desktop", default=PBI_RS)
    ap.add_argument("--oracle", action="store_true")
    ap.add_argument("--hold", type=int, default=70)
    ap.add_argument("--keep-donor-layout", action="store_true",
                    help="keep the donor layout instead of a clean one")
    ap.add_argument("--verify", dest="verify", action="store_true", default=True,
                    help="reverse self-test of the built .pbix (on by default)")
    ap.add_argument("--no-verify", dest="verify", action="store_false",
                    help="disable the reverse self-test")
    ap.add_argument("--no-verify-strict", dest="strict_verify",
                    action="store_false", default=True,
                    help="do not fail on a failed critical check (report only)")
    ap.add_argument("--strict-soft", action="store_true", default=False,
                    help="treat a model read-back failure (pbixray) as a failure too")
    ap.add_argument("--assert-pages", default=None,
                    help="expected pages 'Name=N,Name2=M' for the structure check")
    ap.add_argument("--sample", type=int, default=50,
                    help="how many model rows to compare in the read-back")
    ap.add_argument("--no-model-verify", dest="model_verify",
                    action="store_false", default=True,
                    help="do not read the model via pbixray (layout only)")
    ap.add_argument("--verify-brand", dest="brand_verify", action="store_true",
                    default=True,
                    help="check the report theme against the style guide (on by default)")
    ap.add_argument("--no-brand-verify", dest="brand_verify", action="store_false",
                    help="disable the brand-book check")
    ap.add_argument("--brand-strict", action="store_true", default=False,
                    help="treat brand errors as build failures (e.g. BRAND-ACCENT-MANDATORY)")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db = args.database or (Path(args.out).stem + "_db")
    pipe = EnginePipeline(template=Path(args.template), desktop=args.desktop)
    pages = _parse_pages(args.assert_pages)
    result = pipe.run(Path(args.data), args.table, db, Path(args.out),
                      check_oracle=args.oracle, hold=args.hold,
                      clean_layout=not args.keep_donor_layout,
                      verify=args.verify, strict_verify=args.strict_verify,
                      pages=pages, sample=args.sample,
                      model_verify=args.model_verify,
                      strict_soft=args.strict_soft,
                      brand_verify=args.brand_verify,
                      brand_strict=args.brand_strict)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).write_text(
            f"# engine pbix\n\n- data: `{args.data}`\n- rows: {result['rows']}\n"
            f"- layout: {result['layout']}\n- out: `{result['out']}` "
            f"({result['pbix_bytes']} B)\n- verify: {result.get('verify', 'n/a')}\n"
            f"- oracle: {result['oracle']}\n",
            encoding="utf-8")
    if result.get("verify") == "FAILED":
        return 1
    return 0 if result["oracle"] in ("MODEL_LOADED", "SKIPPED") else 1


if __name__ == "__main__":
    raise SystemExit(main())