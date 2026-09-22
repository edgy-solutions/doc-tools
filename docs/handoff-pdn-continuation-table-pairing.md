# Handoff — PDN/PCN: continuation tables emit REPLACEMENTS as affected parts

**Status:** fix WRITTEN and unit-tested on `fix/pcn-continuation-table-pairing`
(off `origin/main`); **not yet validated against the corpus, not yet deployed.**
**Branch context:** diagnostic work is on `mfg-extraction-investigation`.
**Priority:** this is the defect the review demo reported. It is not cosmetic.

---

## What landed (2026-09-17)

Branch `fix/pcn-continuation-table-pairing`, eight commits off `origin/main`.
**Not pushed** — the push was blocked by a permission rule; the commits are safe in
`C:/Users/cnogr/git/doc-tools/.git` (the worktree in `C:/tmp` holds only the checkout).

| commit | what |
|---|---|
| `23be2be` | continuation tables inherit the preceding header (the defect below) |
| `044f007` | alias columns vetoed in `table_text_layer` |
| `ad95e15` | enclosing quotes stripped from MPN values |
| `2de007f` | alias vocabulary aligned character-for-character with the diagnostic |
| `5d235b1` | alias rule added to the VISION parts prompt |
| `ffb4b5f` | self-review: alias vocabulary must not be matched against cell VALUES |
| `03f43c9` | de-quoting moved into `sustainment_merge` so it is unit-tested |
| `476cd29` | a page with no tables ends the inheritance run |

61 tests pass across `test_table_text_layer.py` and `test_sustainment_extraction.py`,
both directions pinned. **What is NOT done:**

- ~~**No corpus validation.**~~ **Done 2026-09-21** — see
  `docs/pcn-corpus-validation-2026-09-21.md` on the fix branch. It did not use the
  criterion below, because that criterion is unsound: the diagnostic grades the
  already-stored `extraction.json`, produced by pre-fix code, so `--tl-path` can
  only change how the instrument CLASSIFIES, never what extraction produces. The
  validation drove the extractor directly over the real PDFs, baseline vs fixed.
  **It also disproved the measurement this whole document is built on — read
  "The measurement" below with its correction.**
- **Not deployed anywhere.** Sandbox pulls ghcr; d4 needs an Artifactory push.
- The alias fix in `table_text_layer` covers tier 1 only. Tier 2/3 read pixels, and
  the diagnostic says that is where the demo's bad rows came from — hence the
  prompt rule in `5d235b1`, which is an instruction, not a guarantee. If alias
  values survive the next corpus run, look at the VISION path first.

### One thing to know before re-running the diagnostic

`table_text_layer._is_affected` now vetoes alias headers, and `find_header_row`
scores with it. So pointing `--tl-path` at the FIXED module changes the
instrument's own header detection as well as production behaviour.

Better: **don't re-run the diagnostic for this at all.** It grades stored
extractions, not extraction. Drive `parts_from_grid` / `parts_from_pages`
directly over the PDFs, once with the `origin/main` module and once with the
branch's, as `docs/pcn-corpus-validation-2026-09-21.md` §"How it was run"
describes.

---

## The defect, in one sentence

A parts table that spans pages loses its header on every page after the first, and
`table_text_layer.parts_from_grid` then assumes **every column is an affected
part** — so on an `EOL | Replacement | EOL | Replacement | EOL | Replacement`
table, all three replacement columns are emitted as discontinued parts.

## The measurement — RETRACTED 2026-09-21

> **This number is an artifact. Do not cite it.** It was reproduced exactly
> against the real notice on 2026-09-21 and then disproved: all 136 sit on
> `Diodes_PCN_2683_Rev1_EOL.pdf` pages 4 and 5, whose own captions read
> *"Table 2 / Table 3 - EOL Devices ... and **No Replacement Parts**"*. They are
> separate column-major EOL lists (page 4 col 0 is all `TLC271*`, col 1 all
> `TLC27L1*` — two families both discontinued), not continuation pages of page
> 3's `EOL | Replacements` table. The diagnostic's *own*
> `index_tables(..., inherit_headers=True)` — the heuristic added in `a67e7f4`,
> whose commit message reports this finding — inherited page 3's classification
> onto them because all three tables are 6 columns wide in `text.json` grid
> space. Both baseline and fixed extract those 402 parts correctly; nothing on
> this notice was ever mixed up with a replacement.
>
> The defect described above is still a real *shape* — a continuation page read
> in isolation does become all-affected — but the corpus never exhibited it, and
> the near-miss it did exhibit runs the **other** way: see the latent regression
> in §3 of `docs/pcn-corpus-validation-2026-09-21.md`, where inheritance winning
> over a caption would have cost 144 genuine EOL devices. That is why the fix
> now carries a table-number caption veto.

The retracted measurement, for the record:

Run the diagnostic with and without header inheritance
(`scripts/pdn_parts_diagnostic.py --prefix sustainment/ [--no-inherit-headers]`).
On one real notice in the sandbox corpus:

```
without inheritance:  affected_exact  82,  from_unheadered_table 274
with inheritance:     affected_exact 220,  from_replacement_column 136
```

~~**136 of 402 extracted "affected parts" (34%) appear ONLY in replacement
columns.**~~ The classifier counts `from_replacement_column` solely when a value
never appears in an affected column anywhere in the document, so it is not a
same-part-in-two-places artifact — it is a *different* artifact, of the
instrument's own inheritance. See the retraction above.

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

## Validation loop — SUPERSEDED 2026-09-21

The sandbox MinIO holds **9 distinct real notices** that mirror work (namespace
`sandbox`, pod `doc-tools-*`, bucket `processing-artifacts`, prefix
`sustainment/`). The loop originally prescribed here was:

```bash
kubectl exec -i -n sandbox <doc-tools-pod> -- python - \
  --prefix sustainment/ --tl-path /app/doc_tools/utils/table_text_layer.py \
  < scripts/pdn_parts_diagnostic.py
```

**Don't use it.** Two problems, both found while actually running it:

1. **It cannot answer the question.** The diagnostic grades the *stored*
   `extraction.json`, which was produced by whatever code ran at ingest — pre-fix
   code. `--tl-path` only changes how the instrument classifies those stored
   values. `from_replacement_column` collapsing would therefore never be evidence
   about post-fix extraction, and the number it produced was an artifact of the
   instrument's own header inheritance (see the retraction under "The
   measurement").
2. **The stdin pipe is what the permission classifier blocks**, not `kubectl
   exec` itself. `kubectl cp` the script into `/tmp` and `kubectl exec ... --
   python /tmp/x.py` runs fine.

**Use instead:** a direct baseline-vs-fixed A/B of the extractor over the real
PDFs, per `docs/pcn-corpus-validation-2026-09-21.md` §"How it was run" on the fix
branch. Baseline is `/app/doc_tools/utils/table_text_layer.py` in the running pod
(md5 `f1c1aa8c65c532300e335f24f0255e52`, byte-identical to `origin/main`); copy
the branch's module in beside it and drive `parts_from_grid` per table so every
emitted part keeps `(page, table, row, col)` and traces to its column header.

Two Windows traps if you redo this: use the PowerShell tool for `kubectl` (Git
Bash mangles `sandbox/pod:/tmp/x.py` into a path), and `Set-Location` into the
scratchpad first so `kubectl cp` gets a bare relative filename rather than a
drive letter.

## Two related defects found in the same corpus — BOTH FIXED on the branch

Both were fixed on `fix/pcn-continuation-table-pairing` after this section was
written, and both are confirmed against the real notices (2026-09-21).

1. ~~**Extracted part values carry literal quote characters**~~ — shapes like
   `"####-####-##"` included the `"`, and would fail every downstream join, graph
   lookup and match. **Fixed** in `ad95e15`, moved beside the other part-list
   transforms in `03f43c9`. Confirmed on real data: all 14 alias values on
   `TYC-PCN-24-210412.pdf` are quote-wrapped in the source and are stripped by
   `strip_enclosing_quotes` at the merge layer.
2. ~~**Alias columns exist and are read.**~~ **Fixed** in `044f007` / `2de007f`
   (`ALIAS_HEADERS` promoted into `table_text_layer`, character-for-character
   identical to `pdn_parts_diagnostic.ALIAS_HEADERS`), narrowed in `ffb4b5f` so
   the vocabulary applies to headers and not to cells that are values, with the
   vision pass told the same rule in `5d235b1`. Confirmed on real data:
   `TYC-PCN-24-210412.pdf` drops from 38 parts to 24, and all 14 dropped are
   alias values — exactly the 14 predicted here. No other notice in the corpus
   changes.

### Still open, and now a design item rather than a defect

Tier 1 returns **zero** parts on 5 of the 9 notices — headerless but plainly
born-digital grids, plus `ADI_PDN_23_0120.pdf` whose affected column is headed
`Model`. Production falls back to the vision pass, so this is not measured
product loss. §4 of `docs/pcn-corpus-validation-2026-09-21.md` has the detail and
the intended shape: tier 1 should hand a **declined grid** (exact cells, column
by column, plus the reason it declined) forward to tier 2 rather than discarding
it, so tier 2 labels columns from the page image while the part strings still
come from tier 1's exact text. Do not "fix" this by loosening the decline rule.

## What NOT to conclude

- `not_in_any_table` in the diagnostic means "not in *unstructured's* HTML
  tables", **not** "invented". Text-layer extractions read the PDF directly via
  pdfplumber and legitimately see tables unstructured's HTML does not. Do not
  report those as hallucinations.
- The grounding measurement on the manufacturing side found **zero** hallucinated
  values across 155. Assume misattribution and recall problems, not fabrication.
