# PCN/PDN fix — corpus validation against the real notices in sandbox MinIO

**Date:** 2026-09-21. **Branch under test:** `fix/pcn-continuation-table-pairing`
(`476cd29`, 8 commits off `origin/main`).
**This closes the open question in `docs/handoff-next-session.md` §1** — the fix had
61 passing unit tests and had never been run against a real PDN. It has now.

## How it was run

`kubectl exec` into `sandbox/doc-tools-7d5f466995-vwrf6` (scripts copied in with
`kubectl cp`, no stdin pipe — that is what the permission classifier was blocking
last session; the classifier did not block anything this session).

- **Baseline** = `/app/doc_tools/utils/table_text_layer.py` in the running pod.
  `md5 f1c1aa8c65c532300e335f24f0255e52`, **byte-identical to `origin/main`** — so
  the baseline is genuinely the deployed pre-fix code, not an assumption about it.
- **Fixed** = this branch's module, copied to `/tmp/tl_fixed.py`.
- Each side driven the way *its own* `sustainment.py` drives it: baseline
  `parts_from_page(page, pno)` per page; fixed `parts_from_pages(...)` with the
  header threaded across pages. Both call `parts_from_grid` per table directly so
  every emitted part keeps `(page, table, row, col)` and can be traced to the
  column header it came from.
- **9 distinct source PDFs** under `sustainment/inbound/` (20 `text.json` runs
  collapse to 9 notices). Published manufacturer notices, so raw values below.

## Result per notice

| notice | baseline parts | fixed parts | delta |
|---|---|---|---|
| `TYC-PCN-24-210412.pdf` | 38 (24 affected + **14 alias**) | 24 (all affected) | **−14, all alias** |
| `Diodes_PCN_2683_Rev1_EOL.pdf` | 402 | 402 | none |
| `Diodes_PCN_2683_FULLGREEN.pdf` | 402 | 402 | none |
| `EOL-36_BYV34-400,-BYV34-500.pdf` | 4 | 4 | none |
| `ADI_PDN_23_0120.pdf` | 0 | 0 | none |
| `PCN23-002.pdf` | 0 | 0 | none |
| `PCN24-029.pdf` | 0 | 0 | none |
| `onsemi_Generic_IPCN25300X.pdf` | 0 | 0 | none |
| `onsemi_Generic_PD26044X1.pdf` | 0 | 0 | none |

No notice lost a genuine part. The only behavioural change across the whole
corpus is the alias veto on TYC.

## 1. The alias veto works, and is verifiable by eye

`TYC-PCN-24-210412.pdf` page 1, table 5, header row:

```
Part Number | Part Discontinued per | Customer Drawing | Customer Part Number |
Alias Part Number(s) | Substitute Part Number | Substitute Alias Part Number(s) | ...
```

Row 1 of that table reads:

```
1052926-1 | YES | (blank) | (blank) | "2052-8002-92" | (blank) | (blank) | (blank)
```

- **Baseline** emits **two** affected parts for this row: `1052926-1` *and*
  `"2052-8002-92"` — because `Alias Part Number(s)` contains the substring
  `part number`, so the old vocabulary read it as an affected column.
- **Fixed** emits **one**: `1052926-1`. Correct — `"2052-8002-92"` is TE's alias
  designation, not the discontinued part.

14 such values across the table, exactly the 14 instances the handoff predicted.
All 14 are also quote-wrapped in the source (`"2052-8002-92"`), confirming the
de-quoting work on real data; the merge layer strips them via
`strip_enclosing_quotes`.

The 24 kept parts come from `Part Number` (16) and `Customer Part Number` (8).
Both are genuinely affected-part columns. *Observation, not a defect:* a customer
part number is the customer's designation for the same discontinued part, so it
surfaces as a second affected MPN for that row. Worth a decision at some point;
it is pre-existing behaviour and unchanged by this branch.

## 2. The "136 of 402 replacements sold as affected parts" premise is FALSE

