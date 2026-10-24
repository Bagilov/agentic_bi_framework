# Bundle 2: remaining CLI entry points (boundary wiring)

Each section is one source file, path relative to repo root.

==================== FILE: src/agentic_bi/test_build.py ====================

"""Test build: assemble a `.pbix` from a CSV and validate it end-to-end.

This is the framework's self-test entry point. It runs fully offline for the
layout/validation part when a DataModel (`.abf`) is supplied, and builds the
model with the Power BI Desktop AS engine on Windows when `--datamodel` is
omitted (Windows only).

Examples:
    # cross-platform: reuse a prebuilt model + template
    python -m agentic_bi.test_build \
        --data examples/engine_sales.csv --table Sales \
        --template templates/template.pbix --datamodel model.abf \
        --out output_files/test_build.pbix --report output_files/test_build.json

    # on Windows + Power BI Desktop: build the model via the engine
    python -m agentic_bi.test_build --data sales.csv --table Sales \
        --template templates/template.pbix --out out.pbix

Exit code is non-zero if the visual check or a critical verification fails.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import zipfile
from pathlib import Path

from agentic_bi import engine_container, engine_layout, engine_verify, visual_check
from agentic_bi.engine import DEFAULT_TEMPLATE, PBI_RS, EnginePipeline

logger = logging.getLogger(__name__)


def registry_from_spec(spec: dict) -> dict:
    """Build a {table:{columns,measures}} registry from a build spec."""
    return {
        t["name"]: {
            "columns": [c["name"] for c in t["columns"]],
            "measures": [
                m["name"]
                for m in spec.get("measures", [])
                if m.get("table") == t["name"]
            ],
        }
        for t in spec["tables"]
    }


def copy_members_for(template: Path) -> list[str]:
    """COPY_MEMBERS intersected with the template, minus Layout/DataModel."""
    names = set(zipfile.ZipFile(template).namelist())
    return [
        m
        for m in engine_container.COPY_MEMBERS
        if m in names and m not in ("Report/Layout", "DataModel")
    ]


def build_layout(spec: dict, mode: str) -> bytes:
    """Return Report/Layout bytes for the requested mode."""
    if mode == "gallery":
        return engine_layout.build_gallery(spec)
    return engine_layout.build_layout_from_spec(spec)


def run(args: argparse.Namespace) -> dict:
    data = Path(args.data)
    template = Path(args.template)
    out = Path(args.out)

    pipe = EnginePipeline(template=template, desktop=args.desktop)
    rows = pipe.load_rows(data)
    spec = pipe.build_spec(rows, table=args.table, database=args.database)
    logger.info("rows=%d cols=%d", len(rows), len(spec["tables"][0]["columns"]))

    layout = build_layout(spec, args.layout)

    if args.datamodel:
        datamodel = Path(args.datamodel).read_bytes()
    elif sys.platform == "win32":
        # Windows + Power BI Desktop: build the model via the AS engine.
        datamodel = pipe.build_datamodel(spec)
    else:
        raise SystemExit(
            "test build needs a DataModel: pass --datamodel <model.abf> on "
            "non-Windows hosts (the AS engine requires Windows + Power BI Desktop)"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    engine_container.build_container(
        template, layout, datamodel, out, copy_members=copy_members_for(template)
    )

    registry = (
        json.loads(Path(args.registry).read_text())
        if args.registry
        else registry_from_spec(spec)
    )
    visual_errors = visual_check.check_pbix(out, registry)
    report = engine_verify.verify_pbix(out, spec, model=args.model, layout_checks=True)

    result = {
        "out": str(out),
        "bytes": out.stat().st_size,
        "rows": len(rows),
        "layout": args.layout,
        "datamodel_bytes": len(datamodel),
        "visual_errors": visual_errors,
        "verify_ok": report.critical_ok(),
        "verify_passed": report.passed,
        "verify_failed": report.failed,
        "verify_critical_failed": [c.name for c in report.critical_failures],
        "verify_soft_failed": [c.name for c in report.soft_failures],
    }
    return result


def main(argv: list[str] | None = None) -> int:
    from agentic_bi.cli_support import run_boundary

    ap = argparse.ArgumentParser(
        prog="agentic-bi-test-build",
        description="Build and validate a .pbix test build.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--data", required=True, help="CSV/JSON input")
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True, help="output .pbix")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument(
        "--datamodel", default=None, help="prebuilt DataModel (.abf); skips the engine"
    )
    ap.add_argument(
        "--desktop",
        default=PBI_RS,
        help="Power BI Desktop executable (Windows engine mode)",
    )
    ap.add_argument("--database", default=None)
    ap.add_argument("--layout", choices=["gallery", "auto"], default="gallery")
    ap.add_argument(
        "--registry",
        default=None,
        help="JSON model registry; default: derived from the spec",
    )
    ap.add_argument(
        "--model",
        action="store_true",
        help="also read the model back via pbixray (needs readback)",
    )
    ap.add_argument("--report", default=None, help="write the JSON result here")
    args = ap.parse_args(argv)
    if not args.database:
        args.database = Path(args.out).stem + "_db"

    def body() -> int:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        result = run(args)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        print(text)
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(text, encoding="utf-8")

        ok = not result["visual_errors"] and result["verify_ok"]
        return 0 if ok else 1

    return run_boundary(body, prog="agentic-bi-test-build")


if __name__ == "__main__":
    raise SystemExit(main())

==================== FILE: src/agentic_bi/report/pdf_report.py ====================

"""Multi-page PDF report of a lineage page (diagram + matrix + brand audit).

