# Is the crop-bottom clipping systemic? — corpus survey, 2026-09-24

Prerequisite measurement for the crop-geometry fix, run before that fix is
written. The question set on 2026-09-23 was: *"for every Table element,
unstructured bottom minus pdfplumber bottom. If it's short on more than this one
table, the corpus has been silently losing last rows everywhere, and the fix's
seal should cover the worst case found."*

Read-only, against the same nine notices and the same manifests the
`dc12ef3` run used. Pod `doc-tools-686b97448-7sq8z`.

## Answer

**Yes, it is systemic — and no, the corpus has not been losing rows.**

Those are two different findings and the distinction is the point.

- **9 tables across 5 of the 9 notices have a bottom edge that cuts through
  glyphs.** `PCN23-002` is not special. The worst cut in the corpus is *worse*
  than `SYTX9`: `Diodes` page 5 keeps **32%** of `WC21400001`, against `SYTX9`'s
  53%.
- **Not one whole row is lost.** In every cut case the words below the cut line
  are zero. The defect is a horizontal slice through the last row's glyphs, not
  a missing row.

## What was cut

Nine tables, every cut cell a real ground-truth MPN:

| notice | pg | cells cut | worst kept | worst cell |
|---|---:|---:|---:|---|
| Diodes_PCN_2683_Rev1_EOL | 5 | 5 | **32%** | `WC21400001` |
| Diodes_PCN_2683_FULLGREEN | 5 | 5 | **32%** | `WC21400001` |
| PCN23-002 | 2 | 1 | **53%** | `SYTX9-122HP-1+` |
| Diodes_PCN_2683_Rev1_EOL | 2 | 1 | 64% | `DISCLAIMER` (prose) |
| Diodes_PCN_2683_FULLGREEN | 2 | 1 | 64% | `DISCLAIMER` (prose) |
| onsemi_Generic_IPCN25300X | 3 | 3 | 84% | `NSR02F30NXT5G` |
| Diodes_PCN_2683_Rev1_EOL | 2 | 1 | 94% | `TITLE` (prose) |
| Diodes_PCN_2683_FULLGREEN | 2 | 1 | 94% | `TITLE` (prose) |
| TYC-PCN-24-210412 | 1 | 3 | 99% | `1063681-1` |

`WC21400001`, `WL251GF0044.000000`, `NSR02F30NXT5G`, `SNSR01F30NXT5G` and
`1063681-1` are all in `scripts/pcn_ground_truth.json`, verified.

## The part that should be uncomfortable

**Eight of those nine were read correctly anyway.** Diodes scored 402/402 and
IPCN25300X 19/19 in the same run where `SYTX9` flipped to `SYTYD`. A cell with
**32% of its glyph height** reached the model and came back right.

So the geometry defect has been present in five notices the whole time, and it
has cost exactly one part — so far. The corpus has not been passing because the
crops are correct. It has been passing because the model usually guesses
through the damage. That is a latent defect with a stochastic trigger, which is
the kind that looks fine in every report until it doesn't.

It also sets the honest expectation for the fix: repairing the geometry will
change **one** part number in the corpus score. Its value is that it removes a
source of failure that is currently invisible, not that it moves the number.

## The specified fix does not survive the measurement

The 2026-09-23 ruling was: *"The crop should be the union of unstructured's
bbox and pdfplumber's when both exist, clamped to the page."* Measured, that
union costs:

```
max union extension      337.5 pt        <- half a page
max row extension          8.3 pt
```

pdfplumber's `find_tables()` does not return the table a human sees. On the
onsemi and Diodes notices — form-like pages with ruling lines throughout — it
returns bboxes that swallow body prose, in one case **554.9pt** of it. Union
with that bbox does not recover a clipped row; it inflates the crop to most of
the page, drags in `Description and Purpose:` and `DISCLAIMER Unless…`, and
spends the vision budget that `crops_near_cap` exists to watch.

### Bounded variant, same source of truth

Extend the bottom to **the last pdfplumber *row* that starts inside
unstructured's box**, rather than to pdfplumber's outer bbox. Same geometry,
same provenance — the ruling's actual intent, *use the known bottom, not a
guess* — but bounded by construction: a row that begins inside the crop can
only extend it by that row's own height.

```
                    fixes all 9 cut tables?   worst extension
row-bounded                  9 / 9                  8.3 pt
3% padding                   7 / 9                 17.3 pt
union with bbox              9 / 9                337.5 pt
```

Percent padding is both weaker and more expensive: it misses two cases while
extending further than the row-bounded rule on five. It stays only as the
fallback for pages where pdfplumber finds no table at all.

