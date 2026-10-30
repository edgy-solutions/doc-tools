# report → architect, from doc-tools/lane/7f

## The customer-alias column, implemented; two clauses answered by measurement

Ruling of 2026-10-29 (DPP report rulings, items 1–4). Items 1, 2 and 4 are done.
Item 3 is a no-op by instruction. Two clauses inside item 1 came out differently from
how they were written, and both differences are measurements rather than preferences
(§1).

## The before arm, re-scored against the corrected ground truth

One fire's output, scored twice: against the ground truth it was written for, and
against the corrected one. Same run, same emitted values.

| | BEFORE, against its own (conflated) GT | BEFORE, against the CORRECTED GT | AFTER |
|---|---|---|---|
| parts | **522 / 522, clean** | 512 / 512 exact, **10 SPURIOUS** (exit 1) | **512 / 512, clean** (0 spurious, 0 missing) |
| customer aliases | no such field | 0 / 21 | 10 / 21 (TYC 10/10; TI 0/11) |
| headers | 15 / 16 | 15 / 16 | 14 / 16 exact, 16 / 16 passing |

The first two columns are one fire scored twice. The third is a second fire, on the
after tree.

The ten spurious are all TYC customer part numbers, published as **affected parts**:

```
'160303P001'  '160303P1'  '8503812FP-3'  '9501815SP-1'
'TYC1052982-1'  'TYC1056344-1'  'TYC1057289-1'  'TYC1057775-1'
'TYC1059707-1'  'TYC1059928-1'
```

Component IRIs are shared across notices and a row fact names no notice, so those ten
are the non-withdrawable kind: re-ingesting cannot take them back. **A conflated ground
truth is worse than a wrong one** — it scored a ten-part fabrication as perfect, and no
instrument in the tree disagreed, because the instrument had been taught the
fabrication. The 522 → 512 re-label is what makes the number visible at all.

The after arm, the full fire detail and the whitespace fix's measured consequence are
in §5.

---

## 1. The two clauses that came out differently

### 1a. The `"text"` strategy is NOT adopted. Measured, on all ten.

The ruling says *"adopt the 'text' strategy (tables-borderless-whitespace-tables)"*.
Measured across the corpus by `scratchpad/harness/grid_strategy_probe.py`, which runs
both `pdfplumber` strategies over every page of all ten notices and puts each
resulting grid through the real `grid_outcome`, tier 1's accepted-part count is:

| | tier-1 parts, `lines` | tier-1 parts, `text` |
|---|---|---|
| whole corpus | **432** | **136** |
| `TYC-PCN-24-210412.pdf` | 26 | 0 |
| `Diodes_PCN_2683_Rev1_EOL.pdf` | 402 | 112 |
| `EOL-36_BYV34-400,-BYV34-500.pdf` | 4 | 0 |
| `TI_PCN_20210316000.pdf` | 0 | 14 |
| `ADI_PDN_23_0120.pdf` | 0 | 3 |
| `IDT_PDN_OV-19-05.pdf` | 0 | 6 |
| `onsemi_Generic_IPCN25300X.pdf` | 0 | 1 |
| `onsemi_Generic_PD26044X1.pdf`, `PCN23-002.pdf` | 0 | 0 |

(Those counts are tier 1 only, with no vision tier in the loop; they are not a corpus
score. The point is the direction and the size, both of which are unambiguous.)

**And a correction to my own earlier reading, which the ruling relied on.** I had
reported that `text` does not recover the TI page-2 grid. That is wrong, and the probe
shows it: under `text`, TI page 2 yields one 26×4 grid, a header at row 2, and
`grid_outcome` **accepts** it — 14 parts where `lines` yields no grid at all. The
ruling's premise was sound. What it did not have is the other half of the measurement.

**The disqualifying finding is not the part count. It is what `text` accepts as a
header, and what accepting it does to routing.** Under `text`, ADI page 1 produces a
44×9 grid whose header row is the company's own postal address, fragmented across nine
columns:

```
['', 'Analog', 'Devices, Inc. One', 'Analog Wa', 'y, Wilmington, MA 0', '1887', '', '', '']
```

`grid_outcome` accepts that and emits **3 parts** from it. That is the Clause-1 defect
class again — page furniture read as table structure — arriving by a different door,
and this time it is the header rather than the manufacturer.

