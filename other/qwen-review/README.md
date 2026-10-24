# Qwen second-opinion review of `agentic_bi_framework`

- **Date:** 2026-10-21 (rounds 1–2), 2026-10-22 (round 3), 2026-10-24 (rounds 4–7)
- **Purpose:** obtain an independent review of the framework's current state
  before committing to a refactoring plan, and cross-check our own
  measurements against an outside opinion.
- **Method:** `manage_webllm ask` against chat.qwen.ai (single chat per round,
  not a subagent), with the measured repository state pasted as the prompt.
  Each round's `prompt*.md` is what was sent; `answer*.md` is the reply verbatim.
- **Files:**
  - `prompt.md` / `answer.md` — round 1: general state, architecture, staged plan.
  - `prompt-round2.md` / `answer-round2.md` — round 2: security, packaging,
    WinRM, domain testing, logging, release.
  - `prompt-round3.md` / `answer-round3.md` — round 3: the binary layer
    (ABF codec, relayout, container swap, patch pipeline).
  - `prompt-round4-paths.md` / `answer-round4-paths.md` — round 4: every service,
    split into the user path (11 console entry points) and the agent path
    (`agents.py` + the spec `support` section).
  - `prompt-round5-openspec-code.md` / `answer-round5-openspec-code.md` — round 5:
    the OpenSpec change reviewed as files, with the spec and the implementing
    sources attached in three bundles (`round5-*.md`).
  - `prompt-round6-contracts.md` / `answer-round6-contracts.md` — round 6: the
    CLI boundary contract and the agent-manifest validation re-reviewed, in three
    bundles (`round6-*.md`).
  - `prompt-round7-spec-path.md` / `answer-round7-spec-path.md` — round 7: the
    declarative spec path (spec -> layout -> validate -> web), in three bundles
    (`round7-*.md`).
  - `prompt-round8-brand-verify.md` / `answer-round8-brand-verify.md` — round 8:
    the publication gate (brand-audit + engine-verify), in three bundles
    (`round8-*.md`).
  - `security-findings.md` — the two `web_report` injection defects, reproduced
    in a browser.
  - `binary-layer-findings.md` — the three `pbix_binary` defects, reproduced
    against the shipped donor.
  - `round4-findings.md` — the round-4 findings, each re-measured before adoption.
- **Disclaimer:** these are external-reviewer outputs and measurements, not
  authorization for changes. They are recorded as evidence; the plan decides.
- **Result:** folded into `docs/IMPROVEMENT_PLAN.md` as the `[Q]` annotations.
  Nothing from this directory is imported by the package or the test suite.

## Round 1 verdicts

Qwen's stage ordering was adopted with corrections. Two claims were rejected
after local verification:

- a coverage gate of 60 %/75 % "on start" would fail immediately (measured
  baseline is 37 %), so the plan uses a ratchet at the measured floor;
- `mypy --strict` as a near-term goal is out of scope for 92 modules.

One claim was confirmed and sharpened: the `pytest` vs `python -m pytest`
divergence. Qwen's suggested fix (`pythonpath = ["."]`) was tested and works;
the alternative it mentions (`tests/__init__.py`) was rejected.

## Round 2 verdicts

Adopted: escaping the embedded JSON, golden round-trip tests, moving writes out
of `site-packages`, `PlatformNotSupported` on non-Windows, single-sourcing the
version, domain exceptions by inheritance, no upper dependency bounds, no shipped
lock file, and only targeted `print` → `logging`.

Corrected: Qwen called the injection "High/Critical" and was right to; but its
"suffices" answer covers only the `<script>` sink. For the `onclick` sink,
escaping is the wrong class of fix and the string must stop being built as
JS-in-HTML.

Partially rejected: Qwen proposes replacing the WinRM/scheduled-task stack with a
direct `msmdsrv.exe` launch. Inspecting `_engine_build.ps1` shows it loads
Desktop DLLs and reads the Desktop-created workspace port, so it drives an engine
Desktop started rather than starting one — this is a research question, not a
known simplification, and was moved to the backlog as such.

