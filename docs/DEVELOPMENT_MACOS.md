# Developing on macOS (Windows VM in UTM)

This guide covers how to develop and test the framework on a Mac. Two things
run in two different places:

| Concern | Where it runs |
|---|---|
| Layout authoring, container assembly, `validate_pbix`, `visual_check`, `engine_verify` (layout), lineage, brand audit, agents | **macOS natively** (pure Python) |
| Building the canonical VertiPaq `DataModel` via the Analysis Services engine (`.abf`) | **Windows** — Power BI Desktop in a VM |

On Apple Silicon there is no native Power BI Desktop, so the engine path uses a
**Windows 11 ARM VM in UTM** with Power BI Desktop (x64, run through Windows'
x64 emulation). Everything else works directly on macOS.

Settings (Desktop path, template, DataModel) are never hardcoded — pass them
via constructor arguments, CLI flags or environment variables.

---

## 1. Prerequisites

- macOS host (Apple Silicon or Intel).
- [UTM](https://mac.getutm.app) with a Windows 11 ARM/Pro guest.
- Python **>= 3.10** on macOS:

  ```sh
  python3 -m venv .venv
  .venv/bin/python -m pip install -e ".[spec]"        # core + YAML specs
  .venv/bin/python -m pip install -e ".[readback]"    # + pbixray/pandas for model read-back
  ```

---

## 2. Set up the Windows VM

1. **Create the VM** in UTM (UEFI boot, a disk, one *Shared* network adapter).
   Windows 11 ARM installs fine; TPM/Secure Boot can be bypassed during setup
   if needed.
2. **Install Power BI Desktop (x64)** in the guest. The bundle needs an explicit
   EULA flag for unattended installs or it fails with MSI `1603`:

   ```powershell
   PBIDesktopSetup_x64.exe /quiet /norestart ACCEPT_EULA=1
   ```

   Result: `C:\Program Files\Microsoft Power BI Desktop\bin\PBIDesktop.exe`.
3. **Display driver (recommended).** A fresh Windows ARM guest often has no
   VirtIO GPU driver and is stuck at **800x600**. Install the ARM64 driver from
   the UTM Guest Tools ISO (`https://getutm.app/downloads/utm-guest-tools-latest.iso`):

   ```powershell
   # copy Drivers\viogpudo\w11\ARM64\* into the guest, then:
   pnputil /add-driver viogpudo.inf /install
   # reboot, then set a sane mode (see below)
   ```

   Then set a higher resolution (e.g. 1920x1080, 96 DPI) with a small
   `ChangeDisplaySettings` helper run in the interactive session.
4. **Scripted control (optional).** Enable WinRM to drive the guest from macOS:

   ```powershell
   Enable-PSRemoting -Force
   ```

   From macOS, talk to it with `pywinrm` (`pip install pywinrm`) over
   `http://<guest-ip>:5985/wsman` (transport `ntlm`).

---

## 3. Configure the engine paths

The engine modules accept environment overrides:

| Value | Env var | Typical value |
|---|---|---|
| Desktop executable | `PBI_RS_DESKTOP` | `C:\Program Files\Microsoft Power BI Desktop\bin\PBIDesktop.exe` |
| Desktop bin dir (for TOM/AMO DLLs, used by PowerShell) | `PBI_RS_BIN` | `C:\Program Files\Microsoft Power BI Desktop\bin` |
| Template `.pbix` (scaffolding) | `PBI_RS_TEMPLATE` | `templates/template.pbix` |

The engine workspace lives under
`%LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces`
(regular Desktop; the Report Server build uses `...\Power BI Desktop SSRS\...`).
`_engine_build.ps1` connects to the running engine with TOM and exports the
model with `Server.ImageSave`.

---

## 4. Two workflows

### A. Native layout-only build (no Desktop) — works on macOS

Use a **prebuilt DataModel** (`.abf`) plus a template `.pbix`:

```sh
.venv/bin/agentic-bi-test-build \
  --data examples/engine_sales.csv --table Sales \
  --template templates/template.pbix \
  --datamodel model.abf \
  --out output_files/test_build.pbix \
  --report output_files/test_build.json
```

This builds the layout, assembles the container, runs `visual_check` and
`engine_verify` (layout) and writes a JSON report. Exit code is non-zero on a
visual error or a failed critical check.

### B. Full engine build (Windows guest)

Inside the guest (or via WinRM), let the AS engine produce the model and
assemble the `.pbix`:

```powershell
python -m agentic_bi.engine_cli --data engine_sales.csv --table Sales --out out.pbix --verify
# or the self-test wrapper:
python -m agentic_bi.test_build --data engine_sales.csv --table Sales \
    --template templates\template.pbix --out out.pbix
```

On Windows you may omit `--datamodel`: `test_build` builds the model via the
engine automatically. To assemble on macOS instead, copy the `.abf` back and
use workflow A.

---

## 5. Running the tests

Static layout validation (fast, no Desktop):

```sh
.venv/bin/agentic-bi-visual-check output_files/test_build.pbix registry.json
```

Full self-test build (build + validate + JSON report):

```sh
.venv/bin/agentic-bi-test-build --data examples/engine_sales.csv --table Sales \
  --template templates/template.pbix --datamodel model.abf \
  --out output_files/test_build.pbix --report output_files/test_build.json
```

Reverse self-test of a `.pbix` against a spec (programmatic):

```python
from agentic_bi import engine_verify
report = engine_verify.verify_pbix("out.pbix", spec, model=True)
print(report.ok(), report.critical_ok(), [c.name for c in report.failures])
```

Gallery of **every** supported visual kind (one page):

```python
from agentic_bi import engine_layout
layout = engine_layout.build_gallery(spec, page_name="Visual Gallery")
```

`--layout gallery` (default) uses this builder; `--layout auto` falls back to
the automatic table+cards+column+pie selection.

A `registry.json` maps model objects for validation:

```json
{ "Sales": { "columns": ["id","region","product","amount","qty","sale_date"], "measures": [] } }
```

---

## 6. Moving the DataModel between guest and host

The `.abf` is a few KB–MB. Either

- run a throwaway HTTP server on the host and `Invoke-WebRequest` it in the
  guest, or
- read it in the guest and transfer as base64 over WinRM:

  ```powershell
  [Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\out.abf"))
  ```

  then assemble on macOS with `engine_container.build_container(template, layout, datamodel, out)`.

---

## 7. Gotchas we hit

- **Silent Power BI install** fails without `ACCEPT_EULA=1` (MSI `1603`,
  `LaunchConditions`).
- **Date columns in a `DATATABLE(...)` expression** must use the DAX literal
  `dt"2026-01-15T00:00:00"`; `DATEVALUE("...T00:00:00")` is invalid and the
  calculated table ends up empty ("…does not hold any data because there is an
  error in its expression").
- **Workspace path** differs between the regular Desktop and the RS build.
- **No VirtIO GPU driver** → guest locked to 800x600 (see §2.3).
- **Brand checks** (`engine_verify` brand rules) are soft by default; they do
  not fail a build unless `brand_strict=True`.
- Use a **Python >= 3.10** interpreter for the venv; the system `python3` on
  older macOS may be too old.

---

## 8. Quick checklist

1. `python3 -m venv .venv && .venv/bin/pip install -e ".[spec]"`.
2. Guest: Power BI Desktop installed (`ACCEPT_EULA=1`), display driver +
   resolution set, WinRM enabled (optional).
3. Point `PBI_RS_DESKTOP` / `PBI_RS_BIN` / `PBI_RS_TEMPLATE` at the guest build
   (env vars) or pass CLI flags.
4. Author layout on macOS (`engine_layout`), validate with
   `agentic-bi-visual-check`.
5. Build the model in the guest, copy the `.abf` back, assemble, and run
   `agentic-bi-test-build` for the full report.
