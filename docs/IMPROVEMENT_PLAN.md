# Improvement plan for `agentic_bi_framework`

Status: **Stage 0 implemented**; Stages 1–4 not started. Baseline measured on
`main` @ `032d817` (2026-10-21). Every number below was reproduced locally on that commit; the
commands are given so any claim can be re-checked.

Independent review: a second opinion from Qwen (chat.qwen.ai) was taken through
`manage_webllm` and is folded in as `[Q]`. Where the review disagreed with the
measurements, the measurement wins and the disagreement is called out.

---

## 1. Baseline (measured, not estimated)

| Signal | Command | Result |
|---|---|---|
| Lint | `ruff check .` | clean |
| Format | `ruff format --check .` | clean, 116 files |
| Tests (module) | `.venv/bin/python -m pytest -q` | 88 passed, 2 skipped |
| Tests (console) | `.venv/bin/pytest -q` | **2 collection errors** |
| Coverage | `coverage run --source=src/agentic_bi -m pytest` | **37 %** (6597 stmts, 4133 missed) |
| Importability | `walk_packages` over all modules | 92/92 import OK |
| Wheel installs debug code | `python -m build --wheel` + `unzip -l` | `board_fake.py`, `_engine_oracle.py`, `desktop_oracle_guest.py`, `test_build.py`, `_engine_build.ps1` are **shipped** |
| Blind excepts | `ruff check --select BLE --ignore-noqa` | 32 |
| Replaceable `noqa` | `ruff check --select RUF100` | 59 (34 × BLE001, 23 × F401) |
| `print()` in library code | `ruff check --select T20` | 69 |
| Public API docstrings | AST walk over `src/` | 90 of 396 public defs undocumented |
| `print` vs `logging` | AST walk | 22 modules with `print`, 27 with `logger` |
| Windows guards | `grep 'sys.platform\|os.name'` | **1** site, vs a large Windows-only surface |
| Version duplication | `pyproject.toml:7` vs `__init__.py:37` | duplicated; no lock file |
| Package-dir writes | `grep '__file__.*output_files'` | ~~8 sites~~ fixed in Stage 1 (`paths.py`) |
| Injected HTML/JS | browser reproduction | **2 exploitable defects** (see §2.1) |
| CI | — | ~~missing~~ added in Stage 1 (`.github/workflows/ci.yml`) |
| `py.typed` | — | missing |
| Type checker | — | none configured |
| CHANGELOG | — | missing |

Two measurements deserve emphasis because they contradict the code's own
self-description:

- **Coverage is 37 %, not "mostly tested".** 20 modules are at 0 %, including
  `board.py`, `automate.py`, `rebuild.py`, `validate_pbix.py`, `publish.py`,
  `agents.py`, `brand_audit*.py`, the whole `report/` package and most of
  `antipatterns/`.
- **`python -m pytest` is green, plain `pytest` is red.** Both are legitimate
  ways to run the suite; CI will use one of them and may pick the failing one.

---

## 2. Signal vs noise

Qwen's split is accepted with one correction.

**Noise for now (do not spend time):**
- `# type: ignore` (10) and `: Any` (5) — no type checker enforces them yet, so
  they are inert debt. Fix them *when* the checker lands, not before.
- File length > 300 lines (9 files, `board.py` worst at 361). Purely cosmetic;
  churning these modules now would bury the real diffs in git history.
- `except Exception` count *as a number*. What matters is the 32 sites that
  swallow failures in `reportserver/` and `pbix_binary/`; the rest are lazy
  optional imports that never fail silently.
- The 90 missing public docstrings and the 22 `print`-only modules. Both are
  real debt but neither is a defect; a bulk sweep now produces an unreviewable
  diff (`[Q]` agrees, and recommends only a lint rule plus fixing the worst
  module).

**Signal (fix):**
1. **Two exploitable HTML/JS injection defects** in `web_report` — see §2.1.
   These outrank everything else in this document.
2. `pytest` / `python -m pytest` divergence — the tests import
   `tests.web_report_fixtures`, but `tests/` is not a package.
3. No CI at all, plus no coverage gate, on a framework that parses binary
   formats where a silent regression is invisible.