Added beyond the review: a second, independent source into the same JSON sink
(an entity name reaching an issue message), which is why the fix is specified at
the serialization sink rather than per input.

## Round 3 verdicts

Adopted: serialize the ABF virtual directory with `ElementTree`; fail fast on
ambiguous patches with an optional `occurrence`; make self-verification a
mandatory part of `apply_patches` (no `--no-verify`); range validation as a
`0.0.2` item; and the test additions (Hypothesis round-trips, mutation fuzzing,
truncation matrix, `swap_datamodel` byte-exactness).

Verified before adopting: `ET.tostring(..., encoding="unicode")` emits no XML
declaration and is **byte-identical** to the current hand-rolled serializer for
normal paths, so the escape fix cannot change the format for existing donors;
and `swap_datamodel` with an identical `DataModel` is already byte-identical on
the shipped donor, so the proposed test pins current behaviour rather than
demanding a change.

Rejected as a defect: up to 7 trailing bytes on a `DataModel` member are ignored
silently. Real but harmless; recorded as a `logger.debug` note, not filed.

Added beyond the review: `apply_patches` failing silently was traced to a full
end-to-end reproduction (valid zip on disk, unparseable `DataModel` inside), and
the byte-exactness check that cleared `swap_datamodel` was run rather than
assumed.

## Round 4 verdicts

Scope: every service, split by consumer — the user path (11 console entry points)
and the agent path (`agents.py` + the spec `support` section). Findings in
`round4-findings.md`.

Adopted (each re-measured here, raw exit codes recorded):

- the user path leaks unhandled exceptions where a docstring promises an exit
  code (`visual-check`, `pbix-patch`, `brand-audit`, `engine`, `test-build`,
  `lineage`, `report` all print a traceback and exit 1; `web-clone` is the only
  one that catches and prints `error: ...`);
- exit code `2` is overloaded (CLI misuse vs input/spec error);
- `lineage.main()` has no exit contract at all;
- default outputs are written inside the installed package
  (`lineage:180`, `antipatterns:181`) — a `PermissionError` in a read-only install;
- `from_manifest` accepts any `stage`, producing an agent that no stage resolves
  (`all_agents("WRONG")` returns `[]` silently while `agents_for_stage` raises);
- `render_kilo_agent(agent, path)` never uses `path`.

Corrected: Qwen's `render_kilo_agent` path-traversal note is described as a live
risk; it is **latent** — today the function only returns a string and never
writes, so nothing sanitises or traverses. It is recorded as a caveat for whoever
implements the write, not as a vulnerability.

Priority table (both paths, one root cause — boundaries are more permissive than
the contracts they advertise):

| Priority | Item | What |
|---|---|---|
| P0 | U-4 | default outputs written into `site-packages` — **fixed** (CWD-relative) |
| P0 | G-1 | invalid `stage` accepted → orphan agent, silent — **fixed** (raises) |
| P1 | U-1, U-3 | tracebacks instead of exit codes; `lineage` has no contract — **fixed** (`run_boundary`) |
| P1 | U-2 | exit code `2` overloaded — **resolved** (0/1/2 documented per CLI) |
| P2 | G-3 | dead `path` parameter + latent traversal caveat — **fixed** (param removed) |
| P3 | G-2 | document `resolve_agents` priority (no code change) — **done** (docstring) |

All six were closed after round 5, with tests in `tests/test_agents.py` and
`tests/test_cli_boundary.py`; see `REVIEW_DECISIONS.md` ("Round 4 follow-up").

## Round 5 verdicts

Scope: the OpenSpec change `stage0-hardening-and-guest-chain` reviewed **as
files** — spec, design, tasks and the implementing sources sent as three
attachment bundles (`round5-openspec-bundle.md`, `round5-code-a-guest.md`,
`round5-code-b-graph.md`). Prompt: `prompt-round5-openspec-code.md`; reply:
`answer-round5-openspec-code.md`.

Adopted and fixed (each re-measured here before the fix):

