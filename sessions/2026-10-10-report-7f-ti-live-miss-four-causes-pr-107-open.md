# Report — 7f — TI PCN#20210316000.1 live miss: four causes, PR #107 open

2026-10-10. Lane 7f (doc-tools). Order: the four-item TI live-miss order, items 1–4.

## Verdict

All four items closed. PR #107 open, based on `main` at `9649538` (so CI runs —
not stacked). Fix lands on the pin after, per the order.

Measured on the **real PDFs** with working-tree code, not on the fixtures:

| notice | before | after |
|---|---|---|
| TI PCN#20210316000.1 | 1 part, a date; 0 of 9 devices | 9/9 exact, 0 missing, 0 spurious, bait absent |
| TYC-PCN-24-210412 | 26/26 | 26/26 exact, 0 missing, 0 spurious |

Local suite 1503 passed, 16 skipped, 7 deselected, 0 failed.

## Item 1 — the fixture, written first

`tests/test_ti_pcn_live_miss.py`, built from the real artifacts pulled in-pod: the
embedded grids are what pdfplumber returns for page 3 (a 27×30 form, a 2×6 die-coat
pair, a 3×4 device grid), and the element surface is `text.json`'s. It reproduced
the live outcome exactly before any fix: 9 failed, 11 passed, with
`['Jun 22, 2021'] != ['TPS54340DDA'...]` and
`(None, 'no-title-evidence', ['Attachment: 1', ...])`.

It carries a **fidelity guard** that passes independently of the fix: if someone
tidies the sparse form and the label/value row split disappears, the miss stops
reproducing and the outcome tests would pass for the wrong reason.

## Item 2 — the MPN validator

`looks_like_mpn` asked only for ≤48 chars, ≤2 spaces and a digit. `"Jun 22, 2021"`
is 12 chars with **exactly two** spaces — the allowance that exists for ids like
`S1613E-20.0000 (T)` — so it passed, and `_is_prose_cell` (≥3 spaces, ≥30 chars) is
too coarse for a short date. Dates and form labels (trailing `:`) now reject.

The date test is `ltb_candidates.is_entirely_a_date`, reusing the one date parser in
the tree, so the parts validator and the LTB pass cannot disagree about what a date
is. Zero false positives across all 15 real corpus MPNs, `090-44310-31` included.

A latent defect in that shared parser, fixed alongside: `_DMY_NAME_RE` and
`_MDY_NAME_RE` used `,?\s+`, requiring whitespace *after* the comma, so
`"Jun 22,2021"` parsed as no date at all. A date the parser cannot see is a date the
validator cannot reject. `"22-06-2021"` stays out of scope — all-numeric DMY is
genuinely ambiguous with `090-44310-31`-shaped part numbers, and no corpus notice
prints it.

## Item 3 — the parts-table locator

pdfplumber puts the caption `"Product Affected:"` at r25c1 of the **form**, a
different table from the 3×4 device grid, so nothing connected the two. A parts
label elsewhere on the page now names a grid, as a fourth evidence source below the
caption. The bare grid alone **still declines**, correctly: it is byte-for-byte the
shape of a continuation row, which is pinned to decline. The missing piece was never
a grid-intrinsic rule, it was the connection.

Header-region cells are now never a parts source: a headerless grid with 3+
`Label:` cells and no parts caption declines outright with its own visible reason,
ahead of inheritance.

**TYC half, measured.** TYC's parts table has a real column header, so the new rule
never applies to it — 26/26 unchanged. Two of its empty tables now decline with the
clearer "form region" reason, at zero recall cost (both had `n_rows=0`).

## Item 4 — the classifier

`titles_from_elements` takes only `type == "Title"`; TI's four Titles are all section
headings and its headline is typed `NarrativeText`. `doc_type_from_titles`
classifies that headline correctly the moment it is offered, so the fix is the
**input**, not the logic: a new `headline_candidates` supplies it, bounded to 160
chars and restricted to text before the first Title.

Both bounds exist to defeat a measured hazard: page 1's prose
`"This notice does not change the end-of-life status of any product..."` contains
`end-of-life`, a `_PDN_TERMS` entry, and refers to a *previous* notice. TI's real
headline is 91 chars.

`titles_from_elements` keeps its narrow meaning, pinned by a test, rather than being
widened into a name that lies. `scripts/pcn_header_agreement.py` switches to the same
function, so the agreement measurement and the plugin cannot classify from different
surfaces.

## Two findings from reviewing the implementation, both now pinned

**The label must name the nearest table BELOW it, not every table after it.** The
first implementation marked any table following a label. Measured on this very page:
the label bottoms at y=464 and the die-coat table's top is y=309 — *above* it — so a
page-order rule marks the die-coat table too. It yields nothing only because `"NONE"`
and `"POLYIMIDE"` carry no digits; a spec or revision grid in that position emits
four fabricated parts, demonstrated and then pinned. Geometry is load-bearing, so the
fixture carries the real measured bboxes; with placeholders the test falls back to
page order and passes for the wrong reason.

**A label is bounded to 48 chars and 4 spaces.** Page 3 prints
`"...for the devices listed in "Product Affected" section."` in a form cell. It
contains the phrase verbatim and names no table — it *refers* to the section.
Unbounded, that sentence anchors a parts label and the locator names whatever grid
follows it. This was live on TI before the bound.

