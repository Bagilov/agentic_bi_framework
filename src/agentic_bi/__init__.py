"""Programmatic generation of Power BI `.pbix` reports without Power BI Desktop.

The implementation is built up iteratively:
  Iter 1. Empty valid `.pbix` (honest zip + Report/Layout scaffold)
  Iter 2. Data model (model.bim: tables/columns/measures)
  Iter 3. Visuals (card, bar, table) in the layout
  Iter 4. Data source (CSV/JSON/Parquet) + M code
  Iter 5. Read-back (round-trip) + verification
  Iter 6. CLI + documentation + tests

Key finding from iteration 1 (verified against real .pbix files + discussed with Kimi K3):
- A `.pbix` is an ORDINARY zip archive (starts with `PK`), it contains no PBIX magic.
- `Version` inside the zip is a UTF-16LE string `"1.28"` (8 bytes), not a binary version.
- `[Content_Types].xml` uses `Default` + `Override` parts.
- Page/visual layout lives in `Report/Layout` (JSON), NOT in
  `Report/Sections/section1.json`.

Canonical model build (found 2026-09-26):
- The binary VertiPaq `DataModel` cannot be generated from scratch in Python
  (closed XPress9 format). The canonical serialization is performed by the
  **AS engine** of Power BI Desktop RS (`msmdsrv.exe`) — module
  `engine.EnginePipeline`: data -> model via TOM -> `Server.ImageSave` ->
  container -> oracle.
- The report is built from scratch (`engine_layout`) — without donor visuals.

Engine build modules: `engine.py`, `engine_container.py`, `engine_layout.py`,
`engine_cli.py`, `_engine_build.ps1`, `_engine_oracle.py`.

Reverse self-testing: `engine_verify.py` (container, layout, bindings,
filter safety, model data read-back). Wired into `EnginePipeline.run()`
(verify=True by default) and into the CLI (`--verify`).

`agentic_bi` is environment-agnostic: all environment-specific values
(hosts, URLs, shares, paths) are passed via configuration or CLI flags.
"""

__version__ = "0.0.1b1"

__all__ = ["__version__"]
