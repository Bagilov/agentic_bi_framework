# Round ledger

Running log of the improvement loop. Numbers are measured on the working tree
(no commits are made by the loop).

## Baseline (before R1)

| Gate | Value |
|---|---|
| `pytest` | 656 passed, 2 skipped |
| `mypy src` | 166 errors / 25 files (CI baseline 164 → already breached) |
| `ruff check .` | clean |
| `ruff format --check .` | clean |
| Uncommitted tree | 13 modified files, 5 new test files |

## R1 — five zones, review of the uncommitted tree

| Zone | Scope | Result |
|---|---|---|
| A | `guest_*` PowerShell chain | `write_text` chunked (command-line limit), BOM guard, `-LiteralPath`, guarded cleanup, marker can no longer be empty |
| B | `lineage` + `report` PlantUML | `--plantuml` / `--plantuml-png` actually produce artefacts; `render_png` returns the file it produced |
| C | visual types | invented `stackedColumnChart`/`stackedBarChart` removed from engine, skeleton, validator, web mock |
| D | `web_report` UX/UI | a11y (roles, focus, keyboard), dark theme, reduced motion, empty states, responsive, print |
| E | `board_guide` + `shots` | input validation, hotspot clamping/overlap, empty states, deterministic manifest, tool-absent resilience |

## R2 — implement every review finding

| Zone | Findings | Result |
|---|---|---|
| A2 | `_register_on_path` literal path, `Add-Content -Encoding`, non-ASCII `._pth` | done |
| A3 | BOM regression, `$?` footer, child output to log, best-effort teardown, unique task names, `[IO.Directory]::CreateDirectory`, atomic write | done |
| B2 | lazy `out_dir`, umask-safe `export_puml`, three-state PNG diagnostics, race/TOCTOU, stale `<stem>_N.png`, source order, single JVM | done |
| C2 | `chart_visual` emitted `Values` where the validator requires `Y` | done |
| C3 | `Rows` role restored for `barChart`, `clusteredBarChart`, series, duplicate/series invariants, composite visual types | done |
| D2 | print from dark theme, filter-panel focus trap, `BadZipFile`/`KeyError` → exit 2, `--registry` validation, popover focus, scoped checks, mutation-proof tests | done |
| F | lineage typing | 80 → 0 errors in the zone (`LineageState` protocol + PEP 484 self-annotation) |
| G | spec / antipatterns / reportserver boundaries | 45 → 0 errors in the zone, `spec_boundary.py` with field paths |
| H | CLI UX + docs | `validate_pbix:main` + console script, exit-code contract, docs sync |

## R3 — close the remaining gaps