Then the second-order effect, which is the one that would cost real parts. Tier 2 runs
`LabelGridColumns` over `page_declines` **only** — the grids tier 1 *declined*. A page
tier 1 accepts never reaches the vision path. Every document in the right-hand column
above with a `lines` count of 0 is a document whose parts come from the vision tiers
today, precisely because tier 1 declines its pages. Adopting `text` makes tier 1 accept
some of those pages — on the strength of headers like the one above — and so **removes
them from the list that triggers vision at all**. On ADI that trade is a three-part
furniture reading against a salvage measured in four figures.

So the clause is not implemented, and not because the goal is wrong. **What I recommend
instead, and what I have not built:** `text` as a per-page *fallback*, gated on two
conditions measured together — (a) tier 1 produced **no grid at all** on that page under
`lines`, so nothing is being displaced, and (b) the accepted header survives a furniture
veto, so the ADI address cannot become a header row. That recovers TI page 2 (condition
(a) holds there: `lines` yields zero grids) without touching TYC or Diodes (condition (a)
fails there, so the fallback never runs). It needs its own fire before adoption, because
condition (b) is the whole of its safety and I have not measured a veto that holds.

### 1b. TI's affected count stays at 9, and `expect_absent_mpns` is kept.

The ruling re-labels TI as *"8 affected + 11 aliases with `expect_absent_mpns`
retired"*. The 8 is page 2's device count, and page 2's devices are a strict **subset**
of the notice's 9 affected parts — the ninth is printed elsewhere in the document and is
not a page-2 row. Re-labelling the ground truth to 8 would have retired a part the
notice genuinely affects, so the ground truth reads **9 affected + 11 customer
aliases**, and the 11 are the ruling's 11 exactly.

`expect_absent_mpns` is **kept**, with its meaning changed rather than its contents.
It used to enumerate an accident — eleven values excluded because the page yields no
tables. It now enumerates a **rule**: these eleven are customer aliases and must never
appear in the affected set, whatever tier reads the page. The retired thing is the
canary that asserted no rule existed (`tests/test_ti_pcn_live_miss.py`), which
instructed its own deletion the day a rule arrived; what replaces it asserts the rule's
effect on the real page-2 header, including that no `expect_absent_mpns` value is in
the affected set.

---

## 2. What landed (item 1)

`customer_mpn` is a row field, paired positionally to `affected_mpn`, emitted,
reviewable, exportable, and scored as its own column. 22 files, +637/−91.

- **Schema.** `PartRow.customer_mpn string?` and `PartImpact.customer_mpn string?` in
  `baml_src/sustainment.baml`, regenerated (14 client files). Deliberately **no
  `customer_mpn_source` on the promoted shape**: both the tier-1 and the grid-vision
  row dicts carry a `customer_mpn_source` internally, and the review item resolves its
  provenance from it, but it is not promoted into `PartImpact` or the catalogue.
  `tests/test_export_field_catalogue.py` asserts exactly three promoted `*_source`
  names, and that assertion is still true and still meaningful.
- **Tier 1.** `customer_columns()` in `doc_tools/utils/table_text_layer.py`, and the
  veto in **`pair_columns`, not `_is_affected`** — `_is_affected` also feeds
  `find_title_row`, so vetoing there would have moved title detection as a side effect.
- **Tier 2.** `GridColumnRoles.customer_col`, read on the vision path.
- **The merge and the list path** carry the field through (`sustainment_merge.py`,
  `parts_text_list.py`).
- **The catalogue** (`registry/export_field_catalogue.json`) gains the entry, so the
  field is served by the export.
- **Scoring, as its own column.** `split_customer_cell`, `score_customer` and
  `customer_totals` in `scripts/pcn_score.py`; the run row carries
  `customer_mpns` as **cells**, not ids.
- **The gate** reports it per fire, under a block that prints the word ADVISORY and
  names the reason next to the number.

Three decisions inside that are worth the architect's eye:

1. **Composite cells are split in the scorer, not the extractor.** One customer cell
   can hold two ids for one affected part (TYC prints such cells). Splitting in the
   extractor would duplicate the affected part and move the **parts** denominator, so
   tier 1 carries the cell verbatim and the one place that compares ids to a list of
   ids does the splitting. Without the scorer-side split, TYC reads 6 exact / 2
   spurious / 4 missing against a ground truth of 10 it emitted in full.