- `guest_staging.push_file` verified SHA-256 fail-open: an empty `Get-FileHash`
  result skipped the check, so a missing/unreadable staged file passed as verified
  (Critical);
- `guest_winrm.run_ps` ignored `status_code`, so a non-zero guest script read as an
  empty success (Warning);
- `guest_chain_cli._emit` raised on an unwritable `--json` path instead of keeping
  the documented contract (Warning).

Spec/docs from the same round: hash-less and non-zero-exit scenarios, the exit-code
table (0/1/2), and the "no `ps_quote` inside double quotes" caveat. BR-7's
contradiction (spec promised what `tasks.md` 5.2/5.3 still mark `[ ]`) is resolved by
making the open items explicit on both sides.

Corrected after measurement: the finding "`escapeHtml` replaces each character with
itself, so XSS via `innerHTML` remains" is a **false positive** — the source and the
bundle both hold `{'&': '&amp;', '<': '&lt;', …}`; the reviewer's rendering dropped
the entity text.

## Round 6 verdicts

Scope: the round-4/5 boundary fixes re-reviewed — `cli_support.run_boundary`, the
`agents.py` manifest validation, and the CWD-relative default outputs. Prompt:
`prompt-round6-contracts.md`; reply: `answer-round6-contracts.md`; code in three
bundles (`round6-code-1-cli-agents.md`, `round6-code-2-clis.md`,
`round6-code-3-tests.md`).

Adopted and fixed:

- `patch_cli` never used `run_boundary`: `load_spec` parses JSON, so a malformed
  spec raised `JSONDecodeError` (a `ValueError`) as a traceback — the exact
  contract BR-7 promises. Wrapped; a bad spec now exits 2 (Warning);
- `test_build` used `raise SystemExit(...)` for a *configuration* error
  (non-Windows without `--datamodel`), exiting 1 and bypassing the boundary. Now a
  `ValueError`, mapped to exit 2 (Nit).

Confirmed correct (no change): `resolve_agents` stays self-consistent after the
`stage` validation (it calls `from_manifest`, so a bad spec manifest propagates the
same `ValueError`); the reviewer agrees `engine_cli._parse_pages`'s `ValueError` on
`--assert-pages "Overview=abc"` is correctly bad input.

## Round 7 verdicts

Scope: the declarative spec path — `spec.py` -> `engine_layout*.py`,
`validate_pbix.py`, `thresholds.py`, `web_report/` — a fresh area no earlier round
covered. Prompt: `prompt-round7-spec-path.md`, reply:
`answer-round7-spec-path.md`, code in `round7-code-{1,2,3}-*.md`. The exchange was
delayed by an aliyun WAF CAPTCHA on the composer (needed a human) and an earlier
attempt returned a reply from an unrelated chat; it completed on retry.

Local audit + Qwen findings, all re-measured and fixed:

- `spec.py` crashed on malformed untrusted input (bare `KeyError` on a field
  without `property` or a spec without `name`; `AttributeError` on a non-dict
  element) while `validate_spec` reported nothing — now validated and reported
  (also duplicate page names, bad `pos`, unknown field `kind`);
- `engine_layout.build_report([])` raised `IndexError` — now `ValueError`;
- `thresholds.resolve_thresholds` flattened one level, so the documented
  `quality: {thresholds: …}` / `deploy: {guardrails: …}` overrides matched no
  catalog key and were silently dropped (fail-open on the hard gate
  `quality.max_layout_problems = 0`) — now flattened, with a wrong-type override
  keeping the default and unknown keys logged;
- `validate_pbix.validate_layout({})` silently fell back to `EXAMPLE_REGISTRY`
  (falsy empty dict) — only `None` falls back now;
- `web_report` `has_in_filter` / `web_inspect` aborted the whole report on a
  non-dict filter blob or a non-numeric coordinate — now tolerated;
- **Qwen:** `prototypeQuery` carried as a JSON string made `validate_layout` and
  `web_checks` raise `AttributeError` (Critical) — now parsed; confirmed latent,
  not present in the shipped donors (749 `None` + 303 `dict`, no string);