| Zone | Scope | Result |
|---|---|---|
| C4 | the `"In" in json.dumps(filter)` heuristic produced 69 false `unsafe Condition.In` errors on the donor board; remaining `layout_visual` mypy errors | done: 69 → 0, structural `condition.in` walk in `visual_check_filters.py`, 8 → 0 mypy in the zone |
| I | last 16 mypy errors; replace the CI ratchet with a blocking `mypy` | done: `mypy src` clean (164 files), `MYPY_BASELINE`/`set +e`/`tee` removed, one new error fails the leg |
| A4a | `guest_winrm`: command-size budget covering `Replace`/`Move`, non-destructive atomic replace, `_chunks` guard, `ntpath` parent | done: single `MAX_ENCODED_COMMAND = 6000` guard in `ps()`, per-path derived chunk budget, backup-rename chain replaces delete+move, `guest_winrm_commands.py` (223) split out of `guest_winrm.py` (286) |
| A4b | guest log ownership, per-run artefact token, `$?` footer, teardown stop, reserved names, atomic marker | done: runner is the only log writer, `RunPaths` with one `uuid4` token over task/runner/payload/log/marker, `_exit_rule` shared by payload and runner, `Stop-ScheduledTask` before unregister, atomic marker requiring its terminator; split into `guest_task.py` + `guest_task_script.py` (298/298) |
| B3 | PlantUML: stage-inside-`out_dir` publish, stem collisions, duplicate headers, publish `OSError` → exit 1, artefact manifest instead of blind unlink, no `umask(0)` | done: split into `plantuml_names`/`plantuml_publish` (237/206/266), header uniquing `__dg_<n>`, manifest-only cleanup, `java not runnable` → exit 1 |
| B4 | lineage: `_has_diagram_body` parity, JSON-before-checks, `cli_support` docstring, protocol end-to-end, retryable brand cache | done: case-sensitive block parse, diagram work before any export (stdout only on exit 0), `build_lineage_data(model: LineageState)` with a mypy drift test, successful-only brand cache with TypedDicts |
| C5 | `verify_safe_filters` / page-level filters reuse the structural walk (7 false entries on the template) | done: `ok=False` 7 entries → `ok=True` 0 (76 visual + 72 page filters), `engine/verify_filters.py:31`, 8 tests all fail on revert |
| E2 | `shots`: output path leaking into the manifest on failure, `tomllib` without a 3.10 fallback, duplicate figure names, stale PNG on a failed figure | done: `portable()` strips as-given/resolved/symlink-resolved roots and reasons carry no path, `tomllib`→`tomli` fallback (3.10), duplicate-name rejection exit 2, `discard_stale()` for every non-`ok`, IEND completeness probe; `shots_records.py` split out |
| E3 | `board_guide`: print letterbox shifting hotspots by 463 px, panel covering hotspots above 1100 px, non-PNG accepted, launch failure → traceback, aspect-ratio drift | done: print offset −513.58 → −0.002 px, `padding-right:400px` (0/81 dead points), `guide_png.py` signature+IHDR, `ValueError` on a refused launch, aspect warning >1%, `role="button" tabindex="0" aria-label`; `guide_print`/`guide_index` split out |
| D3 | web_report: print clipping of wide canvases, light-theme badge contrast, filter scrim, severity fills in print, single live region, `style` injection | done: `--print-scale` (975 px budget) fixes 1920 px clipping (maxx 708.9 → 748.1 pt), light badges 3.35 → 4.88+, real scrim, print tokens restored, one `role=status`, geometry re-formatted from numbers |
| D4 | web_report: non-dict `config`/`singleVisual`/`projections` tracebacks, `<style>`/comment scoping, popover markers pinned in checks | done: all 5 malformed inputs → diagnostic (0 tracebacks), 4 popover markers added with an independent oracle, `html_issues` wired into `_run`/`--strict` |
| D5 | `web_checks.has_in_filter` is the third copy of the false-positive `In` heuristic (3 legitimate visuals on the template) | done: 3 → 0 via `web_report/web_filter_checks.py` delegating to `visual_check_filters`, malformed payload now `FILTER-UNREADABLE`, 7 tests all fail on revert |

## R4 — integration review of the D3/D4/D5 package, plus the size sweep

| Zone | Scope | Result |
|---|---|---|
| J1 | four oversized core modules (369/347/324/314 lines) | done: `board.py` 175 + `board_page.py` 228, `dax_detail.py` 164 + `dax_detail_extract.py` 246, `spec_boundary.py` 230 + `spec_boundary_values.py` 144, `brand/eval.py` 195 + `eval_rules.py` 165; every top-level unit identical by AST, logger name pinned |
| J2 | three oversized pipeline modules (341/328/333 lines) | done: `automate.py` 143 + `automate_pipeline.py` 242, `build.py` 141 + `pbip_project.py` 221, `reportserver/pbix_analysis.py` 258 + `pbix_report.py` 120; `PbiRsBulk` MRO unchanged |
| J3 | remaining §1 violations | done: `lineage_brand_metrics` → `+lineage_brand_primitives`, `report/pdf_report` → `+pdf_style`, `skeleton/assembly` → `+report_model`, `skeleton/visuals` → `+query_item`; 16/17 functions AST-identical |
| D6 | `visualType` escaping coercion: `[1]`/`{"a":1}`/`5` → `TypeError` traceback, rc 1 | done: `web_checks.visual_type()` + model `__post_init__` coercion, `unknown` for any non-string; renderer sorts only strings; 6 hostile values × 2 tests |
| D7 | print budget was width-only: 1280×1050 → 2 sheets, 1080×1920 → 3 sheets with the caption alone on one | done: A4-landscape box (`1046.93 × 693.41` px after the 10 mm margin and 14 pt caption), scale = min of both axes, `@page size:A4 landscape`, `break-before:page` per page; 6 canvas sizes asserted |
| D8 | dark error badge in the metrics table measured 4.26:1 (test modelled the wrong stack and read 5.12) | done: `--err:#ff8a94`, `--err-bg` α 0.16 → 5.23–5.52:1 on both gradient ends; the test composites tint → panel → bg-from/bg-to |
| D9 | popover focus/announcement: tab switch left the card open, close dropped focus to `<body>`, Escape announced a close for a never-opened card | done: `detailOpen` flag, card closes with its page, focus falls back to `#filterToggle`, announcement and title carry the page |
| D10 | donut hole used the default element surface on severity elements; `#filter-count` empty on open | done: `--el-bg-error`/`--el-bg-warning` tokens (composited in the test), counter seeded at load |
| D11 | page-level `sections[].filters` were not inspected by the clone | done: `PageReport.filter_issues`, counted in summary/tab badge and rendered as a page notice; tri-state `unsafe_in_filter` separates unsafe from unreadable |
| D12 | `HTML-A11Y-MODAL` matched the attribute name, not its value | done: requires `aria-modal="false"`; `true` is reported |
| A5 | guest review leftovers: per-run artifacts leaked, oracle left a whole `.pbix`, shared final `.pbix` race, `_MAX_NAME` in code points, `CONIN$`/`CONOUT$`/`CLOCK$`, second name token, dead `_MARKER_TOKEN`, unused `payload_footer()` | done: finished runs delete payload/runner/marker/`marker.tmp` and keep the log, the oracle deletes its upload, the chain pulls its own per-run build (`ChainResult.guest_build`), the cap counts UTF-16 units, the device list and the `"con "` stem are covered, `task_name` removed, `_EXIT_FOOTER = payload_footer()` |
| P1 | `report/pdf_report` on a hostile `lineage.json`: list-typed `summary`/`meta` and a scalar `pages` raised `AttributeError`/`TypeError`, scalar entries in `tables`/`semantics`/`visuals` raised on `.get`, and an unclosed `<b>` in a header counter raised inside reportlab's parser | done: `as_mapping`/`as_list`/`as_rows` in `lineage_brand_cols`, applied in `lineage_matrix`, `pdf_tables` and `pdf_report`; header counters escaped per value; 17 hostile documents each build a readable PDF |
| T1 | mutation gaps from the review: 6 of 12 mutations survived | done: all 6 (and 5 more from the guest round) now fail a test; each mutation was applied, run and restored with a verified sha256 |

