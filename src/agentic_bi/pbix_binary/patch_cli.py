"""CLI for member-level `.pbix` patching (`apply_patches` / ABF inspection).

Usage:
    # apply a patch spec, optionally verifying the output opens in Desktop
    agentic-bi-pbix-patch apply --pbix template.pbix --spec patch.json \
        --out out.pbix [--report report.md]

    # list the ABF members of a .pbix (storage path + logical name + size)
    agentic-bi-pbix-patch members --pbix template.pbix [--json members.json]

Exit codes: 0 on success, 2 on a patch error (invalid spec / unmatched pattern).
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from agentic_bi.pbix_binary import abf_codec, abf_relayout
from agentic_bi.pbix_binary.patch_pipeline import (
    PatchError,
    apply_patches,
    load_spec,
)


def _read_datamodel(pbix: Path) -> bytes:
    with zipfile.ZipFile(pbix) as z:
        return z.read("DataModel")


def _cmd_members(args: argparse.Namespace) -> int:
    abf = abf_codec.decompress_datamodel(_read_datamodel(Path(args.pbix)))
    index = abf_relayout.parse_abf_index(abf)
    entries = {e.storage_path: e for e in index.log.iter_files()}
    rows = []
    for vf in index.files:
        entry = entries.get(vf.path)
        rows.append(
            {
                "storage": vf.path,
                "logical": index.log.logical_name(entry) if entry else vf.path,
                "size": vf.size,
                "offset": vf.offset,
            }
        )
    if args.json:
        Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    for row in rows:
        print(f"{row['size']:>12}  {row['storage']:<24}  {row['logical']}")
    print(f"total {len(rows)} members, ABF {len(abf)} B")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    patches = load_spec(Path(args.spec))
    report = apply_patches(Path(args.pbix), patches, Path(args.out))
    for line in report.log:
        print(" ", line)
    print(f"wrote {report.out} ({report.size} B), abf={report.abf_size} B")
    if args.report:
        Path(args.report).write_text(
            f"# pbix patch report\n\n- source: `{args.pbix}`\n"
            f"- out: `{report.out.name}` ({report.size} B)\n"
            f"- abf: {report.abf_size} B\n- edits:\n"
            + "".join(f"  - {line}\n" for line in report.log),
            encoding="utf-8",
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the patch CLI."""
    parser = argparse.ArgumentParser(
        prog="agentic-bi-pbix-patch",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    members = sub.add_parser("members", help="list ABF members of a .pbix")
    members.add_argument("--pbix", required=True)
    members.add_argument("--json", default=None, help="write members as JSON")
    members.set_defaults(func=_cmd_members)

    apply_cmd = sub.add_parser("apply", help="apply a patch spec")
    apply_cmd.add_argument("--pbix", required=True)
    apply_cmd.add_argument("--spec", required=True)
    apply_cmd.add_argument("--out", required=True)
    apply_cmd.add_argument("--report", default=None, help="write a markdown report")
    apply_cmd.set_defaults(func=_cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PatchError as exc:
        print(f"patch error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
