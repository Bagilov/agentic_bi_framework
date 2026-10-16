# agentic_bi — automation for building and publishing Power BI dashboards

**Package:** `agentic_bi` (part of the `agentic_bi_framework` project)
**Purpose:** automate the full cycle "query → dashboard → publish to Report Server"

**Concepts, methods and techniques across all 5 aspects (develop, test, deploy,
control, support — including agent support) — see [FRAMEWORK.md](FRAMEWORK.md).**

---

## 1. Purpose

1. **Skeleton build** of a dashboard (KPI + chart + table + filters),
   config-driven — `skeleton.py`.
2. **Folding into a binary `.pbix`** — donor pattern: take a clean `.pbix`
   skeleton from Power BI Desktop (donor) and replace only `Report/Layout`,
   keeping the donor's binary VertiPaq `DataModel` byte-for-byte — `rebuild.py`.
3. **Layout validation against the donor model** — verify that visuals reference
   only real tables/columns/measures before publishing — `validate_pbix.py`.
4. **Publishing** — two ways:
   - directly via REST API v2.0 (`publish_pbix`) — `publish.py`;
   - via an external git-deploy client (`git-deploy`, optional, out-of-tree).

## 2. Why "skeleton from a donor"

- The binary VertiPaq `DataModel` (the `DataModel` member inside a `.pbix`)
  **cannot be generated from scratch in Python** — it is a closed format
  (XPress9 container).
- So the framework takes a **clean `.pbix` skeleton** from Power BI Desktop
  (donor) and replaces only `Report/Layout`.
- The layout references the donor's binary-model objects by name; the build
  generates exactly the layout (visuals/pages/filters), while the data comes
  from the donor model.

### 2.1 Canonical model build via the AS engine

No VertiPaq reverse-engineering is needed: canonical serialization is performed
by the **Power BI Desktop RS AS engine** (`msmdsrv.exe`). This lets you build a
`.pbix` from **arbitrary data** (not just a layout over a donor model).

```
data (CSV/JSON) -> model via TOM -> Server.ImageSave (canonical DataModel)
               -> container (scaffolding + our Report/Layout) -> Desktop oracle
```

- `engine.py` (`EnginePipeline`) — the orchestrator.
- `engine_host.py` — host discovery (Desktop exe, AS workspace root, donor template) and process plumbing (port/`taskkill`/PowerShell build/oracle).
- `engine_container.py` — OPC: read members, `swap_datamodel`, `build_container`.
- `engine_layout.py` — build `Report/Layout` from scratch (table/card/column/bar/line/pie/donut).
- `engine_cli.py` — CLI; `_engine_build.ps1` — TOM + `ImageSave`; `_engine_oracle.py` — strict open check.
- The report is assembled **from scratch** (no donor visuals); `--keep-donor-layout` keeps the donor layout.
- Verified: `MODEL_LOADED` across several datasets and visual sets.

## 3. Components