## R4 gate snapshot

| Gate | Value |
|---|---|
| `pytest` | 1521 passed, 4 skipped |
| `pytest --cov` | 76.93% (floor raised 58 → 72) |
| `mypy src` | 0 errors / 185 files (blocking in CI) |
| `ruff check .` | clean |
| `ruff format --check .` | clean (325 files) |

## R5 — the two read-only reviews of R4, implemented

Each finding below was reproduced before the fix and is pinned by a test that
fails when the fix is reverted (11 guest + 11 web mutations, all caught).

| Id | Finding | Result |
|---|---|---|
| G1 (P0) | `run_build` published the finished `.pbix` with `publish_script`, which is an atomic **move**: the per-run file was gone before `build_dashboard` pulled it, `pull_file` read a missing path as size 0, wrote 0 bytes over the caller's previous artifact and still reported `BUILT` | done: `publish_copy_script` (copy to `<dst>.publish.tmp`, then the same atomic `Replace`/`Move`), used by the build stage; the chain pulls the per-run path under an explicit invariant and removes it after the pull |
| G2 (P2) | the pull was silent about a missing/empty/truncated guest file | done: the size probe runs under `$ErrorActionPreference='Stop'`, `0` bytes and a short read are `StageError`s raised **before** the local file is touched |
| G3 (P2) | `COM¹/²/³`, `LPT¹/²/³` are reserved device names and were accepted | done: added to `_RESERVED_NAMES`; `check_name` refuses them |
| G4 (P2) | a lone surrogate raised `UnicodeEncodeError` from the UTF-16 length step, while `check_name` documents `ValueError` | done: `_has_surrogate()` refuses it first; the count uses `surrogatepass` |
| G5 (P2) | `run_task` teardown/cleanup used 4 attempts with 60 s/90 s timeouts and a 2/4/6 s backoff, so a dead guest could add ~6 min per call after the chain's own timeout | done: both `finally` calls run with `attempts=1` |
| G6 (P3) | `write_text` sized the chunk command but not the final move: at a 655-character path the move is 6304 encoded chars (cap 6000) yet `chunk_budget` still returns 876, so every byte was uploaded before the move failed | done: `check_size(replace_script(path))` runs up front |
| G7 (P3) | `utmctl status` had no timeout and `vm.stop()` raised `TimeoutExpired` out of `build_dashboard`, replacing a finished verdict with a traceback | done: 30 s status timeout, VM stop guarded and logged |
| G8 (P3) | stale docstrings and `__all__` drift (`main` documented in `guest_chain` but living in `guest_chain_cli`; `_chunks` re-documented `split_payload`; `guest_winrm`/`guest_winrm_commands` had no `__all__`) | done |
| G9 (P3) | the suite encoded the P0: `test_guest_chain_literal` required the move and `test_guest_chain_pull` answered a size for a path that no longer existed; the oracle-cleanup exception path was untested | done: the move assertions became copy assertions plus "the source survives", the pull test asserts pull-before-cleanup, and the oracle cleanup now has two failure cases |
| W1 (P1) | the print budget still did not fit the sheet: the caption's **line box** is 23 px in Chrome (18.67 px font) while 24.67 px was reserved, and page-level notices were free of charge — every height-bound canvas still tore onto a second sheet | done: `line-height:1.2` pinned in print, caption reserve 28.4 px, per-notice 21 px row + 10 px gap (both measured), 1 px paper-box back-off; verified with real Chrome `--print-to-pdf` (9 canvases × clean/finding, all one sheet) |
| W2 (P2) | closing the card on a page switch stole keyboard focus (`#filterToggle`), killing arrow-key tab navigation and ejecting focus from the filter panel | done: focus is restored only when the card owns it |
| W3 (P2) | two pages with the same `displayName` collapsed into one element key: the card showed the other page's element and the filter jumped pages | done: keys are page-ordinal-qualified (`<ordinal>:<page>#<index>`) and the page filter matches by ordinal |
| W4 (P2) | `json.loads` raises `RecursionError` (not `ValueError`) on deep nesting: a deep layout/config/`prototypeQuery` exited 1 with a traceback | done: caught in `load_layout`, `_element`, `_count_filters` and `_as_prototype_query`; the CLI returns 2 with one line |
| W5 (P2) | the page tab badge counted elements with issues but announced "замечаний: N", contradicting the header | done: the badge uses `PageReport.issues` |
| W6 (P2) | a clean element's only boundary was 1.60:1 (light) / 1.86:1 (dark) against the canvas | done: `--border` light α 0.28 → 0.78 (3.82:1), dark α 0.22 → 0.62 (4.5:1); non-text contrast asserted for both |
| W7 (P3) | page-level findings were missing from the filter panel and never dimmed | done: their check ids are options, each notice carries `data-severity`/`data-check`, and `applyFilters` dims them by the same criteria |
| W8 (P3) | `PageReport.name` was not coerced (a numeric `displayName` disagreed with `ElementReport.page`), and non-`Issue` entries / unknown severities crashed the public model | done: `_page_name`, `_issues` filters, `_sev_label` fallback |
| W9 (P3) | test quality: the print test never measured geometry, the floor was only pinned against `ceil`, the focus test passed for a worse implementation, and `1920×1`/`1×1920` were missing | done: real print geometry, floor-vs-round sizes chosen to differ, ownership-order assertions, hostile canvases added, plus a headless-Chrome pagination test |
| W10 (P3) | `filters_of` was fail-**open** for three malformed shapes: a blob that parses to a single object, a non-object entry, and a double-encoded filter were all reported as "no filters" | done: the shared parser (web clone, `visual_check`, `engine.verify_filters`) returns a readable error for a non-list blob and for a non-object entry, and parses a double-encoded filter instead of skipping it; parity tests in both checkers |

