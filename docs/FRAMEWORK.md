# Agentic BI Framework

A framework for building and operating Power BI deliverables with agents.
It is **implementation-agnostic**: no organization-specific URLs, hosts, network
shares or personal paths are shipped. Everything environment-specific is passed
through configuration or CLI flags.

This document is the framework overview: concepts, lifecycle, methods. For the
module/API map see [IMPLEMENTATION.md](IMPLEMENTATION.md); for brand compliance
see [BRAND_AUDIT.md](BRAND_AUDIT.md).

---

## 1. Why this framework

A `.pbix` is an ordinary ZIP/OPC archive containing a **binary VertiPaq
`DataModel`** and a **textual `Report/Layout`** (JSON). The binary model cannot
be authored byte-by-byte in Python (closed compression format). The reliable,
canonical ways to produce a valid model are:

1. **Donor transplant** — take the binary `DataModel` from an existing working
   `.pbix` and replace only the layout. The layout references the model *by
   name*, so visuals work as long as object names match. This is the fastest
   path and needs no Power BI Desktop.
2. **AS engine build** — let the Power BI Desktop RS engine (`msmdsrv.exe`)
   serialize a model you define through TOM, then read it back via
   `Server.ImageSave`. This is the canonical, Desktop-verified path but requires
   Windows + Desktop RS.

The framework packages both paths behind one consistent API, plus the
surrounding lifecycle: authoring, validation, brand auditing, lineage, deep DAX
analysis, publishing and monitoring.

---

## 2. Core concepts

### 2.1 The `.pbix` container

```
<pbix> (zip)
├── Version                     # UTF-16LE "1.28"
├── [Content_Types].xml         # OPC part types
├── DataModel                   # binary VertiPaq (opaque, from donor/engine)
├── Report/Layout               # JSON, UTF-16LE without BOM
├── DiagramLayout, Settings, Metadata, ...
└── Report/StaticResources/...  # themes, registered resources
```

Key facts (verified against real files):

- A `.pbix` starts with `PK`; there is no PBIX magic.
- `Report/Layout` is JSON encoded as UTF-16LE **without BOM** by Power BI.
  Encoding it any other way makes Desktop/analyzers fail to parse it.
- `DataModel` and `Report/Layout` are independent: the layout addresses model
  objects by name, not by offset.

### 2.2 Layout semantics

A layout has `sections` (pages). Each section has `visualContainers`; each
container has a `config` string containing a `singleVisual` with:

- `visualType` — `card`, `tableEx`, `pivotTable`, `columnChart`, `lineChart`,
  `pieChart`, `donutChart`, `barChart`, `slicer`, ...
- `projections` — **required**; without them Power BI binds no fields and the
  visual renders empty.
- `prototypeQuery` — `From` (source alias → entity) and `Select` (measure /
  column / aggregation).

Regression guard: filters in the form `column IN (...)` (`Condition.In`) crash
the pivot serializer on drill (`visitIn`/`serializeAll`). Use a `slicer` plus a
`matrix` on the same table instead.

### 2.3 PBIP (text project)

A textual, versionable report project that Power BI Desktop opens directly:

```
<name>.pbir
<name>.Report/report.json
<name>.Semantic/model.bim
<name>.Semantic/definition.pbism
```

A text `model.bim` is **not** recognized inside a `.pbix`; it only works in the
PBIP format. Folding a PBIP report into a binary `.pbix` is done by the rebuild
or engine path.

---

## 3. Lifecycle

The framework covers five stages. Each stage maps to concrete modules and to an
optional *support agent* (see §5).

```
develop → test → deploy → control → support
```

### 3.1 develop

Turn a declarative spec (or programmatic board) into a report artifact.

- `board.py` — high-level `Board`/`PageView` builder: `header`, `kpi`, `chart`,
  `table`, `filters`, multi-page support, grid auto-layout.
- `skeleton.py` — query-driven PBIP skeleton (`report.json` + `model.bim`).
- `spec.py` — declarative dashboard spec (YAML/JSON) → `DashboardSpec` →
  `spec_to_board()`.
- `build.py` — PBIP project generator (iteration 1+2).
- `engine_layout.py` — build `Report/Layout` from scratch (`Visual`, `build_report`).
- `rebuild.py` — fold a layout into a binary `.pbix` using a donor DataModel.
- `engine.py` — data → AS engine → canonical DataModel → clean container.

### 3.2 test

Check the artifact before it reaches users.

- `validate_pbix.py` — every object referenced by the layout (tables, columns,
  measures in visuals and filters) must exist in the donor/model registry.
- `spec.validate_spec()` — structural validation of a declarative spec.
- `engine_verify.py` — reverse self-test of a built `.pbix`: container integrity,
  pages/visuals presence, field bindings, unsafe IN-filter guard, model data
  read-back (best-effort via `pbixray`), brand theme check.
- `dax_detail.py` and `antipatterns/` — DAX/M analysis and distortion markers.

### 3.3 deploy

Publish the artifact.

- `publish.py` — REST publish/update to a Report Server via
  `POST /api/v2.0/CatalogItems` (Negotiate auth).
- `automate.py` — orchestration: build → validate → publish → verify.
- Optional external git-sync deploy via an out-of-tree client (not shipped).

### 3.4 control

Verify the artifact actually landed and matches expectations.

