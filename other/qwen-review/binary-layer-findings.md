# Binary-layer findings in `pbix_binary`

Three defects found in round 3, all **reproduced locally against the shipped
donor** `templates/template.pbix`. Unlike the `web_report` injection pair
(round 2), none of these is attacker-triggered through a normal workflow — but
all three make the tooling lie about its own success, which matters more here
because the output is a `.pbix` that Power BI must be able to open.

Full reproduction commands are in `prompt-round3.md`; the reviewer's answers are
in `answer-round3.md`.

## D-1: XML-escaping asymmetry corrupts the written ABF (High)

`abf_model.serialize_virtual_directory` builds XML by hand with f-strings:

```python
parts.append(f"<BackupFile><Path>{f.path}</Path><Size>{f.size}</Size>...")
```

Nothing is escaped. `parse_virtual_directory` reads through `ET.fromstring`,
which *decodes* entities, so the two directions disagree: a document containing
`<Path>A&amp;B_Storage_1234</Path>` parses to the path `A&B_Storage_1234`, and
writing that path back emits bare `&` — not well-formed XML.

The `backup_log` document does not have this problem because it is serialized
with `ET.tostring`, which escapes correctly. The defect is local to the
hand-rolled virtual-directory serializer.

Reproduced end-to-end through the real pipeline (patch a donor whose virtual
directory uses a validly-escaped path, then let `apply_patches` run):

```
donor parses; parser decodes path to: ['A&B_Storage_1234']
apply_patches returned successfully: 971482 B
zip testzip(): None                       <- the zip is valid
SHIPPED DataModel BROKEN: ParseError: not well-formed (invalid token), column 587
```

`apply_patches` returns success and writes a `.pbix` whose `DataModel` can no
longer be parsed. The shipped donor has 515 virtual-directory paths, all clean
20-character hex ids, so it is not triggered today; any donor whose storage path
contains `&`, `<` or `>` is affected (`&` is the realistic one — a workspace path
like `R&D`).

Cross-checked fix direction (verified): `ET.tostring(root, encoding="unicode")`
emits no XML declaration and, for a normal path, produces **byte-identical**
output to the current hand-rolled serializer. So switching to `ET.Element`/
`SubElement` is behaviour-preserving in the ordinary case and correct in the
hostile one.

## D-2: virtual-directory offsets and sizes are never validated (Medium)

`parse_virtual_directory` accepts any integers — verified with
`<Size>-5</Size><m_cbOffsetHeader>-1</m_cbOffsetHeader>` and `999999999`: no
error is raised. `parse_abf_index` checks only the virtual directory's own range
and that the last entry is `LOG`; member ranges are never checked, so a negative
offset silently yields the wrong bytes:

```
member_blob with a negative offset returned 0 bytes and did not fail
```

For a malformed or hostile `.pbix` this is a silent wrong-bytes read instead of
a domain error. Not currently a crash and not currently reached by the shipped
donor, but it is the missing guard that makes D-1 and future bugs invisible.

## D-3: ambiguous equal-length patches hit the first match silently (Medium)

`_apply_even` does `bytes(abf).find(find)` and takes the first occurrence:

```
occurrences of 64x NUL: 7356
ambiguous patch accepted with NO warning; log: ['replace: 64 B at offset 963']
total candidate sites ignored: 7355
```

A patch spec of `{"kind": "replace_hex", "find": "00"*64, ...}` lands at offset
963 while 7356 sites match. The user gets a valid zip with a different byte
changed than intended — worse than a hard error, because nothing signals it.

## Also: `apply_patches` never re-reads its own output

Neither `apply_patches` nor `patch_cli._cmd_apply` verifies the result.
`swap_datamodel`/`build_container` check only `zip.testzip()` — archive
integrity, not whether the `DataModel` inside parses. That is exactly why D-1
reached disk. Note the test helper `_assert_index_consistent` in
`tests/test_pbix_binary_relayout.py` already does what production code does not.

## Verified as already correct (not defects)

- `decompress_datamodel` rejects truncated chunks for all of -1/-4/-28/-4096
  (`DataModelCodecError: truncated ... need 71087 bytes`).
- `relayout_abf` recomputes offsets, keeps the prefix verbatim, writes the UTF-16LE
  header into its 4096-byte page with an overflow check.
- `swap_datamodel` with an identical `DataModel` is **byte-identical** — verified
  `orig == new` on the shipped donor, so it touches nothing it should not.
- `swap_datamodel` shifts the central directory and the local headers of members
  stored after `DataModel`, and preserves the compression method.
- `backup_log` serialization escapes correctly via `ET.tostring`.
- Zero-byte replacement member and a 2000-character logical name are both
  accepted by `relayout_abf` without breaking the index.

Known leniency, recorded but not filed as a defect: up to 7 trailing bytes on a
`DataModel` member are silently ignored (`decompress_datamodel` stops when fewer
than 8 bytes remain). Low impact; worth a `logger.debug` at most.

## Fix plan (accepted from round 3)

Ordered, and all four are small. `[Q]`'s staging is adopted: the first three are
`0.0.1b2` blockers, the deeper validation is `0.0.2`.

1. **Serialize the virtual directory with `ElementTree`**, replacing the
   hand-rolled f-strings. Add a regression test that round-trips a path
   containing `&`, `<`, `>`, `'`, `"` and asserts the parsed path is unchanged.
2. **Fail fast on ambiguous patches.** Default to requiring exactly one match;
   add an optional `occurrence` field (0-based index, or `all`) for deliberate
   multi-site replacement. Existing tests patch unique strings, so they keep
   passing; a test that relied on ambiguity would be relying on undefined
   behaviour.
3. **Make `apply_patches` self-verifying** (not opt-in): re-read the written
   `DataModel`, decompress, and `parse_abf_index` it. This is milliseconds on a
   ~500-member model and would have caught D-1 at the source.
4. **Validate ranges** (`0.0.2`): non-negative `size`/`offset` at parse time;
   `offset >= PREFIX_SIZE`, `offset + size <= vdir_offset`, and no overlaps in
   `parse_abf_index`; a final bounds check in `member_blob`.

`[Q]` recommends `--no-verify` not be offered for step 3; that is accepted — for
a tool that rewrites binary models, self-check is the contract, not an option.