## R5 gate snapshot

| Gate | Value |
|---|---|
| `pytest` | 1635 passed, 4 skipped |
| `pytest --cov` | 78.35% (floor 72) |
| `mypy src` | 0 errors / 185 files (blocking in CI) |
| `ruff check .` | clean |
| `ruff format --check .` | clean (330 files) |

## R6 — the R5 review, implemented

Six findings from the read-only review of the R5 work, three of which were
regressions R5 itself introduced. Each fix is pinned by a test that fails when
the fix is reverted (6 mutations, all caught).

| Id | Finding | Result |
|---|---|---|
| R6-1 (P1) | `publish_copy_script` staged every publish under the shared `<dst>.publish.tmp`: two concurrent chains copying the same declared name hit `FileShare.None` and the cleanup `Remove-Item` of one deleted the other's staging file | done: the staging name carries the run token (`<dst>.<token>.publish.tmp`), `run_build` reuses the same token for the per-run `.pbix`; a token that is not ASCII alphanumeric is refused |
| R6-2 (P1) | the `write_text` move guard measured `replace_script(path)` while the command actually sent prepends the 30-character `$ErrorActionPreference` preamble: a 612-character path measured 5960 encoded chars (under the cap) but sent 6040, so the whole payload uploaded and the guest truncated the move | done: the guard measures the exact final command and that same string is sent; the empty-file command is guarded too |
| R6-3 (P1) | the only `.page-issues li.dim` rule lived in `@media print` and set `opacity:1`, so the page filter's "isolate a finding" changed nothing on screen | done: a screen rule sets `opacity:0.25`; print keeps `1` |
| R6-4 (P2) | `ElementReport.page` coerced through `_text` (`7` → `"page"`) while `PageReport.name` used `_page_name` (`7` → `"7"`), so a numeric `displayName` never matched between the element and its page | done: both use `_page_name`; the fallback for empty/non-text is `"Page"` on both sides |
| R6-5 (P2) | `VMController.stop` ignored `utmctl`'s exit status and logged success, and the chain recorded `vm: stopped` for a refused stop | done: `stop()` returns True only on exit 0, logs the failure detail otherwise, and the chain records "stop was not confirmed by utmctl" |
| R6-6 (P3) | `load_layout` read `Report/Layout` with `z.read` and no decompressed-size bound, in the loader hardened for hostile input | done: a `_MAX_LAYOUT_BYTES` (64 MiB) guard on the declared size plus a bounded read, so a lying header cannot get past it either |

