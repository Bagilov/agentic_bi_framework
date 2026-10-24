"""Summary/index building mixin for the Report Server bulk analysis."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class IndexMixin:
    def build_index(self, results: list[dict]) -> dict:
        """Summary registry across all boards (for index.json)."""
        rows = []
        for res in results:
            if "error" in res:
                rows.append(
                    {
                        "root": res.get("root"),
                        "name": res.get("name"),
                        "path": res.get("path"),
                        "error": res.get("error"),
                    }
                )
                continue
            lin = res.get("lineage", {})
            summary = lin.get("summary", {})
            ap = res.get("antipatterns", {})
            ap_summary = ap.get("summary", {})
            brand = lin.get("brand", {}).get("summary", {}) or {}
            rows.append(
                {
                    "root": res.get("root", ""),
                    "name": res.get("name"),
                    "path": res.get("path"),
                    "pages": summary.get("pages", 0),
                    "visuals": summary.get("visuals", 0),
                    "tables_total": summary.get("tables", 0),
                    "tables_business": summary.get("business_tables", 0),
                    "measures": summary.get("measures", 0),
                    "calc_columns": summary.get("calc_columns", 0),
                    "power_queries": summary.get("power_queries", 0),
                    "sources": summary.get("sources", 0),
                    "sources_with_data": summary.get("sources_with_data", 0),
                    "antipatterns_total": ap_summary.get("total_findings", 0),
                    "antipatterns_critical": ap_summary.get("critical", 0),
                    "brand_fonts_pct": brand.get("fonts_compliance"),
                    "brand_colors_pct": brand.get("colors_compliance"),
                    "brand_ok_pages": brand.get("ok", 0),
                    "brand_warning_pages": brand.get("warnings", 0),
                    "brand_error_pages": brand.get("errors", 0),
                    "analyzed_at": res.get("analyzed_at"),
                }
            )
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "boards": rows,
            "n": len(rows),
        }

    # --- main run ---------------------------------------------------------
    def finalize(self, results: list[dict]) -> Path:
        idx = self.report_out / "index.json"
        idx.write_text(
            json.dumps(self.build_index(results), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return idx

    def drill_path(self) -> Path:
        return self.report_out / "drill_index.parquet"

    def save_drill(self, results: list[dict]) -> Path:
        """Save a flat drill index to Parquet (one row per element).
        Extraction from ready boards: for each element (source/table/measure/
        page/finding) a separate row is generated, enriched with board values.
        Reads well in Power BI."""
        try:
            import pandas as pd
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as e:  # noqa: BLE001
            logger.error("pyarrow is not installed - parquet unavailable (%s)", e)
            raise

        rows = self._drill_rows(results)
        out = self.drill_path()
        if rows:
            df = pd.DataFrame(rows)
            for col in df.columns:
                try:
                    df[col] = pd.to_numeric(df[col], errors="ignore")
                except Exception:  # noqa: BLE001
                    pass
            table = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_table(table, out, compression="snappy")
        else:
            pd.DataFrame().to_parquet(out, engine="pyarrow")
        logger.info("Drill parquet saved: %s (rows %d)", out, len(rows))
        return out

    def _drill_rows(self, results: list[dict]) -> list[dict]:
        """Flat drill rows: one row per board element."""
        rows: list[dict] = []
        run_at = datetime.now().isoformat(timespec="seconds")

        # a single set of all antipatterns - so has_* flags exist on EVERY board
        # (0 when absent, not NaN) and the dashboard can filter by one metric.
        all_ids: set[str] = set()
        for res in results:
            if "error" in res:
                continue
            all_ids.update(
                (res.get("antipatterns", {}).get("summary", {}) or {}).get("by_id", {})
                or {}
            )

        def base(res: dict) -> dict:
            lin = res.get("lineage", {})
            summary = lin.get("summary", {})
            ap = res.get("antipatterns", {})
            asum = ap.get("summary", {})
            bsum = lin.get("brand", {}).get("summary", {}) or {}
            by_id = asum.get("by_id", {}) or {}
            # server placement path on the Report Server: /<root>/<folder...>/<Name>
            srv = res.get("path") or ""
            is_server = srv.startswith("/")
            folder = srv.rsplit("/", 1)[0] if is_server else None
            depth = srv.count("/") if is_server else 0
            d = {
                "board": res.get("name"),
                "root": res.get("root"),
                "board_path": res.get("path"),
                "board_server_path": srv if is_server else None,  # full server path
                "board_folder": folder,  # placement folder (without the report name)
                "board_folder_depth": depth,  # folder nesting depth
                "analyzed_at": res.get(
                    "analyzed_at"
                ),  # when the board itself was analyzed
                "index_built_at": run_at,  # when this drill index was built
                "board_pages": summary.get("pages", 0),
                "board_visuals": summary.get("visuals", 0),
                "board_tables_total": summary.get("tables", 0),
                "board_tables_business": summary.get("business_tables", 0),
                "board_measures": summary.get("measures", 0),
                "board_calc_columns": summary.get("calc_columns", 0),
                "board_sources": summary.get("sources_with_data", 0),
                "board_ap_total": asum.get("total_findings", 0),
                "board_ap_critical": asum.get("critical", 0),
                "board_brand_fonts": bsum.get("fonts_compliance"),
                "board_brand_colors": bsum.get("colors_compliance"),
                "board_brand_errors": bsum.get("errors", 0),
            }
            # presence flags of specific antipatterns on the board (0/1).
            # set for ALL known ap_id - 0 if the pattern is absent.
            for aid in all_ids:
                d[f"has_{aid}"] = 1 if by_id.get(aid, 0) > 0 else 0
            return d

        for res in results:
            if "error" in res:
                rows.append(
                    {
                        "board": res.get("name"),
                        "root": res.get("root"),
                        "level": "board",
                        "error": res.get("error"),
                        "analyzed_at": res.get("analyzed_at"),
                        "index_built_at": run_at,
                    }
                )
                continue
            b = base(res)
            lin = res.get("lineage", {})
            ap = res.get("antipatterns", {})
            # --- sources ---
            sources = lin.get("sources")
            by_table = sources.get("by_table", {}) if isinstance(sources, dict) else {}
            for t, s in (by_table or {}).items():
                rows.append(
                    {
                        **b,
                        "level": "source",
                        "element": t,
                        "source_type": s.get("type"),
                        "source_path": s.get("path"),
                        "source_detail": s.get("detail"),
                        "status": s.get("status"),
                    }
                )
            # --- tables ---
            for t, tb in lin.get("tables", {}).items():
                rows.append(
                    {
                        **b,
                        "level": "table",
                        "element": t,
                        "technical": tb.get("technical"),
                        "columns": tb.get("columns_count", 0),
                        "measures": tb.get("measures_count", 0),
                        "source_type": (tb.get("source") or {}).get("type"),
                        "source_path": (tb.get("source") or {}).get("path"),
                        "table_refs": tb.get("refs", 0),
                    }
                )
            # --- measures ---
            for t, sem in lin.get("semantics", {}).items():
                for m in sem.get("measures", []):
                    mname = m.get("name") if isinstance(m, dict) else m
                    rows.append(
                        {
                            **b,
                            "level": "measure",
                            "element": mname,
                            "table": t,
                            "measure_refs": m.get("refs")
                            if isinstance(m, dict)
                            else None,
                        }
                    )
            # --- pages ---
            for pg in lin.get("pages", []):
                bm = pg.get("brand") or {}
                rows.append(
                    {
                        **b,
                        "level": "page",
                        "element": pg.get("name"),
                        "page_index": pg.get("index"),
                        "page_visuals": pg.get("n_visuals", 0),
                        "page_refs": pg.get("refs", 0),
                        "page_tables": ", ".join(pg.get("tables", [])),
                        "page_brand_fonts": (bm.get("fonts") or {}).get("compliance"),
                        "page_brand_colors": (bm.get("colors") or {}).get("compliance"),
                        "page_brand_status": bm.get("level"),
                        "page_brand_has_red": (bm.get("colors") or {}).get("has_red"),
                    }
                )
            # --- antipattern findings ---
            for lvl, findings in ap.get("findings", {}).items():
                for f in findings:
                    rows.append(
                        {
                            **b,
                            "level": f"ap_{f.get('level', lvl)}",
                            "element": f.get("scope"),
                            "ap_id": f.get("id"),
                            "ap_name": f.get("name"),
                            "ap_critical": f.get("critical"),
                            "ap_detail": f.get("detail"),
                            "ap_fix": f.get("fix"),
                        }
                    )
        return rows

    # --- drill-down index -------------------------------------------------

    def load_board_results(self) -> list[dict]:
        """Load ready board JSONs from report_out (to rebuild indexes)."""
        results = []
        for sub in self.report_out.iterdir():
            if not sub.is_dir() or sub.name in ("pbix_tmp", "sources_pbix"):
                continue
            for jf in sub.glob("*.json"):
                try:
                    results.append(json.loads(jf.read_text(encoding="utf-8")))
                except json.JSONDecodeError as e:  # noqa: BLE001
                    logger.warning("skip %s: %s", jf, e)
        return results