4. `pywinrm` imported but declared in **no** extra; the wheel also ships debug
   modules, so the published artifact does not match the documented surface.
5. Writes into the installed package directory (8 sites, e.g. `engine.py:64`).
   Verified: a read-only package dir makes `EnginePipeline()` raise
   `PermissionError` at construction.
6. 34 of all `noqa` directives are unused (`RUF100`), i.e. the suppression set
   is partly decorative and hides nothing.
7. Donor-specific defaults (`fact_table`, `kpi_measures`) baked into
   `board.py`, `automate.py`, `spec.py`, `validate_pbix.py`, `board_fake.py`
   while the README claims the framework is implementation-agnostic.

`[Q]`'s rating of "file length" and "type: ignore" as noise matches; its claim
that the `pytest` failure is "CRITICAL" is over-stated — a one-line config defect
with a proven fix — but it is still first because it is nearly free.

### 2.1 Injectable HTML/JS in `web_report` (new, High)

Found in round 2, both **reproduced in a browser**; full detail in
`../other/qwen-review/security-findings.md`.

- `web_render.py:246` embeds `json.dumps(payload)` into a `<script>` without
  escaping `<`/`>`, so a `</script>` in any untrusted `.pbix` string breaks out
  of the element and executes. Two independent sources were reproduced (a visual
  title, and an entity name that lands in an issue message), which is why the
  fix belongs at the serialization sink.
- `web_render.py:98` places the element key in a single-quoted JS string inside
  `onclick`; `_e()` escapes for HTML, the browser then un-escapes the attribute
  before JS parsing, so a page name breaks out of the string.

`[Q]`'s round-2 advice is adopted with one correction: escaping `<`/`>`/`&` in
the payload is sufficient for the `<script>` sink and should **not** be replaced
by an HTML sanitizer (which would corrupt legitimate `<`/`>` in labels), but for
the `onclick` sink escaping is the wrong fix entirely — the string must stop
being built as JS-in-HTML.

---

## 3. Staged plan

Each stage is independently shippable; do not start one before the previous is green.

### Stage 0 — Close the injection and corruption defects (**implemented**)

These came first: unlike everything else here, they were exploitable or silently
destructive, and every fix is small. Status below.

- `web_render.py`: escape `<`, `>`, `&` in the serialized payload before it is
  interpolated into `<script>`. Done via a single `_json_for_script` sink helper,
  so future sources are covered too.
- `web_render.py`: stop building JS inside the HTML attribute — the element key
  now travels in `data-key` and the handler is bound with `addEventListener`
  (`web_assets.py`). The client also escapes interpolated model strings before
  writing them with `innerHTML`.
- Serialize the ABF virtual directory with `ElementTree` instead of hand-rolled
  f-strings (**verified**: byte-identical to the engine output for normal paths;
  correct escaping for `&`/`<`/`>`/`'`/`"`).
- `apply_patches` is now self-verifying: it re-reads the written `.pbix`,
  decompresses the `DataModel` and parses the ABF index, raising `PatchError` if
  anything fails. Not optional, and the CLI reports it as exit code 2.
- Ambiguous equal-length patches fail fast; `occurrence` (0-based index) selects
  one site and `"occurrence": "all"` replaces every match.
- `pythonpath = ["."]` added to `[tool.pytest.ini_options]`.
- Regression tests: `tests/test_web_report_injection.py` (6) and
  `tests/test_pbix_binary_hardening.py` (11). Each was run against the pre-fix
  code and fails there, so they genuinely pin the defects.
- Result: `pytest -q` and `python -m pytest -q` exit 0 with identical counts;
  `ruff check` / `ruff format --check` clean.

Remaining Stage 0 follow-ups (not blocking): none.

### Guest chain — implemented and proven end to end

The bounded chain (`guest_chain.py` + the split `guest_*` modules, CLI
`agentic-bi-guest-dashboard`) is done: one call starts the VM, stages the
framework, builds the board in the guest's interactive session, pulls it back,
optionally runs the Desktop oracle, and always tears down. Proven from a **cold
start** (VM stopped first): `verdict BUILT`, `oracle MODEL_LOADED`, exit 0, VM
stopped by the chain. The `guest` extra and offline `tests/test_guest_chain.py`
are in place. Round 5 (`REVIEW_DECISIONS.md`) tightened two silent-success paths:
SHA-256 verification is fail-closed on an empty guest hash, and `run_ps` raises on
a non-zero exit.