## R6 gate snapshot

| Gate | Value |
|---|---|
| `pytest` | 1645 passed, 4 skipped |
| `pytest --cov` | 78.40% (floor 72) |
| `mypy src` | 0 errors / 185 files (blocking in CI) |
| `ruff check .` | clean |
| `ruff format --check .` | clean (330 files) |

## R7 — a fresh review of the guest chain and the clone

Six fixes from a review of the areas changed in R5/R6 (each pinned by a test that
fails when the fix is reverted; 6 mutations, all caught).

| Id | Finding | Result |
|---|---|---|
| R7-1 (P2) | `agentic-bi-guest-dashboard --json` was honored only on the success path: both `NOT_CONFIGURED` branches (and the `RuntimeError` branch) printed to stdout and dropped the file, so a CI job that reads the verdict got nothing and had to scrape stdout | done: `_emit(..., args.json)` on every path, including the missing-configuration one |
| R7-2 (P2) | a bad budget escaped as a traceback: `--timeout -5` raised `ValueError: deadline must be positive` and `AGENTIC_BI_CHAIN_TIMEOUT=abc` raised `ValueError: invalid literal for int()` out of `main` (exit 1, full traceback), while the CLI contract for a bad value is exit 2 and one line | done: `from_env` names the variable and the value, `--timeout <= 0` is refused explicitly (a `--timeout 0` used to be silently ignored), and the body runs under `run_boundary` |
| R7-3 (P2) | an empty report page printed **without its name**: `.canvas-title` was emitted only when the page had elements, and the tabs are hidden on paper, so a page with no visuals printed as a bare "Страница без визуалов" placeholder | done: the caption is emitted for every page, before the canvas/empty state; a headless-Chrome test pins that the added caption still prints as one sheet |
| R7-4 (P3) | `push_file` checked the deadline inside the `finally` that closes the staging server, so a concrete fetch failure was replaced by a generic `push: exceeded the budget` whenever the clock had also run out | done: the server is closed in `finally`, the budget is checked after it |
| R7-5 (P3) | `pull_file` parsed the size probe with `int(last line)`: a warning line on stdout escaped as `error: ValueError: invalid literal for int()`, naming neither the guest file nor the stage | done: only an all-digit line is accepted (same rule as the build-size probe); otherwise `StageError` names the path and the raw answer |
| R7-6 (P3) | `test_guest_chain` had no CLI boundary coverage: `main` was only exercised for `NOT_CONFIGURED`, which is why R7-1 and R7-2 were invisible | done: `TestChainCliBoundary` (json file, `--timeout` and env budgets) plus `test_guest_staging_push.py` (fetch failure vs budget, checksum mismatch) |

## R7 gate snapshot

| Gate | Value |
|---|---|
| `pytest` | 1657 passed, 4 skipped |
| `pytest --cov` | 78.52% (floor 72) |
| `mypy src` | 0 errors / 185 files (blocking in CI) |
| `ruff check .` | clean |
| `ruff format --check .` | clean (331 files) |

## R8 — the round table (four independent reviewers)

Four read-only reviewers with disjoint lenses (guest chain · web clone ·
documents/reportserver/lineage · cross-cutting contracts). Each was required to
verify every claim against an artefact and to drop what it could not demonstrate;
26 findings were accepted (6 of them P1) and every one was implemented. 20 are
pinned by a mutation-checked test (20 mutations, one per fix, all caught); the
other six are the documentation, typing and test-hygiene items (D2-D6, plus the
report-server boundary that D and C reported independently and that is covered by
one test).

Guest chain (reviewer A):

