to: doc-tools/lane/gov, cc architect
from: doc-tools/lane/7f, 2026-10-29
re: LlamaIndex's Document Parsing Protocol, tabled against what the ten-notice
    corpus already measures — plus its two example PDFs run as a side corpus

**No contract in this tree binds to DPP.** Nothing here is a code change, a schema
change or a gate change. The one edit this report carries is a citation block in
`docs/contracts/batch-column-map.md` §12, labelled as external corroboration.

> Rules and rule ids quoted here are from *Document Parsing Protocol, LlamaIndex*,
> CC BY 4.0 (<https://creativecommons.org/licenses/by/4.0/>), repo
> `run-llama/document_parsing_protocol` at commit `a9c49e2` (2026-10-27). Quotations
> are verbatim; the agree/differ verdicts and all measurements are ours.

---

## 0. What DPP actually is, and where it does not reach us

Working draft 0.1. Measured from the tree, not from the announcement: 161 markdown
pages under `protocol/`, of which **138 carry `status: rule`**, 2 carry
`status: either` (two conforming renderings, pick one per document) and 1 is an
explicit open point. 138 + 2 = **140**, which is the figure the launch post gives.
Thirteen numbered sections plus three appendices.

**The first thing to say is a scope fact, because it governs two thirds of the
table below.** DPP specifies a *representation*: one Markdown document per
document, pages separated by `---`, HTML where Markdown has no syntax, optionally a
sidecar of elements with boxes. Our pipeline specifies an *extraction*: `PartRow[]`
of `{affected_mpn, replacement_mpn, ltb_date}` plus a fixed `NoticeHeader`. We never
emit a table at all. So a DPP rule about colspans is not something we disagree with
— it is something we have no surface for. Those entries are marked **not covered**,
and the distinction between "not covered" and "differ" is doing real work: a
*differ* is a place where both sides decide the same question and decide it
differently, and I have kept it to those.

Where the two genuinely meet is tier 1, `doc_tools/utils/table_text_layer.py`: the
deterministic text-layer pass that reads a pdfplumber grid and decides what its
columns mean. That is a parsing stage making exactly DPP's decisions, and it is
where every **agree** and every **differ** below is located.

---

## 1. Table vs aligned text

| DPP rule | our decision | verdict |
|---|---|---|
| `tables-borderless-whitespace-tables` — "A whitespace-aligned block with columns MUST be rendered as a table… and the block MUST NOT be rendered as preformatted text." | `_tables_of` calls `page.find_tables()` with **no** `table_settings`. | **DIFFER — and DPP is right** |
| `tables-is-this-even-a-table` — a region is a table "when, and only when, its rows and columns **encode a relation**" | `grid_outcome` requires a column header, an inherited pairing, or a parts caption; absent all three it declines. | **AGREE**, different mechanism |
| `tables-header-only-tables` — no orphan header row standing as a table | `find_header_row` requires **more than one** non-empty cell; a lone labelled cell is read as a caption by `find_title_row`. | **AGREE** |

**Evidence for the differ.** pdfplumber's default is `vertical_strategy: str = "lines"`
(`.venv/Lib/site-packages/pdfplumber/table.py:487`), i.e. ruling-line based. A block
aligned by whitespace alone yields nothing. This is not hypothetical for us: on
**TI PCN#20210316000.1 page 2**, `page.find_tables()` returns **zero** tables,
measured on the real PDF, and that page carries a 15-row `DEVICE | CUSTOMER PART
NUMBER` grid. Tier 1 never sees it as a table.

**And the differ cannot be closed by adopting the rule.** That notice scores 9/9
under the DEVICES-ONLY ruling *because of* the miss. Make the grid visible — the
`"text"` strategy is the knob — and `grid_outcome` accepts it (`device` and
`part number` are both in `AFFECTED_HEADERS`), pairs both columns as affected, and
emits 19 parts: 8 real devices plus all 11 customer part numbers. The guard today is
an enumeration, not a rule: TI's ground-truth entry carries `expect_absent_mpns`
and `tests/test_ti_pcn_live_miss.py` pins it. So conforming to
`tables-borderless-whitespace-tables` is **blocked behind the deferred
customer-part-column question**, which is deferred for a measured reason — TYC's
26 ground-truth parts are 16 from `Part Number` **plus 10 from `Customer Part
Number`**, so "a customer part number is never an affected part" takes TYC from
26/26 to 16/26. Two notices use that column to mean different things. DPP has no
rule that helps here, because DPP never has to decide *which* column is the subject.

**Evidence for `tables-header-only-tables`.** Ours was bought: taking the first
vocabulary match instead of the best-scoring row picked the *title* —
"Table 1 - EOL Devices with Life-time Buy Opportunity and Replacement Parts"
contains the words the vocabulary looks for — which "collapsed a three-pair table
into a single unpaired column and silently lost two thirds of a 111-part page."

---

## 2. Multi-row headers

| DPP rule | our decision | verdict |
|---|---|---|
| `tables-multi-row-header-tiers` — "Every printed header tier MUST be rendered as its own header row, with exact colspans… MUST NOT be flattened" | `find_header_row` returns **one** row index, best-scoring, `search_depth=6`. No tier model exists. | **NOT COVERED** |
| `tables-header-wrap-vs-real-tier` — a rule beneath + ≥2 self-standing leaf labels is a real tier; stacked fragments reading as one phrase are a wrapped label joined with a space | nothing in the tree distinguishes the two. | **NOT COVERED** |
| `tables-sec-period-tiers` — a financial period stack renders as its printed tiers | — | **NOT COVERED** |
| `tables-units-row` (*either*) — a units line MAY be a second header row or folded into the label, but "MUST NOT become the first body row" | a units row carries no affected/replacement vocabulary, so it never scores as our header, and `is_part_row` rejects it unless it carries an MPN-shaped cell. | **AGREE — but unsealed** |

The side corpus makes "not covered" literal rather than inferred: `find_header_row`
returned **`None` on all four pages of the Apple statements**, which are exactly the
multi-tier period stack `tables-sec-period-tiers` governs. Our header detection is
vocabulary-gated, so DPP's header rules are unreachable from our pipeline, not
disputed by it.

The `tables-units-row` agreement is worth flagging precisely because **no test
asserts it.** It holds as a consequence of two unrelated predicates. If either is
loosened it goes away silently.

---

## 3. Repeated headers

| DPP rule | our decision | verdict |
|---|---|---|
| `tables-repeated-headers-and-title-bands` — "a column-header row printed again after data rows MUST close the table and open a new one at the repeat. Header repetition is the table-boundary signal." | `find_header_row(search_depth=6)` looks only at the first six rows. One header per grid; no mid-grid boundary exists. | **DIFFER** |
| `tables-split-tables-sharing-a-header` — fragments sharing a header printed once MUST be **one** table; "The missing header is the proof that the second fragment was never meant to stand alone." | `InheritedHeader`: carry the last declared pairing forward. | **AGREE — independently arrived at** |
| `tables-cross-page-tables` — fragments "MUST NOT be joined"; one per page, each with two continuation flags | we join across pages by inheriting the pairing. | **DIFFER — deliberately** |
| `tables-horizontal-slicing`, `tables-column-continuation` — one table per printed block; but "A checker MUST accept source-supported joined equivalents without losing or reassigning records." | `pair_columns` reads `EOL \| Replacement \| EOL \| Replacement \| EOL \| Replacement` as three pairs of one table. | **AGREE under DPP's own acceptance clause** |
| `tables-duplicated-tables`, `tables-continued-in-the-title` — every printed occurrence is its own table; the continuation marker stays verbatim in the title | `_caption_label`: "a caption that numbers its table is the document stating which table this is; two numbers that differ are two tables." | **AGREE** |

**The repeated-header differ costs no part today, and I want to be exact about
why.** A re-printed header deep in a grid is treated as a data row and then
rejected — it carries no digit, so `looks_like_mpn` refuses it. What is lost is the
*boundary*, not the rows. And we have met this case: `split_composite_cell` guards
each fragment with `not _is_affected(f) and not _is_replacement(f)`, with the
comment "a repeated column header is not a part". So we encountered header
repetition and handled it as a **contaminant to filter**, where DPP reads it as a
**signal to segment**. DPP's reading is the stronger one; ours is sufficient for an
output that has no table boundaries in it.

**The cross-page differ is the one I would defend unchanged.** Per-page isolation
is precisely the defect `docs/handoff-pdn-continuation-table-pairing.md` records:
"A parts table that spans pages loses its header on every page after the first, and
`parts_from_grid` then assumes **every column is an affected part** — so on an
`EOL | Replacement | EOL | Replacement | EOL | Replacement` table, all three
replacement columns are emitted as discontinued parts." DPP can require fragments
to stay separate because its output keeps the printed header on page 1 and flags
the continuation; our output has nowhere to put a flag — an unpaired column *is* a
wrong answer.

What is worth noting is that our two guards are DPP-shaped without having been
copied from it. `width` (column count) and `label` (the caption's table number) are
both "the document said so" tests. The `label` guard was bought the expensive way:
**Diodes PCN 2683 pages 3, 4 and 5 are three different tables that share a column
count**, and inheriting page 3's `EOL | Replacement` pairing onto pages 4 and 5
"turns 144 genuine EOL devices into replacements and drops them from the affected
list." That is the same proposition as `tables-duplicated-tables` arriving from the
other direction.

---

## 4. Merged cells

| DPP rule | our decision | verdict |
|---|---|---|
| `tables-record-groups-and-multi-line-cells` — "lines that pair up one-to-one MUST be separate rows, and a list whose neighbours print a single value for the whole list MUST stay in one cell, `<br/>`-joined, beside that value" | `split_composite_cell` + its call site: positional pairing *i↔i* **only** when both cells are composite and the counts match; otherwise every fragment gets the whole un-split neighbour. | **AGREE on both halves** |
| `tables-repeated-identical-values` — a value printed *k* times at *k* positions MUST be *k* cells; "repeated content MUST NOT be merged" | per-cell extraction, no dedup. | **AGREE — measured** |
| `tables-header-body-column-count-mismatch` — pad the short side with empty cells, "MUST NOT be padded with a duplicated or invented value" | we **decline**. | **NOT COVERED — and a gap in DPP** |
| `tables-nested-tables` — subdivide; no nested `<table>` | no surface. | **NOT COVERED** |

The agreement on `tables-record-groups-and-multi-line-cells` is substantive, not
coincidental. Our call-site comment reads: "Positional pairing (fragment i <->
fragment i) is the only reading the page supports when both counts match; anything
else — counts differ, or the replacement isn't composite at all — has no positional
correspondence the page states, so every fragment gets the whole un-split
replacement value instead of a guessed pairing." That is DPP's two clauses, derived
from the never-invent principle, in our vocabulary. Three notices' worth of
composite cells (`TYC-PCN-24-210412.pdf`) produced it.

`tables-repeated-identical-values` is the one DPP rule the launch post proposes as a
concrete test, and we pass it: on Apple page 1 the value **`6,485` is printed in two
cells and our extraction yields two cells**, unmerged.

**The gap.** `tables-header-body-column-count-mismatch` addresses a *count*
mismatch. Our measured failure is a *header offset*:
`onsemi_Generic_IPCN25300X.pdf` p3 prints the header `Part Number` at column 1 while
its 17 MPNs sit at column 0 — and columns 0 and 2 both hold 17 MPN-like values, so
"a one-column shift is equally likely to emit the Qualification Vehicle column as
affected parts." Padding cannot help; the counts agree. We decline. **DPP has no
rule for a header label sitting over the wrong column**, and it will need one,
because that is not a rare defect — it was one of three "silent zero" causes we
found across nine notices.

---

## 5. Forms

| DPP rule | our decision | verdict |
|---|---|---|
| `forms-forms-and-key-value-regions`, `forms-the-key-value-list` — a key-value region MUST be rendered as a key-value list | `_is_form_region` detects the notice's header block **in order to exclude it**: "It is the notice's header/form region and is never a parts source." The fields are read separately by `ExtractHeader` against a fixed `NoticeHeader` schema. | **DIFFER in locus — and a real drop** |
| `forms-values-are-verbatim` | our MPN and header contracts are verbatim; `affected_mpn_source` is "VERBATIM and unnormalized… character-for-character". | **AGREE — and we go further** |
| `forms-checkboxes` (`[x]` / `[ ]`), `forms-fill-ins`, `forms-blanks-inside-sentences` (`[blank]`) | nothing in the tree reads a checkbox or distinguishes an empty field from a missed one. | **NOT COVERED** |
| `forms-ids-and-labels` — a field's printed id | `looks_like_mpn` accepts a bare field id as part-shaped (48 such cells on the 1040). | **NOT COVERED — see §6** |

**The drop is genuine under `principles-never-drop-never-invent`.** A field printed
in the notice's form region that `NoticeHeader` does not name — a qualification
vehicle, a contact, a sample-availability date — is emitted nowhere. For a field
extractor that is by design; stated against DPP it is a drop, and it is the honest
entry in this table.

**Where we are ahead of the draft.** `forms-values-are-verbatim` and
`principles-the-page-is-the-ground-truth` ("text transcribed verbatim — typos
included") have **no rule for two correct readings of one field**. Our ground truth
does: all five `_rule` blocks in `scripts/pcn_ground_truth.json` define an
ACCEPTED-VERBATIM SET where "`value` stays the CANONICAL form; every non-underscore
key here is a verbatim-correct reading of THIS notice, and comparison is
canonical-after-alias". We ruled that on 2026-10-09 after the alternative cost us a
real measurement: "a raw-string compare against `value` is the wrong comparator for
a verbatim field, and it is what made the witness supplier score 0/3 with every
answer correct: the witness read the logo, the text layer read its own damaged
heading, and the comparator called two correct readings a disagreement." TI prints
its manufacturer twice on one page — `Texas Instruments Incorporated` in the footer
band and `TEXAS INSTRUMENTS` as the logo wordmark. Both are verbatim-correct. A
protocol that says "verbatim" and stops cannot say which, and a conformance checker
built on it will score a correct parse wrong. **This is the single most useful thing
we could send upstream.**

---

## 6. The side corpus: DPP's example pages through our extractor

**What was runnable.** The repo ships 548 example PNGs and **two PDFs**. Our tier 1
needs a text layer, so the side corpus is those two: Apple's FY2024 Q4 condensed
statements (4 pages) and IRS Form 1040 (2020) (2 pages). The 546 PNG pages would
exercise only the vision pass, which is the tier DPP's *table* rules reach least.
Harness at `scratchpad/harness/dpp_side_corpus.py` (pdfplumber + the pure grid
functions; no GPU, no MinIO, no model), logs at `scratchpad/dpp_side.log` and
`scratchpad/dpp_mpn_shaped.log`.

**Neither PDF is in this tree and neither should be.** The Apple statements are
third-party copyright, "do not redistribute them as part of this project" (their
`NOTICE`); the 1040 is US federal public domain. Reproduce by cloning the DPP repo
at `a9c49e2`.

### The headline: 11 of 11 grids declined, **0 parts emitted**

| | Apple FY24 Q4 | IRS 1040 (2020) |
|---|---|---|
| pages | 4 | 2 |
| grids `find_tables()` returned | 4 | 7 |
| `find_header_row` non-null | **0** | **0** |
| `find_title_row` non-null | 0 | 0 |
| `_is_form_region` true | **3** (pp. 1–3) | **0** |
| grids declined | 4 | 7 |
| **parts emitted** | **0** | **0** |

Every decline carried a reason. Pages 1–3 of Apple: "form region: no column header,
no parts caption, and 3+ form-label cells". Everything else: "no column header,
nothing to inherit, and no caption naming the contents". **The refusal path holds on
two wholly out-of-domain documents** — no fabricated part, no silent zero.

### Miss 1 — the decline is the *only* thing holding, and now it is quantified

`looks_like_mpn` accepts **255 cells** of the Apple statements and **48** of the
1040. `is_part_row` passes **56** Apple rows and **42** 1040 rows. The accepted
Apple cells are dollar amounts — `'$ 69,958'`, `'391,035'`, `'6,485'`; the accepted
1040 cells are IRS **line numbers** — `'1'`, `'2b'`, `'10c'`.

So: one header cell anywhere in Apple's statements matching our AFFECTED vocabulary
and we would have emitted up to 56 rows of dollar amounts as discontinued part
numbers. Nothing about the *values* stops it — the plausibility floor waves all 255
through. This is a measured, numeric restatement of the standing rule in
`docs/pcn-corpus-validation-2026-09-21.md` §4: **do not "fix" tier-1's zero-part
notices by loosening the decline rule.** The safety is entirely in the column
decision, not in the value filter.

### Miss 2 — a real defect in `looks_like_mpn`: the space budget is blind to `\n`

`looks_like_mpn` rejects on `v.count(" ") > _MAX_MPN_SPACES` (2). It counts the
ASCII space only. So the 1040 cell

```
'(2) Social security\nnumber'
```

— 27 characters, **two** spaces, carries a digit, does not end in `:`, is not a date
— **passes the floor**, and `_is_prose_cell` also lets it through (2 spaces < 3, 27
chars < 30), so `is_part_row` calls its row a part row. Confirmed in the run output,
not inferred.

This is not an out-of-domain curiosity. Multi-line cells are routine in our corpus —
`split_composite_cell` exists for them, and it only splits on comma+newline, so a
newline-joined cell with no comma stays glued and keeps the whole budget. A fix is
one character of intent: count all whitespace (`sum(ch.isspace() for ch in v)`), or
normalise the cell before measuring. It fails toward *not* emitting, which is the
recoverable direction, so this is a tightening with no recall risk. **Not changed in
this report** — it is a change to the predicate the corpus score is computed with,
and that goes through a fire, not a drive-by.

### Miss 3 — `_is_form_region` is notice-shaped, in both directions

It fired **true** on Apple's financial statements pages 1–3 (false positive: ≥3 cells
ending in `:`, no column header) and **false** on all seven grids of the archetypal
government form (false negative: the 1040 labels its fields with numbered captions,
not trailing colons). Its test is `len(v) > 1 and v.endswith(":")`.

Neither costs a part today, because both land in a decline either way — the Apple
pages decline *as* a form region and the 1040 grids decline for want of a header. But
the predicate is named for a general thing and measures a particular one, and §5's
"never a parts source" claim rests on it. Worth knowing before anyone reuses it for a
non-PCN kind.

### Miss 4 — verbatim fidelity passes the test DPP proposes

Not a miss; recorded because it is the one check the launch post asks for. On Apple
page 1 our cell extraction preserves `(565)` **with its parentheses, in both cells
that print it**, and `6,485` **as two separate cells**. That is
`tables-accounting-number-formats` and `tables-repeated-identical-values` satisfied,
measured rather than asserted.

---

## 7. One narrow place we normalise where DPP forbids it

`tables-accounting-number-formats`: "The output MUST NOT carry a normalised twin of
the value beside it, and MUST NOT replace the printed form with a normalised one."

`strip_enclosing_quotes` removes a **balanced enclosing** quote pair from a part
value. Our argument is in the code: "The quote is a DELIMITER around the part
number, never a character of it, so removing a balanced enclosing pair is not
normalization: it is reading the delimiter as a delimiter." The cost of not doing it
is concrete — a notice that prints part numbers in quotes plus a faithful extractor
produce `'"090-44310-31"'`, "a string that matches nothing downstream."

**DPP would call this non-conforming, and under its own terms it is right.** I am
recording it as a known, bounded, documented divergence rather than proposing we
change it: our MPN is a join key, not a transcription, and 14 measured instances on
`TYC-PCN-24-210412.pdf` were all quote-wrapped.

---

## 8. Traceability — agree, and a gap worth sending back

`principles-traceability`: "every Markdown element MUST have a box, and every box
MUST cover exactly the printed content of its element."

We agree and we are sealed to it: pdfplumber yields a bbox **per cell**, so an MPN
carries exact coordinates, emitted "in PDF POINTS together with the page's point
dimensions, so the sealed bbox-scale rule (fraction = bbox / page_dims) is
unit-agnostic". `EvidenceRef` became `{page, bbox, note?}` on 2026-10-28.

**The gap: DPP never names a coordinate space.** Ours cost us a defect — IDT row
bboxes are in image-pixel space while TI's are in PDF points, and the only thing
that makes a fraction comparable across them is carrying the page dimensions
alongside. A sidecar that lists boxes without declaring their space is one producer
change away from the same bug.

---

## 9. Verdict tally

Counting only the rules that bear on the five dimensions asked about, plus the four
principles:

- **AGREE — 11.** `tables-is-this-even-a-table`, `tables-header-only-tables`,
  `tables-units-row` (unsealed), `tables-split-tables-sharing-a-header`,
  `tables-column-continuation` (via its acceptance clause),
  `tables-duplicated-tables`, `tables-continued-in-the-title`,
  `tables-record-groups-and-multi-line-cells`, `tables-repeated-identical-values`,
  `forms-values-are-verbatim`, `principles-traceability`.
- **DIFFER — 5.** `tables-borderless-whitespace-tables` (we miss it; DPP is right,
  and we cannot adopt it until the customer-part-column question is settled),
  `tables-repeated-headers-and-title-bands` (boundary invisible to us; costs no
  part), `tables-cross-page-tables` (we join, deliberately, and I would keep it),
  `forms-forms-and-key-value-regions` (a real drop),
  `tables-accounting-number-formats` (one narrow case: enclosing quotes).
- **NOT COVERED — 7**, all because we emit no table:
  `tables-multi-row-header-tiers`, `tables-header-wrap-vs-real-tier`,
  `tables-sec-period-tiers`, `tables-nested-tables`,
  `tables-header-body-column-count-mismatch` (and DPP has no rule for the
  misalignment we actually hit), `forms-checkboxes` and its two siblings,
  `forms-ids-and-labels`.
- `principles-never-drop-never-invent` splits: **never-invent is the principle our
  whole decline apparatus implements**; never-drop we fail by design, being a field
  extractor.

**Three things worth sending upstream**, if anyone is corresponding with the draft:
a rule for **two verbatim-correct readings of one field** (§5), a rule for a
**header label offset from its data column** (§4), and a **declared coordinate
space** for sidecar boxes (§8). All three are places where our corpus paid for the
knowledge and the draft is currently silent.

---

## 10. What was edited, and what was not

**Edited:** `docs/contracts/batch-column-map.md` gains a **§12**, citing the
agreeing rules as external corroboration, with the CC BY attribution and an explicit
"nothing in this contract binds to DPP". That is the whole of the citation work the
order asked for.

**Deliberately not edited:**

1. `looks_like_mpn`'s whitespace budget (§6 miss 2) — a one-line tightening to the
   predicate the corpus score is computed with. It needs a fire, not a drive-by.
2. `page.find_tables()`'s strategy (§1) — blocked behind the deferred
   customer-part-column question, and changing it would admit 11 spurious parts on TI
   with no ruling having changed.
3. `_is_form_region` (§6 miss 3) — the false positive and false negative both land in
   a decline today. Tightening it on out-of-domain evidence would be tuning against a
   corpus of two.

— lane 7f

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