| File | Purpose |
|------|---------|
| `skeleton.py` | Generate a PBIP skeleton and layout: KPI/chart/table/filters, query structure |
| `rebuild.py` | `rebuild_pbix(src, out, ..., layout=...)` — fold a layout into a binary `.pbix` |
| `engine.py` | `EnginePipeline` — build a `.pbix` from arbitrary data via the Desktop AS engine |
| `engine_host.py` | Host/process plumbing: `PBI_RS`, `WS_ROOT`, `DEFAULT_TEMPLATE`, `wait_port`, `run_engine_build`, `run_oracle` |
| `engine_container.py` | OPC operations on a `.pbix`: `swap_datamodel`, `build_container`, `read_member` |
| `engine_layout.py` | Build `Report/Layout` from scratch: `Visual`, `build_report`, `build_layout_from_spec` |
| `engine_verify.py` | **Reverse self-test of a `.pbix`**: container, layout/pages, bindings, IN-filter guard, model read-back, **theme vs style guide** (`verify_brand`, `extract_report_theme`) |
| `engine_cli.py` | Engine-build CLI (`--data/--table/--out/--oracle/--verify`) |
| `_engine_build.ps1` / `_engine_oracle.py` | TOM+`ImageSave` and the strict Desktop oracle (internal) |
| `pbix_binary/` | **Binary DataModel (ABF) member editing**: member-level patching of a `.pbix`, equal- and **uneven-length** (re-layout with recomputed offsets). See [§16](#16-binary-datamodel-editing-pbix_binary) |
| `validate_pbix.py` | `validate_pbix(path)` — validate a produced `.pbix` layout against the donor model registry |
| `publish.py` | `publish_pbix(pbix, name, folder, cfg)` — publish directly via REST /api/v2.0 |
| `automate.py` | Orchestration: `run()`, `run_from_skeleton()`, `verify_published()`; CLI `--skeleton` |
| `board_fake.py` | A ready example: a board over real donor-model objects (KPI+chart+table+filters) |
| `board.py` | Declarative multi-page board builder (`Board`/`PageView`, auto-layout) |
| `spec.py` | Declarative spec (YAML/JSON): dashboard/quality/deploy/control/support → `Board` |
| `thresholds.py` | A single catalog of quality/deploy/build thresholds (value/unit/domain/why/source) |
| `brand.py` | Machine-readable brand style spec (palette/fonts/background/elements) for automated checks: `check_brand_compliance`, `rules_by_category`, `font_files` |
| `brand_config.py` / `brand_config.yaml` | Document-audit config: palette, fonts, backgrounds, severity, tolerances (`BrandConfig.load`) |
| `brand_audit.py` | Audit `.pptx` for brand compliance: `audit_pptx`, `audit_document`, CLI `python -m agentic_bi.brand_audit` (locations, JSON, `--fail-on`) |
| `agents.py` | Agent support: `SupportAgent` manifests by lifecycle stage, `resolve_agents`, `render_kilo_agent` |
| `inspect_board.py` | Inspect an existing Report Server dashboard: find by path → download `.pbix` → break down elements via PbiLineage |
| `dax_detail.py` | Deep DAX/M analysis of a `.pbix`: all measures with expressions, calc columns, M code, distortion-risk indices + antipattern summary |
| `docs/FRAMEWORK.md` | **Framework overview**: methods/techniques/concepts across the 5 aspects |
| `tests/` | Binary DataModel (`pbix_binary`) and web-clone (`web_report`) tests |

## 4. Quick start

### 4.0 Build a `.pbix` from arbitrary data (engine path)

A separate path: the model is built from data by the Desktop AS engine itself
(see §2.1).

```bash
cd agentic_bi_framework

# CSV -> .pbix (with a Desktop open check)
python -m agentic_bi.engine_cli \
    --data examples/engine_sales.csv --table Sales --database SalesDB \
    --out output_files/sales.pbix --oracle

# custom visuals (table/card/column/pie) — Python script
python examples/engine_custom_visuals.py
```

Example data/scripts are in `examples/`. Types are inferred automatically
(`Int64`/`Double`/`String`/`DateTime`). The report is built from scratch
(`--keep-donor-layout` keeps the donor layout).

### 4.1 Build and publish

```bash
cd agentic_bi_framework

# Build the .pbix only (no publish)
python -m agentic_bi.board_fake --dry-run

# Build, validate, publish and verify
python -m agentic_bi.board_fake
```

What `board_fake --dry-run` does:
1. `build_skeleton(...)` → a PBIP project under `output_files/skel_fake/`.
2. Enriches the layout resourcePackages/config from the donor.
3. `rebuild_pbix(src, out, layout=...)` → a binary `.pbix`.
4. `validate_pbix(out)` — if the layout references non-existent model objects,
   it **raises (RuntimeError)** and publishing does not happen.

A full run additionally:
5. `publish_pbix(out, name, folder, cfg)` to the configured folder.
6. `verify_published(server, folder, name)`.

Result (`--dry-run`):
```json
{
  "built":  { "path": "...", "size": 892454 },
  "validate": { "ok": true, "problems": [] },
  "publish": { "skipped": "dry-run" }
}
```

## 5. How `board_fake` works (configuration example)

`board_fake.py` builds a board over **real objects** of the donor model:

```python
TABLE = "fact_table"  # table for columns/axes/filters
MEASURE_TABLE = "kpi_measures"  # table the measures come from
MEASURES = [
    {"name": "metric_a", "expression": ""},
    {"name": "metric_b", "expression": ""},
]
```

`build_skeleton(...)` call:
- `table="fact_table"`, `measure_table="kpi_measures"` — columns from
  one table, measures from another.
- `kpi={"kind":"measure","property":"metric_a"}` — the "Metric A" KPI.
- `chart_type="lineChart"`, axis `period_start` (a fact_table column), value `metric_b` (a measure).
- `table_fields` = column `metric` + measures `metric_a`/`metric_b`.
- `filter_columns=["category","metric"]` — page-level filters.

### Visual field configuration

Each "field" is a dict with keys:
- `kind`: `"column"` | `"measure"` (if `agg:true` and `kind="column"` — an aggregated column).
- `property`: the object name in the donor model (e.g. `period_start`, `metric_a`).
- `display`: the label in the visual (e.g. `"Metric A"`).

## 6. Building an arbitrary skeleton (API)

The main function is `build_skeleton` (skeleton.py):

```python
from pathlib import Path
from agentic_bi.skeleton import build_skeleton, layout_from_report

pbir = build_skeleton(
    out=Path("output_files/my_proj"),  # project folder
    report_name="my_proj",  # name for .pbir/.Report/.Semantic
    display_name="My dashboard",  # page name
    table="fact_table",  # columns table
    measure_table="kpi_measures",  # measures table (opt.)
    columns=[
        {"name": "metric", "dataType": "string"},
        {"name": "period_start", "dataType": "datetime"},
    ],
    measures=[{"name": "metric_a", "expression": ""}],
    kpi={"kind": "measure", "property": "metric_a", "display": "Metric A"},
    chart_type="lineChart",  # or "clusteredColumnChart"
    chart_axis={"kind": "column", "property": "period_start", "display": "Period"},
    chart_value={"kind": "measure", "property": "metric_b", "display": "Metric B"},
    table_fields=[
        {"kind": "column", "property": "metric", "display": "Metric"},
        {"kind": "measure", "property": "metric_a", "display": "Metric A"},
    ],
    filter_columns=["category", "metric"],  # page-level filters
)
```

Logic:
- without `measure_table`, measures come from the same table as columns;
- with `measure_table`, measures use alias `s` and columns use alias `m`.
- `build_model` creates a model with empty DATATABLE partitions so the structure
  matches the donor's binary model.

## 7. Folding into a `.pbix` (rebuild)

```python
from pathlib import Path
from agentic_bi.rebuild import rebuild_pbix
from agentic_bi.skeleton import build_skeleton, layout_from_report

# 1. Build the skeleton
_, layout = build_skeleton(...)

# 2. Fold the layout into a binary .pbix (taking the DataModel from the donor)
out = rebuild_pbix(
    Path("donor.pbix"),  # binary DataModel source
    Path("output_files/my_dashboard.pbix"),
    layout=layout,  # our layout
)
```

`rebuild_pbix(src, out, layout=...)` copies all `.pbix` parts from `src`,
replacing only `Report/Layout` with the given layout (JSON, UTF-16LE without
BOM). `[Content_Types].xml` and other parts are preserved.

## 8. Validation before publishing (critical)

`validate_pbix` compares the `.pbix` layout against the donor model registry
(tables/columns/measures in visuals and filters). Caught errors look like
"No table/column/measure X in the donor model". Without this check, a broken
layout is published and renders on the server with "Could not load data for this
visual".

```bash
cd agentic_bi_framework
python -m agentic_bi.validate_pbix "output_files/my_dashboard.pbix"
# OK: layout matches the donor model   - or a list of problems
```

The example donor registry is in `validate_pbix.EXAMPLE_REGISTRY` (no network or
donor needed). In `board_fake` validation is built in and blocks publishing on
any problem.

## 9. Publishing

### 9.1 Directly via REST (publish_pbix)

```python
from pathlib import Path
from agentic_bi.publish import publish_pbix

res = publish_pbix(
    Path("output_files/my_dashboard.pbix"),
    "my_dashboard",  # name on the server (without .pbix)
    "/Target/Dev",  # folder
    {
        "server": "reportserver.example.com",
        "base_path": "/reportserver",
        "api_prefix": "/api/v2.0",
        "timeout": 300,
    },
)
print(res)  # {"Id": "...", "Path": "...", ...} or {"status": ...}
```

- Authentication is Windows SSO (Negotiate).
- If a report already exists at `Path` — update via `PUT` (idempotent re-publish);
  otherwise `POST` (201).
- The response omits the base64 `Content`/`ContentType` (keeps output small).

### 9.2 Via a git-deploy client (`git-deploy`)

`git-deploy` is an optional, out-of-tree one-way deploy of `.pbix` files from a
git repository into a Report Server. It requires the `.pbix` to live in the git
repo, the target repository to be configured, and all LFS objects to be available.

> **Note on LFS:** `.pbix` files are commonly stored via Git LFS. `deploy` runs
> `git lfs pull` for all `.pbix` under the target branch's `root_folder`. If any
> LFS object is missing, deploy fails. Verify with `git lfs verify` / `git lfs pull`.

Example local config (`git-deploy.yaml`):
```yaml
server:
  url: "https://reportserver.example.com/reportserver"
  verify_ssl: false
  timeout: 180
repository:
  path: "C:/path/to/git-deploy-target"   # clone of the target repo with .pbix
  branch: "dev"
  remote: "origin"
sync:
  patterns: ["*.pbix"]
  mode: "diff"
  target_folder: "/Target/Dev"
  root_folder: ""
  state_resource_path: "/Target/Dev/deploy-state.json"
  lock_resource_path: "/Target/Dev/deploy.lock"
  lock_ttl_seconds: 600
metadata:
  enabled: false
```

## 10. Orchestration (automate.py)

`automate.py` combines the steps:

```bash
cd agentic_bi_framework

# Single visual (legacy layout) — build+publish
python -m agentic_bi.automate --name "api rebuild test" --dry-run

# Query-driven skeleton (KPI+chart+table+filters)
python -m agentic_bi.automate --skeleton --name "my_dashboard" --dry-run
```

Main APIs:
- `run(src, out, name, folder, ...)` — build-publish a single-visual report.
- `run_from_skeleton(src, out, name, folder, ...)` — build-publish a skeleton.
- `verify_published(server, folder, name, base, api)` — GET by Path, returns `exists/Id/Size/...`.

## 11. Tests

> Developing on macOS with a Windows VM in UTM? See
> [DEVELOPMENT_MACOS.md](DEVELOPMENT_MACOS.md) for the VM setup, engine paths
> and the test-build commands. Framework self-tests also ship as CLIs:
> `agentic-bi-visual-check` (static layout validation) and
> `agentic-bi-test-build` (build + validate + JSON report).

```bash
cd agentic_bi_framework
pytest tests/ -q
```

The binary and web-clone tests need a real `.pbix` container and use the shipped
donor `templates/template.pbix` (tracked in git). When it is absent they are
**skipped**, not failed, so the stdlib-only suite still runs anywhere.

| File | What it checks |
|------|----------------|
| `test_pbix_binary_codec.py` | the XPress9/ABF codec: header, member table, round-trip |
| `test_pbix_binary_relayout.py` | uneven re-layout of `DataModel` (member-level offsets) |
| `test_pbix_binary_patch.py` | the patch pipeline: spec load, classify, apply, guard rails |
| `test_pbix_binary_board.py` | build a board, patch its binary model, read it back |
| `test_pbix_desktop_oracle.py` | Desktop oracle (skipped unless `AGENTIC_BI_GUEST_*` is set) |
| `test_web_report_checks.py` | per-element checks (`STRUCT-*`, `BIND-*`, `FILTER-*`) |
| `test_web_report_render.py` | layout render: geometry, mock glyphs, severity, filters, donor clone |

## 11.1 Reverse self-testing of a `.pbix` (`engine_verify`)

Every engine build is **automatically** checked by a reverse test: read the
produced `.pbix` back and confirm all page elements are present and the model
returns the expected data.

```python
from agentic_bi.engine import EnginePipeline

pipe = EnginePipeline()
res = pipe.run(
    "sales.csv", "Sales", "SalesDB", "out.pbix", pages={"Sales": 5}
)  # verify=True by default
# res["verify"] == "ok", res["verify_passed"], res["verify_failed"]
```

CLI:

```bash
# build + reverse test + page structure check
python -m agentic_bi.engine_cli --data sales.csv --table Sales --out out.pbix \
    --assert-pages "Sales=5" --oracle

# disable the test / make the model read-back critical
python -m agentic_bi.engine_cli ... --no-verify
python -m agentic_bi.engine_cli ... --strict-soft
```

**What is checked** (`engine_verify.verify_pbix`):

| Check | Criticality |
|-------|-------------|
| Container integrity (zip/CRC, `Report/Layout`, `DataModel`, `[Content_Types].xml`) | critical |
| Pages: presence and visual count (`pages={"Name": N}`) | critical |
| Every visual has `projections` (otherwise it renders empty) | critical |
| All visual fields reference existing tables/columns/measures | critical |
| No "unsafe" `column IN (...)` filters (they crash the pivot on drill) | critical |
| Model read-back: rows/columns/values match the spec (`pbixray`) | soft |
| **Brand book** of the theme: Brand Sans/Text fonts, palette, mandatory accent, background, contrast | soft (`error` becomes critical with `--brand-strict`) |

A failed critical check raises `RuntimeError` (strict by default). A soft
(read-back) failure is only reported: the third-party `pbixray` decoder does not
always parse certain types correctly. Make it critical with `strict_soft=True`.

Available separately: `verify_container`, `verify_layout`, `verify_bindings`,
`verify_safe_filters`, `verify_model_data`.

### Final brand-book check (`engine_verify.verify_brand`)

In the final stage the report theme is checked against the corporate style
(spec in `brand.py`):

```python
import agentic_bi.engine_verify as engine_verify

theme = engine_verify.extract_report_theme("out.pbix")  # fonts/colors/background
engine_verify.verify_brand("out.pbix", theme=theme, strict=False)
```

- `extract_report_theme(pbix)` — takes the **actually used** visual colors and
  fonts plus the report-theme background/text (`Report/StaticResources/**`);
- the mandatory accent is recognized with a tolerance (dashboards often use
  `#D0302A`/`#D3212A` instead of the canonical `#D32F2F`);
- level-`error` violations (e.g. `BRAND-ACCENT-MANDATORY`) become critical with
  `strict=True` / CLI `--brand-strict`.

CLI: `--no-brand-verify` disables the check; `--brand-strict` makes brand errors
fail the build. Built into `EnginePipeline.run()` (`brand_verify=True`).

## 12. Typical "query-driven" pipeline

```
User query
   │
   ▼
1. Skeleton build (skeleton.build_skeleton) ── config: table/measure_table/
   │                                            KPI/chart/table/filters
   ▼
2. layout_from_report → layout (.pbix format)
   │
   ▼
3. rebuild_pbix(src_donor, out, layout=...) ── binary .pbix (DataModel from donor)
   │
   ▼
4. validate_pbix(out) ── ✗ broken layout → stop (RuntimeError), do not publish
   │                       ✓ ok
   ▼
5. publish: publish_pbix (REST) OR git-deploy deploy
   │
   ▼
6. verify_published → GET by Path (HTTP 200) ── confirmation
```

## 12.5 Inspecting an existing dashboard (inspect_board)

View the elements of an already-published report (pages, visuals, tables,
measures, sources) — find it by server path, download the `.pbix`, break it down
via PbiLineage. Download/analysis logic reuses
`reportserver.pbix_analysis.PbiRsBulk`.

```bash
cd agentic_bi_framework
python -m agentic_bi.inspect_board --path "/Shared Reports/Self-service"
```

- `--path` — the full report path on the server (required).
- `--keep-pbix` — keep the downloaded `.pbix` in `output_files/inspect/`.

As an API:

```python
from agentic_bi.inspect_board import inspect_board

thesis = inspect_board("/Reports/MyReport")  # dict: summary + pages + sources
```

Returns a thesis structure: `summary` (pages/visuals/tables/measures/sources),
`pages` (name, visual/binding counts, tables used, visual types), `sources`
(by_table/by_group/unresolved).

**Permission errors (HTTP 403):** if `Content/$value` is closed for the current
user, downloading gives `PbirsAccessError`. The item is found in the catalog
(path search works) but the `.pbix` internals are unavailable — a role with
report-download permission is required.

## 13. Variables and paths

- **Donor (` .pbix` skeleton):** passed via CLI/constructor (no baked-in path).
- **Output files:** `agentic_bi/output_files/`.
- **Reports on the server:** configured via `publish.cfg` / `reportserver_diagnostics_config.json`.

## 14. Troubleshooting

**Publish error `409 Conflict`**
- Already exists → re-publishing uses PUT (normal; 409 can happen on a race, retry).

**`layout does not match the donor model: ...`**
- `validate_pbix` found visuals/filters referencing non-existent model objects.
  Check `table/measure_table/columns/measures` against the real donor model
  (registry in `validate_pbix.EXAMPLE_REGISTRY` or your own registry).

**`git lfs pull` → 404 Object does not exist**
- The `.pbix` LFS object is missing in the repository bucket. Restore/re-push it
  (`git lfs push`) or use a version with an available object.

**`deploy-state.json` is not created (HTTP 400)**
- A known `git-deploy` limitation (creating a JSON resource). Does not affect
  report publishing; the next deploy will be a full one.
## 15. PDF lineage report (`report/`)

Turns a `PbiLineage.to_json()` dict into a printable, multi-page PDF that
replaces the old wiki-page hand-off: a PlantUML diagram, a brand-book scorecard,
the flat level matrix and the list of brand deviations.

Install the optional extra:

```bash
pip install -e ".[report]"        # reportlab + Pillow + pandas + openpyxl
```

CLI:

```bash
# .pbix or lineage.json -> multi-page PDF (A4 landscape by default)
agentic-bi-report path/to/lineage.json -o lineage.pdf
agentic-bi-report "dashboard.pbix" --page-size A3 --no-visuals --no-diagram
```

Programmatic:

```python
from agentic_bi.report import build_report, LineageTable, lineage_to_table

rows = lineage_to_table(data)  # flat level matrix (list[dict])
LineageTable(data).to_excel("matrix.xlsx")

build_report(
    data,
    "lineage.pdf",
    plantuml=plantuml_source,
    page_size="A4",
    orientation="landscape",
    max_level=7,
    include_visuals=True,
)
```

Module map:

| Module | Responsibility |
|---|---|
| `report/lineage_matrix.py` | `lineage_to_table`: JSON -> flat rows + `COLUMNS`/`LEVEL` |
| `report/lineage_table.py` | `LineageTable`: pandas DataFrame + Excel export |
| `report/plantuml_tools.py` | PlantUML validate/render (`PLANTUML_JAR`/`PLANTUML_JAR_DIR`) |
| `report/pdf_diagram.py` | render the diagram and tile it across pages |
| `report/pdf_tables.py` | scorecard, matrix table and brand-issue flowables |
| `report/pdf_report.py` | `build_report` orchestration + CLI |

Notes:

- The diagram is skipped (with a message) when `plantuml.jar` or Pillow is
  unavailable; the rest of the report is still produced.
- A Unicode TTF font is auto-resolved for non-Latin dashboard text; override with
  `REPORT_PDF_FONT` (or the `--font` flag) when auto-detection is not enough.
- Page size/orientation are flags; the matrix paginates automatically and the
  diagram tiles when it is taller than one page.

---

## 16. Binary DataModel editing (`pbix_binary/`)

The binary VertiPaq `DataModel` is a closed, XPress9-framed member that cannot
be authored from scratch — but it can be edited at the *member* level, including
members whose new payload has a **different length**. This is the only place in
the framework that touches the DataModel framing and the ABF indexes; every
higher layer works through this API.

```
.pbix (zip)  ->  DataModel  ->  ABF (decompressed)
                                   |  header (BackupLogHeader XML page)
                                   |  member payloads
                                   |  backup_log XML   (logical files/classes)
                                   |  virtual_directory (absolute offsets/sizes)
```

Replacing a member with a different length invalidates the absolute offsets
recorded in the virtual directory and the header, so the buffer is **re-laid**
(payloads + backup log + directory) with every offset recomputed, then re-framed
and swapped back into a **size-safe** container (the central directory and the
local-header offsets of any member stored after `DataModel` are shifted too).

Module map:

| Module | Responsibility |
|---|---|
| `pbix_binary/abf_model.py` | ABF member model + the two XML indexes (parse/serialize; keeps the raw trees so engine-managed fields survive) |
| `pbix_binary/abf_codec.py` | XPress9 framing of the `DataModel` member (`decompress_datamodel`, `compress_datamodel`, `crc32c`) |
| `pbix_binary/abf_relayout.py` | `relayout_abf(abf, replace=..., add=...)` — rebuild around arbitrary-length members, re-offsetting |
| `pbix_binary/patch_pipeline.py` | `apply_patches(pbix, patches, out)`, `classify_patches`, `load_spec`, size-safe `swap_datamodel` re-export |
| `pbix_binary/patch_cli.py` | `agentic-bi-pbix-patch` CLI (`members`, `apply`) |

Patch kinds (a JSON spec is a list, or `{"patches": [...]}`):

```json
{"patches": [
  {"kind": "replace",        "find": "<utf-16 text>", "with": "<same length>"},
  {"kind": "replace_hex",    "find": "<hex>",         "with": "<same length>"},
  {"kind": "replace_member", "member": "metadata.sqlitedb", "path": "new.db"},
  {"kind": "replace_member", "member": "<logical name>", "data": "<base64>"}
]}
```

`replace`/`replace_hex` are byte-in-place and must keep the length: a
length-changing byte patch is rejected (it would silently shift the stream).
`replace_member` is the uneven-length path — the buffer is re-laid.

### CLI

```bash
# list ABF members (storage id + logical name + size)
agentic-bi-pbix-patch members --pbix template.pbix

# apply a patch spec (uneven member replacement) + write a markdown report
agentic-bi-pbix-patch apply --pbix template.pbix --spec patch.json \
    --out out.pbix --report patch.md
```

### API

```python
from pathlib import Path
from agentic_bi.pbix_binary import patch_pipeline

report = patch_pipeline.apply_patches(
    Path("template.pbix"),
    [{"kind": "replace_member", "member": "metadata.sqlitedb", "path": "new_model.db"}],
    Path("out.pbix"),
)
print(report.size, report.abf_size, report.log)
```

Notes:

- The `xpress9` codec is an optional dependency: `pip install -e ".[binary]"`.
- The verify path (`engine_verify`) is unaffected by a member edit — the layout
  references the model by name, and the edited model is read back with
  `pbixray` in the integration tests.
- Tests: `tests/test_pbix_binary_{codec,relayout,patch,board}.py`. The board test
  builds a `.pbix` from the shipped donor and then edits its binary DataModel.

### Desktop oracle stage (macOS host + Windows guest)

`desktop_oracle_guest.py` runs the strict Desktop oracle on a built `.pbix`
through a Windows VM. It is the authoritative "Desktop opens the report and
attaches the model" stage that cannot run natively on Apple Silicon.

- `GuestConfig.from_env()` / `GuestConfig.available()` — read the gate from
  `AGENTIC_BI_GUEST_*` (+ optional `AGENTIC_BI_HOST_IP`); unset means "skipped".
- `run_oracle(pbix, ...) -> OracleResult` — serve over host HTTP, guest fetches
  (`Invoke-WebRequest`), run `_engine_oracle.py` as an interactive scheduled task,
  poll the verdict (`MODEL_LOADED` = pass).
- Tests: `tests/test_pbix_desktop_oracle.py` (skipped unless the guest is set).

The oracle itself (`_engine_oracle.py`) is env-driven and auto-detects the
Desktop/workspace (regular vs RS), with `PBI_RS_ORACLE_OPEN_TIMEOUT` for slow
emulated cold starts.

Observed on a Windows 11 ARM UTM guest (Power BI Desktop x64): both a freshly
built board and the same board edited with the uneven `metadata.sqlitedb`
replacement returned `MODEL_LOADED`.

---

## 17. Dashboard web clone (`web_report/`)

`web_report` renders a **single self-contained HTML page that looks like the
original report**: page tabs, and on each page every element sits at its true
`Report/Layout` position/size, drawn with a mock glyph for its visual type (the
real visuals cannot render without the engine). The page is interactive:

* hovering an element shows a tooltip with its metrics and the checks it failed;
* problem elements are outlined by severity (red/amber/green);
* the filter panel (severity / page / visual type / **check id**) dims everything
  that does not match, so problem spots can be isolated on the layout;
* clicking an element opens a detail popover; a collapsed section carries the
  flat metrics/issues table.

The shell and interactions follow the framework's own process-mining HTML report
style (dark theme, stats grid, slide-in filter panel, hover tooltips).

```
.pbix  ->  Report/Layout  ->  WebReportModel  ->  single HTML file (layout)
                                 (pages, elements, geometry, issues, metrics)
```

Module map:

| Module | Responsibility |
|---|---|
| `web_report/web_model.py` | typed model: `Issue`, `ElementMetrics`, `ElementReport`, `PageReport`, `WebReportModel` |
| `web_report/web_checks.py` | per-element checks (issue ids below) |
| `web_report/web_inspect.py` | layout -> model; `registry_from_pbix` (pbixray, optional) |
| `web_report/web_mock.py` | mock SVG glyph per visual type (gives the board look) |
| `web_report/web_assets.py` | CSS/JS assets (dark shell, layout canvas, tabs, filters, popover) |
| `web_report/web_render.py` | model -> one HTML file (`render_html`, `write_html`) |
| `web_report/web_cli.py` | `agentic-bi-web-clone` CLI |

Per-element checks (issue ids, all re-usable):

| Check id | Severity | Meaning |
|---|---|---|
| `STRUCT-NO-SINGLEVISUAL` | error | container has no `singleVisual` |
| `STRUCT-NO-PROJECTIONS` | error | a data visual renders empty (no projections) |
| `INFO-STATIC-VISUAL` | info | a decorative visual (textbox/image/shape) has no data |
| `STRUCT-UNKNOWN-TYPE` | warning | visualType not in the role table (info if decorative) |
| `STRUCT-ROLE-NOT-ALLOWED` | error | projection role not allowed for the type |
| `STRUCT-MISSING-ROLE` | error | required role missing for the type |
| `BIND-NO-SELECT` | error | projection `queryRef` has no matching `Select` |
| `BIND-TABLE-MISSING` / `BIND-FIELD-MISSING` | error | Select/aggregation outside the model (needs a registry) |
| `FILTER-UNSAFE-IN` | error | `Condition.In` visual filter (crashes the pivot on drill) |

Usage counts (colors, explicit fonts, visual-filter count) are **metrics**, not
issues; they appear in the tooltip/popover and in the details table (fields,
roles, colors, filters, errors, warnings, violated check ids, status badge).

### CLI

```bash
# clone with model-membership checks read from the .pbix via pbixray
agentic-bi-web-clone --pbix board.pbix --out board_clone.html --model-registry

# or supply an explicit registry (no pbixray needed)
agentic-bi-web-clone --pbix board.pbix --out board_clone.html --registry reg.json
```

Runnable example: `examples/web_report_clone.py` (clones the shipped donor and
prints the per-element findings to the console).

### API

```python
from agentic_bi.web_report import build_model, write_html
from agentic_bi.web_report.web_inspect import registry_from_pbix

reg = registry_from_pbix("board.pbix")  # optional; "" if pbixray missing
model = build_model("board.pbix", registry=reg)
print(model.summary())  # pages/elements/issues by severity
write_html(model, "output_files/board_clone.html")
```

Notes:

- The layout is pure HTML/CSS; no network is required (no CDN, no JS libraries).
- `pbixray` is optional: without it the `BIND-*-MISSING` checks are skipped.
- Tests: `tests/test_web_report_checks.py` (checks) and
  `tests/test_web_report_render.py` (layout render + the shipped donor + a board).