| Id | Finding | Result |
|---|---|---|
| A1 (P2) | the staging step has no per-run identity: `extract_zip` removes the shared `guest.root` while another chain's builder imports from it, and `abf.zip` has one name per guest — the only two paths without a token | done: `chain_lock_script` takes an atomic `[IO.File]::Open(..., CreateNew, ...)` lock (stale after the chain budget) and `run_build` releases it in `finally`; a live lock is a `STAGE_FAILED`, never a silent wipe |
| A2 (P3) | `int(deadline.remaining)` under one second is `0`, and `Deadline(0)` raises: an exhausted budget was reported as `ORACLE_FAILED / ERROR:ValueError` instead of `TIMEOUT` | done: `< 1 s` left records "no budget left" and returns `TIMEOUT` before the oracle is called |
| A3 (P3) | `_MAX_NAME` budgets the name only; with a long `GUEST_OUT` the payload path passed `MAX_PATH` and the teardown command passed the encoded cap, where the broad `except` swallowed it and leaked the run's files | done: `run_paths` validates every artifact against `MAX_PATH` and the cleanup command against the encoded cap, with a message naming both limits |
| A4 (P3) | `build_script` hardcoded the Desktop `bin` directory although `GuestConfig.desktop` models it and the oracle honours it | done: `guest.desktop or _DEFAULT_DESKTOP_BIN` |

Web clone (reviewer B):

| Id | Finding | Result |
|---|---|---|
| B1 (P1) | a list where a name belongs (`Select[].Name`, `From[].Name`, `SourceRef.Source`, `queryRef`) was used as a set member / dict key: `TypeError: unhashable type` aborted the whole clone | done: only strings are hashed; the rest becomes a diagnostic |
| B2 (P1) | a lone UTF-16 surrogate (legal JSON `"\ud800"`) reached `write_html` and raised `UnicodeEncodeError`: no document at all | done: `_scrub` at the model boundary replaces surrogates and NUL with U+FFFD |
| B3 (P2) | `zlib.error`/`EOFError`/`RuntimeError` from a damaged member escaped `load_layout` as a traceback | done: translated to a `ValueError` naming the file |
| B4 (P2) | a page-level finding was the *only* match of a filter: no page was switched, the matching notice stayed in a hidden panel and the counter said "0 элементов" | done: the target page comes from the first visible notice, and the counter names the page findings |
| B5 (P3) | the metrics table honoured only severity, so page/kind/check isolation never dimmed it | done: rows carry `data-page-idx`/`data-kind`/`data-checks` and share `matches()` with the elements |
| B6 (P3) | the counter seed called the full `applyFilters()`, which jumped to the first element's page and overrode the server-rendered tab | done: `applyFilters(true)` fills the counter only |
| B7 (P3) | the element key travelled as an attribute; the HTML parser folds CR to LF and NUL to U+FFFD, so the client lookup missed | done: CR is emitted as `&#13;` and NUL is scrubbed at the model boundary |
| B8 (P3) | `_print_scale` budgets the whole sheet, but sheet 1 also carried `header` and the summary grid: a one-page report printed as three sheets | done: both are print-hidden; verified with real Chrome (3 → 1) |

Documents, report server, lineage (reviewer C):

| Id | Finding | Result |
|---|---|---|
| C1 (P1) | `use_l7 = include_visuals or max_level >= 7` was true for every default run, so all L1-L6 rows printed through the visual layout and lost origin/source/table/semantics (the summary layout was dead code) | done: one table per layout — identity rows keep `SUMMARY_COLS`, visuals get `L7_COLS` |
| C2 (P1) | a failed Report Server read was indistinguishable from a single entity: a 401/500 reported one `Unknown` item, `count: 1` per entity set and exit 0 | done: `_get_json` returns `None`, `walk_values` stops instead of inventing a record, `run()` reports `fetch_errors`, the CLI exits 1 and the config is inside `run_boundary` |
| C3 (P1) | `theme#<ColorId>` never parses to hex and was dropped silently: 59 of 147 donor visuals had no colour data yet were rated `ok` | done: unresolved tokens are counted, and a page with only theme colours is `unknown`, not `ok` |
| C4 (P2) | the first diagram tile ignored the heading already on its page, so the heading occupied a sheet alone | done: `_tiles(first_h=...)` sizes the first tile from the space left |
| C5 (P2) | the diagram was resolved only when `find_plantuml_jar()` succeeded, and the "diagram omitted" note keyed on a field nothing writes, so a requested diagram vanished without a word | done: the source is always resolved (it needs no jar) and `diagram_story` prints its own state |
| C6 (P3) | `None` compliance printed as "fonts None%" | done: `n/a` in the summary line and in `brand_label` |
| C7 (P3) | `verify_manifest` re-hashed the PNG but never compared the recorded `bytes` | done: a size mismatch is drift |

Cross-cutting (reviewer D):

