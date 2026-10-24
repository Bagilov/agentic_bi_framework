# Review decision log

Records of the independent Qwen (chat.qwen.ai) review taken through
`manage_webllm`: what was adopted, what was corrected, and what was rejected
after local verification. The plan itself is in
[IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md); raw exchanges and reproduction
commands are under `../other/qwen-review/`.

The review is input, not authorization: every claim below was re-checked against
the repository, and where a claim disagreed with a measurement, the measurement
won.

## Round 1: state, architecture, staging

- **Adopted:** the stage ordering (fix the test harness first, then CI and
  coverage, then tests, then the public contract, then the namespace split), and
  the reading that file length, `type: ignore` count and the raw
  `except Exception` count are noise at this point.
- **Rejected after measurement:** a 60 %/75 % coverage gate "on start" — the
  measured baseline is 37 %, so it would fail immediately; the plan uses a
  ratchet at the measured floor. `mypy --strict` as a near-term target — 92
  modules with 20 at 0 % coverage makes it weeks of noise.
- **Confirmed and sharpened:** the `pytest` vs `python -m pytest` divergence.
  `[Q]`'s fix (`pythonpath = ["."]`) was tested and works; its alternative
  (`tests/__init__.py`) was rejected because it changes the suite's import
  namespace and forces an editable install for every run.
- **Over-stated:** calling the harness divergence "CRITICAL". It is a one-line
  config defect with a proven fix, and it is scheduled first only because it is
  nearly free.

## Round 3: binary layer

Round 3 (`../other/qwen-review/answer-round3.md`) covered `pbix_binary/` and
found three defects, all reproduced against the shipped donor — see
`../other/qwen-review/binary-layer-findings.md`.

Ordering matters here: D-1 and D-3 make the tool report success while writing a
broken artifact, so they outrank the round-2 items above.

1. **D-1 XML-escaping asymmetry (High, `0.0.1b2`)** — the hand-rolled
   virtual-directory serializer does not escape, while the parser decodes
   entities. Verified end-to-end: `apply_patches` returns success and the
   written `.pbix` has an unparseable `DataModel`. Fix by serializing the
   virtual directory with `ElementTree`; **verified** that this is byte-identical
   for normal paths, so the change is behaviour-preserving.
2. **D-3 ambiguous patches (Medium, `0.0.1b2`)** — an equal-length patch that
   matches many sites silently edits the first (7356 candidate sites, 1 edited).
   Default to requiring a unique match; add an optional `occurrence` for
   deliberate multi-site replacement.
3. **Self-verification (must, `0.0.1b2`)** — `apply_patches` must re-read and
   re-parse the `DataModel` it just wrote. `[Q]` argues this should not be an
   opt-in flag, and that is accepted: it is milliseconds and it would have caught
   D-1. `zip.testzip()` validates the archive, not the model inside it.
4. **D-2 range validation (Medium, `0.0.2`)** — negative/oversized
   `offset`/`size` in the virtual directory are accepted and then used as truth.
   Validate at parse time and in `parse_abf_index` (bounds, non-overlap).

Carried over from round 3's test advice (folds into Stage 2): property-based
`relayout → parse` round-trips, mutation fuzzing of the virtual directory and
backup log, truncation at -1/-4/-28/-4096 (already passes), and a byte-exactness
test proving `swap_datamodel` with an identical `DataModel` is byte-identical —
**verified**: `orig == new` already holds today, so that test pins current
behaviour.

## Round 2: packaging, security, release

Adopted from round 2 (`../other/qwen-review/answer-round2.md`), ordered by value:

1. **Single-source the version** — realistically a `0.0.1b2` item, not a 1.0
   item. `importlib.metadata.version("agentic-bi-framework")` with a
   `PackageNotFoundError` fallback replaces `__init__.py:37`; verified the
   metadata lookup resolves to `0.0.1b1` today.
2. **Domain exceptions by inheritance** — `class PbixParseError(ValueError)`,
   `class EngineExecutionError(RuntimeError)` and so on, so existing
   `except ValueError` callers keep working while new code can be specific. This
   is the safe migration path and is preferred over a breaking rename. Applies
   to the 21 `ValueError` / 9 `RuntimeError` raises that are not already domain
   types; it is backlog, not a release blocker.