2. **The column is ADVISORY, and that is load-bearing, not deference.** TI's 11
   aliases sit on a page `find_tables()` returns zero tables for under *both*
   strategies. A blocking recall term there would be a red the tree cannot clear by
   any change to the extractor. It is reported in full, by name, beside the parts
   score; the parts verdict in `main()` names its own keys so this one cannot leak in;
   and `tests/test_customer_alias_column.py` pins it with a real `gate.score_fires`
   harness — a deliberately red customer column yields `blocking == []`,
   `exempted == []`, `verdict == "pass"`.
3. **A missing `customer_mpns` key is not an empty one.** Missing means the notice has
   no customer column (8 of 10) and scores `None`, never zero. An explicit `[]` is a
   positive claim of *none*, so a spurious alias against it is still reported. (My own
   first test of this asserted the wrong thing; the code was right.)

**The denominator moved by a re-label: 522 → 512.** TYC's ground truth was conflating
affected parts with customer aliases; 26 becomes 16 affected + 10 aliases. Numerator
and denominator fall together by the same 10, so a **rate** at 512 is comparable to one
at 522 and a **count** is not. This is the fourth permitted kind of ground-truth change
and it is commented as such at the source (`scripts/pcn_corpus_run.py`), with the three
dependent test files updated to match.

---

## 3. The whitespace budget (item 2)

`looks_like_mpn`'s whitespace budget now counts **all** whitespace rather than spaces
alone, as ruled. It fails toward **not** emitting, which is the direction the ruling
approved. Its measured consequence on all ten is in the fire section below.

---

## 4. Item 3, and item 4

**Item 3** — `_is_form_region` and `strip_enclosing_quotes` are untouched. Both remain
recorded divergences with reasons, as instructed.

**Item 4** — drafted at
[`sessions/2026-10-29-draft-issue-for-the-dpp-repo-three-gaps-synthetic-only.md`](2026-10-29-draft-issue-for-the-dpp-repo-three-gaps-synthetic-only.md),
ready to paste, for Chris to post under his name. All three findings (two
verbatim-correct readings, header label offset from its data column, declared
coordinate space) with **synthetic examples only** — invented part numbers, an invented
manufacturer, invented coordinates. No document name, part number, manufacturer,
customer, filename or host appears in it. The file opens with that disclosure check
stated explicitly, so the person posting can verify it rather than trust it.

---

## 5. The fire, before and after

Both arms in `doc-tools-65766ddbdc-46bgv` (namespace `sandbox`, context `edge`), with
`PROMPT_SOURCE=file` and `LANGFUSE_PROMPT_LABEL=production` on both, distinct output
paths on both, and each arm proved to be running its own code by a script under
`scripts/` rather than by `python -c`: the before tree has no `_whitespace_count`, no
`_is_customer`, no `customer_columns` and no `score_customer`, and declares
`gt_parts 522`; the after tree has all four and declares `512`.

### Before

The headline is at the top of this report. The raw scorer rows behind it:

```
TYC-PCN-24-210412.pdf                    16    26     16    10     0     0  <<
TOTAL                                   512   522    512    10     0     0
SCORE 512 / 512 by exact part number        (exit 1: spurious is non-empty)
```

Customer aliases on the before tree: **0 / 21** (TYC 10 missing, TI 11 missing), as
expected — the field does not exist in that tree, and the block correctly reads
all-missing rather than vanishing, which is the behaviour it was written to have for a
pre-ruling score JSON.

Headers on the before tree: **15 / 16** established fields exact over 10 of 10, with
the one non-exact being an `expect_absent` pass (TI's `doc_level_ltb_date`, correctly
absent), not a miss.

### After

```
TYC-PCN-24-210412.pdf                    16    16     16     0     0     0
Diodes_PCN_2683_Rev1_EOL.pdf            402   402    402     0     0     0
EOL-36_BYV34-400,-BYV34-500.pdf           4     4      4     0     0     0
ADI_PDN_23_0120.pdf                       1     1      1     0     0     0
PCN23-002.pdf                            18    18     18     0     0     0
PCN24-029.pdf                             1     1      1     0     0     0
onsemi_Generic_IPCN25300X.pdf            19    19     19     0     0     0
TI_PCN_20210316000.pdf                    9     9      9     0     0     0
IDT_PDN_OV-19-05.pdf                     17    17     17     0     0     0
onsemi_Generic_PD26044X1.pdf             25    25     25     0     0     0
TOTAL                                   512   512    512     0     0     0
SCORE 512 / 512 by exact part number
```