| Id | Finding | Result |
|---|---|---|
| D1 (P1) | `agentic-bi-pbix-patch` promised exit 2 for an unreadable `.pbix`, but `zipfile.BadZipFile` is not an `OSError` | done: `BadZipFile` is an input error for every command |
| D2 (P2) | the docstring claimed `--json` is written on "every path", including a rejected budget | done: the doc now says "every path that reaches a verdict" |
| D3 (P2) | `assert "/Users/" not in stdout` cannot fail on a Linux CI checkout | done: asserts the real tmp path and any absolute home-style path |
| D4 (P2) | `tests/test_guest_chain.py` was over the 300-line rule | done: split into `test_guest_chain.py`, `test_guest_chain_cli.py`, `test_guest_vm.py` |
| D5 (P2) | the coverage comment contradicted itself ("~60%" and "77%" in one sentence) while the suite measures 79% | done: one measured figure |
| D6 (P3) | the package docstring still described the shell as "dark theme" | done: light-first, dark under `prefers-color-scheme` |
| D7 (P3) | `_side(value: Any)` was added under a comment claiming no `Any` | done: `object` |

## R8 gate snapshot

| Gate | Value |
|---|---|
| `pytest` | 1694 passed, 4 skipped |
| `pytest --cov` | 79.51% (floor 72) |
| `mypy src` | 0 errors / 185 files (blocking in CI) |
| `ruff check .` | clean |
| `ruff format --check .` | clean (340 files) |

## Gate snapshots

| Point | pytest | mypy |
|---|---|---|
| baseline | 656 passed, 2 skipped | 166 / 25 files |
| after R1 | 1135 passed, 4 skipped | 149 / 23 files |
| after R2 | 1166 passed, 4 skipped | 16 / 6 files |
| after R3 | 1475 passed, 4 skipped | 0 errors, 182 files, blocking |
| after R4 | 1521 passed, 4 skipped | 0 errors, 185 files, blocking |
| after R4.1 (PDF boundary) | 1542 passed, 4 skipped, 78.13% cov | 0 errors, 185 files, blocking |
| after R5 (R4 reviews) | 1635 passed, 4 skipped, 78.35% cov | 0 errors, 185 files, blocking |
| after R6 (R5 review) | 1645 passed, 4 skipped, 78.40% cov | 0 errors, 185 files, blocking |
| after R7 (chain/CLI review) | 1657 passed, 4 skipped, 78.52% cov | 0 errors, 185 files, blocking |
| after R8 (round table) | 1694 passed, 4 skipped, 79.51% cov | 0 errors, 185 files, blocking |

## Defects the loop found that no test had caught

These are the ones worth remembering, because each was invisible to the suite:

1. `stackedColumnChart` / `stackedBarChart` do not exist in Power BI Desktop.
   Desktop renders them as an uninstalled *custom* visual. Only the guest's
   automation tree showed it.
2. `barChart` legitimately carries a `Rows` role — visible in
   `templates/template.pbix`, contradicted by a comment in the validator.
3. `powershell.exe -File` without a BOM decodes the script in the ANSI code page,
   so a Cyrillic `--title` was silently corrupted while the build still
   reported success.
4. `Remove-Item <missing>` under `$ErrorActionPreference='Stop'` exits 1, so the
   first run on a clean guest failed its own cleanup.
5. A `PowerShell` payload dot-sourced into the marker writer lost its exit code
   (`exit N` skipped the marker; `$LASTEXITCODE` after a cmdlet is `$null`).
6. `render_png` returned any PNG it found in the output directory, not the one it
   produced.
7. `--plantuml` was accepted and silently ignored, so no run ever produced a
   `.puml`.
8. `check_pbix` searched for the substring `In` in serialised filters, flagging
   69 legitimate filters on the donor board. The same heuristic survived in
   `verify_safe_filters` (7 more false entries) and in `web_checks.has_in_filter`
   (3 visuals) after the first fix, because each checker had its own copy.
9. `shots` wrote the output path into the manifest reason only on failure, so
   "two runs are byte-identical" held exactly where nothing failed.
10. `board_guide` print applied `max-height:100vh` under `width:100%`, which turned
   on `object-fit: contain` and moved every hotspot by up to 463 px on paper.
11. `web_report` print clipped the right ~45% of every 1920 px canvas: paged media
   has no horizontal scrolling, so the content was cut, not pushed to a new page.
12. The light theme shipped badge text at 3.25–3.77:1 while dark and print passed —
   the contrast regression came in with the new palette, not with the print work.
13. `details::details-content` keeps `content-visibility:hidden`, so a closed
   `<details>` was never painted even with `display:block` on its children: the
   147-row table silently disappeared from the PDF.
14. The print budget was only horizontal: an A4 landscape sheet also limits the
   height, so a 1280×1050 canvas was torn across two sheets and a 1080×1920 one
   across three, with the page name alone on the first.