This is the headline number the continuation-table fix was built on, and it does
not survive contact with the document.

**Reproduced exactly.** Feeding the 402 parts the text layer really extracts from
`Diodes_PCN_2683_Rev1_EOL.pdf` into `scripts/pdn_parts_diagnostic.py`:

```
inherit_headers=True : {affected_exact: 219, affected_partial: 8,
                        not_in_any_table: 39, from_replacement_column: 136}
inherit_headers=False: {affected_exact: 82,  affected_partial: 7,
                        not_in_any_table: 39, from_unheadered_table: 274}
```

**All 136 sit on pages 4 and 5. Those pages' own captions are:**

- page 4 — `Table 2 - EOL Devices with Life-time Buy Opportunity and **No Replacement Parts**`
- page 5 — `Table 3 - EOL Devices with No Life-time Buy Opportunity and **No Replacement Parts**`

They are not continuation pages of page 3's `EOL | Replacements` table. They are
separate tables that the document states contain no replacements at all, laid out
as a multi-column list of EOL devices read column-major. Page 4 column 0 is all
`TLC271*` variants and column 1 is all `TLC27L1*` variants — two part families
both being discontinued, listed side by side. They look like EOL/replacement pairs
row-wise only because each column is sorted.

**Where the 136 came from:** the diagnostic's *own* `index_tables(...,
inherit_headers=True)`. In the unstructured `text.json` grid space those three
tables are all 6 columns wide, so the diagnostic inherited page 3's
`affected|replacement|affected|replacement|affected|replacement` classification
onto pages 4 and 5 and relabelled half of their genuine EOL devices as
replacement-sourced. The heuristic added in `a67e7f4` (*"finds 136 replacements
sold as affected parts"*) manufactured the finding it reported.

**Both baseline and fixed extract those 402 parts correctly.** Nothing was ever
mixed up with a replacement on this notice.

## 3. Latent regression in the fix — inheritance can override a caption

On the pdfplumber path the fix's inheritance **never fires on any of the 9
notices**, because pdfplumber gives pages 4/5 a width of 8 while page 3's header
is 6, and the column-count guard declines. That is the guard doing its job — but
it is the *only* thing standing between this fix and the same mistake the
diagnostic made.

Simulated by trimming pages 4/5's two trailing all-empty columns to width 6 and
offering page 3's pairing:

| page | as pdfplumber gives it | if the width had matched |
|---|---|---|
| 4 | 34 affected, 0 replacements | 18 affected, 16 replacements |
| 5 | 257 affected, 0 replacements | 129 affected, 128 replacements |

**144 genuine EOL devices would silently stop being affected parts** — on pages
whose captions say, in the document, that there are no replacement parts.

`parts_from_grid` decides in the order *own header → inherit → caption → decline*,
so the caption can never veto an inherited pairing. `find_title_row` **does** find
these captions (returns row 0 on both pages); the evidence is already in hand and
is simply not consulted.

**Recommendation:** a grid that has its own caption naming its contents should not
inherit a pairing from a previous table. A caption is a statement *about this
table*; a matching column count is a coincidence. This mirrors the reasoning
already written into `header_pairing`'s docstring for why a caption-derived
pairing is not itself inheritable — the same argument runs in this direction too.

## 4. Pre-existing recall gap (not caused by this branch, not fixed by it)

5 of 9 notices yield **zero** tier-1 parts. In production these fall back to the
vision pass, so this is **not** proof the product loses them — but tier 1 is not
reading tables that are plainly born-digital:

- `PCN23-002.pdf` p2 — an 18-row, single-column list of MPNs (`SYDC-10-52VHP+`, …).
  No header, no caption → declined.
- `onsemi_Generic_PD26044X1.pdf` p2 — 15 rows × 3, `NCN5192MNRG | #NONE | #NA`.
  No header → declined.
- `onsemi_Generic_IPCN25300X.pdf` p4 — `NSR01F30NXT5G | SNSR01F30NXT5G, NSR2…`,
  an affected/replacement pair. No header → declined.