- `build_gallery({'tables': []})` raised `IndexError` — now `ValueError`;
- `get_threshold` on a typo returned `None` silently — now logs a warning;
- with no registry the model-membership layer is skipped silently — `web-cli` now
  warns on stderr.

Corrected: Qwen's "`build_layout_from_spec` incompatible with `DashboardSpec`
(Critical)" is a naming issue — the two "spec" objects live on separate paths; the
docstring now states it.

Tests: `tests/test_spec_path.py` (22) + a web-cli warning test. Suite: 212 passed,
2 skipped.

## Round 8 verdicts

Scope: the **publication gate** — `brand_audit*.py` / `brand*.py` (brand-book
audit) and `engine_verify*.py` / `rebuild.py` / `engine_container.py` (structural
check of the produced `.pbix`) — a fresh area. Prompt:
`prompt-round8-brand-verify.md`, reply: `answer-round8-brand-verify.md`, code in
`round8-code-{1,2,3}-*.md`.

Qwen findings, each re-measured before adoption:

- `brand_audit_math.luminance` (Critical) — a non-hex value (`""`, `"rgb(...)"`)
  raised `ValueError` from `int(h[1:3], 16)` and **crashed the whole audit**;
  reproduced by calling it directly. Now `_channels` returns `None` and
  `luminance`/`contrast` raise a clear `ValueError`, while `is_neutral` stays a
  predicate (`False`), not an exception;
- `brand_audit_eval._eval_contrast` (Warning, fail-open) — an unknown background
  was replaced with `#ffffff`, so a light-on-dark violation compared against white
  and passed silently; now the text colors are reported once as un-assessed;
  reproduced by driving `evaluate_observations` with a light chromatic color;
- `engine_verify_core.load_layout` / `engine_verify_brand.extract_report_theme`
  (Critical) — `Report/Layout` was decoded as UTF-16LE only, so a UTF-8 layout
  (re-exported/hand-edited `.pbix`) crashed `verify_pbix` with
  `JSONDecodeError`; reproduced by re-zipping a real layout as UTF-8. Both now use
  a shared sniffing decoder;
- `engine_verify_checks.verify_layout` (Critical, fail-closed) — "all visuals have
  projections" failed on decorative visuals (`shape`/`textbox`/`image`/
  `pageNavigator`), which legitimately have none; reproduced on every real donor
  `.pbix` (e.g. 347 errors in `visual_check` before). Now decorative types are
  exempt;
- a container without `config` / a `singleVisualGroup` raised `KeyError` in
  `_iter_visuals`; reproduced with an in-memory layout. Now skipped;
- `brand_audit_math.font_weight` (nit) — "Extra Bold" (spaced) matched `bold`
  instead of `extrabold`; reproduced. Now separators are ignored;
- `engine_verify_checks.verify_bindings` (Warning) — table/column names were
  matched case-sensitively, so a layout with `sales` vs the spec's `Sales` failed;
  reproduced. Now case-insensitive (DAX is), while a genuinely missing table still
  fails;
- `brand_audit_extract._paint_observations` (Warning, fail-open) — a gradient/
  pattern/picture fill whose color could not be read was dropped, so it escaped
  the palette check silently; now it becomes a `PAINT-UNRESOLVED` info finding;
- the parallel theme path (`brand_eval_common._is_neutral` +
  `brand_eval_background`) had the **same** crash on a non-hex color; reproduced
  via `check_brand_compliance` and hardened identically.

Extracted to keep files within budget: `layout_meta.py` (shared decoder + the one
decorative-type list + a tolerant visual iterator, now used by
`engine_verify_*`, `visual_check`, `rebuild`, `web_inspect`, `web_checks`) and
`brand_audit_typography.py` (font family/weight/size rules out of
`brand_audit_eval`). `NON_DATA_TYPES is DECORATIVE_VISUAL_TYPES` now — one source
of truth.