3. **PowerShell argument passing** — `desktop_oracle_guest.py` builds PS scripts
   by f-string interpolation with no single-quote escaping, and the interpolated
   values (`AGENTIC_BI_GUEST_ROOT`, `AGENTIC_BI_GUEST_OUT`, `python`, derived
   `runner`/`log_file` paths) come from the environment. A quote in any of them
   breaks out of the PS string (verified at the string level). This is
   operator-controlled, not attacker-controlled, so it is below the two web
   defects — but the fix (`[Q]`'s base64-encoded JSON payload, or
   `session.run_ps` with encoded arguments) should land before 1.0.
4. **Consider `msmdsrv.exe` directly** — `[Q]` proposes dropping the whole
   WinRM/scheduled-task/RunLevel-Highest stack. Partially verified and
   partially rejected: `_engine_build.ps1` loads `Microsoft.PowerBI.Tabular.dll`,
   `Microsoft.PowerBI.Amo.dll` and `Microsoft.PowerBI.Amo.Core.dll` from the
   Desktop `bin`, and reads `msmdsrv.port.txt` from the Desktop-created
   workspace, so it drives an engine that Desktop already started rather than
   starting one itself. Whether `msmdsrv.exe` alone can replace that is a
   genuine research question, not a known simplification, and it must not be
   assumed to remove the GUI dependency.
5. **`PlatformNotSupported` on non-Windows** — only one `sys.platform` check
   exists in the whole package (`test_build.py:83`) against a large Windows-only
   surface. Non-Windows callers should get a documented exception, not a
   `FileNotFoundError` for a missing `msmdsrv.exe`.

## Round 4: every service — user path and agent path

Round 4 (`../other/qwen-review/answer-round4-paths.md`, findings in
`../other/qwen-review/round4-findings.md`) covered all 11 console entry points
and `agents.py` + the spec `support` section. Every raw exit code was re-measured
here.

Adopted:

1. **Default outputs inside the package (Critical, user path)** —
   `lineage/pbi_lineage.py:180` and `antipatterns/pbi_antipatterns.py:181`
   default to `Path(__file__).resolve().parent / "output_files"`, i.e. into
   `site-packages`, so a read-only install fails with `PermissionError`. Already
   a Stage 1 item; this confirms the severity against a second scenario.
2. **Unhandled exceptions vs promised exit codes (Warning)** —
   `visual-check`, `pbix-patch`, `brand-audit`, `engine`, `test-build`, `lineage`,
   `report` exit 1 with a traceback on unreadable input; `patch_cli`'s docstring
   claims code 2 for a patch error, but a missing file is not a `PatchError`.
   `web-clone` handles it correctly.
3. **Exit code 2 overloaded (Warning)** — CLI misuse (`argparse`) and
   input/spec errors share code 2, so a caller cannot distinguish them.
4. **`lineage.main()` has no exit contract** — no `return`, success is implicit.
5. **Manifest stage not validated (Critical, agent path)** —
   `from_manifest` accepts any `stage` string; `all_agents("WRONG")` returns
   `[]` silently while `agents_for_stage` raises. A typo silently orphans an
   agent.
6. **Dead `path` parameter** — `render_kilo_agent(agent, path)` never reads
   `path`; the README passes `""`.

Corrected: Qwen frames the `render_kilo_agent` path as a live traversal risk.
It is **latent** — the function returns a string and never writes, so nothing
traverses today. Recorded as a caveat for a future writer, not a vulnerability.

Not a defect (Qwen agrees): `resolve_agents` priority ordering is fail-closed and
correct; a documentation note is enough.


## Round 5: OpenSpec change reviewed as files

Round 5 (`../other/qwen-review/answer-round5-openspec-code.md`, prompt
`../other/qwen-review/prompt-round5-openspec-code.md`) was the first round taken
**against the OpenSpec change** (`openspec/changes/stage0-hardening-and-guest-chain/`)
rather than prose: the spec, design, tasks and the implementing sources were sent
as three attachment bundles (`round5-openspec-bundle.md`, `round5-code-a-guest.md`,
`round5-code-b-graph.md`; the chat accepts about five attachments, so the files
were grouped).

Adopted and fixed:

1. **SHA-256 verification fail-open (Critical, fixed)** — `guest_staging.push_file`
   only raised when a non-empty hash disagreed; an empty `Get-FileHash` result
   (`splitlines()` empty) skipped the check entirely, so a missing/unreadable
   staged file looked verified. Now a hash-less result is a `StageError`, and the
   `Get-FileHash` call runs under `$ErrorActionPreference='Stop'`.
2. **`run_ps` swallowed guest failures (Warning, fixed)** — `guest_winrm.run_ps`
   returned only `std_out` and ignored `status_code`, so a script that exited
   non-zero (terminating error, explicit `exit 1`) read as an empty success.
   Non-zero now raises `StageError` carrying the exit code and stderr.
3. **`--json` verdict path raised (Warning, fixed)** — `guest_chain_cli._emit`
   called `mkdir`/`write_text` unguarded, so an unwritable path produced a
   traceback instead of the documented contract. It now warns on stderr and still
   prints the verdict to stdout.

Spec/docs updated with the same round: added the hash-less and non-zero-exit
scenarios, the full exit-code table (0/1/2), and the `ps_quote`-inside-double-quotes
caveat; the mandatory-`stage` and CLI-boundary items stay open (tasks 5.2, 5.3).

Corrected after measurement: Qwen's first finding — "`escapeHtml` in
`web_assets.py` replaces each character with itself, so XSS via `innerHTML`
remains" — is a **false positive**. The function is `{'&': '&amp;', '<': '&lt;',
'>': '&gt;', '"': '&quot;', "'": '&#39;'}` in the source and byte-exact in the
attachment bundle; the reviewer's rendering dropped the entity text.

The BR-7 contradiction Qwen raised is accepted as a real spec defect and resolved
by making the open items explicit in both `spec.md` and `tasks.md` (5.2/5.3 remain
`[ ]`) rather than implying they are done.

## Round 4 follow-up: boundary contracts implemented

The round-4 items that were still open are now closed (code + tests):

1. **CLI error contract (U-1, U-2, U-3)** — a shared `cli_support.run_boundary`
   maps an input failure (`OSError`/`ValueError`/`NotImplementedError`) to exit 2
   with a one-line `error:` message, and lets an *unexpected* error stay a
   traceback (a bug is not a user mistake). Applied to `visual-check`,
   `brand-audit`, `engine`, `test-build`, `lineage`, `antipatterns`, `report` and
   `pbix-patch` (the last also maps a missing file to 2, not just `PatchError`).
   `lineage.main` and `pdf_report.main` now return a code. Each CLI's docstring
   states its exit codes.
2. **Agent manifest contract (G-1)** — `from_manifest` rejects an unknown `stage`,
   and `all_agents` raises on an unknown stage instead of returning `[]`
   (`agents_for_stage` now merely delegates).
3. **Default outputs (U-4)** — `lineage` and `antipatterns` resolved their default
   output inside the installed package (`Path(__file__).../output_files`), a
   `PermissionError` on a read-only install. Both now use CWD-relative
   `output_files/`, matching what their `--help` already promised.
4. **Dead parameter (G-3)** — the unused `path` argument is gone from
   `render_kilo_agent`; the docstring notes the returned body is inert and that a
   writer must treat `agent.id` as a filename.

Tests: `tests/test_agents.py` (15) and `tests/test_cli_boundary.py` (11). G-2
(`resolve_agents` priority) stays documentation-only.

## Round 6: the boundary contract re-reviewed

Round 6 (`../other/qwen-review/answer-round6-contracts.md`, prompt
`prompt-round6-contracts.md`) reviewed the round-5/round-4 fixes in place:
`cli_support.run_boundary`, the agent-manifest validation, and the CWD-relative
default outputs. Sent as three attachment bundles (`round6-code-1-cli-agents.md`,
`round6-code-2-clis.md`, `round6-code-3-tests.md`).

Adopted and fixed:

1. **`patch_cli` was not wrapped in `run_boundary` (Warning, fixed)** —
   `load_spec` parses JSON, so a malformed spec raised `JSONDecodeError` (a
   `ValueError`) straight through as a traceback, breaking the very contract BR-7
   states. Reproduced (`apply --spec bad.json` → traceback), then wrapped: a
   malformed spec, an unreadable file and a `PatchError` now all exit 2.
2. **`test_build` used `SystemExit` for a configuration error (Nit, fixed)** —
   `raise SystemExit("needs a DataModel")` exits 1 and bypasses `run_boundary`,
   so a *configuration* error looked like a runtime failure. It now raises
   `ValueError`, which the boundary maps to the documented exit 2.

Confirmed correct (no change): `resolve_agents` stays self-consistent — it calls
`from_manifest`, so a bad `stage` in a spec manifest propagates the same
`ValueError` (re-measured). Qwen's note that `engine_cli._parse_pages`'s
`ValueError` on `--assert-pages "Overview=abc"` is *correctly* classified as bad
input agrees with the design.

Tests: two added to `tests/test_cli_boundary.py` (malformed patch spec, missing
`--datamodel` on macOS). Suite: 189 passed, 2 skipped.

## Round 7: declarative spec path

Round 7 targeted a fresh area — the declarative spec path (`spec.py` ->
`engine_layout*.py`, `validate_pbix.py`, `thresholds.py`, `web_report/`) — which
no earlier round had reviewed. The Qwen exchange was completed on retry
(`../other/qwen-review/answer-round7-spec-path.md`, prompt
`prompt-round7-spec-path.md`, code in `round7-code-{1,2,3}-*.md`); it was delayed
by an aliyun WAF CAPTCHA on the composer that needed a human, and an earlier
attempt returned a reply from an unrelated chat.

Local audit findings (each reproduced before the fix) — adopted:

1. **`spec.py` crashed on malformed untrusted input (Warning, fixed)** —
   `_field_dict` read `f["property"]` directly, so a field without `property`
   gave a bare `KeyError` inside `spec_to_board` while `validate_spec` reported
   nothing; a missing `dashboard.name` raised `KeyError` in `from_dict`; a
   non-dict element/field or a non-list `elements` raised `AttributeError`.
   `from_dict`, `_parse_page`, `_parse_element` and `_field_dict` now validate and
   raise a message naming the value, and `validate_spec` reports a missing
   `property`, an unknown field `kind`, a malformed `pos`, and duplicate page
   names (whose sections collide in the built layout).
2. **`engine_layout.build_report([])` (Warning, fixed)** — an empty page list
   reached `sections[0]["name"]` and raised `IndexError`; a report with zero
   sections is not a valid layout, so it now raises `ValueError`.
3. **`thresholds.py` dropped documented overrides (Warning, fixed)** — the spec
   nests values one level deeper than the key domain (`quality: {thresholds: …}`,
   `deploy: {guardrails: …}`), but `resolve_thresholds` flattened only one level,
   producing keys like `quality.thresholds.max_layout_problems` that match no
   catalog entry — so a documented override of the **hard gate**
   `quality.max_layout_problems = 0` was silently ignored (fail-open). The
   container level is now flattened; an unknown key is logged as a likely typo;
   an override with the wrong type keeps the default and logs instead of reaching
   a comparison as a `TypeError`; and `validate_override` rejects a `bool` for an
   `int` threshold (`isinstance(True, int)` is `True`).
4. **`validate_pbix.validate_layout` empty registry (Warning, fixed)** — an
   explicitly passed `{}` was falsy, so `registry or EXAMPLE_REGISTRY` silently
   validated against the unrelated sample model. Only `None` falls back now; `{}`
   means "no known objects" and every reference is a problem.
5. **`web_report` robustness (Warning, fixed)** — `has_in_filter` raised
   `AttributeError` on a parseable-but-non-dict filter blob, and `web_inspect`
   raised `ValueError` on a non-numeric `x`/`y`/`width`/`height` in an untrusted
   layout; both aborted inspection of the whole report. Both now tolerate the bad
   value (skip / coerce to 0) while keeping the fail-closed parse behaviour.

Qwen findings confirmed and fixed on top of the local audit:

6. **`prototypeQuery` as a JSON string (Critical, fixed)** — both
   `validate_pbix.validate_layout` and `web_checks._projection_issues` /
   `_field_issues` assumed `prototypeQuery` is a dict and called `.get` on it; a
   layout that carries it as a string (Power BI does this for `query`) raised
   `AttributeError`, aborting validation. Both now parse a string via `_as_obj` /
   a new `_as_prototype_query` and fall back to `{}`. This was **not** present in
   the shipped donors (a scan of every `.pbix` in the repo found 749 `None` + 303
   `dict`, no string), so it is a real but latent defect against a string-shaped
   layout.
7. **`build_gallery({'tables': []})` (Warning, fixed)** — `spec["tables"][0]`
   raised `IndexError`; now a `ValueError` naming the cause.
8. **`get_threshold` on a typo (Warning, fixed)** — an unknown key returned `None`
   silently, which then breaks a `value > threshold` comparison far away; it now
   logs a warning.
9. **Skipped model-membership checks (Warning, fixed)** — with no registry
   (`pbixray` absent / none passed) `web_checks` skips the whole membership layer,
   and the CLI reported a clean result without saying so. `web-cli` now prints a
   warning on stderr when `fields_checked` is false.

Corrected after measurement: Qwen's "`engine_layout.build_layout_from_spec`
expects `spec["tables"]`, incompatible with `DashboardSpec` (Critical)" is a
**naming** issue, not a live defect — the two "spec" objects are used on separate
paths (`build_layout_from_spec` is only ever called with the engine spec from
`engine.EnginePipeline.build_spec`; `DashboardSpec` goes through `spec_to_board`
to a `Board`). The docstring now states the distinction explicitly.

Tests: `tests/test_spec_path.py` (22) and a web-cli warning test. Suite: 212
passed, 2 skipped.

## Rounds 8–11: fresh-area audits (publication gate, lineage, server, board)

Four further rounds each took a subsystem no earlier round had covered; every
finding was re-measured before adoption, and the full verdicts (with the corrected
false positives) are recorded in `other/qwen-review/README.md`.

- **Round 8 — publication gate** (`brand_audit*`, `engine_verify*`, `rebuild`):
  `luminance` crashed on a non-hex color; the layout decoder assumed UTF-16LE; the
  "all visuals have projections" check failed every decorative visual; a
  `singleVisualGroup` raised `KeyError`. A shared `layout_meta.py` (decoder + one
  decorative-type list + a tolerant visual iterator) and the color-math guards
  fixed across `engine_verify_*`, `visual_check`, `rebuild`, `web_report`.
- **Round 9 — lineage + report**: an aggregated queryRef (`Sum(T.c)`) lost its
  table (14/168 bindings on a real donor) and a non-string queryRef raised; a
  double quote was not escaped for the PlantUML `package "..."` literal. Fixed
  queryRef parsing (repeated aggregation stripping) and `_pu_escape`.
- **Round 10 — Report Server + antipatterns**: the OData walk ignored
  `@odata.nextLink` (a large catalog was silently truncated); a `CALCULATE(...)`
  whose argument was a nested call was missed by the regex; `verify_published`
  interpolated a name into `Path='...'`. Fixed with `reportserver/odata.py`
  (`walk_values`), a balanced-paren `CALCULATE` scan, and the shared quote escaper.
- **Round 11 — board/skeleton/agents**: `hash()`-based filter/node names made the
  build non-reproducible; `card_visual` emitted an invalid
  `OrderBy: [{"Aggregation": null}]` for a plain column; three more OData filters
  were unescaped; `inspect_board.download_report` raised `KeyError` on an item
  without `Id`. Fixed with SHA-1 stable names, a valid/omitted `OrderBy`, the
  shared `odata_quote`, and domain errors. (Qwen was WAF-blocked this round; the
  audit was local — see `other/qwen-review/round11-qwen-blocked.md`.)

The recurring cross-cutting themes: fail-open vs fail-closed in a **gate**
(a silent skip must be reported), untrusted names reaching a serialization sink
(JSON / PlantUML / PDF / OData / DAX), and non-determinism from salted `hash()`
or process-scoped state. Suite after round 11: 278 passed, 2 skipped.

Round 11 addendum: the Qwen exchange completed on retry and confirmed five further
defects (all measured): `Visual` accepted a half-built visual that became
`Sum(table.None)`; the title DAX literal was unescaped; `validate_spec` accepted an
unknown chart `visual_type` and a non-string page filter; `_query_item` raised a
bare `KeyError`; a narrow page emitted a negative layout width. Qwen's "quote a
queryRef with spaces" was refuted (real layouts store it unquoted). Split out
`spec_validate.py`. Suite after the addendum: 299 passed, 2 skipped.