**Parts: 512 / 512, zero spurious, zero missing, zero malformed, on every one of the
ten.** TYC is 16 / 16, which is the whole ruling working: the veto removed the ten
customer ids from the affected column and the sixteen real affected parts are untouched.
The whitespace fix cost **no real part** -- every notice scores exactly its ground truth,
so the widened budget declined nothing that was being emitted correctly before.

```
CUSTOMER ALIASES (2 of 10 notices declare the column) - ADVISORY, never part of the parts verdict
TYC-PCN-24-210412.pdf                    10      8     10     0     0
TI_PCN_20210316000.pdf                   11      0      0     0    11  <<
TOTAL                                    21      8     10     0    11
SCORE 10 / 21 customer aliases by exact id (ADVISORY - a red here does not fail the gate)
```

**Customer aliases: 10 / 21.** TYC is **10 of 10** -- the ten ids the before arm
published as affected parts are now in the field they belong to, from **8 cells** (two
cells hold two ids each, which is why the scorer splits cells and the extractor does
not: splitting in the extractor would duplicate the affected part and move the PARTS
denominator). All 8 carry a text-layer cell bbox, so the review card highlights the
cell rather than a string match.

TI is **0 of 11**, and this is the red that was expected and argued for in advance: TI's
eleven aliases sit on a page `find_tables()` returns **zero** tables for, under BOTH
strategies, so no change to the extractor can clear it. It is the exact case the
ADVISORY framing exists for -- a blocking term there would be a permanent red that the
code cannot satisfy, and it would have earned the gate's exemption state.

Headers: **14 / 16 exact, 16 / 16 passing.** The two non-exact are both PASSES in
`HEADER_PASSES`:

- TI `doc_level_ltb_date`: `correctly_absent` -- unchanged from the before arm.
- TI `mfr`: `alias`, wrote `'Texas Instruments'` where canonical is `'Texas Instruments
  Incorporated'`. **This moved between the arms** (before: `exact`), and it is not a
  regression -- it is upstream finding #1 from the DPP draft happening live, on this
  corpus, between two runs of code that did not touch the `mfr` arm. The page prints
  both forms; the model read a different correct one. `alias` is in `HEADER_PASSES`, so
  `clean` holds and the gate verdict is unaffected. It is also exactly the case the
  architect still owes a comparator ruling on (PR #189).

Crop seal: `tables=37 stored_cut_tables=2 repaired_cut_tables=0 errors=0` -- green.

The run exits **0**.

---

## 6. Three things found on the way, none of them asked for

### 6a. A NUL byte inside a TYC column header

TYC prints one header as `Subs\x00tute Part\nNumber` — a literal NUL where the `ti`
ligature should be. This is the same damaged-font condition that gives that notice
`TE Connecvity`, but it reaches a **header** rather than a value, and a NUL is not a
dropped character: it is a byte no comparator expects. Today it is harmless — that
header is not one the pairing needs to match — and it is a latent Murata-class defect:
the moment a header spelling with a ligature pair becomes load-bearing, a NUL in it
matches nothing and the column silently loses its role. It wants its own ruling; I have
not touched it. (It is also visible in the fire log, which `grep` reports as a binary
file for exactly this reason — use `grep -a`, or `tr -d "\000"`.)

### 6b. `customer_col` reaches the vision model only through the schema description

`GridColumnRoles.customer_col` is a new field on the vision call's return type, and the
model learns what it means **only** from the BAML field description. The prompt prose in
`prompts/sustainment_grid_columns_instructions.md` was deliberately **not** changed, so
this fire measures whether a schema description alone is enough instruction for a new
column role. That is a cheap experiment with a real answer either way, and the answer is
in the fire numbers above: if the vision path finds no customer column where tier 1
does, the prose is the knob.

### 6c. `customer_mpn` is NOT checked by the dropped-character detector, on purpose

`text_layer_health.uncorroborated_parts` flags a part value whose characters the text
layer dropped. I left `customer_mpn` out of it and recorded why at the source
(`doc_tools/utils/text_layer_health.py`): every finding that function returns sets
`needs_review` at its call site, and a needs-review notice earns a corpus-gate exemption
that does not lapse. Checking an **advisory** field there would hand it the one path into
the gate's exemption state that this ruling explicitly closed. The cost is real and named:
a dropped ligature inside a customer id is not flagged. It is empty today — the one notice
with both a damaged text layer and a declared customer column prints ids that are digits
and a dash, so there is no ligature pair to lose — and it will not stay empty for ever.
The fix when a case arrives is a separate advisory finding that does not touch
`needs_review`, not a third entry in that tuple.

### 6d. The after arm found a defect in my own work: a third projection boundary

The first after fire scored parts **512 / 512 with zero spurious and zero missing**, and
customer aliases **0 / 21**. The veto had worked (TYC 26 -> 16) and the capture had not,
which is a contradictory-looking pair, because both are decided by the same header cells.

The probe (`scratchpad/harness/tyc_customer_probe.py`, model-free, tier-1 only) read the
real TYC header and printed `customer_columns = [3, None]` and `grid_outcome: parts=16
with_customer=8`. So the header was read correctly, the column was found, and the cells
were captured -- and then dropped. The drop is in `_parts_from_page`, which is a
**projection, not a pass-through**: it names each field of the row it builds from
`grid_outcome`, and I had added `customer_mpn` to `grid_outcome` and not to it. No error,
no missing-key warning, no failing fixture test (the fixtures exercise `grid_outcome`
directly, which is the layer that was right).

Worth naming as a shape, because it is the third such boundary on this one field: the
grid row, the page projection, and the plugin's shape-to-vision-dict. A field has to be
named at all three or it is captured and discarded, and the evidence pattern -- a veto
working while the capture it shares a header with does not -- points at the header code,
which is the one place that was fine. There is now a comment at that projection saying so.

The fix also carries the customer **cell bbox** through the same three hops, so a
text-layer customer value gets `match_method: "text_layer_cell"` like its affected and
replacement siblings rather than falling to a string search. All 8 TYC cells carry one.
The 8 cells hold the 10 ground-truth ids -- two of them are two-id cells, which is why
the scorer splits cells and the extractor does not.

Re-fired on all ten after the fix: customer aliases **10 / 21**, TYC **10 / 10**, parts
unchanged at 512 / 512 clean. The numbers in §5 are the re-fire.

---

## 7. Suite

From PowerShell, per the repo rule:

```
1 failed, 2337 passed, 13 skipped, 16 deselected, 1 xfailed in 169.06s
FAILED tests/test_overlay_kind_drift.py::test_the_shared_kinds_declare_the_same_passes
```

The one failure is the **pre-existing, unrelated** overlay drift seal naming
`doors-export`. This diff touches no `passes` declaration, and the failure is the
known one: that seal reads the sibling **working tree**, which is 149 commits behind,
so the red is an artefact of the local checkout rather than a real divergence. It is
what PR #181 replaces with a pinned read, and platform #120 -- the fix for the `course`
drift that seal was hiding -- is now on platform master, so that pin bump is unblocked
and is the next thing this lane does.

The new `tests/test_customer_alias_column.py` passes 21 of 21.

---

## 8. Still owed to this lane, unchanged by this report

- The TI `mfr` comparator ruling (PR #189, `7f/ti-mfr-comparator-finding` at `a66f3eb`).
- The gate's written arm vs `mfr_agreement` contradiction on the same trio — two
  modules disagree and the TI red is unsatisfiable until one of them is ruled.
- #167's Neo4j migration dry run as a pod Job; #181's pin bump once platform #120 is on
  master; the registry `branch`/`refresh` plumbing from ADR-0063 §1.

**New, from the 2026-10-29 SDK adoption packet (item 2):** doc-tools pins SDK
**v0.9.11** and registers its kinds through `ContentKindRegistration`, taking kinds
adoption 0 -> 1, measured by ca's census seal in invincible-agent. Not started and not
in this PR. Two things this lane will check before claiming it, both read from state
rather than from a packet: that v0.9.11 is actually tagged, and that
`ContentKindRegistration` exists in it with a shape our kinds can be expressed in -- the
SDK's event branch is already a case where a declared shape could not be projected onto
our dataclass (ADR-0063 §1). The standing hold also still applies: `xml` stays out of
`ingestable_kinds()` until a user-drop sensor actually processes a bare xml drop, so a
registration must not be read as making that kind ingestable.