Not adopted: Qwen's `verify_model_data` soft-failure on a missing `pbixray` is by
design (third-party decoder, documented); the 8-digit `normalize_hex` ARGB/RGBA
ambiguity is not reachable from the audited sources.

Tests: `tests/test_gate_robustness.py` (26). Suite: 238 passed, 2 skipped;
`ruff check .` clean, 145 files formatted.

## Round 9 verdicts

Scope: the **lineage analysis + report generation** area — `lineage/*` (model,
queryRef/DAX parsing, origins, export, PlantUML, brand metrics) and `report/*`
(matrix/table builders, PDF via reportlab, diagram tools) — a fresh area. Prompt:
`prompt-round9-lineage-report.md`, reply: `answer-round9-lineage-report.md`, code
in `round9-code-{1,2,3}-*.md`.

Qwen findings, each re-measured before adoption:

- **aggregated queryRefs lost their table** (Critical, real) —
  `lineage_types._split_table_col` split `Sum(Opportunities.Discount)` into
  `('Sum(Opportunities', 'Discount)')`, and `_strip_agg` only ran in
  `_resolve_table` on an already-mangled token. Reproduced on the shipped donors:
  14 of 168 bindings had `table=None`, `unresolved_table_refs` showed
  `Sum(Opportunities`, `Avg(Opportunities`, `Min(Accounts`. Now the wrappers are
  stripped first (repeatedly, so `Count(Distinct(T.C))` works); real donors went
  14 → 1 unresolved, the remaining one being a genuine display name that needs an
  alias and is correctly reported;
- **a double quote broke the PlantUML** (Warning, real) — `_pu_escape` did not
  escape `"`, but the label is interpolated into a quoted `package "..."`, so a
  name with a quote produced `package "He said "hi"" {`. Reproduced directly. Now
  `"` is escaped, and the `package "{group}"` in the renderer is escaped too;
- `lineage_model._resolve_table` was case-sensitive (Warning) — aligned with the
  round-8 `engine_verify_bindings` fix: names are now matched case-insensitively
  (a `_tables_lower` map), while a genuinely unknown table is still reported;
- **non-string queryRef** (Warning) — `_split_table_col` called `.split` on an
  `int`/`None`/`bool`, raising `TypeError`; reproduced. Now a non-string yields
  `('', None)`.

**Corrected / not adopted:** Qwen's "critical" — `pdf_report._safe` and
`pdf_tables._esc` "do not use `html.escape()`" — is false: both escape
`&`/`<`/`>` and a hostile name (`Sales&Marketing`, `Table<Column`,
`</font><b>x`) renders fine as a reportlab `Paragraph` (pinned by a test). The
"`_strip_agg` trailing characters" nit only bites on a non-aggregate token that
`_split_table_col` no longer feeds it.

Tests: `tests/test_lineage_report_robustness.py` (10). Suite: 248
passed, 2 skipped; `ruff check .` clean, 145 files formatted.

## Round 10 verdicts

Scope: the **Report Server diagnostics, DAX antipatterns and automation** area —
`reportserver/*` (OData catalog walk, `.pbix` download/analysis, index),
`antipatterns/*` + `dax_detail.py`, and `automate.py` / `cli_support.py` /
`engine_cli.py` — a fresh area. Prompt: `prompt-round10-reportserver.md`, reply:
`answer-round10-reportserver.md`, code in `round10-code-{1,2,3}-*.md`.

Qwen findings, each re-measured before adoption:

- **no OData pagination** (Critical, real) — the catalog walk used a fixed
  `$top` (1000/500) and ignored `@odata.nextLink`, so a server with more items
  than one page was read only up to the first page and reported as complete.
  Measured with a two-page fake: the old walker returned 1000 of 1500. The walk
  now follows `nextLink` to the end (with a seen-set guard against a server that
  loops on one link), bounded samples opt out with `paginate=False`. Extracted to
  `reportserver/odata.py` (`walk_values`) to stay within the file budget;