Assembles the full lineage page into a single multi-page PDF:

    1. title + headline counters
    2. the PlantUML lineage diagram (tiled across pages when tall)
    3. the flat level matrix (automatically paginated)
    4. elements deviating from the brand book

Requires the ``report`` optional extra: ``reportlab`` (and ``Pillow`` for the
diagram, ``pandas``/``openpyxl`` for the Excel export).

CLI exit codes: 0 on success, 2 on a bad input (missing/unreadable JSON/.pbix).
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A3, A4, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

from agentic_bi.report.lineage_matrix import lineage_to_table
from agentic_bi.report.pdf_diagram import diagram_story
from agentic_bi.report.pdf_tables import brand_issues, brand_scorecard, lineage_matrix
from agentic_bi.report.plantuml_tools import find_plantuml_jar

logger = logging.getLogger(__name__)

_PAGE_SIZES = {"A4": A4, "A3": A3}

# Common Unicode font locations, tried when REPORT_PDF_FONT is not set.
_FONT_CANDIDATES = [
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/DejaVuSans.ttf", "C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
]


def _resolve_fonts(font_ttf: str | None = None) -> tuple[str, str]:
    """Register a Unicode TTF when available; fall back to Helvetica."""
    import os

    regular = font_ttf or os.getenv("REPORT_PDF_FONT")
    candidates = []
    if regular:
        candidates.append((regular, regular))
    candidates.extend(_FONT_CANDIDATES)
    for reg, bold in candidates:
        if reg and Path(reg).exists():
            try:
                pdfmetrics.registerFont(TTFont("ReportFont", reg))
                if bold and Path(bold).exists():
                    pdfmetrics.registerFont(TTFont("ReportFont-Bold", bold))
                    return "ReportFont", "ReportFont-Bold"
                return "ReportFont", "ReportFont"
            except Exception as exc:  # noqa: BLE001 - fall back on any font error
                logger.warning("font %s rejected: %s", reg, exc)
    return "Helvetica", "Helvetica-Bold"


def _styles(regular: str, bold: str) -> dict:
    normal = getSampleStyleSheet()["Normal"]
    return {
        "Title": ParagraphStyle(
            "TitleX",
            parent=normal,
            fontName=bold,
            fontSize=20,
            leading=24,
            spaceAfter=4 * mm,
        ),
        "Heading2": ParagraphStyle(
            "Heading2X",
            parent=normal,
            fontName=bold,
            fontSize=13,
            leading=16,
            spaceAfter=2 * mm,
        ),
        "Body": ParagraphStyle(
            "BodyX", parent=normal, fontName=regular, fontSize=9, leading=12
        ),
        "Cell": ParagraphStyle(
            "CellX", parent=normal, fontName=regular, fontSize=6.5, leading=8
        ),
        "CellHead": ParagraphStyle(
            "CellHeadX",
            parent=normal,
            fontName=bold,
            fontSize=6.5,
            leading=8,
            textColor="#FFFFFF",
        ),
    }


