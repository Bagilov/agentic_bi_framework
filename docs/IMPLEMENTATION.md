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
| `engine_container.py` | OPC operations on a `.pbix`: `swap_datamodel`, `build_container`, `read_member` |
| `engine_layout.py` | Build `Report/Layout` from scratch: `Visual`, `build_report`, `build_layout_from_spec` |
| `engine_verify.py` | **Reverse self-test of a `.pbix`**: container, layout/pages, bindings, IN-filter guard, model read-back, **theme vs style guide** (`verify_brand`, `extract_report_theme`) |
| `engine_cli.py` | Engine-build CLI (`--data/--table/--out/--oracle/--verify`) |
| `_engine_build.ps1` / `_engine_oracle.py` | TOM+`ImageSave` and the strict Desktop oracle (internal) |
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
| `tests/` | Skeleton, antipattern and validation tests |

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
TABLE         = "fact_table"                 # table for columns/axes/filters
MEASURE_TABLE = "kpi_measures"    # table the measures come from
MEASURES      = [{"name": "metric_a", "expression": ""},
                 {"name": "metric_b", "expression": ""}]
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
    out=Path("output_files/my_proj"),   # project folder
    report_name="my_proj",              # name for .pbir/.Report/.Semantic
    display_name="My dashboard",        # page name
    table="fact_table",                  # columns table
    measure_table="kpi_measures",  # measures table (opt.)
    columns=[{"name": "metric", "dataType": "string"},
             {"name": "period_start", "dataType": "datetime"}],
    measures=[{"name": "metric_a", "expression": ""}],
    kpi={"kind": "measure", "property": "metric_a", "display": "Metric A"},
    chart_type="lineChart",             # or "clusteredColumnChart"
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
    Path("donor.pbix"),                 # binary DataModel source
    Path("output_files/my_dashboard.pbix"),
    layout=layout,                      # our layout
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
    "my_dashboard",                       # name on the server (without .pbix)
    "/Target/Dev",                        # folder
    {"server": "reportserver.example.com", "base_path": "/reportserver",
     "api_prefix": "/api/v2.0", "timeout": 300},
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

```bash
cd agentic_bi_framework
pytest tests/ -v
```

| File | What it checks |
|------|----------------|
| `test_skeleton.py` | query-item format, filters, layout, model, serialization |
| `test_antipatterns.py` | antipattern detectors (measures, columns, tables, pages) |
| `test_validate_pbix.py` | the built board layout references only real donor objects |
| `test_board.py` | the declarative `Board` builder (pages, KPI/chart/table, auto-layout, rebuild) |
| `test_agents.py` | `SupportAgent` manifests, lifecycle stages, spec overrides, Kilo materialization |
| `test_engine.py` | OPC container, visuals/layout, type inference **and the `engine_verify` reverse test** |

## 11.1 Reverse self-testing of a `.pbix` (`engine_verify`)

Every engine build is **automatically** checked by a reverse test: read the
produced `.pbix` back and confirm all page elements are present and the model
returns the expected data.

```python
from agentic_bi.engine import EnginePipeline
pipe = EnginePipeline()
res = pipe.run("sales.csv", "Sales", "SalesDB", "out.pbix",
               pages={"Sales": 5})          # verify=True by default
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
theme = engine_verify.extract_report_theme("out.pbix")   # fonts/colors/background
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

thesis = inspect_board("/Reports/MyReport")   # dict: summary + pages + sources
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