- **OData quote not escaped** (Warning, real) — `automate.verify_published` built
  `CatalogItems(Path='{server_path}')` by interpolation, so a name with a single
  quote broke (or injected into) the request. Now `_odata_quote` doubles the quote
  (the OData escape); verified the URL carries `My''Report`;
- **`CALCULATE` false negative** (Warning, real) — the detector regex
  `CALCULATE\s*\(\s*[A-Za-z_\[\]\s'\.]+\s*\)` could not see through a nested call,
  so `CALCULATE(SUM([A]))` — the common case — was **not** flagged. Reproduced,
  then replaced by a balanced-paren scan (`_calculate_without_filter`) that flags
  a call with no top-level comma and correctly leaves `CALCULATE([A], ALL(T))`
  alone;
- **`KeyError`/`AttributeError` on a malformed response** (Warning, real) —
  `pbix_analysis` used `item['Id'][:8]` and `item['Name']` (a server item without
  `Id` crashed), and `pbix_index._drill_rows` called `.get("by_table")` on
  `sources` assuming a dict (a list/null raised). Both reproduced; now guarded and
  logged;
- **silent empty result** (Warning) — `_get_json` returned `{}` for a non-JSON or
  non-200 body at `debug` level, so a 403/500 looked like "no objects"; now a
  warning. The CLI exit contract for `verify` was tightened from
  `== "FAILED"` to "any non-ok verdict fails", so a future/absent value cannot
  read as success.

**Corrected / not adopted:** Qwen's "Critical `re.error: missing )` in
`analyze_calc_column`" is false — it misread the raw-string escaping; the actual
pattern `r"\b(?:YEAR|MONTH|QUARTER)\s*\(\[?Date\]?"` compiles and matches. The
"`dax_detail` `\d+.\d+` matches any char" claim is also false — the file already
has `\d+\.\d+`. The `verify=False` / `urllib3.disable_warnings` warnings are the
documented Windows-integrated-Negotiate design (host from config, no password),
not a defect. `requests_negotiate_sspi` missing on macOS is expected: that step is
the `server` extra and is not exercised by the stdlib-only suite.

Tests: `tests/test_reportserver_robustness.py` (17). Suite: 265 passed, 2 skipped;
`ruff check .` clean, 148 files formatted.

## Round 11 verdicts

Scope: the **board/skeleton construction and agents** area — `board.py`, `spec.py`,
`engine_layout_visual.py`, `engine_layout_query.py`, `engine_types.py`,
`skeleton*.py`, `board_fake.py`, `build.py`, `agents.py`, `inspect_board.py`,
`dax_markers.py` — a fresh area. Prompt `prompt-round11-board-skeleton.md`, code in
`round11-code-a-core.md` / `round11-code-b-rest.md`.

The first attempt hit the aliyun WAF CAPTCHA (`#waf_nc_block`, a full-screen
overlay intercepting the composer click; evidence in `round11-qwen-blocked.md`), so
the area was first audited locally (as in round 7). The exchange later completed on
retry (reply `answer-round11-board-skeleton.md`, chat `244ec05f`); Qwen confirmed
five further defects, all re-measured before the fix. Every finding below was
reproduced.

Adopted and fixed:

1. **non-reproducible builds from `hash()` (Warning, real)** — `page_filter`
   (`skeleton_visuals.py`) named a page filter `FilterAuto_{hash(column):08x}` and
   `PlantUmlMixin._pu_id` (`lineage/lineage_plantuml.py`) appended
   `hash(name) % 100000`. Python salts `hash()` per process, so the same input
   produced a different filter id / node id on every run — measured across three
   processes (three different values), which makes the built `.pbix` and the
   generated diagram non-diffable. Both now use a SHA-1 digest (`_stable_suffix`,
   `hashlib.sha1`), stable across runs and machines.
2. **invalid card query (Warning, real)** — `card_visual` always emitted
   `OrderBy: [{"Direction": 1, "Expression": {"Aggregation": None}}]` for a plain
   column (no aggregation), and `{"Measure": null}` for a measure. `null` is not a
   valid QOM Expression; measured through `spec_to_board` with a `kind: column` KPI.
   `OrderBy` now keeps the real wrapper (`{"Measure": {...}}` /
   `{"Aggregation": {...}}`, matching every real donor layout) and is omitted for a
   bare column.