## Seal for the fix

The ruling said the seal should cover the worst case found, not just
PCN23-002. The worst case found is Diodes page 5 at 32%, so:

1. `PCN23-002` reaches 18/18 exact with `SYTX9-122HP-1+` verbatim.
2. `Diodes_PCN_2683_Rev1_EOL` page 5 crop fully contains `WC21400001` and
   `WL251GF0044.000000` — asserted on geometry, not on the model's output,
   since that cell already reads correctly through a 32% cut and would seal
   green with the bug still in.
3. No crop grows by more than one row height against its current bottom.
   This is the guard against the union blow-up above, and it fails loudly if
   pdfplumber's bbox ever gets used directly.

Point 2 is the important one. Sealing on model output alone would let the
regression back in, because the corpus score cannot see a cut that the model
happens to survive — the same blindness `pcn_score.py` was written to remove
one layer up.

## Method

`unstructured`'s Table bbox is converted from layout space to PDF points via
`layout_height / page.height`, matched to the pdfplumber table with the largest
overlap area, then every word in that table is classed against the cut line.
Words covered by a **sibling** Table element's crop on the same page are
excluded: unstructured routinely splits one visual table into several elements,
and a first pass that ignored this reported 924 "lost" words that were in fact
inside the next element's crop. That correction is why the delta column and the
loss column disagree so widely here — a large delta with zero loss is a split,
not a defect.

Survey scripts are scratchpad-only; the numbers above are reproducible from
`/tmp/pcn_clip_survey3.json` on the pod.

## What shipped, and what it measured on the real PDFs

The fix in this PR implements the row-bounded rule. Run against the real source
PDFs — not a fixture — with the real crop files staged, every sealed case is
covered and every extension is small:

```
PCN23-002       p2  bottom 465.9 -> 474.2 pt  (+8.3)   SYTX9-122HP-1+      COVERED
Diodes p5           bottom 682.3 -> 688.2 pt  (+5.9)   WC21400001          COVERED
                                                        WL251GF0044.000000  COVERED
Diodes p2           bottom 185.3 -> 187.9 pt  (+2.6)
Diodes p2           bottom 487.4 -> 492.8 pt  (+5.4)
IPCN25300X      p3  bottom 739.4 -> 744.5 pt  (+5.0)   NSR02F30NXT5G       COVERED
                                                        SNSR01F30NXT5G      COVERED
IPCN25300X      p1  bottom 414.7 -> 434.7 pt  (+20.0)
TYC             p1  unchanged                           1063681-1           COVERED
6 seals checked, 0 failures
```

The largest correction in the corpus is **+20.0pt**, against the **337.5pt**
the literal bbox union would have cost. The extensions reproduce the survey's
predicted `row_ext` figures exactly.

### The guard, corrected

The guard as first specified — *"reject if the extension exceeds the tallest row
involved"* — is unreachable. The row that sets the new bottom is itself one of
the rows measured, and its own height necessarily exceeds the extension, so the
test is an identity of the rule rather than a check on it. A sibling-comparison
reading is reachable but still blind in the case that matters most: a matched
table with exactly **one** candidate row, which is the lone swallowed prose
block, has no sibling to be compared against.

What shipped instead is a **filter on implausible rows** — absolute (a row over
72pt is not a table row at any font size) and relative (over 3× its siblings'
median, with a floor so a dense 8pt parts list does not reject its own header).
Filtering rather than aborting means a genuine row sharing a table with a
swallowed block still gets completed. Both limbs are tested, including the
single-row case that the sibling comparison could not see.

### The two `crops_row_short` fixes, sealed on the recorded run

Replaying the real declines against the vision counts the 2026-09-23 run
recorded:

```
IPCN25300X   old n_rows per decline [1, 0, 4, 4, 4, 2] -> fires 3   (the false positives)
             new n_rows per decline [1, 0, 0, 0, 0, 2] -> fires 0
PCN23-002    n_rows 18, vision 17                      -> fires 1   (exactly one)
             n_rows 18, vision 18 (post crop fix)      -> fires 0
```

Both mechanisms carry weight: the prose exclusion alone empties the JEDEC
tables on pages 2 and 3 (4 → 0), and the 5-row floor drops pages 1 and 4.

**The floor's cost, stated plainly:** IPCN25300X page 4 has two *genuine* part
rows (`NSR01L30NXT5G`, `NSR01F30NXT5G`). A real shortfall there would now go
unflagged. That is the deliberate trade — a detector that fires three times on
a correct notice is worse than one that stays quiet on a two-row table, because
the first teaches reviewers to ignore it.