- `ADI_PDN_23_0120.pdf` p1 — header is
  `Model | Product Family | Replacement Part | Pin To Pin Compatible | Comments`.
  The affected column is headed **`Model`**, which is absent from
  `AFFECTED_HEADERS`, so no affected column is found and the row yields nothing.
  (`Product Family` and `Pin To Pin Compatible` are correctly vetoed as aliases by
  this branch.) A one-word vocabulary addition — but **gate it on content**: a
  column headed `Model` counts as affected only if its values are part-shaped by
  the test the extractor already applies. That covers ADI without pulling in
  vendors whose `Model` column holds product families.

### The shape this should take (design item, deliberately not done here)

Falling back to the vision pass trades a **labelling** problem for a
**transcription** problem. The grid tier 1 already has is exact; the only thing
it lacks is column meaning. MPNs are precisely the strings a vision model gets
wrong by one character, so re-reading them off pixels is the wrong trade.

Tier 1 should never return "nothing" for a born-digital table. It should return
one of three things:

1. **Parts** — when the headers classify. Unchanged.
2. **A declined grid** — the exact cells, column by column, plus the reason it
   declined (`no header row`, `unknown header: Model`, `single column`, …).
   Data with a known uncertainty, rather than silence.
3. **Nothing** — only when there is no text layer at all.

Tier 2 then has two jobs instead of one. Given a declined grid it receives the
page image *and* the grid, and answers only the narrow question: which column is
the affected part, which is the replacement, which are neither. **The part
strings come from tier 1's text, never from the model's reading of pixels.**
Full extraction from the image happens only for case 3.

The "decline rather than guess" rule survives intact — tier 1 still never
guesses, it just hands its evidence forward instead of discarding it. Do not
implement this by loosening the decline rule; that rule is what keeps the
continuation-table fix in §3 honest.

**Measure before building.** Nothing above is urgent until someone runs the
*full* path (tier 1 → tier 2 → merge) on these 5 notices and diffs the emitted
parts against ground truth. If tier 2 is already getting them right, this is a
cost and robustness improvement. If it is dropping or mis-transcribing them,
this is the parts-missing bug, and it moves to the front.

## Verdict

- **Ship-worthy on the evidence:** the alias veto and de-quoting are correct on
  real data and cost nothing elsewhere. That is a genuine improvement.
- ~~**Fix before ship:** the caption-vs-inheritance ordering in §3.~~ **Done the
  same day.** `parts_from_grid` now refuses an inherited pairing when the grid's
  own caption numbers a *different* table (`_names_a_different_table`), firing
  only on positive evidence so a continuation page that repeats or omits its
  parent's caption still inherits. Re-running the §3 simulation gives **0** lost
  devices on both pages (was 16 and 128), 4 new tests pin both directions, and
  the full-corpus A/B above is byte-for-byte unchanged after the patch.
- **Correct the record:** the 136/402 figure was quoted in
  `docs/handoff-pdn-continuation-table-pairing.md`, `docs/handoff-next-session.md`,
  `parts_from_grid`'s docstring and the `ALIAS_HEADERS` comment — all corrected
  in place. It remains in the `a67e7f4` commit message, which cannot be edited.
  It is a measurement artifact and should not be cited again.
- **No Weaviate exposure.** Extracted parts never reach a vector store: the
  sustainment path ends at `extraction.json` / `review.json` in S3
  (`semantic_assets.py:399`, `:428`), Neo4j (`:450`) and Jena (`:458`). The
  Weaviate writes in the same asset (`:333`, `:373`) carry page chunk text for
  every domain, and go through `_index_chunk`'s plain `data.insert` with no UUID
  (`:73`) — not the whole-object `replace` that strips vectors on embed failure.
  So the held vector-stripping fix is not on this path.

Scripts used are not committed (one-off instruments, per the instrument-hygiene
note): `ab_pdn.py`, `probe.py`, `repro136.py`, `latent.py`, `dump_grid.py` in this
session's scratchpad.