3. **OData `$filter`/path quote not escaped (Warning, real)** — three more sites
   interpolated a path/id into an OData literal without escaping a single quote:
   `inspect_board.find_by_path` (`Path eq '{path}'`), `diagnostics._api_url`
   (`('{item_id}')`), `diagnostics.list_root_items` / `pbix_analysis.list_powerbi`
   (`startswith(Path,'{root}')`). Reproduced by passing a path with a quote. The
   escaper is now one shared `reportserver.odata.odata_quote` (the round-10
   `automate._odata_quote` is a thin alias of it), applied everywhere.
4. **`KeyError` on a malformed catalog item (Warning, real)** —
   `inspect_board.download_report` used `item["Id"]`/`item["Name"]` directly, so an
   item without `Id` or `Name` raised a bare `KeyError` while iterating a server
   response. Reproduced; now a domain `PbirsAccessError` naming the item, with the
   id escaped.

Extracted for the file-size budget: `skeleton_container.py` (the shared
`query_layout` / `full_query` wrappers that `skeleton_visuals` and
`skeleton_visuals_extra` both need).

Qwen-confirmed on retry (each re-measured):

5. **`Visual` never validated required inputs (Critical, real)** — a value-less
   `card`/`gauge`/`kpi` (or a `table` with no columns, a chart with no
   `axis`/`value`, a scatter missing one axis) reached `_visual_config` and became
   `Sum(table.None)` with `"Property": null` — an unbound, blank visual.
   Reproduced for every kind; `Visual.__post_init__` now raises a `ValueError`
   naming the missing group.
6. **title DAX literal unescaped (Critical, real)** — `_visual_config` wrote
   `Literal: "'" + title + "'"`, so a title with a single quote (`Sales '23`)
   produced `'Sales '23'` and corrupted the visual config. Reproduced; a shared
   `engine_layout_query.dax_literal` doubles the quote.
7. **unknown chart `visual_type` accepted (Warning, real)** —
   `validate_spec` never checked `ElementSpec.visual_type`, so `myCustomChart`
   reached `singleVisual.visualType` (Power BI rejects an unknown type at render).
   Reproduced; `spec_validate.CHART_TYPES` is now enforced.
8. **non-string page filter (Warning, real)** — `validate_spec` did not check
   `filters`, so a `None`/int/dict element crashed `spec_to_board` with
   `AttributeError: 'NoneType' object has no attribute 'encode'`. Reproduced; the
   filter must now be a non-empty string.
9. **`_query_item` bare `KeyError` (Warning, real)** — `skeleton_visuals._query_item`
   read `pq_query["property"]` directly; a direct caller (bypassing
   `spec.py` validation) got a bare `KeyError`. Reproduced; now a `ValueError`.
10. **negative layout width on a narrow page (Warning)** — `board.PageView._add`
    computed `(width - 40) // cols`, so a page narrower than twice the margin
    emitted a negative `width` into the layout (measured `-5`). Now clamped to a
    positive size.

**Corrected / not adopted:** Qwen's "quote `queryRef` for names with spaces" is
false — real layouts store `Table.Column Name` unquoted (measured across the
donors: `Accounts.Account Name`, `Opportunities.Days Remaining In Pipeline`). The
`board_fake` "divergence" nit is by design: that CLI is a fixed sample over the
donor model, not a spec-driven path.

Extracted for the file-size budget (beyond the round-11 `skeleton_container.py`):
`spec_validate.py` (the structural validator out of `spec.py`, which had grown to
337 lines).

Tests: `tests/test_board_skeleton_robustness.py` (13, incl. two cross-process
stability checks) + `tests/test_board_spec_validation.py` (21). Suite: 299 passed,
2 skipped; `ruff check .` clean, 152 files formatted.
