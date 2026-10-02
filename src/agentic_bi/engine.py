"""Pipeline to build a `.pbix` from tabular data via the Power BI Desktop RS AS engine.

The engine itself (`msmdsrv.exe`) performs the canonical model serialization, so
the binary VertiPaq `DataModel` is guaranteed valid; the report is built from
scratch with our own methods (`engine_layout`).

Public API:
    EnginePipeline(template=..., desktop=..., work_dir=...)
    EnginePipeline.load_rows(path) -> list[dict]
    EnginePipeline.build_spec(rows, table, database) -> dict
    EnginePipeline.run(data, table, database, out, check_oracle, hold, clean_layout) -> dict
    EnginePipeline.run_oracle(pbix, hold) -> str
    EnginePipeline.verify(pbix, spec, pages=None, sample=50, strict=True, model=True) -> dict

`run()` by default (verify=True) performs a reverse self-test: container, layout,
bindings, filter safety and model data read-back (`engine_verify`). With
`strict_verify` a failed check raises RuntimeError.

Requires Windows + Power BI Desktop RS. Data: CSV / JSON / JSONL.

Environment-specific values (the Desktop RS executable path and the template
.pbix) are NOT hardcoded: set them via the constructor / CLI flags, or override
the module defaults below.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agentic_bi.engine_types import coerce, is_date, try_fmt, to_iso, typed_column
import agentic_bi.engine_container as engine_container
import agentic_bi.engine_layout as engine_layout
import agentic_bi.engine_verify as engine_verify

logger = logging.getLogger(__name__)

# Default Desktop RS executable and workspace root (override via constructor).
PBI_RS = os.environ.get(
    "PBI_RS_DESKTOP",
    r"C:\Program Files\Power BI Desktop RS\bin\PBIDesktop.exe")
WS_ROOT = (Path.home() / "AppData" / "Local" / "Microsoft"
           / "Power BI Desktop SSRS" / "AnalysisServicesWorkspaces")
DEFAULT_TEMPLATE = Path(os.environ.get("PBI_RS_TEMPLATE", "templates/template.pbix"))

_DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                 "%d.%m.%Y", "%d.%m.%Y %H:%M:%S", "%Y/%m/%d")

_HERE = Path(__file__).resolve().parent
_ENGINE_PS1 = _HERE / "_engine_build.ps1"
_ORACLE_PY = _HERE / "_engine_oracle.py"


class EnginePipeline:
    """End-to-end: data -> engine model -> clean `.pbix` -> oracle."""

    def __init__(self, template: Path = DEFAULT_TEMPLATE, desktop: str = PBI_RS,
                 work_dir: Path | None = None) -> None:
        self.template = Path(template)
        self.desktop = desktop
        self.work_dir = Path(work_dir) if work_dir else _HERE / "output_files" / "_work"
        self.work_dir.mkdir(parents=True, exist_ok=True)

    # -- data -> spec -------------------------------------------------------
    @staticmethod
    def load_rows(path: Path) -> list[dict]:
        """Load rows from CSV / JSON / JSONL."""
        suffix = path.suffix.lower()
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        if suffix in (".json", ".jsonl", ".ndjson"):
            text = path.read_text(encoding="utf-8").strip()
            if suffix == ".jsonl" or (text.startswith("{") and "\n{" in text):
                return [json.loads(line) for line in text.splitlines() if line.strip()]
            data = json.loads(text)
            return data if isinstance(data, list) else [data]
        raise ValueError(f"unsupported input: {path.suffix}")

    @staticmethod
    def build_spec(rows: list[dict], table: str, database: str) -> dict:
        """Infer column types and return the build spec for the engine."""
        if not rows:
            raise ValueError("no rows")
        cols = []
        for key in rows[0].keys():
            vals = [EnginePipeline._coerce(r.get(key)) for r in rows]
            cols.append(EnginePipeline._typed_column(key, vals))
        return {"database": database,
                "tables": [{"name": table, "columns": cols}]}

    # -- engine -------------------------------------------------------------
    def _kill(self) -> None:
        for img in ("PBIDesktop.exe", "msmdsrv.exe"):
            subprocess.run(["taskkill", "/F", "/IM", img], capture_output=True)
        time.sleep(4)

    def _wait_port(self, timeout: int = 60) -> int:
        t0 = time.time()
        while time.time() - t0 < timeout:
            ws = sorted(WS_ROOT.glob("*"), key=lambda p: p.stat().st_mtime,
                        reverse=True)
            if ws:
                port_file = ws[0] / "Data" / "msmdsrv.port.txt"
                if port_file.exists():
                    return int(port_file.read_text().replace("\x00", "").strip())
            time.sleep(1)
        raise TimeoutError("engine port not found")

    def _run_engine_build(self, spec_path: Path, abf: Path) -> str:
        """Run `_engine_build.ps1` with one retry (the engine does not start at once)."""
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(_ENGINE_PS1), "-Spec", str(spec_path),
               "-Out", str(abf)]
        proc = None
        for attempt in (1, 2):
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if abf.exists():
                return (proc.stdout or "")[-400:]
            if attempt == 1:
                time.sleep(15)
        logger.error("engine build failed: %s", (proc.stdout or "")[-400:])
        raise RuntimeError(f"engine build failed:\n{(proc.stdout or '')[-400:]}\n"
                           f"{(proc.stderr or '')[-400:]}")

    def build_datamodel(self, spec: dict) -> bytes:
        """Start the engine and get the canonical DataModel (ImageSave stream)."""
        self._kill()
        subprocess.Popen([self.desktop, str(self.template)])
        port = self._wait_port()
        logger.info("engine port %s", port)

        spec_path = Path(tempfile.gettempdir()) / f"pbix_spec_{int(time.time())}.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        abf = self.work_dir / "engine_out.abf"
        if abf.exists():
            abf.unlink()
        tail = self._run_engine_build(spec_path, abf)
        logger.info("engine tail: %s", tail.strip()[-200:])
        return abf.read_bytes()

    # -- assembly -----------------------------------------------------------
    def assemble(self, datamodel: bytes, spec: dict, out: Path,
                 clean_layout: bool = True) -> Path:
        """Write `out`: a clean layout (default) or the donor layout."""
        if clean_layout:
            layout = engine_layout.build_layout_from_spec(spec)
            engine_container.build_container(self.template, layout, datamodel, out)
        else:
            engine_container.swap_datamodel(self.template, datamodel, out)
        return out

    # -- oracle -------------------------------------------------------------
    @staticmethod
    def run_oracle(pbix: Path, hold: int) -> str:
        """Strict open check in Desktop RS; return the verdict."""
        proc = subprocess.run([sys.executable, str(_ORACLE_PY),
                               str(pbix.resolve()), str(hold)],
                              cwd=str(_HERE), capture_output=True, text=True,
                              timeout=hold + 120)
        verdicts = re.findall(r"RESULT\s*\[([A-Z_]+)\]", proc.stdout + proc.stderr)
        return verdicts[-1] if verdicts else "NO_RESULT"

    # -- reverse self-test --------------------------------------------------
    def verify(self, pbix: Path, spec: dict,
               pages: dict[str, int] | None = None, sample: int = 50,
               strict: bool = True, model: bool = True,
               layout_checks: bool = True, strict_soft: bool = False,
               expected_types: set[str] | None = None,
               brand: bool = True, brand_strict: bool = False) -> dict:
        """Reverse-check the `.pbix` against the build spec.

        Checks: container integrity, presence of pages/visuals, that all fields
        reference real objects, absence of "dangerous" IN-filters, that the model
        returns the expected data (best-effort via pbixray) and that the theme
        matches the brand book (`brand.py`).

        With `strict=True`, a failed critical check raises RuntimeError; the model
        read-back (non-critical) fails the build only with `strict_soft=True`.
        Brand findings are critical only with `brand_strict=True` (level `error`).

        Returns:
            dict: {ok, critical_ok, passed, failed, critical_failed,
                   soft_failed, failures, checks}
        """
        report = engine_verify.verify_pbix(
            Path(pbix), spec, pages=pages, sample=sample, model=model,
            layout_checks=layout_checks, expected_types=expected_types,
            brand=brand, brand_strict=brand_strict)
        if strict:
            report.raise_if_failed(strict_soft=strict_soft)
        return {
            "ok": report.ok(),
            "critical_ok": report.critical_ok(),
            "passed": report.passed,
            "failed": report.failed,
            "critical_failed": len(report.critical_failures),
            "soft_failed": len(report.soft_failures),
            "failures": [c.name for c in report.failures],
            "checks": report.checks,
        }

    def verify_layout_only(self, pbix: Path, spec: dict,
                           pages: dict[str, int] | None = None,
                           strict: bool = True) -> dict:
        """Fast check without the model read-back (no pbixray needed)."""
        return self.verify(pbix, spec, pages=pages, strict=strict, model=False)

    # -- orchestration ------------------------------------------------------
    def run(self, data: Path, table: str, database: str, out: Path,
            check_oracle: bool = True, hold: int = 70,
            clean_layout: bool = True, verify: bool = True,
            strict_verify: bool = True, pages: dict[str, int] | None = None,
            sample: int = 50, model_verify: bool = True,
            strict_soft: bool = False, brand_verify: bool = True,
            brand_strict: bool = False) -> dict:
        """Full run: data -> datamodel -> container -> checks -> oracle."""
        rows = self.load_rows(data)
        spec = self.build_spec(rows, table, database)
        logger.info("rows=%d cols=%d", len(rows), len(spec["tables"][0]["columns"]))

        datamodel = self.build_datamodel(spec)
        self.assemble(datamodel, spec, out, clean_layout=clean_layout)
        result = {"out": str(out), "rows": len(rows),
                  "pbix_bytes": out.stat().st_size,
                  "datamodel_bytes": len(datamodel),
                  "layout": "clean" if clean_layout else "donor"}
        if verify:
            report = self.verify(out, spec, pages=pages, sample=sample,
                                 strict=strict_verify, model=model_verify,
                                 layout_checks=clean_layout,
                                 strict_soft=strict_soft,
                                 brand=brand_verify, brand_strict=brand_strict)
            result["verify"] = "ok" if report["critical_ok"] else "FAILED"
            result["verify_passed"] = report["passed"]
            result["verify_failed"] = report["failed"]
            result["verify_soft_failed"] = report["soft_failed"]
        result["oracle"] = self.run_oracle(out, hold) if check_oracle else "SKIPPED"
        self._kill()
        return result

    # -- type inference (delegates to engine_types) -------------------------
    _coerce = staticmethod(lambda v: coerce(v))
    _is_date = staticmethod(lambda v: is_date(v))
    _try_fmt = staticmethod(lambda v, fmt: try_fmt(v, fmt))
    _to_iso = staticmethod(lambda v: to_iso(v))
    _typed_column = staticmethod(lambda name, vals: typed_column(name, vals))
