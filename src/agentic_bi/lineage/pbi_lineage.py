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
        origins: source-origin map as a `{"origins": [...]}` dict or a path to a
            YAML/JSON file; `None` uses the built-in neutral default.
        brand_config: path to `brand_config.yaml/json` (brand rules for page
            compliance metrics); defaults to `brand.py`.
    """

    # Technical tables (DateTable / LocalDateTable), created by Power BI
    _TECH_PREFIXES = ("DateTableTemplate_", "LocalDateTable_")

    def __init__(
        self,
        pbix_path: str | Path,
        display_aliases: dict[str, str] | None = None,
        origins: dict | str | Path | None = None,
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
