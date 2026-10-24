# Round 4 findings: the user-facing path and the agent path

Independent Qwen review (chat `07a5187f-2849-44f0-b86c-6bf902c9a578`, transcript in
`answer-round4-paths.md`, prompt in `prompt-round4-paths.md`) covering every
service of the package: the 11 console entry points (user path) and
`agents.py` + the spec `support` section (agent path).

Every claim below was re-measured here before being accepted; the raw exit codes
and last output lines are reproduced.

## User path (11 console scripts)

### U-1 (Warning). Uncaught exceptions where a docstring promises an exit code

Measured, unreadable input (`/nonexistent.*`):

| command | exit | last line |
|---|---|---|
| `visual-check /nonexistent.pbix /nonexistent.json` | 1 | `FileNotFoundError: ... '/nonexistent.json'` |
| `pbix-patch members --pbix /nonexistent.pbix` | 1 | `FileNotFoundError: ... '/nonexistent.pbix'` |
| `brand-audit templates/template.pbix` | 1 | `NotImplementedError: format '.pbix' is not supported yet` |
| `engine --data /nonexistent.csv ...` | 1 | `FileNotFoundError: ... '/nonexistent.csv'` |
| `test-build --data /nonexistent.csv ...` | 1 | `FileNotFoundError: ... '/nonexistent.csv'` |
| `lineage /nonexistent.pbix` | 1 | `FileNotFoundError: File not found: ...` |
| `report /nonexistent.json` | 1 | `FileNotFoundError: ...` |
| `web-clone --pbix /nonexistent.pbix ...` | 2 | `error: [Errno 2] ...` (handled) |
| `web-clone --pbix <ok> --out /nonexistent_dir/x.html` | 1 | `OSError: [Errno 30] Read-only file system` |

Each of `visual-check`, `pbix-patch`, `brand-audit`, `engine`, `test-build`,
`lineage`, `report` prints a full Python traceback; `patch_cli`'s own docstring
says "Exit codes: 0 on success, 2 on a patch error", yet a missing file is an
unhandled `FileNotFoundError` (exit 1), not `PatchError` (exit 2). `web-cli` is
the only one that catches and prints `error: ...`.

**Qwen:** confirmed; Warning — a CI step parsing stderr breaks on a traceback.
**Verdict:** accepted.

### U-2 (Warning). Exit code 2 is overloaded

`argparse` uses 2 for CLI misuse; `web-clone`, `pbix-patch` and
`guest-dashboard` also use 2 for *input/spec* errors. A caller cannot tell
"wrong flags" from "bad artifact" with the same code.

**Qwen:** confirmed; Warning — POSIX convention is `1` = runtime/data error,
`2` = CLI misuse. **Verdict:** accepted, and this is already the scheme
`docs/IMPROVEMENT_PLAN.md` targets.

### U-3 (Warning). `lineage.main()` has no exit contract

`pbi_lineage.main()` never returns; success is an implicit `None` → 0, failure an
exception → 1 with a traceback. No documented `Exit codes` block.

**Qwen:** confirmed; Warning. **Verdict:** accepted (same class as U-1).

### U-4 (Critical). Default outputs are written inside the installed package

`lineage/pbi_lineage.py:180` → `Path(__file__).resolve().parent / "output_files"`,
`antipatterns/pbi_antipatterns.py:181` → `Path(__file__).resolve().parent / "output_files"`.
In an installed `site-packages` tree (Docker/CI/system Python) the first run
raises `PermissionError`.

**Qwen:** confirmed; Critical. **Verdict:** accepted (already tracked as Stage 1
in the plan — not a new defect, but it is the top user-path item).

### U-5. Checklist, not a defect

Qwen confirmed the 4-point acceptance checklist (exit contract, boundary
validation, output overwrite, infra-error handling). **Verdict:** accepted as
review criteria.

## Agent path (`agents.py` + spec `support`)

### G-1 (Critical). `from_manifest` accepts any `stage` — orphan agents

Measured:
```python
agents.from_manifest({"id": "agent.custom", "role": "X", "stage": "WRONG"})
# -> accepted; agent.stage == "WRONG"
agents.all_agents("WRONG")  # -> []   (silent)
agents.agents_for_stage("nope")  # -> ValueError (strict)
```
A typo (`stage: "develp"`) yields a valid agent that no stage ever resolves, and
`agents_for_stage("develop")` never finds it — a silent failure with no error at
load time.

**Qwen:** confirmed; Critical — silent failure, hours of debugging. Fix:
validate `stage in STAGES` in `from_manifest`; make `all_agents("WRONG")` raise
instead of returning `[]`. **Verdict:** accepted, with one correction — the
silent-failure severity is real but the user path (U-4) is the same severity, so
both are P0.

### G-2 (Nit). `resolve_agents` priority is correct but undocumented

Measured: override manifest wins; `disable_ids` beats `enable_ids`; enabling a
default-off agent forces `enabled=True`. Qwen confirmed the logic is safe
(fail-closed) and asks only for a docstring/README note.

**Qwen:** not a defect; Nit. **Verdict:** accepted as a doc tweak.

### G-3 (Warning). `render_kilo_agent(agent, path)` — `path` is dead

Measured: the parameter is never read; the README call passes `""`.
Qwen notes the latent risk that a future "write the file" implementation using
`agent.id` (which can come from a spec, i.e. LLM/attacker-influenced) would allow
path traversal without sanitisation.

**Qwen:** confirmed; Warning. **Verdict:** accepted — the dead parameter is real;
the traversal risk is latent (not reachable today), so it is a caveat for the fix,
not a live vulnerability.

## Priority table

| Priority | Item | What |
|---|---|---|
| P0 | U-4 | default outputs written into `site-packages` (permission failure) |
| P0 | G-1 | `from_manifest` accepts an invalid `stage` → orphan agent, silent |
| P1 | U-1, U-3 | tracebacks instead of exit codes; `lineage` has no contract |
| P1 | U-2 | exit code 2 overloaded (CLI misuse vs bad data) |
| P2 | G-3 | dead `path` parameter + latent traversal caveat |
| P3 | G-2 | `resolve_agents` priority documented, not changed |

Both paths share one root cause: boundaries (CLI entry points and manifest
validation) are more permissive than the contracts they advertise.
