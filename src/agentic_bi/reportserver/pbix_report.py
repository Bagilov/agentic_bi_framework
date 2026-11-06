"""Per-board analysis: lineage + antipatterns for one .pbix, and local re-analysis.

`PbiRsBulk` (see `agentic_bi.reportserver.pbix_analysis`) composes this mixin
with `IndexMixin`: the orchestrator owns catalog discovery and download, this
module owns what is computed from a downloaded file and how the per-board JSON
is rewritten.

Public API:
    AnalysisMixin.analyze(pbix) -> dict
    AnalysisMixin.reanalyze_local(keep_dir) -> (ok, results)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Protocol

from agentic_bi.reportserver.catalog import item_str, slug
from agentic_bi.reportserver.reportserver_client import config_str_list

logger = logging.getLogger(__name__)


class BulkState(Protocol):
    """The `PbiRsBulk` state and helpers the analysis mixin reads."""

    cfg: dict[str, object]
    report_out: Path
    skip_ap: bool

    def list_powerbi(self, roots: list[str]) -> list[dict]: ...

    def analyze(self, pbix: Path) -> dict: ...


class AnalysisMixin:
    """Analysis half of `PbiRsBulk`: one .pbix in, one board result out."""

    # --- analyze one file -------------------------------------------------
    def analyze(self: BulkState, pbix: Path) -> dict:
        from agentic_bi.lineage.pbi_lineage import PbiLineage

        with PbiLineage(str(pbix)) as lg:
            lineage = lg.to_json()

        result = {
            "file": pbix.name,
            "path": str(pbix),
            "analyzed_at": datetime.now().isoformat(timespec="seconds"),
            "lineage": lineage,
        }
        if not self.skip_ap:
            try:
                from agentic_bi.antipatterns.pbi_antipatterns import analyze_pbix

                ap = analyze_pbix(str(pbix))
                result["antipatterns"] = ap
            except Exception as e:  # noqa: BLE001
                logger.warning("Antipatterns %s: %s", pbix.name, e)
        return result

    def reanalyze_local(self: BulkState, keep_dir: Path) -> tuple[int, list[dict]]:
        """Re-analyze local .pbix files (without a server), rewriting the board JSON.

        Useful after a schema change (`to_json`) - to refresh source fields
        (path/type) and rebuild a fresh drill index without re-downloading.

        Args:
            keep_dir: the saved-sources directory (sources_pbix/<root>).

        Returns:
            (number of successes, results)
        """
        ok = 0
        results: list[dict] = []
        # maps id(8) -> displayed name and server path from the catalog
        id2name: dict[str, str] = {}
        id2path: dict[str, str] = {}
        for item in self.list_powerbi(config_str_list(self.cfg, "roots")):
            iid = str(item.get("Id") or "")
            if not iid:
                continue
            id2name[iid[:8]] = item_str(item, "Name") or "?"
            id2path[iid[:8]] = item_str(item, "Path")
        for root_dir in sorted(keep_dir.iterdir()) if keep_dir.exists() else []:
            if not root_dir.is_dir():
                continue
            root_key = (
                "/" + root_dir.name
                if not root_dir.name.startswith("/")
                else root_dir.name
            )
            for pbix in sorted(root_dir.glob("*.pbix")):
                stem = pbix.stem
                try:
                    res = self.analyze(pbix)
                    res["root"] = root_key
                    id8 = stem.split("_")[-1]
                    res["name"] = id2name.get(id8) or (
                        stem.rsplit("_", 1)[0] if "_" in stem else stem
                    )
                    # the server path (Report Server folder) matters more than the file name
                    res["path"] = id2path.get(id8) or pbix.name
                    per = self.report_out / slug(root_key) / f"{stem}.json"
                    per.parent.mkdir(parents=True, exist_ok=True)
                    per.write_text(
                        json.dumps(res, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                    results.append(res)
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    logger.error("reanalyze %s: %s", pbix.name, e)
                    results.append(
                        {"root": root_key, "name": pbix.stem, "error": str(e)}
                    )
        return ok, results
