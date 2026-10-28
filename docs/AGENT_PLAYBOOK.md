# Agent playbook: board from data via the AS engine

Goal: turn tabular data into a `.pbix` board and drop it on a path (for example
the Windows Desktop), then optionally render a PDF lineage report next to it.
Copy the commands below; never hand-build `Report/Layout`.

## Two separate examples

They are **different deliverables**, not one pipeline. Start with the simple
one; only enrich when explicitly asked.

| Stage | Example | Model | Page | Output |
|---|---|---|---|---|
| 1 — simple | `examples/engine_table_board.py` | one table | 1 `tableEx` visual | `sales_table_dashboard.pbix` |
| 2 — enrich | `examples/engine_rich_board.py` | table + 5 DAX measures | 18 visuals of every kind | `sales_rich_board.pbix` |

An agent may be asked for the simple table first and, in a later request, to
enrich it. Do not jump to the rich board unless enrichment is requested.

## Why the moving parts matter

- `EnginePipeline.build_datamodel` drives the Power BI Desktop Analysis
  Services engine (`msmdsrv`) through PowerShell, so the **engine path is
  Windows-only**. On macOS pass a prebuilt DataModel (`.abf`) instead.
- Desktop must start in an **interactive** session. WinRM runs in session 0,
  where Desktop does not bring up the engine, so run the build through a
  scheduled task with `-LogonType Interactive`.
- A data-bound visual renders only when its container carries the
  container-level `query` (`SemanticQueryDataShapeCommand`) **and**
  `dataTransforms`, and the section carries an `id`. `engine.layout` emits all
  of these now; a layout without them shows an empty report with the table
  present only in the data model.
- Desktop, template and workspace are env-driven and auto-detected:
  `PBI_RS_DESKTOP`, `PBI_RS_BIN`, `PBI_RS_WS_ROOT`, `PBI_RS_TEMPLATE`.
  Auto-detect prefers the RS build and falls back to the regular Desktop.
- Use a **classic** donor `.pbix` (one that contains `Report/Layout`, not the
  PBIR `Report/definition/` format) as the template.

## One-time guest setup (Windows VM, no installer needed)

The framework is pure Python, so an embeddable CPython is enough. These steps
are idempotent; re-run them to update the staged framework.

```powershell
# embeddable CPython (arm64 example)
Invoke-WebRequest -UseBasicParsing `
  https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-arm64.zip `
  -OutFile C:\pbi\py.zip
Expand-Archive C:\pbi\py.zip -DestinationPath C:\pbi\py -Force

# stage the framework (serve a zip from the host, e.g. http://<host-ip>:8000/abf.zip)
Invoke-WebRequest -UseBasicParsing http://<host-ip>:8000/abf.zip -OutFile C:\pbi\abf.zip
Remove-Item C:\pbi\abf -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive C:\pbi\abf.zip -DestinationPath C:\pbi\abf -Force

# let the embeddable interpreter see the package (only once)
$pth = 'C:\pbi\py\python312._pth'
if (-not (Select-String -Path $pth -Pattern 'abf\\src' -Quiet)) { Add-Content $pth 'C:\pbi\abf\src' }
```

Confirm the classic template is staged:
`Test-Path C:\pbi\abf\templates\template.pbix`.

## Build (Windows guest, interactive session)

Both stages share one scheduled-task shape. Pick the builder script and output
name, then register and start it as the interactive user (Desktop needs
session 1):

```powershell
# C:\pbi\build_board.ps1  — stage 1; for stage 2 swap the script and --out
$env:PBI_RS_BIN = 'C:\Program Files\Microsoft Power BI Desktop\bin'
$env:PBI_RS_TEMPLATE = 'C:\pbi\abf\templates\template.pbix'
& C:\pbi\py\python.exe C:\pbi\abf\examples\engine_table_board.py `
    --data  C:\pbi\abf\examples\engine_sales.csv `
    --table Sales `
    --template C:\pbi\abf\templates\template.pbix `
    --out   "$env:USERPROFILE\Desktop\sales_table_dashboard.pbix" *> C:\pbi\out\build.log
```

```powershell
# register + start (works for either stage)
$act = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\pbi\build_board.ps1'
$pr  = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName 'boardbuild' -Action $act -Principal $pr -Settings $set -Force
Start-ScheduledTask -TaskName 'boardbuild'
# ... poll C:\pbi\out\build.log, then:
Unregister-ScheduledTask -TaskName 'boardbuild' -Confirm:$false
```

Stage 2: in `C:\pbi\build_board.ps1` change the `& ... engine_table_board.py`
line to `... engine_rich_board.py`, set `--out ...\Desktop\sales_rich_board.pbix`,
then run the same register/start block.

The manual steps above are the background for `guest_chain`, which performs them
automatically over WinRM inside one bounded, self-cleaning call: it stages the
framework, runs the builder as an interactive scheduled task, pulls the `.pbix`
back, optionally runs the Desktop oracle, and stops the VM only if it started it.
Prefer it over hand-driven tasks:

```sh
.venv/bin/agentic-bi-guest-dashboard --repo . --vm-uuid <utm-uuid> --oracle
```

See `docs/DEVELOPMENT_MACOS.md` for the environment and verdict tokens.

## Visual kinds and value binding (stage 2)

Supported kinds (`Visual(kind, ...)`): `table`, `matrix`, `card`, `column`,
`bar`, `line`, `area`, `pie`, `donut`, `funnel`, `waterfall`, `treemap`,
`stackedColumn`, `stackedBar`, `scatter`, `gauge`, `kpi`, `slicer`.

Two ways to feed a value:

- `value=<column>, agg="sum|avg|min|max|count|count_nonnull|median|stddev|var"`
  — aggregate a column;
- `measure="<Name>"` — bind an existing model **measure**. Declare measures in
  the spec under `measures`: `{"table", "name", "expression"}`. Prefer measures
  for ratios/KPIs, e.g.
  `Amount per Unit = DIVIDE(SUM(Sales[amount]), SUM(Sales[qty]))`.

Roles by kind: charts use `axis` (+ `series` for stacked) + value; `matrix`
uses `columns` (rows) + value; `scatter` uses `x`/`y` (+ `size`); `kpi` uses
value + `trend`; `treemap` uses `axis` + value; `slicer` uses `axis`.

## PDF report next to the board

The PDF lineage report needs the `report` extra (`reportlab`, `Pillow`,
`pandas`, `openpyxl`), so run it where that extra is installed (e.g. the macOS
venv) and place the result next to the `.pbix`. Without `-o` the output name is
timestamped (`<name>_YYYYMMDD_HHMMSS.pdf`), so runs never overwrite each other.

```bash
# input may be a .pbix or a lineage .json; timestamped default output
PLANTUML_JAR=/path/to/plantuml.jar \
  .venv/bin/python -m agentic_bi.report.pdf_report /path/to/board.pbix
# -> /path/to/board_YYYYMMDD_HHMMSS.pdf
```

Copy the PDF next to the `.pbix` on the guest:

```powershell
Invoke-WebRequest -UseBasicParsing `
  http://<host-ip>:8000/<pdf-name>.pdf -OutFile "$env:USERPROFILE\Desktop\<pdf-name>.pdf"
```

## Build (macOS, prebuilt model — workflow A)

```bash
.venv/bin/python examples/engine_table_board.py \
  --data examples/engine_sales.csv --table Sales \
  --template templates/template.pbix --datamodel model.abf \
  --out output_files/sales_table_board.pbix
```

## Verify

```python
from pathlib import Path

from agentic_bi.engine import EnginePipeline
from agentic_bi import visual_check
from agentic_bi.engine import verify as engine_verify

spec = EnginePipeline.build_spec(
    EnginePipeline.load_rows(Path("examples/engine_sales.csv")), "Sales", "SalesTable"
)
# Rich boards add model measures; list them so the checks know they resolve.
registry = {
    "Sales": {
        "columns": [c["name"] for c in spec["tables"][0]["columns"]],
        "measures": [m["name"] for m in spec.get("measures", [])],
    }
}
print("visual_errors:", visual_check.check_pbix("out.pbix", registry))
report = engine_verify.verify_pbix("out.pbix", spec, model=True, layout_checks=True)
print("critical_ok:", report.critical_ok())
```

Passing checks: layout members present, every visual has projections that
resolve (columns **and** measures), and the model row count matches the input.
Soft failures do not block: brand checks (theme not brand-tuned) and the
`sample values` check on `date` columns.

## Expected results (reference)

| Artifact | Observed |
|---|---|
| stage 1 `.pbix` | 1 visual (`tableEx`), 8 rows, ~20 KB |
| stage 2 `.pbix` | 18 visuals, 5 measures, 8 rows, ~23 KB; measures visible in the model |
| PDF | multi-page A4 landscape, timestamped name (sample: 6 pages stage 1, 5 pages stage 2), ~120–128 KB |

## Gotchas

- Blank report with data only in the model → the visual container is missing
  `query`/`dataTransforms` (or the section is missing `id`).
- `Measure … not in model` in `visual_check` → the registry lacks the measure
  names; pass `measures` (or use `test_build.registry_from_spec`).
- `TimeoutError: engine port not found` → wrong workspace root; set
  `PBI_RS_WS_ROOT`, or use a Desktop build that matches the installed one
  (RS vs regular: the install dir is `Microsoft Power BI Desktop`).
- Desktop launched from WinRM session 0 → engine never starts; use the
  interactive scheduled task above.
- Date columns must be written as the DAX literal `dt"YYYY-MM-DDThh:mm:ss"`
  (the builder does this); `DATEVALUE("...T00:00:00")` leaves the table empty.
