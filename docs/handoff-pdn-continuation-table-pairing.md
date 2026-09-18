# Handoff — PDN/PCN: continuation tables emit REPLACEMENTS as affected parts

**Status:** root cause confirmed and measured; production fix not yet written.
**Branch context:** diagnostic work is on `mfg-extraction-investigation`. The
production fix belongs on a branch off `origin/main` (see "Where the fix goes").
**Priority:** this is the defect the review demo reported. It is not cosmetic.

---

## The defect, in one sentence

A parts table that spans pages loses its header on every page after the first, and
`table_text_layer.parts_from_grid` then assumes **every column is an affected
part** — so on an `EOL | Replacement | EOL | Replacement | EOL | Replacement`
table, all three replacement columns are emitted as discontinued parts.

## The measurement

Run the diagnostic with and without header inheritance
(`scripts/pdn_parts_diagnostic.py --prefix sustainment/ [--no-inherit-headers]`).
On one real notice in the sandbox corpus:

```
without inheritance:  affected_exact  82,  from_unheadered_table 274
with inheritance:     affected_exact 220,  from_replacement_column 136
```

**136 of 402 extracted "affected parts" (34%) appear ONLY in replacement
columns.** The classifier counts `from_replacement_column` solely when a value
never appears in an affected column anywhere in the document, so this is not a
same-part-in-two-places artifact.

Corpus-wide the affected-document rate moves from **1/9 to 3/9** once continuation
tables become readable. The work corpus shows the same shape: doc_0009 had 43
parts in `from_other_column` sourced from continuation tables whose headers had
truncated to `["Part Number","PCN","Drawing","Number(s)","Number","Number(s)",
"Difference"]`.

## Root cause (confirmed in code, not inferred)

`doc_tools/utils/table_text_layer.py`, `parts_from_grid`, the no-header branch:

```python
# No column header. If a CAPTION names the contents ("Table 3 - EOL Devices"),
# every column is an affected part and there are no replacements — the shape of a
# bare discontinuance list. Without a caption we decline: an unlabelled grid of
# unknown columns must not be guessed into parts.
ti = find_title_row(grid)
...
pairs = [(c, None) for c in range(width)]
```

The assumption is **correct for a genuine bare list** — the comment cites the real
page where it holds — and **wrong for a continuation of a paired table**. The
function cannot tell them apart because it sees each table in isolation. The
missing information is recoverable: the preceding table carries the header, and a
matching column count confirms it is the same table continued.

## The fix

Thread pairing state across tables/pages so the priority order becomes:

1. header row found → `pair_columns(header)`
2. **no header, but a preceding table had one with the SAME column count →
   inherit its pairs** *(new)*
3. no header, caption present → all-columns-affected *(existing, now last)*
4. otherwise → decline

Signature change required: `parts_from_page` is called per page by
`sustainment.py::_extract_parts_text_layer`, so the inheritance state has to live
across that loop — either returned from `parts_from_page` and threaded by the
caller, or a new `parts_from_pages(pages)` that owns the loop. Prefer whichever
keeps `parts_from_grid` pure; it is unit-tested as a pure function today and that
property is worth keeping.

Guard on column count. Without it an unrelated later table inherits a stale
header, which would be a worse bug than the one being fixed (it would mislabel
parts confidently rather than declining).

## Tests that must pin both directions

The whole risk is trading one wrong assumption for another, so pin both:

- **A genuine bare list must still read all-affected.** Caption present, no
  header, single column of parts → every column affected, no replacements. This
  is the case the current code was written for and it is real.
- **A continuation of a paired table must NOT.** Headed `EOL|Replacement` table,
  followed by a second grid with the same column count and no header → the second
  grid's odd columns are replacements, not affected parts.
- **Column-count mismatch must NOT inherit** → falls through to the caption rule.
- Fixtures exist: `tests/fixtures/manufacturing/` has the generators, and the
  sandbox corpus has real instances (the notice above) for an integration check.

## Validation loop (fast — no courier needed)

The sandbox MinIO now holds **9 distinct real notices** that mirror work
(namespace `sandbox`, pod `doc-tools-*`, bucket `processing-artifacts`, prefix
`sustainment/`). Run the diagnostic through the pod:

```bash
kubectl exec -i -n sandbox <doc-tools-pod> -- python - \
  --prefix sustainment/ --tl-path /app/doc_tools/utils/table_text_layer.py \
  < scripts/pdn_parts_diagnostic.py
```

After the production fix, `from_replacement_column` should collapse toward zero
**because the parts were never extracted as affected in the first place** — that
is the success criterion, not a change in the diagnostic's classification.

## Two related defects found in the same corpus, NOT yet fixed

1. **Extracted part values carry literal quote characters** — shapes like
   `"####-####-##"` include the `"`. These will fail every downstream join, graph
   lookup and match. Cheap to strip; silently corrosive if left.
2. **Alias columns exist and are read.** One notice has an explicit
   `Alias Part Number(s)` / `Substitute Alias Part Number(s)` header, and parts
   are sourced from it (14 instances in the work corpus, 1 in sandbox). Once
   pairing is correct, the next step is to **reject alias-sourced values at
   extraction** so they never reach a review card. The column classification in
   `pdn_parts_diagnostic.classify_columns` (with its `ALIAS_HEADERS` vocabulary)
   is the logic to promote into production.

## What NOT to conclude

- `not_in_any_table` in the diagnostic means "not in *unstructured's* HTML
  tables", **not** "invented". Text-layer extractions read the PDF directly via
  pdfplumber and legitimately see tables unstructured's HTML does not. Do not
  report those as hallucinations.
- The grounding measurement on the manufacturing side found **zero** hallucinated
  values across 155. Assume misattribution and recall problems, not fabrication.