def _page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor("#666666")
    canvas.drawRightString(doc.pagesize[0] - 10 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_report(
    data: dict,
    out_path: str | Path,
    *,
    plantuml: str = "",
    title: str = "Data lineage report",
    source_name: str | None = None,
    page_size: str = "A4",
    orientation: str = "landscape",
    font_ttf: str | None = None,
    max_level: int = 7,
    include_visuals: bool = True,
    with_diagram: bool = True,
) -> Path:
    """Build a multi-page PDF report and return the output path.

    Args:
        data: dict in the ``PbiLineage.to_json()`` structure.
        out_path: destination ``.pdf`` path.
        plantuml: PlantUML source for the diagram (skipped when empty).
        title: report title.
        source_name: shown under the title (e.g. the source file name).
        page_size: ``"A4"`` (default) or ``"A3"``.
        orientation: ``"landscape"`` (default) or ``"portrait"``.
        font_ttf: explicit Unicode TTF path; otherwise resolved automatically.
        max_level: deepest lineage level included (1-7).
        include_visuals: include level 7 (visuals) in the matrix.
        with_diagram: render and embed the PlantUML diagram.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    size = _PAGE_SIZES.get(page_size.upper(), A4)
    pagesize = landscape(size) if orientation == "landscape" else portrait(size)

    margin = 12 * mm
    content_w = pagesize[0] - 2 * margin
    content_h = pagesize[1] - 2 * margin - 10 * mm

    regular, bold = _resolve_fonts(font_ttf)
    styles = _styles(regular, bold)

    summary = data.get("summary") or {}
    meta = data.get("meta") or {}
    story: list = [Paragraph(_safe(title), styles["Title"])]
    subtitle = source_name or meta.get("file") or ""
    if subtitle:
        story.append(Paragraph(_safe(subtitle), styles["Body"]))
    story.append(
        Paragraph(
            f"Generated: {datetime.now():%Y-%m-%d %H:%M}. "
            f"Pages: {summary.get('pages', len(data.get('pages', [])) or 0)}, "
            f"visuals: {summary.get('visuals', '')}, "
            f"tables: {summary.get('tables', '')}, "
            f"measures: {summary.get('measures', '')}.",
            styles["Body"],
        )
    )

    if with_diagram and plantuml.strip():
        story.append(PageBreak())
        story.extend(diagram_story(plantuml, content_w, content_h, styles))

    if summary.get("plantuml_available") is False:
        story.append(
            Paragraph("plantuml.jar not found; diagram omitted.", styles["Body"])
        )

    story.extend(brand_scorecard(data, styles, content_w))

    rows = lineage_to_table(data)
    if rows:
        story.append(PageBreak())
        story.extend(
            lineage_matrix(rows, styles, content_w, max_level, include_visuals)
        )

    issues = brand_issues(data, styles, content_w)
    if issues:
        story.append(PageBreak())
        story.extend(issues)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=pagesize,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=14 * mm,
        title=title,
        author="agentic-bi-framework",
    )
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    logger.info("PDF report written: %s", out)
    return out


def _safe(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _plantuml_for(src: Path, data: dict) -> str:
    """Resolve PlantUML source: from a .pbix, the JSON block, or a sibling .puml."""
    if src.suffix.lower() == ".pbix":
        from agentic_bi.lineage.pbi_lineage import PbiLineage

        with PbiLineage(src) as lg:
            return lg.to_plantuml()
    block = data.get("plantuml")
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        found = block.get("lineage") or block.get("source")
        if found:
            return found
    sibling = src.with_suffix(".puml")
    if sibling.exists():
        return sibling.read_text(encoding="utf-8")
    return ""


def main(argv: list[str] | None = None) -> int:
    from agentic_bi.cli_support import run_boundary

    parser = argparse.ArgumentParser(
        prog="agentic-bi-report",
        description="Build a multi-page PDF lineage report from JSON/.pbix.",
    )
    parser.add_argument("input", help="path to lineage.json or .pbix")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="output .pdf path (default: next to the input as "
        "'<name>_YYYYMMDD_HHMMSS.pdf')",
    )
    parser.add_argument("--title", default="Data lineage report")
    parser.add_argument("--page-size", default="A4", choices=["A4", "A3"])
    parser.add_argument(
        "--orientation", default="landscape", choices=["landscape", "portrait"]
    )
    parser.add_argument("--font", default=None, help="Unicode TTF font path")
    parser.add_argument("--max-level", type=int, default=7)
    parser.add_argument(
        "--no-visuals", action="store_true", help="exclude level 7 (visuals)"
    )
    parser.add_argument("--no-diagram", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    def body() -> int:
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(levelname)s: %(message)s",
        )

        from agentic_bi.report.lineage_table import load_json

        data = load_json(args.input)
        plantuml = ""
        if not args.no_diagram and find_plantuml_jar():
            try:
                plantuml = _plantuml_for(Path(args.input), data)
            except Exception as exc:  # noqa: BLE001 - diagram is best-effort
                logger.warning("could not build PlantUML: %s", exc)

        inp = Path(args.input)
        if args.output:
            out = args.output
        else:
            # Timestamped default so repeated runs never overwrite each other.
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = str(inp.with_name(f"{inp.stem}_{stamp}.pdf"))
        build_report(
            data,
            out,
            plantuml=plantuml,
            title=args.title,
            source_name=Path(args.input).name,
            page_size=args.page_size,
            orientation=args.orientation,
            font_ttf=args.font,
            max_level=args.max_level,
            include_visuals=not args.no_visuals,
            with_diagram=not args.no_diagram,
        )
        print(f"PDF report saved: {out}")
        return 0

    return run_boundary(body, prog="agentic-bi-report")


if __name__ == "__main__":
    raise SystemExit(main())

==================== FILE: src/agentic_bi/pbix_binary/patch_cli.py ====================

"""CLI for member-level `.pbix` patching (`apply_patches` / ABF inspection).

Usage:
    # apply a patch spec; the written .pbix is re-read and verified before exit
    agentic-bi-pbix-patch apply --pbix template.pbix --spec patch.json \
        --out out.pbix [--report report.md]

    # list the ABF members of a .pbix (storage path + logical name + size)
    agentic-bi-pbix-patch members --pbix template.pbix [--json members.json]

Self-verification covers the archive and the `DataModel` inside it; it does not
open the report in Power BI Desktop.

Exit codes: 0 on success, 2 on a bad input (unreadable .pbix/spec) or a patch
error (invalid spec, unmatched or ambiguous pattern, failed self-verification).
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
    """CLI entry point: apply/patch a `.pbix`, exit 0/1/2 (2 = bad input)."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PatchError as exc:
        print(f"patch error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"patch error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

==================== FILE: src/agentic_bi/lineage/pbi_lineage.py ====================

"""
Build data lineage of a Power BI dashboard (.pbix) without Power BI installed.

The `PbiLineage` class parses any .pbix (embedded VertiPaq model) and produces
the full linear data trail:

    Origin (process/repository) -> Source -> Power Query
    -> model tables -> semantics -> pages -> visuals.

Data sources:
- Model (tables, measures, calculated columns, schema, relationships, M code) via `pbixray`.
- Report layout (pages, visuals, queryRef bindings) from `Report/Layout` (JSON).

Usage example:

    from agentic_bi.lineage.pbi_lineage import PbiLineage

    lg = PbiLineage("C:/dashboards/report.pbix")
    lg.print_summary()                      # a short summary to the console
    lg.export_excel("out/lineage.xlsx")     # 3 sheets: pages/visuals/tables
    lg.export_markdown("out/REPORT.md")     # a human-readable report
    df_visuals = lg.visuals_dataframe       # visuals as a pandas.DataFrame

Dependencies: pbixray, pandas, openpyxl.

Implementation is split across mixins for readability:
    lineage_types.py    - Source/Visual/Page dataclasses + helpers
    lineage_model.py    - model extraction, layout parsing, source resolution
    lineage_query.py    - counts / DataFrames / lookup helpers
    lineage_export.py   - summary, Excel, Markdown, JSON, brand metrics
    lineage_plantuml.py - the PlantUML data-flow diagram
"""

from __future__ import annotations

import logging
from pathlib import Path

from agentic_bi.lineage.lineage_export import ExportMixin
from agentic_bi.lineage.lineage_model import ModelMixin
from agentic_bi.lineage.lineage_plantuml import PlantUmlMixin
from agentic_bi.lineage.lineage_query import QueryMixin
from agentic_bi.lineage.lineage_sources import SourceMixin
from agentic_bi.lineage.lineage_types import (  # noqa: F401
    Page,
    Source,
    SourceAccessError,
    Visual,
    VisualBinding,
    _load_brand_config,
)

logger = logging.getLogger(__name__)


class PbiLineage(ModelMixin, SourceMixin, QueryMixin, ExportMixin, PlantUmlMixin):
    """Extract data lineage from a .pbix.

    Args:
        pbix_path: path to the .pbix file.
        display_aliases: map of displayed table names -> physical ones
            (e.g. {"Sales Registry": "dim_registry"}).
            Used when visuals reference tables by display name.
        brand_config: path to `brand_config.yaml/json` (brand rules for page
            compliance metrics); defaults to `brand.py`.
    """

    # Technical tables (DateTable / LocalDateTable), created by Power BI
    _TECH_PREFIXES = ("DateTableTemplate_", "LocalDateTable_")

    def __init__(
        self,
        pbix_path: str | Path,
        display_aliases: dict[str, str] | None = None,
        origins: list | dict | str | Path | None = None,
        brand_config: str | Path | None = None,
    ):
        self.pbix_path = Path(pbix_path).resolve()
        if not self.pbix_path.exists():
            raise FileNotFoundError(f"File not found: {self.pbix_path}")
        self.display_aliases = display_aliases or {}
        self.origins = load_origins(origins)
        self._brand_cfg = _load_brand_config(brand_config)
        self._brand_cache: dict | None = None
        self._pu_seen: set[str] = set()
        self._pu_ids: dict[tuple[str, str], str] = {}
        self._unresolved_table_refs: set[str] = set()

        self._model = None
        self._open_model()

        try:
            self._load_model_artifacts()
            self._load_layout()
            self._build()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Close the pbixray model."""
        if self._model is not None:
            try:
                self._model.close()
            finally:
                self._model = None

    def __enter__(self) -> PbiLineage:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# Imported here to avoid a circular import at module definition time.
from agentic_bi.lineage.lineage_origins import load_origins  # noqa: E402


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json

    from agentic_bi.cli_support import run_boundary

    parser = argparse.ArgumentParser(
        prog="agentic-bi-lineage",
        description="Build data lineage of a Power BI dashboard (.pbix).\n"
        "Process: input .pbix -> output JSON with the analysis structure.",
    )
    parser.add_argument("pbix", help="path to the .pbix file (input)")
    parser.add_argument(
        "--json",
        dest="json_out",
        default=None,
        metavar="OUT.json",
        help="output JSON path (default: <out-dir>/lineage.json)",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="print the JSON analysis to stdout (instead of saving)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="output directory (default: output_files/pbi_lineage)",
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        metavar="DISPLAY=PHYSICAL",
        help="display table name -> physical alias (repeatable)",
    )
    parser.add_argument("--no-xlsx", action="store_true", help="do not save Excel")
    parser.add_argument("--no-md", action="store_true", help="do not save Markdown")
    parser.add_argument("--no-json", action="store_true", help="do not save JSON")
    parser.add_argument(
        "--plantuml",
        action="store_true",
        help="add the PlantUML diagram to the JSON 'plantuml' key",
    )
    parser.add_argument(
        "--brand-config",
        default=None,
        metavar="brand_config.yaml",
        help="brand rules config (page compliance metrics)",
    )
    args = parser.parse_args(argv)

    def body() -> int:
        aliases = {}
        for a in args.alias:
            if "=" in a:
                k, _, v = a.partition("=")
                aliases[k] = v

        out_dir = (
            Path(args.out_dir) if args.out_dir else Path("output_files") / "pbi_lineage"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        with PbiLineage(args.pbix, aliases, brand_config=args.brand_config) as lg:
            # main output - the structured JSON
            if args.print_json:
                # JSON to stdout (minimal object; plantuml per flag)
                print(_json.dumps(lg.to_json(), ensure_ascii=False, indent=2))
            else:
                if not args.no_json:
                    json_path = (
                        Path(args.json_out)
                        if args.json_out
                        else out_dir / "lineage.json"
                    )
                    p = lg.export_json(json_path)
                    print("JSON export:", p)
                lg.print_summary()
                if not args.no_xlsx:
                    p = lg.export_excel(out_dir / "lineage.xlsx")
                    print("Excel export:", p)
                if not args.no_md:
                    p = lg.export_markdown(out_dir / "REPORT.md")
                    print("Markdown export:", p)
        return 0

    return run_boundary(body, prog="agentic-bi-lineage")


if __name__ == "__main__":
    raise SystemExit(main())

==================== FILE: src/agentic_bi/antipatterns/pbi_antipatterns.py ====================

"""Antipattern analysis of Power BI calculations/scripts.

Scans ALL dashboard calculations - both at the **source** level (Power Query M
code) and **inside the dashboard** (DAX measures, calculated columns) - and
returns a JSON metric of **antipatterns tied to the analyzed level**:

    source       -> table (source), M code
    table        -> model table (aggregated: measures/columns/source)
    measure      -> a specific DAX measure
    calc_column  -> a specific calculated column
    board        -> the whole dashboard (summary statistics)

Every finding: {id, name, level, critical, detail, fix}.

This module is a **facade** over focused submodules:
    antipattern_registry.py  - Antipattern dataclass + ANTIPATTERNS list
    antipattern_detectors.py - per-level detectors

The data source is a `.pbix` (via `PbiLineage`), from which `power_query` (M code),
`dax_measures.Expression`, `dax_columns.Expression` are available.

Usage:
    python -m agentic_bi.antipatterns.pbi_antipatterns "C:\\path\\to\\report.pbix" -o out.json
    python -m agentic_bi.antipatterns.pbi_antipatterns "C:\\path\\to\\report.pbix" --summary

CLI exit codes: 0 on success, 2 on a bad input (missing/unreadable .pbix).
Default output is `output_files/<name>_antipatterns.json` (relative to the CWD).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from agentic_bi.antipatterns.antipattern_detectors import (  # noqa: F401
    analyze_board,
    analyze_calc_column,
    analyze_measure,
    analyze_source_m,
    analyze_table,
)
from agentic_bi.antipatterns.antipattern_registry import (  # noqa: F401
    ANTIPATTERNS,
    Antipattern,
    _registry,
)


def analyze_board_objects(m: object, pages: list[dict] | None = None) -> dict:
    """Build the full antipattern metric by level.

    Args:
        m: a pbixray object (self._model) - with tables, dax_measures,
            dax_columns, power_query, schema, relationships.
        pages: a list of pages from lineage (for board patterns), optional.

    Returns:
        dict {meta, summary, findings}
    """
    reg = _registry()
    meta = {
        "type": "pbi_antipatterns",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "anti_patterns": len(reg),
    }

    findings: dict[str, list] = defaultdict(list)  # level -> list of findings

    # ---- sources (M code) ----
    pq = m.power_query
    if hasattr(pq, "iterrows"):
        for _, row in pq.iterrows():
            findings["source"] += analyze_source_m(row["Expression"], row["TableName"])
    else:
        for tbl, expr in pq.items():
            findings["source"] += analyze_source_m(expr, tbl)

    # ---- DAX measures ----
    measures_exprs_by_table: dict[str, list[str]] = defaultdict(list)
    for _, row in m.dax_measures.iterrows():
        t = row["TableName"]
        expr = row["Expression"]
        findings["measure"] += analyze_measure(row["Name"], expr)
        measures_exprs_by_table[t].append(expr)

    # ---- calculated columns ----
    for _, row in m.dax_columns.iterrows():
        findings["calc_column"] += analyze_calc_column(
            row["TableName"], row["ColumnName"], row["Expression"]
        )

    # ---- tables (aggregated) ----
    tables_json = {}
    n_cols_by_table = defaultdict(int)
    for _, row in m.schema.iterrows():
        n_cols_by_table[row["TableName"]] += 1
    for t in m.tables:
        tables_json[t] = {
            "measures_count": len(measures_exprs_by_table.get(t, [])),
            "columns_count": n_cols_by_table.get(t, 0),
        }
        exprs = [e for e in measures_exprs_by_table.get(t, []) if isinstance(e, str)]
        findings["table"] += analyze_table(t, tables_json[t], exprs)

    # ---- board ----
    total = {
        "sources": len(m.power_query),
        "measures": len(m.dax_measures),
        "calc_columns": len(m.dax_columns),
        "tables": len(m.tables),
    }
    if pages is not None:
        findings["board"] = analyze_board(
            {"file": meta.get("file", "board")}, pages, total
        )

    # ---- summary by id ----
    id_counter: Counter = Counter()
    for items in findings.values():
        for it in items:
            id_counter[it["id"]] += 1

    return {
        "meta": meta,
        "summary": {
            "total_findings": sum(len(v) for v in findings.values()),
            "by_level": {lv: len(v) for lv, v in findings.items()},
            "by_id": dict(id_counter),
            "critical": sum(1 for v in findings.values() for it in v if it["critical"]),
            "counts": total,
        },
        "findings": {lv: findings[lv] for lv in sorted(findings)},
    }


def analyze_pbix(pbix_path: str) -> dict:
    """Analyze a .pbix for antipatterns: input .pbix, output JSON metric."""
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    with PbiLineage(pbix_path) as lg:
        m = lg._model
        pages_json = lg.to_json(include_plantuml=False).get("pages", [])
        data = analyze_board_objects(m, pages=pages_json)
        data["meta"]["file"] = lg.pbix_path.name
        return data


def _write(data: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    from agentic_bi.cli_support import fail, run_boundary

    parser = argparse.ArgumentParser(
        prog="agentic-bi-antipatterns",
        description="Antipattern analysis of Power BI calculations (source M code + DAX inside the board).\n"
        "Output: JSON with an antipattern metric tied to the level (source/measure/calc/table/board).",
    )
    parser.add_argument("pbix", help="path to the .pbix file")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="output JSON (default output_files/<name>_antipatterns.json)",
    )
    parser.add_argument(
        "--summary", action="store_true", help="print a short console summary"
    )
    args = parser.parse_args(argv)

    pbix = Path(args.pbix)
    if not pbix.exists():
        return fail("agentic-bi-antipatterns", f"input not found: {pbix}")

    def body() -> int:
        data = analyze_pbix(str(pbix))
        out = (
            Path(args.output)
            if args.output
            else Path("output_files") / f"{pbix.stem}_antipatterns.json"
        )
        _write(data, out)
        print(f"Antipatterns saved: {out}")
        if args.summary:
            s = data["summary"]
            print(f"Total findings: {s['total_findings']} (critical: {s['critical']})")
            for lv, cnt in s["by_level"].items():
                print(f"  {lv:12} {cnt}")
            print("By type:")
            for aid, cnt in sorted(s["by_id"].items(), key=lambda kv: -kv[1]):
                name = _registry().get(aid).name if _registry().get(aid) else aid
                print(f"  {aid:32} x{cnt}  {name}")
        return 0

    return run_boundary(body, prog="agentic-bi-antipatterns")


if __name__ == "__main__":
    raise SystemExit(main())

