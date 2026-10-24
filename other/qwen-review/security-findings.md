# Security findings in `web_report`

Two exploitable injection defects were found in `agentic_bi.web_report` and
**both were reproduced in a real browser**, not just reasoned about. They are
independent, need separate fixes, and share one root cause: untrusted values
from a `.pbix` reach an HTML/JS context without context-appropriate escaping.

Threat model: a `.pbix` is a downloadable file. Its `Report/Layout` carries
page `displayName`, visual titles, projections and `visualType`. Anyone who can
hand a `.pbix` to the clone command controls those strings. The clone is a local
HTML document, which normally lowers severity — but the same renderer feeds the
published report path, and a shared `.pbix` is an ordinary file-transfer vector.

## F-1: script breakout through the embedded JSON (High)

`web_render.py:176` builds the client payload with
`json.dumps(..., ensure_ascii=False)` and `web_render.py:246` embeds it verbatim:

```python
<script>window.__REPORT_MODEL__ = {model_json};</script>
```

`json.dumps` escapes quotes and backslashes but **not** `<` or `>`, so a visual
label of `</script><script>…</script>` closes the script element early.

Reproduced: label `</script><script>document.title='PWNED'</script>` → the
browser executed the injected script and the document title became `PWNED`.
The same input also truncates the payload, so the browser-visible JSON no longer
parses (`JSONDecodeError`), breaking the clone even without script execution.

The sink has **more than one source**, which is the reason the fix belongs at the
sink and not at each input. A second route was reproduced independently: an
invalid entity name in `prototypeQuery.From` becomes an issue message built by
`web_checks.py:214` (`f"{vt} {what} table '{ent}' not in model"`), that message
is serialized into the same payload, and the breakout fires with no visual title
involved at all:

```
payload has '</script>': True
issue: BIND-TABLE-MISSING "... table '</script><script>document.title='PWNED3'</script>' not in model"
render breakout: True
```

Neither `_e()` on the label nor escaping `visualType` would close this. Escaping
the serialized payload closes both, and any future third source, at once.

Fix (verified in the browser): escape the three characters that are unsafe in a
script context before interpolation —
`.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")`.
JSON stays valid, the original label round-trips through `json.loads`, and the
injected title no longer fires. `\u003c` alone is enough for the breakout; `&`
is included for the HTML-entity case and costs nothing.

Note: the failure of a naive `{,}`-based fix is worth recording. Cutting the
script at the **first** `</script>` matches on the injected copy inside the
payload, not the real closing tag, so a fix must edit the serialized string
before it is interpolated — never post-process the assembled document.

## F-2: JS-string breakout through `onclick` (High)

`web_render.py:98` writes the element key into a single-quoted JS string inside
an HTML attribute:

```python
f'title="{_e(_tooltip(el))}" onclick="showDetails(\'{_e(el.key)}\')">'
```

`_e()` is `html.escape(..., quote=True)`, which is correct for the HTML attribute
context but not for the JS context nested inside it. The browser un-escapes the
attribute first (`&#x27;` → `'`), so the injected text lands in JavaScript
source with the quoting already undone.

Reproduced: page `displayName` of `P');document.title='PWNED';//` (page names
become part of `el.key`) produced `onclick="showDetails('P');document.title='PWNED';//#0')"`;
clicking the element set the title to `PWNED`.

The correct fix is to stop building JS inside HTML strings: attach the key via a
`data-` attribute and read it from the event handler, or pass it through
`json.dumps` inside a script block. Escaping harder is the wrong direction —
HTML-escaping a JS literal is not a sound composition.

## Verified non-issues

Checked to avoid over-reporting:

- `_detail_rows` interpolates `{m.fields}`, `{m.roles}`, `{m.colors}`,
  `{m.filters}`, `{m.errors}` without `_e()`, but every one of those is an `int`
  (`web_model.py:42-49`), so no markup can flow through today. It is a latent
  trap, not a live defect: adding a string field there would silently open a
  third vector. Worth a comment or a typed wrapper, not a rewrite.
- `_tooltip` content reaches HTML only through `_e(_tooltip(el))`, i.e. escaped.
- `mock_body(el.visual_type)` ignores its argument for output (looks up a static
  SVG by category, `web_mock.py:241`), so no raw interpolation.
- Severity values are constrained by `ElementMetrics.worst` to
  `error|warning|info`, so the unescaped `{severity}` in class names and
  `data-severity` cannot carry a payload.
- No `extractall`/`extract` anywhere in the package, so the zip write path in
  `engine_container.py:172` has no path-traversal surface; member names are
  copied from the donor and `testzip()` validates the output.

## Regression tests to add

Both defects are cheap to pin and both must be pinned, because the fix for each
is a one-line change that a later refactor can silently undo:

1. Label `</script><script>…</script>` → assert the rendered HTML contains no
   `</script><script>` and that the extracted JSON parses and round-trips the
   label unchanged (F-1).
2. Page name `P');…;//` → assert no `onclick` attribute contains a bare `'` from
   the key, or (after the fix) that the rendered HTML carries no inline JS
   string built from untrusted data (F-2).

Both use only in-memory `Report/Layout` fixtures from `tests/web_report_fixtures.py`
and run on macOS with no Desktop, so they belong in the default suite.

## Reported to the other participant

The findings and the exact reproduction commands were posted to the shared board
for the main session; the raw review exchange is in
`answer-round2.md` and `prompt-round2.md` next to this file.