15. The dark error badge passed its own contrast test because the test composited
   the tint over `--surface` while the table actually sits on `--panel` over a
   gradient: measured 4.26:1 against a claimed 5.12:1.
16. A non-string `visualType` in an untrusted layout was used as a dict key and in
   `sorted()`, so `[1]`, `{"a":1}` or `5` aborted the whole clone with a traceback.
17. `run_task` never removed its per-run payload/runner/marker, and the oracle
   never removed its uploaded `.pbix`: every run leaked four files, every oracle
   run a whole board.

18. The publish step of the build stage was an atomic **move**, so the chain pulled
    a path that no longer existed: 0 bytes replaced the previous good board and
    the verdict stayed `BUILT`. The suite modelled neither `Replace` nor `Move`, and
    one test explicitly required the move.
19. The print fit reserved the caption's font size instead of its line box and
    never counted the page-level findings: a 4.3 px overflow is enough for Chrome
    to break a `break-inside:avoid` block onto a second sheet.
20. Two pages with the same `displayName` produced one element key, so a click on
    one page's element opened the other page's metrics.
21. `json.loads` raises `RecursionError` on deep nesting, which is not a
    `ValueError`: an untrusted layout exited 1 with a traceback.
22. A tab switch that closed the detail card moved focus to `#filterToggle`; the
    arrow keys then went nowhere because the listener sits on `#pageTabs`.
23. `COM¹` / `LPT³` are reserved device names on Windows (the superscript digits
    are read as digits), so the payload of a run named that way targeted the
    console instead of creating a file.
24. `run_task`'s `finally` ran with four WinRM attempts and a 60 s operation
    timeout: a dead guest could add ~6 minutes *per teardown call* after the
    chain's own budget had already expired.

25. `publish_copy_script` used one staging name per **destination**, not per run:
    two chains publishing `<out>\board.pbix` shared `board.pbix.publish.tmp`, and
    the `FileShare.None` copy plus the cleanup `Remove-Item` turned a valid
    publish into `STAGE_FAILED`.
26. The `write_text` size guard measured a string that the channel never sent:
    the 30-character preamble pushed a 612-character path from 5960 to 6040
    encoded characters, so the guard passed and the guest truncated the move
    after the whole payload had been uploaded.
27. The page filter toggled `.dim` on page-level notices, but the only matching
    CSS rule sat inside `@media print` with `opacity:1` — the interaction was
    implemented and invisible.
28. A numeric `displayName` produced `"page"` on the element side and `"7"` on
    the page side, so the element could never be matched to its own page.
29. `utmctl stop`'s exit status was ignored: a refused stop logged "stopped VM"
    and the chain result claimed the VM was stopped.
30. `load_layout` decompressed `Report/Layout` without a size bound, so a zip
    bomb declared in an untrusted `.pbix` was read into memory before any JSON
    validation ran.
31. The chain CLI's `--json` was silently dropped on the `NOT_CONFIGURED` path,
    and a malformed budget (`AGENTIC_BI_CHAIN_TIMEOUT=abc`, `--timeout -5`) left
    the process as a traceback with exit 1 instead of exit 2 and one line.
32. An empty report page had no printed caption at all: the page name lived only
    in `.canvas-title`, which was emitted for pages with elements.
33. `push_file` checked its deadline inside the `finally` that stops the staging
    server, so a real fetch error became a generic budget timeout.
34. `pull_file` turned a noisy size probe into a bare `ValueError` that named no
    file and no stage.
35. A list where a prototype `Name` belongs made the whole clone fail with
    `TypeError: unhashable type` — one malformed visual, no document.
36. A legal JSON lone surrogate (`"\ud800"`) made `write_html` raise
    `UnicodeEncodeError`, so the clone produced nothing at all.
37. Two concurrent chains shared the staged framework: `extract_zip` deleted the
    tree the other builder was importing from, and one upload broke the other's
    SHA-256 probe.
38. A Report Server 401/500 was reported as one `Unknown` item and exit 0, so an
    unreachable server looked like an empty one.
39. Theme colour ids never resolved to hex and were dropped, so a page with only
    theme colours was rated "brand compliant" while nothing had been measured.
40. The PDF matrix used the visual column layout for every level, hiding the
    origin/source/table cells of the L1-L6 rows.
41. The first diagram tile ignored the heading on its page, so the PDF opened the
    diagram section with a sheet that contained only its title.
42. A one-page web clone printed as three sheets: the print fit budgeted the whole
    sheet although the header and the summary grid were also printed.
43. The printed element key lost its carriage return to HTML attribute
    normalisation, so clicking such an element opened nothing.