### Stage 1 — CI, coverage gate, honest extras, writable paths (2–3 days)

**Status: done and green on `main`.** 17 files changed, 322 tests (was 299),
coverage 58.66 %. CI run
[40229597008](https://github.com/Bagilov/agentic_bi_framework/actions/runs/40229597008)
passes all four jobs (lint, py3.10/py3.12 on Ubuntu, py3.12 on Windows).

- ✅ `.github/workflows/ci.yml`: `lint` job (`ruff check` + `ruff format --check`)
  and `test` job — `ubuntu-latest` × Python 3.10/3.12 plus one `windows-latest`
  × 3.12 leg (the AS-engine path is Windows-only; the leg proves the core suite
  passes there and needs no Desktop). The `test` job installs `.[all,dev]`.
- ✅ `pytest-cov`, `[tool.coverage.run] source`, and a **ratchet** gate at the
  measured floor. The floor is **55 %** against a measured **58.66 %** (the plan
  guessed 37 %; the real number is much higher). Verified negatively: a
  deliberate `--cov-fail-under=99` fails the run (exit 1), the configured floor
  passes (exit 0). Raise it in the same change that adds tests, never lower it.
- ✅ The missing `guest = ["pywinrm>=0.5"]` extra was already declared; a clean
  `.[guest]` install was measured to make `desktop_oracle_guest` importable.
- ✅ Package-relative writes routed out of the package (9 modules, new
  `paths.py`): `engine.py` `work_dir`, `engine_host.py` `cwd`, `dax_detail.py`,
  `inspect_board.py`, `automate.py`, `build.py`, `board_fake.py`,
  `skeleton_assembly.py`, `validate_pbix.py`. Verified on a chmod-read-only
  install: pre-fix `PermissionError`, post-fix exit 0.
- ✅ Temp spec leak made deterministic: a unique `TemporaryDirectory` (removed
  right after the build) replaces `pbix_spec_<epoch>.json`, whose 1-second
  resolution collided between parallel runs and left files behind.
- ➕ **Three defects the matrix caught that local runs could not** (each is the
  reason the corresponding job exists, and each now has a regression test):
  - Python **3.10**: `tests/test_packaging_contract.py` imported `tomllib`
    (3.11+), so the 3.10 leg failed to collect while 3.12 passed. Fixed with a
    `tomli` fallback; `dev` declares `tomli>=2.0; python_version < '3.11'`.
  - **Windows**: `test_as_dict_is_json_serialisable` compared `str(Path)` against
    the POSIX literal `/tmp/x.pbix`; Windows joins with backslashes. Fixed to
    compare against the same path object.
  - **Node 20 deprecation**: `checkout@v4`/`setup-python@v5` were forced onto
    Node 24; bumped to v7 (whose `runs.using` is `node24`) after checking the v7
    breaking change does not apply to a `push`/`pull_request` workflow.
- ➕ **Two install blockers found and fixed by measurement** (neither was in the
  plan): `server-native` declared `spnego>=0.4`, a distribution that no longer
  exists on PyPI (404; the module is now provided by `pyspnego`); and `server`
  declared `requests-negotiate-sspi>=0.4`, whose every sdist up to 0.5.0 declares
  its own version as `0.0.0` — the constraint is unsatisfiable, so pip returned
  `resolution-too-deep` and made the whole `[all]` extra uninstallable. It is also
  Windows-only (`pywin32`), so it now carries a `sys_platform == "win32"` marker
  and a `>=0.5.2` floor.
- Done when (all verified): CI config present and green on `main` (four green
  jobs on run 40229597008); a deliberate coverage drop fails; `.[guest]` imports
  `desktop_oracle_guest`; a read-only install constructs `EnginePipeline` without
  writing into the package.
- Effort: 2–3 days.

### Stage 2 — Test the untested core, not the whole tree (1 week)

**Status: done.** 6 new test files, 437 tests (was 322), coverage 59.97 %, and the
ratchet floor raised 55 → 58 in the same change.

The three write paths, measured after this stage (target was ≥ 70 %):

| Module | Before | After |
|---|---|---|
| `validate_pbix.py` | 37 % | **89 %** |
| `rebuild.py` | 21 % | **98 %** |
| `engine_container.py` | 91 % | **100 %** |

Priority order is by blast radius, not by module size:

1. `validate_pbix.py`, `rebuild.py`, `engine_container.py` — the paths that
   write a `.pbix`; a regression here ships a corrupt deliverable.
2. `pbix_binary/` codec/relayout round-trips on the shipped `templates/template.pbix`
   (fixtures and skip logic already exist in `tests/conftest.py`).
3. `lineage/` model → JSON → PlantUML/table, pure data, cheap to pin.

Add golden round-trip tests (`[Q]`'s suggestion, adopted): `parse → to_dict`
against a frozen snapshot, and `parse → serialize → parse` equality. This is the
only mechanism that catches a silent `.pbix` format regression without Desktop,
and it covers the boundary cases that matter here (empty report, broken
bindings, very long column names, Cyrillic/special characters).

Extend the existing `test_pbix_binary_*` suite with the round-3 invariants:
property-based `relayout → parse` round-trips (e.g. Hypothesis), mutation fuzzing
of the virtual directory and backup log (expect a domain error, never
`IndexError`/`MemoryError`), truncation at -1/-4/-28/-4096, and the
`swap_datamodel` byte-exactness test (REVIEW_DECISIONS.md, round 3). Range validation for D-2 also lands
here as a `0.0.2` item.

Do **not** chase `reportserver/` or `publish.py` coverage: they need a live
server and would only buy mock-versus-mock tests. Skip `_engine_oracle.py` and
`desktop_oracle_guest.py` entirely until they are removed from the package.

- Done when (all verified): coverage 59.97 % (≥ 55 %), with the three write paths
  at 89/98/100 % (≥ 70 %); golden `parse → serialize → parse` snapshots exist for
  the virtual directory and backup log; every strict prefix and a deterministic
  mutation sweep raise only domain errors, never `IndexError`/`MemoryError`;
  `swap_datamodel` with an identical payload is byte-identical; no new test
  skipped on macOS (still the two Windows-guest skips).
- Effort: ~1 week.

**Defects and dead code found while writing these tests** (not in the plan):

- `layout_meta.decode_layout_with_encoding` reported `utf-8-sig` for a *BOM-less*
  UTF-8 source, so `rebuild_pbix` re-encoded with `json.dumps(...).encode(
  "utf-8-sig")` and *added* a BOM the source never had — the opposite of the
  documented "UTF-8 sources are preserved as UTF-8". Now returned only when the
  bytes actually carry the BOM (`_ENCODINGS` reordered, explicit BOM check).
- `rebuild._default_content_types` was dead since the first commit (no caller,
  no test, not in any doc); removed per the workspace rule that dead code is
  deleted rather than kept "for later". Its removal is why `rebuild.py` reaches
  98 % instead of 79 %.

### Stage 3 — Public contract and packaging (2–3 days)

- Ship `src/agentic_bi/py.typed`; add `__all__` where a module is a facade, and
  resolve the 23 `F401`: verified that `brand.py`/`skeleton.py`/`engine_verify.py`
  keep passing `ruff --select F401` with the `noqa` removed (they already have
  `__all__`), while `pbi_lineage.py`, `reportserver/diagnostics.py`,
  `pbix_binary/abf_codec.py`, `antipatterns/pbi_antipatterns.py` still need
  either `__all__` or the directive. Run `ruff check --select RUF100 --fix` to
  delete the 34 unused `BLE001` directives.
- Configure a type checker in report-only mode first (`mypy` or `pyright`),
  non-blocking, then flip to blocking once the count is at zero.
- Exclude debug modules from the wheel: `board_fake`, `_engine_oracle`,
  `desktop_oracle_guest`, `test_build`, `_engine_build.ps1` — they currently
  ship (confirmed in the built wheel). Keep `test_build` as a `scripts/` entry
  (it already has a thin wrapper there) instead of a console script, or replace
  it with a real `agentic-bi doctor` subcommand as `[Q]` suggests.
- Add `noqa`-free `BLE` to the ruff `select` list so new blind excepts cannot
  be added silently.
- CLI error contract (round 4, **implemented**): `cli_support.run_boundary` maps a
  bad input to exit `2` with a one-line message and lets an unexpected error stay a
  traceback. Wired into all of `visual-check`, `brand-audit`, `engine`, `test-build`,
  `lineage`, `antipatterns`, `report`, `pbix-patch`; `lineage.main` and
  `pdf_report.main` now return a code, and each docstring lists its exit codes.
- Agent manifest contract (round 4, **implemented**): `from_manifest` rejects an
  unknown `stage`; `all_agents` raises instead of returning `[]`; the dead `path`
  parameter is gone from `render_kilo_agent`.
- Default outputs are CWD-relative now (round 4, **implemented**) —
  `output_files/` beside the caller, not inside `site-packages`.
- Done when: the wheel contains no debug/script modules, `py.typed` is present,
  `RUF100` is clean, the type checker runs in CI in report-only mode, every CLI
  returns a documented code for a bad input, and `from_manifest` rejects an
  unknown stage.
- Effort: 3–4 days.

### Stage 4 — De-hardcode the donor and split the namespace (1–2 weeks)

- Introduce `agentic_bi/settings.py` (dataclass-based, no new runtime
  dependency) holding table/measure names; make every default `None` and
  resolve from settings. `fact_table`/`kpi_measures` survive only as values
  inside `examples/` and the sample registry in `validate_pbix.py`.
- Split `src/agentic_bi/` into `engine/`, `brand/`, `skeleton/` subpackages
  (`engine_core.py` → `engine/core.py`, and so on), keeping module-level
  re-export shims for one release so `from agentic_bi.engine_layout import ...`
  keeps working.
- Reject as out of scope: nothing here is required for Stages 0–3 and the move
  touches ~40 modules; do it only after the suite can absorb the churn.
- Done when: no donor object name is hardcoded in `src/` outside
  `settings.py` defaults and test fixtures; the pre-existing
  `tests/test_refactor_parity.py` pattern extends to the new splits.
- Effort: 1–2 weeks.

---

## 4. Explicit non-goals for this plan

- **Do not** chase a `mypy --strict` target `[Q]` proposes for Stage 4. With 92
  modules, 5 `Any` and 10 `type: ignore`, strict mode is weeks of noise for a
  library whose core is intentionally duck-typed over opaque binary parts.
  `[Q]`'s own round-2 position (basic `mypy`, not strict) is what this plan uses.
- **Do not** raise the coverage floor above the measured value in one jump.
- **Do not** refactor file sizes; the nine > 300-line files get revisited only
  when Stage 4 moves their directories anyway.
- **Do not** add a runtime dependency. The stdlib-only core is a real,
  verified property (92/92 modules import with zero third-party packages).
- **Do not** add upper bounds to dependency pins. `[Q]`'s round-2 reasoning is
  correct and overrides nothing here: a library with `<2.0` caps causes
  dependency hell for consumers.
- **Do not** ship a lock file. It is right for CI determinism and wrong for the
  published artifact; if a dev lock is added it must stay out of the wheel.
- **Do not** bulk-replace `print` → `logging`. Add a lint rule (`T201`) to freeze
  new occurrences and fix only `lineage/lineage_export.py` (15 `print`, 0
  `logger`), which is the one module where the missing logging is in a real
  pipeline.

## 5. Review decision log

The per-round decisions, corrections and rejected claims from the independent
Qwen review live in [REVIEW_DECISIONS.md](REVIEW_DECISIONS.md), with the raw
exchanges under `../other/qwen-review/`. That document is the record of *why*
each item above is in the plan; this one is the plan itself.

## 6. Platform note

The Windows-only surface (`msmdsrv.exe`, PowerShell, WinRM in session 0) is
untested anywhere in this plan's baseline and cannot be tested on macOS. Stage 1
adds a Windows CI leg for the parts that do not need Desktop; the Desktop path
stays covered by `docs/DEVELOPMENT_MACOS.md`'s manual VM procedure.