- `automate.verify_published()` — GET the item by Path and confirm
  Id/Size/Type/ModifiedDate.
- `reportserver/diagnostics.py` — catalog-wide diagnostics (hidden items,
  subscriptions, schedules, favorites).

### 3.5 support

Explain and triage.

- `thresholds.py` — every threshold in the pipeline with its rationale and
  override path.
- `agents.py` — support-agent manifests (develop/test/deploy/control/support).

---

## 4. End-to-end pipelines

### 4.1 Donor transplant (no Desktop)

```python
from pathlib import Path
from agentic_bi.board import Board, col, measure
from agentic_bi.rebuild import rebuild_pbix
from agentic_bi.validate_pbix import validate_pbix

board = Board(table="fact_table", measure_table="kpi_measures")
p = board.add_page("p1", "Main")
p.kpi(measure("metric_a", "Metric A"))
p.chart(
    "lineChart",
    axis=col("period_start", "Period"),
    value=measure("metric_b", "Metric B"),
)
p.table([col("metric", "Metric"), measure("metric_a", "Metric A")])
p.filters(["category", "metric"])

out = rebuild_pbix(Path("donor.pbix"), Path("out/board.pbix"), layout=board.layout())
problems = validate_pbix(out)
assert not problems, problems
```

### 4.2 Engine build (Windows + Desktop RS)

```python
from pathlib import Path
from agentic_bi.engine import EnginePipeline

pipe = EnginePipeline(template=Path("templates/template.pbix"))
result = pipe.run(
    data=Path("sales.csv"),
    table="Sales",
    database="SalesDB",
    out=Path("out/sales.pbix"),
    verify=True,  # reverse self-test
    check_oracle=True,  # strict Desktop open check
)
```

Full run: data → inferred model spec → AS engine `ImageSave` → clean container
(scaffolding + our layout + DataModel) → verification → oracle.

On macOS the engine runs in a Windows 11 ARM VM (UTM) with Power BI Desktop;
layout authoring and validation run natively. See
[docs/DEVELOPMENT_MACOS.md](DEVELOPMENT_MACOS.md) for the VM setup, engine
paths and the test-build commands.

---

## 5. Working with agents

Agents are an **optional smart layer**, not a mandatory pipeline step. The
pipeline runs without them. A support agent is a declarative manifest
(`SupportAgent`) bound to one lifecycle stage, with a role, purpose, triggers,
tools and a start instruction.

Registry (`agents.AGENT_REGISTRY`):

| id | role | stage | purpose |
|----|------|-------|---------|
| `agent.builder` | Builder | develop | spec → Board → layout → `.pbix` |
| `agent.tester` | Tester | test | validate_pbix, spec checks, thresholds |
| `agent.deployer` | Deployer | deploy | publish with guardrails |
| `agent.watchdog` | Watchdog | control | compare published vs expected |
| `agent.supporter` | Supporter | support | explain thresholds, triage incidents |

Resolution and overrides come from the spec's `support` section:

```yaml
support:
  enable_ids: [agent.builder, agent.tester]   # force-enable (even if off by default)
  disable_ids: [agent.deployer]               # exclude
  agents:                                     # project-specific override manifest
    - {id: agent.builder, role: Builder, stage: develop, purpose: "...", enabled: true}
```

```python
from agentic_bi.spec import load
from agentic_bi.agents import resolve_agents, render_kilo_agent

spec = load("board_declare.yaml")
for agent in resolve_agents(spec):
    print(agent.id, agent.stage)
    # materialize into a Kilo agent file .kilo/agent/<id>.md
    # Path(f".kilo/agent/{agent.id}.md").write_text(render_kilo_agent(agent, ""))
```

### Checklist for an agent automating this framework

1. **Know the model objects.** Never reference a table/column/measure that is
   not in the donor model. Run `validate_pbix` before publishing; treat any
   problem as a hard stop.
2. **Never hand-craft the binary model.** Use donor transplant or the engine.
3. **Preserve layout encoding.** `Report/Layout` must be UTF-16LE without BOM.
4. **Carry `projections`** on every visual, or it renders empty.
5. **Avoid `IN` filters.** Use slicer + matrix.
6. **Be environment-agnostic.** Server host, base path, target folder, donor
   path and thresholds are configuration, not constants.
7. **Verify after build and after publish.** Use `engine_verify` /
   `validate_pbix` and `verify_published`.

---

## 6. Configuration

All environment-specific values are inputs:

| Concern | Where |
|---------|-------|
| Report Server host / base path / API prefix | `publish.cfg`, `reportserver_diagnostics_config.json` |
| Target folders, branch | spec `deploy` section |
| Donor `.pbix` / engine template | CLI flags / constructor |
| Desktop RS executable | `PBI_RS_DESKTOP` env var |
| Desktop RS binary dir (PowerShell) | `PBI_RS_BIN` env var |
| Brand rules | `brand_config.yaml` / `brand.py` |
| Threshold overrides | spec `quality`/`deploy` sections |
| Origin map | `origins.yaml` or built-in neutral default |

---

## 7. Optional dependencies

The core runs on the standard library. Integrations are opt-in (see
`pyproject.toml`): `spec` (PyYAML), `readback` (pbixray/pandas), `server`
(requests/requests-negotiate-sspi/urllib3), `brand` (python-pptx/lxml),
`tables` (pandas/pyarrow).