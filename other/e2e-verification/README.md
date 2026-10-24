# End-to-end verification of the Stage 0 fixes

- **Date:** 2026-10-22
- **Purpose:** prove the two `web_report` injection defects and the two
  `pbix_binary` defects are real and are actually closed, by running the *real*
  pipeline end to end (a real `.pbix`, the real CLI, a real browser) instead of
  the unit-level regression tests alone.
- **Decision under test:** `docs/IMPROVEMENT_PLAN.md`, Stage 0.
- **Method:** one render / one patch run against the pre-fix sources (a git
  worktree at `HEAD` = `032d817`, before the fixes) and the same run against the
  working tree. Pre-fix behaviour is the control; post-fix must differ.

## Files

- `make_evil_pbix.py` — writes the two payloads into `Report/Layout` of a real
  copy of `templates/template.pbix`: `script` mode (`</script>` breakout, F-1) and
  `onclick` mode (single-quote JS breakout, F-2).
- `binary_e2e.py` — drives the shipped `agentic-bi-pbix-patch` CLI from the
  pre-fix and post-fix sources and inspects the bytes it writes.
- `evil-script.pbix`, `evil-onclick.pbix` — weaponized donors (built artifacts).
- `fixed-*.html` / `prefix-*.html` — rendered reports, post-fix and pre-fix.
- `bin/` — the `.pbix` files the binary scenarios produced (built artifacts).
- `fixed-script.png` — the fixed report in the browser, after a click.

## Results

### F-1 — `</script>` in a visual title (issue-level: page title hijack on load)

Real `.pbix` (9 pages, 147 visuals), rendered by the real `agentic-bi-web-clone`.

| | pre-fix | post-fix |
|---|---|---|
| literal `</script><script>` in HTML | 1 | 0 |
| `document.title` after load (real browser) | **`PWNED_SCRIPT`** | `Evil Report · evil-script.pbix` |
| model still carries the payload string | — | yes, intact |
| console errors | 2 | 0 |

The pre-fix page executed the injected script on load. Post-fix the same string
round-trips into `window.__REPORT_MODEL__` verbatim and does not execute.

### F-2 — JS-string breakout in `onclick` (issue-level: execution on click)

| | pre-fix | post-fix |
|---|---|---|
| handler form | `onclick="showDetails('…')"` | `data-key="…"` + `addEventListener` |
| `document.title` after a real `.el` click | **`PWNED_ONCLICK`** | unchanged |
| details panel opens on click | yes | yes (`textbox #0 · textbox`, page shown verbatim) |
| tabs / filter panel still work | — | 9 tabs switch, panel opens, 5 severity options |

The pre-fix page executed the payload on click; post-fix the click shows the
details panel and the payload stays literal text.

### D-1 — unescaped virtual directory (corrupt `.pbix` written as success)

Donor path replaced with a validly-escaped `&amp;` (decodes to a real `&`, e.g.
`R&D`). A legitimate uneven-member patch is applied through the real CLI.

| | pre-fix | post-fix |
|---|---|---|
| CLI exit code | 0 | 0 |
| `DataModel` in the written file | **unparseable** (`ParseError: not well-formed, column 587`) | parses |
| vdir bytes at offset 1959641 | `<Path>A&B_Storage_1234</Path>` | `<Path>A&amp;B_Storage_1234</Path>` |
| parsed path round-trips | n/a (parse fails) | `A&B_Storage_1234` |

The pre-fix CLI reported success and wrote a `.pbix` whose model cannot be read.
(The new self-verification is what turns this into a loud failure; it is exercised
by the `ambiguous` scenario below and by `tests/test_pbix_binary_hardening.py`.)

### D-3 — ambiguous byte patch (silent first-match edit)

Pattern `ffffffffffffffff`, 437 matching sites in the donor.

| | pre-fix | post-fix |
|---|---|---|
| CLI exit code | 0 | 2 |
| sites edited | 1 (437 -> 436) | none |
| file written | yes (silent, arbitrary site) | no |
| message | — | `pattern … matches 437 sites; set 'occurrence' … or 'all'` |

Pre-fix the CLI silently edited the first of 437 sites and returned success.
Post-fix it refuses without an explicit `occurrence` / `"all"`.

## Verdict

All four Stage 0 defects reproduce end to end and are closed by the working-tree
fixes, with the report still fully functional afterwards. The pre-fix column above
is the evidence that each defect was real, not a code-reading claim.

## Notes

- The pre-fix sources are a **detached git worktree at `HEAD`**; nothing in this
  directory is committed and nothing here is imported by the package or tests.
- Reproduce: `git worktree add --detach <dir> HEAD`, then
  `python other/e2e-verification/binary_e2e.py <dir>/src`, and render both
  variants with `agentic-bi-web-clone` / a `PYTHONPATH=<dir>/src` run.
- The rendered `.html` and `.pbix` artifacts here are disposable build output.
