"""Model extraction, report-layout parsing and data-source resolution mixin."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from pbixray import LiveConnectionError, NoEmbeddedModelError, PBIXRay

from agentic_bi.lineage.lineage_types import (
    Page,
    Source,
    SourceAccessError,
    Visual,
    VisualBinding,
    _split_table_col,
    _strip_aggs,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from agentic_bi.lineage.pbi_lineage import PbiLineage

logger = logging.getLogger(__name__)


class ModelMixin:
    def _open_model(self) -> None:
        try:
            self._model = PBIXRay(str(self.pbix_path))
        except LiveConnectionError as e:
            raise ValueError(
                f"Thin report (no embedded model): {getattr(e, 'database_name', None)}"
            ) from e
        except NoEmbeddedModelError as e:
            raise ValueError("No embedded data model") from e
        except zipfile.BadZipFile as e:
            raise SourceAccessError(
                f"File is corrupted or is not a .pbix: {self.pbix_path}"
            ) from e
        except PermissionError as e:
            raise SourceAccessError(
                f"No permission to read the file: {self.pbix_path}"
            ) from e
        except OSError as e:
            raise SourceAccessError(
                f"Could not open the file (OSError): {self.pbix_path} ({e})"
            ) from e
        except Exception as e:
            # any other pbixray errors (corrupted model, unsupported
            # compression, etc.) - an explicit clear error instead of a traceback
            raise SourceAccessError(
                f"Could not open the model in {self.pbix_path.name}: {e}"
            ) from e

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

    # ---------------- extract artifacts ----------------
    def _load_model_artifacts(self) -> None:
        assert self._model is not None
        m = self._model

        self.tables: list[str] = list(m.tables)
        self._tables_lower: dict[str, str] = {t.lower(): t for t in self.tables}

        self.measures: dict[str, list[str]] = defaultdict(list)
        for _, row in m.dax_measures.iterrows():
            self.measures[row["TableName"]].append(row["Name"])

        self.calc_columns: dict[str, list[str]] = defaultdict(list)
        for _, row in m.dax_columns.iterrows():
            self.calc_columns[row["TableName"]].append(row["ColumnName"])

        self.power_query: dict[str, str] = {}
        for _, row in m.power_query.iterrows():
            self.power_query[row["TableName"]] = row["Expression"]

        self.columns: dict[str, list[str]] = defaultdict(list)
        for _, row in m.schema.iterrows():
            self.columns[row["TableName"]].append(row["ColumnName"])

        self.relationships = m.relationships

    def _load_layout(self) -> None:
        try:
            with zipfile.ZipFile(self.pbix_path) as z:
                raw = z.read("Report/Layout")
        except (zipfile.BadZipFile, KeyError) as e:
            raise SourceAccessError(
                f"Could not read Report/Layout from the .pbix: {e}"
            ) from e
        for enc in ("utf-16", "utf-8", "utf-8-sig"):
            try:
                self._layout = json.loads(raw.decode(enc))
                return
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        raise ValueError("Could not decode Report/Layout")

    # ---------------- normalize the table name ----------------
    def _resolve_table(self, token: str) -> str | None:
        """Resolve a display/layout name to the physical model table.

        Names are matched case-insensitively: DAX/visuals resolve table names
        without regard to case, and a donor or patched layout frequently carries a
        different case than the model, so an exact-case test would silently drop
        the relationship. An aggregation wrapper is stripped first.
        """
        if not isinstance(token, str):
            return None
        raw = _strip_aggs(token).strip()
        # strip a possible 'Table.Column' suffix (the table part comes first)
        raw = raw.split(".", 1)[0].strip()
        phys = self.display_aliases.get(raw, raw)
        if phys in self.tables:
            return phys
        by_lower = self._tables_lower.get(raw.lower())
        if by_lower is not None:
            return by_lower
        self._unresolved_table_refs.add(raw)
        return None

    # ---------------- build pages/visuals ----------------
    _HEX_RE = re.compile(r"#([0-9A-Fa-f]{6,8})\b")
    _THEME_RE = re.compile(r'"ThemeDataColor"\s*:\s*\{\s*"ColorId"\s*:\s*(\d+)')
    _FONT_RE = re.compile(r'"fontFamily"\s*:\s*"([^"]+)"')

    def _collect_colors(self, sv: dict) -> set[str]:
        """Collect the unique colors of a singleVisual: hex + ThemeDataColor(ColorId)."""
        text = json.dumps(sv, ensure_ascii=False)
        colors: set[str] = set()
        for m in self._HEX_RE.finditer(text):
            hexv = m.group(1).upper()
            colors.add(f"hex#{hexv[:6]}")
        for m in self._THEME_RE.finditer(text):
            colors.add(f"theme#{m.group(1)}")
        return colors

    def _collect_fonts(self, sv: dict) -> set[str]:
        """Collect the unique families actually set in a singleVisual."""
        text = json.dumps(sv, ensure_ascii=False)
        return {m.group(1) for m in self._FONT_RE.finditer(text)}

    def _collect_visual_fonts(self, page: Page) -> list[str]:
        """Unique fonts used by the page visuals (stable order)."""
        fonts: set[str] = set()
        for v in page.visuals:
            fonts |= v.fonts
        return sorted(fonts)

    def _parse_visual(self, vc: dict, page_idx: int, page_name: str) -> Visual | None:
        cfg = vc.get("config", "")
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except json.JSONDecodeError:
                cfg = None
        if not isinstance(cfg, dict):
            return None
        sv = cfg.get("singleVisual", {})
        proj = sv.get("projections", {})
        bindings: list[VisualBinding] = []
        for role, items in proj.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict) and it.get("queryRef"):
                    qr = it["queryRef"]
                    tbl, col = _split_table_col(qr)
                    bindings.append(
                        VisualBinding(
                            role=role,
                            query_ref=qr,
                            table=self._resolve_table(tbl),
                            column=col,
                        )
                    )
        return Visual(
            page=page_name,
            page_idx=page_idx,
            visual_type=sv.get("visualType", "?"),
            z_index=str(vc.get("z", "")),
            bindings=bindings,
            colors=self._collect_colors(sv),
            fonts=self._collect_fonts(sv),
        )

    def _build(self) -> None:
        sections = self._layout.get("sections", [])
        sections = sorted(sections, key=lambda s: s.get("ordinal", 0))

        self.pages: list[Page] = []
        for i, sec in enumerate(sections):
            name = sec.get("displayName") or sec.get("name") or f"Page{i + 1}"
            visuals: list[Visual] = []
            for vc in sec.get("visualContainers", []):
                v = self._parse_visual(vc, i + 1, name)
                if v is not None:
                    visuals.append(v)
            self.pages.append(Page(index=i + 1, name=name, visuals=visuals))

        # sources by table
        self.sources: dict[str, Source] = {}
        self.unresolved_sources: list[
            dict
        ] = []  # explicit report of unavailable/undetermined
        for tbl in self.tables:
            expr = self.power_query.get(tbl)
            if expr:
                src = self._source_from_m(expr)
            else:
                src = Source(
                    "No Power Query",
                    None,
                    status="no_power_query",
                    error=f"No M code (Power Query) for table {tbl}",
                )
            self.sources[tbl] = src
            if src.status in ("access_error", "unresolved", "no_power_query"):
                self.unresolved_sources.append(
                    {
                        "table": tbl,
                        "type": src.type,
                        "status": src.status,
                        "detail": src.detail,
                        "error": src.error,
                    }
                )

        # --- count references from the visual bindings ---
        # How many times a table/measure/column is used in visuals (board code).
        self.table_refs: Counter = Counter()
        self.field_refs: Counter = Counter()  # by the whole queryRef
        for p in self.pages:
            for v in p.visuals:
                for b in v.bindings:
                    self.field_refs[b.query_ref] += 1
                    if b.table:
                        self.table_refs[b.table] += 1

    def _resolve_refs(self) -> dict:
        """Map queryRef -> (measure|column -> name) for detailed counting.

        A queryRef of the form 'Table.Name' for columns and 'Name' /
        'Table.Measure' for measures. Returns {measure: count, column: count}.
        """
        measure_map: dict[str, str] = {}  # displayed -> name
        for tbl, names in self.measures.items():
            for n in names:
                measure_map[f"{tbl}.{n}"] = n
                measure_map[n] = n
        col_map: dict[str, str] = {}
        for tbl, names in self.columns.items():
            for n in names:
                col_map[f"{tbl}.{n}"] = n
        out = {"measures": Counter(), "columns": Counter()}
        for qr, cnt in self.field_refs.items():
            if qr in measure_map:
                out["measures"][measure_map[qr]] += cnt
            elif qr in col_map:
                out["columns"][qr] += cnt
            else:
                # try to split 'Table.col'
                if "." in qr:
                    t, c = qr.split(".", 1)
                    if c in measure_map:
                        out["measures"][c] += cnt
                    elif c in col_map:
                        out["columns"][c] += cnt
        return out

    # ---------------- determine the source from M code ----------------
