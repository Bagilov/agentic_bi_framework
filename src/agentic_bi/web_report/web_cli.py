"""CLI: render the web clone of a `.pbix` dashboard.

Usage:
    agentic-bi-web-clone --pbix board.pbix --out board_clone.html
        [--registry registry.json] [--title "Board"]

`--registry` is a JSON `{table:{columns,measures}}` (adds model-membership
checks). Without it, checks run without the model layer; with `--model-registry`
the registry is read from the `.pbix` via `pbixray` when available. An empty
`--registry '{}'` is treated as "no registry": counting it as a registry would
turn on membership checks that flag every visual.

After writing the document, its accessibility/media markers are checked with
`html_issues`; a missing marker is reported as a warning and fails `--strict`.

Exit codes: 0 on success, 1 when `--strict` is given and the report has
error-severity issues (element or generated-document), 2 when the `.pbix` or
registry cannot be read. Expected input failures end on a short human-readable
message, not a traceback (`cli_support.run_boundary`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentic_bi.cli_support import EXIT_FAILED, EXIT_OK, run_boundary
from agentic_bi.web_report import build_model, html_issues, write_html
from agentic_bi.web_report.web_inspect import registry_from_pbix

PROG = "agentic-bi-web-clone"


def _validate_registry(data: dict, path: Path) -> dict:
    """Enforce `{table:{columns:[str], measures:[str]}}`; raise `ValueError`."""
    for table, spec in data.items():
        if not isinstance(spec, dict):
            raise ValueError(
                f"реестр {path}: значение таблицы {table!r} должно быть объектом "
                "{columns: [...], measures: [...]}"
            )
        for bucket in ("columns", "measures"):
            values = spec.get(bucket, [])
            if not isinstance(values, list) or not all(
                isinstance(v, str) for v in values
            ):
                raise ValueError(
                    f"реестр {path}: {table}.{bucket} должен быть списком строк"
                )
    return data


def _load_registry(args: argparse.Namespace) -> dict | None:
    """Read the optional registry; bad or missing JSON is an input error.

    An empty object is returned as `None`: "a registry was passed" must mean
    "there are tables to check against", otherwise every visual fails
    `BIND-TABLE-MISSING` while no skip warning is printed.
    """
    if args.registry:
        path = Path(args.registry)
        if not path.is_file():
            raise ValueError(f"файл реестра не найден: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"реестр {path} — некорректный JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"реестр {path} должен быть объектом {{таблица: {{columns, measures}}}}"
            )
        return _validate_registry(data, path) or None
    if args.model_registry:
        reg = registry_from_pbix(args.pbix)
        return reg or None
    return None


def _skip_reason(args: argparse.Namespace) -> str:
    """Why model-membership checks did not run (for the single warning line)."""
    if args.registry:
        return f"реестр {args.registry} пуст"
    if args.model_registry:
        return "pbixray не дал реестр"
    return "нет реестра: pass --registry/--model-registry или install pbixray"


def _run(args: argparse.Namespace) -> int:
    """Command body: build the model, write the HTML clone, check the document."""
    pbix = Path(args.pbix)
    if not pbix.is_file():
        raise ValueError(f"файл .pbix не найден: {pbix}")
    registry = _load_registry(args)
    model = build_model(pbix, registry=registry)

    out = write_html(model, args.out, title=args.title)
    document_issues = html_issues(out.read_text(encoding="utf-8"))
    document_errors = sum(1 for i in document_issues if i.severity == "error")
    s = model.summary()
    print(f"Готово: {out} ({out.stat().st_size} байт)")
    print(
        f"Страниц: {s['pages']}, элементов: {s['elements']}, замечаний: "
        f"{s['issues']} (ошибок: {s['error']}, предупреждений: {s['warning']}, "
        f"инфо: {s['info']})"
    )
    if registry is None:
        print(
            "warning: model-membership checks were skipped "
            f"({_skip_reason(args)}); a clean result does not cover "
            "table/column/measure references",
            file=sys.stderr,
        )
    for issue in document_issues:
        print(f"warning: {PROG}: {issue.check_id}: {issue.message}", file=sys.stderr)
    if args.strict and (model.errors or document_errors):
        print(
            f"{PROG}: error: отчёт содержит ошибок: "
            f"{model.errors + document_errors} (--strict)",
            file=sys.stderr,
        )
        return EXIT_FAILED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; expected input errors exit with code 2."""
    ap = argparse.ArgumentParser(
        prog=PROG,
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--pbix", required=True, help="source .pbix")
    ap.add_argument("--out", required=True, help="output .html")
    ap.add_argument(
        "--registry",
        default=None,
        help="model registry JSON {table:{columns,measures}}",
    )
    ap.add_argument(
        "--model-registry",
        action="store_true",
        help="read the registry from the .pbix via pbixray",
    )
    ap.add_argument("--title", default="Dashboard Web Clone")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when the report has error-severity issues (default: 0)",
    )
    args = ap.parse_args(argv)
    return run_boundary(lambda: _run(args), prog=PROG)


if __name__ == "__main__":
    raise SystemExit(main())
