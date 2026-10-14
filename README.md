# Agentic BI Framework

A self-contained, dependency-light framework for building and operating
Power BI deliverables with agents: authoring `.pbix` reports, validating them
against a model, auditing brand compliance, extracting lineage/DAX insights,
and (optionally) publishing to a Power BI Report Server.

The framework is **implementation-agnostic**: it ships no organization-specific
URLs, hosts, network shares or personal paths. Everything environment-specific
is passed through configuration or CLI flags.

## Start here

- **[docs/FRAMEWORK.md](docs/FRAMEWORK.md)** — concepts, the five lifecycle
  stages, and a working checklist for agents automating this framework.
- **[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)** — the module/API map and
  recipes.
- **[docs/BRAND_AUDIT.md](docs/BRAND_AUDIT.md)** — brand-compliance auditing.
- **[docs/DEVELOPMENT_MACOS.md](docs/DEVELOPMENT_MACOS.md)** — develop and test
  on macOS with a Windows VM in UTM.

## Layout

```
agentic_bi_framework/
├── README.md                  # this file — start here
├── docs/
│   ├── FRAMEWORK.md           # the framework: concepts, lifecycle, methods
│   ├── IMPLEMENTATION.md      # reference implementation details / API map
│   ├── BRAND_AUDIT.md         # brand compliance auditing
│   └── DEVELOPMENT_MACOS.md   # macOS + UTM dev setup and testing
├── examples/
│   ├── board_declare.yaml     # declarative multi-page board spec
│   ├── engine_custom_visuals.py
│   └── engine_sales.csv
├── pyproject.toml             # packaging & optional dependency groups
└── src/agentic_bi/            # the implementation (depth)
    ├── board.py               # declarative Board/Page builder
    ├── skeleton.py            # PBIP skeleton + layout generation
    ├── rebuild.py             # fold layout into a donor .pbix
    ├── engine*.py             # build a .pbix from arbitrary data via the AS engine
    ├── validate_pbix.py       # validate layout against the donor model
    ├── engine_verify.py       # reverse self-test of a built .pbix
    ├── spec.py / thresholds.py / agents.py
    ├── brand*.py              # corporate brand rules & auditing
    ├── publish.py / automate.py
    ├── pbix_binary/           # member-level binary DataModel editing (incl. uneven length)
    ├── lineage/               # vendored: .pbix lineage extraction
    ├── antipatterns/          # vendored: DAX/M antipattern analysis
    ├── reportserver/          # vendored: generic Report Server access
    └── report/                # multi-page PDF lineage report (diagram+matrix+brand)
```

The `report` subpackage turns a `PbiLineage.to_json()` dict into a printable
multi-page PDF: PlantUML diagram (tiled across pages), brand-book scorecard, the
flat level matrix and the list of brand deviations. It needs the `report` extra.
See [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md#pdf-lineage-report).

## Quick start

```bash
pip install -e .                 # core (stdlib-only)
pip install -e ".[all]"          # with every optional integration
```

```python
from agentic_bi import spec, board
# See docs/FRAMEWORK.md for the full lifecycle.
```

## The five lifecycle stages

| Stage | Modules | What it does |
|-------|---------|--------------|
| develop | `board`, `skeleton`, `spec`, `build`, `engine_layout`, `rebuild`, `engine` | spec/query → layout → `.pbix` |
| test | `validate_pbix`, `engine_verify`, `dax_detail`, `antipatterns` | validate against model, reverse self-test, DAX/M analysis |
| deploy | `publish`, `automate` | REST publish + orchestration |
| control | `automate.verify_published`, `reportserver/diagnostics` | confirm published state, catalog diagnostics |
| support | `thresholds`, `agents` | explain thresholds, triage, agent manifests |

## Working with agents

Agents are an **optional smart layer**, not a mandatory pipeline step. A support
agent is a declarative manifest bound to one lifecycle stage:

```python
from agentic_bi.spec import load
from agentic_bi.agents import resolve_agents, render_kilo_agent

spec = load("examples/board_declare.yaml")
for agent in resolve_agents(spec):
    print(agent.id, agent.stage, agent.role)
    # materialize a Kilo agent file:
    # Path(f".kilo/agent/{agent.id}.md").write_text(render_kilo_agent(agent, ""))
```

Registry: `agent.builder` (develop), `agent.tester` (test), `agent.deployer`
(deploy), `agent.watchdog` (control), `agent.supporter` (support). Enable,
disable or override them in the spec's `support` section.

**Agent checklist (see FRAMEWORK.md §5):** never build the binary model by hand;
reference only real model objects; run `validate_pbix` before publishing; keep
`Report/Layout` UTF-16LE without BOM; carry `projections` on every visual; avoid
`IN` filters; treat all environment values as configuration.

## Optional dependencies

The core runs on the Python standard library alone. Integrations are opt-in:

| Extra | Enables |
|-------|---------|
| `spec` | YAML/JSON declarative specs |
| `readback` | model read-back / deep DAX-M analysis (`pbixray`) |
| `server` | Report Server REST publish & inspection |
| `brand` | `.pptx` brand auditing |
| `tables` | Excel/Parquet export of lineage tables |
| `binary` | member-level binary DataModel (ABF) editing (`xpress9`) |

## License

See [LICENSE](LICENSE).