Bare words are matched **whole-cell only**, which is how the order's literal
`"Devices"` is honoured without the substring hazard: a cell reading `"Devices"`
above a list names the list, while TI's form is captioned `"Die Coating addition for
Select Devices"`, so a substring rule classifies the notice's own form as its parts
table.

## NOT fixed — reported

**TI page 2 is excluded by accident, not by rule.** `find_tables` returns **zero**
tables for page 2, so the DEVICES-ONLY ruling holds for a reason unrelated to the
ruling. A change in table detection, or a vision pass reading that page, could admit
11 customer part numbers without any rule changing. Not fixed because the general
question — whether a Customer Part Number column is a parts source — is formally
deferred (TYC yes, TI no by ruling), and this is now its second instance.

**Now GUARDED, by order, in the same branch** — see the section below.

## The page-2 guard (ordered after the above, landed on this branch)

**Why no global rule, measured.** 10 of TYC's 26 ground-truth parts come from a
column headed `Customer Part Number`: 16 from `Part Number`, 10 from that one.
`"a customer part number is never an affected part"` would take TYC from 26/26 to
**16/26**. The deferral was correct and the two notices genuinely use that column
to mean different things.

**What page 2 would do if detected, measured.** Its grid has a real column header,
so `grid_outcome` accepts it on its own merits and pairs *both* columns as affected
(`device` and `part number` are both in `AFFECTED_HEADERS`). It yields **19
distinct parts: 8 real devices + all 11 customer part numbers**, and declines
nothing. There is no rule to point at.

**So the ruling is landed as an enumeration, not a rule.** Ground truth gains
`expect_absent_mpns` for TI — the 11 strings verbatim, with `_expect_absent_why`
recording both the accident and the TYC measurement. The parts-side analogue of
#105's header `expect_absent`.

`score_notice` gains `ruled_out`, a **labelled subset** of `spurious`: the part
stays counted in `spurious`, so `main`'s verdict (`not t["spurious"]`) cannot be
weakened by anything added here, and a test pins exactly that. Its only job is to
make a known failure legible — the ruling named, rather than 11 anonymous strings.
Requiring and ruling out the same part now aborts as a ground-truth defect.

The guard is a **subset** assertion by design, so it never inverts: everything page
2 can contribute is either one of the nine devices or one of the eleven ruled out —
true today, still true if the ruling is ever implemented. What it rejects is a
string on neither list, which is the case nothing else would catch before a fire.

**Mutation-checked both ways.** Dropping one part from the enumeration fails 4 tests
naming it; making `looks_like_mpn` digitless fails the guard on `'null'`.

One test is **meant** to invert: `test_nothing_in_the_extractor_declines_page_twos_grid`
asserts no rule exists today. Its going red is the signal that one now does, and it
says to update the ground-truth prose and delete it rather than loosen the guard.

Suite 1515 passed, 16 skipped, 7 deselected.

**TI's text layer is degraded**: `text_layer_retention=0.1075` against a 0.35
threshold, worst bigram `tt` at 2/18.6 observed/expected. A second TYC-like case.

**The bait reached a reviewer unflagged**: `needs_review=False`,
`review_reason=None`, `match_confidence=1.0`, `parts_uncorroborated=0`. A date was
presented as a certain answer.

## Still needing the user

- Narrow the broad `needs_review` disagreement exemption (`57f1806` is not on main).
- **Rotate `PCN_GATE_PUBLISH_TOKEN`** (len=93, printed into a transcript by my own
  drift script; a transcript is not editable).
- **Rotate the sandbox Fuseki `ADMIN_PASSWORD`** on `iagent-fuseki-0`, printed by my
  own `grep -i fuseki` over env output.
- Decide on the `node_id` empty-default fallback.

## Tomorrow's sequence, unchanged

Nightly 07:00Z on `c8dce84a` → pin `image.digest` **and** `corpusGate.expectImage`
to `sha256:d16b44021549cb0d109c512aaa17a31404a533f4515a8fbf5103aa62f6b1db19` → roll
(plain `helm upgrade`, three `-f` files) → read `imageID` off the pods (arch child,
not the index digest) → gate three fires with `--out-dir` → commit the report.

The ordered one-line disclaimer goes beside the corpus block: the nightly measured
898 by the old enumeration, now 898/924 by ordering, so nobody reads it as a
regression.

No pin or roll before the nightly — tonight's nightly measures exactly the image
that passed 3/3. #107 lands on the pin after.

## Day-1 item 3 (`extraction_defect` consumer) is BLOCKED on Lane 1

Lane 1's packet `2026-10-10-packet-to-7f-and-74-...retry-cannot-reach-it.md` was
**superseded the same night** by the steward-correction ruling, and that ruling is
what defines the record this lane is to consume:

> Every correction files an `extraction_defect` record {notice, pin digest,
> extracted, corrected, evidence} to the admin/7f queue.

`extraction_defect` appears **nowhere in doc-tools and nowhere in iagent code** —
only in that packet. Lane 1 owes the PR. Nothing is built against the shape until
it lands; guessing the schema would produce a consumer that passes its own tests
and reads nothing real.

The TI live miss is the first candidate record and its five fields are already
known, so the consumer has a ready first fixture the day the schema arrives:
notice `TI_PCN_20210316000.pdf`, pin `c8dce84a`, extracted `"Jun 22, 2021"`,
corrected the nine devices, evidence page 3 `Product Affected` table.

(The packet is now committed here, as the convention requires of a placed packet.
A large backlog of untracked `sessions/` files from September remains; not swept
unilaterally.)
