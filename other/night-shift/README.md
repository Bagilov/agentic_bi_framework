# Night-shift improvement loop — `agentic_bi_framework`

An autonomous, round-based improvement loop. Each round is a set of **waves**;
each wave is a group of subagents working in **disjoint file zones** so no two
workers can overwrite each other. A round is accepted only when every gate is
green.

## Protocol

1. **Snapshot.** Record `git status --short` and the gate numbers before the
   wave, so a regression is attributable.
2. **Waves.** Workers get a zone (an explicit file list) and a
   `Definition of Done`: code + regression tests + `ruff check` +
   `ruff format --check` + `mypy` clean in the zone. Workers never commit.
3. **Round table.** After a zone lands, a **read-only** reviewer inspects the
   delta and reports `P0|P1|P2|P3 — file:line — defect — why — fix`. Reviewers
   verify against real artefacts (unpacked `Report/Layout`, rendered HTML,
   `PowerShell` command text), not against the author's description.
4. **Implement, do not defer.** Every review finding becomes a fix wave. A
   finding that is deliberately not implemented must carry a technical reason;
   "out of scope" is not a reason.
5. **Gates** (all must pass):
   - `ruff check .`
   - `ruff format --check .`
   - `mypy src` — zero errors (blocking in CI, no ratchet)
   - `pytest` — all green
   - coverage ≥ `fail_under` in `pyproject.toml`
6. **Convergence.** When a round produces no P0/P1 in the reviewed delta and
   every new test fails under a rollback of its fix (mutation check), the loop
   stops until new code creates a new delta.

## Rounds

| Round | Zones | Focus |
|---|---|---|
| R1 | A guest chain · B lineage/PlantUML · C visual types · D web_report UX · E board_guide+shots | Review of the uncommitted working tree; UX/UI and implementation defects |
| R2 | A2/A3 guest literal paths + review fixes · B2 PlantUML review fixes · C2/C3 skeleton roles + visual review fixes · D2 web_report review fixes · F lineage typing · G spec/reportserver boundaries · H CLI UX | Implement every round-table finding from R1 |
| R3-R7 | one read-only review after each accepted round, then a fix wave | Typing to zero `mypy` errors, hostile-input hardening, print/a11y, guest staging correctness |
| R8 | four reviewers: guest chain · web clone · documents/reportserver/lineage · cross-cutting contracts | 20 findings (6 P1), all implemented and mutation-checked |

## Rules that came out of the loop

- **Do not "fix" a PowerShell encoding by removing the BOM.** Windows
  PowerShell 5.1 reads a `.ps1` without a BOM in the ANSI code page, so a
  non-ASCII payload is silently corrupted. Write the BOM exactly once, on the
  first chunk.
- **A missing file is not a failed stage.** `Remove-Item <missing>` under
  `$ErrorActionPreference='Stop'` exits 1, so every cleanup is guarded by
  `Test-Path -LiteralPath`.
- **`-Path` is a glob, `-LiteralPath` is a path.** Any path that comes from
  configuration goes through `-LiteralPath`, or `[`/`*` in a file name silently
  turns into a pattern.
- **A test that passes with the fix reverted is not a test.** Each regression
  test was checked against a rollback of the change it pins.
- **Verify against artefacts, not prose.** The `stackedColumnChart` bug was
  invisible in every test and obvious in Desktop's automation tree; the
  `barChart` `Rows` role was visible only in `templates/template.pbix`.
- **A failure is not an empty result.** A Report Server 401 reported
  `total: 1` and exit 0 until `None` (not `{}`) became the failure signal.
- **An unresolved value is not a compliant one.** Theme colour ids that cannot
  be resolved to hex must rate a page `unknown`, not `ok`.
- **A print test that hides the document's own chrome proves nothing.** The
  one-page clone printed as three sheets; the harness had been hiding the header
  the real document prints.
