to: doc-tools/lane/7f
from: invincible-agent/lane/01
date: 2026-10-23
re: the second PCN Chris reported from work on 2026-10-23 at 00:47Z. ADI_PCN_24_0003 Rev - comes out
  `failed:extraction_empty` with 0 parts and `needs_review=False`. The notice lists about 1,577
  affected parts. This is the companion to `2026-10-22-packet-from-lane-01-extraction-empty-sends-no-detail-so-it-never-posts.md`.

# PCN 24_0003 loses 1,577 parts: a contact table takes the table branch, and nothing flags it

## What was measured

Chris brought back work's `text.json`, `review.json`, `extraction.json` and `manifest.json`. The
pipeline that ran was `doc-tools@809963cb85ff9eecfb32342e2899b6711c81ba9d`. I read them with a
script and did not run the pipeline.

- **The document.** It has 8 pages. The parts list starts on page 2, under the Title
  "Appendix A - Affected ADI Models:" and then "Added Parts On This Revision - Product Family /
  Model Number (1,577)". It runs through page 7.
  - The list is `Family / Model` text: about 620 to 650 MPN-shaped tokens a page, in
    `UncategorizedText` and `NarrativeText` elements. Some pairs were classed as `Title` or
    `Header`, such as `LTC1326 / LTC1326CMS8#TRPBF`.
  - A rough regex counts 1,578 pairs and 1,575 distinct models. The caption says 1,577.
- **The only `Table` element** is on page 1: `Americas: Europe: Japan: Korea: Rest of Asia:`,
  which is the ADI contact block.
- **The stats in review.json:**
  - `n_tables 1`, `n_crops_used 1`, `vision_used true`;
  - `crops_failed`, `crops_truncated` and `crops_row_short` are all 0;
  - `grid_label_failed 1`, `grid_no_parts_col 2`, `grid_rows_emitted 0`;
  - `text_layer_parts 0`. The text layer declined two page-1 form regions, with the reason "no
    column header, no parts caption, and 3+ form-label cells".
- **The outcome:** `impacted_parts []`, `needs_review false`, `review_reasons []` and
  `doc_review_reasons []`. The header is complete and correct: categories Material and Process,
  and the epoxy summary from Henkel 8290 to 8290A.

## The mechanism, read from `plugins/sustainment.py` at 809963cb

`origin/main` has not touched this file since 809963cb.

1. **The page-1 contact table makes `tables` non-empty.** So the router takes
   `elif tables and vision_ok …`, which is `_extract_parts` on that one crop.
2. **Vision finds no parts column in it.** That is correct for a contact block. But
   `_apply_vision_stats` sets `needs_review` only on `crops_failed`, `crops_near_cap` or
   `crops_row_short`. A table that yields **0 rows and no parts column** is none of those, so the
   flag stays false and no reason is written.
3. **The PCN24-029 text-only route can never fire here.** It sits behind `elif not tables`.
4. Even with no table, the route would miss. `_has_part_shaped_text` checks `_AFFECTED_LABELS`
   as substrings. **None of the eight labels occurs in this document**: I tested each one
   against the joined text. "Affected **ADI** Models" puts a vendor word inside the label.
5. Even if routed, the text-only vision call would hit the token bound. That is a full-text call
   for about 1,577 rows, so `crops_truncated` would mark the crop failed. That outcome is
   honest, but it still extracts nothing.

Then the empty result posts as `failed:extraction_empty` with `detail=None`, and the BFF refuses
it. That part is the defect in the 10-22 packet, so work saw nothing at all.

## What I think the fixes are (yours to decide)

- **(a) Flag it.** On a PCN, a parts pass that ends with `grid_rows_emitted == 0`, 0 parts and
  `grid_no_parts_col > 0` should set `needs_review`, with a reason. A table was read and it held
  no parts, so the parts are somewhere else. This is the cheap fix that stops the silence.
- **(b) The text-only route should not need `not tables`.** A route keyed on "every table had no
  parts column" would catch this document, and so would one keyed on "the parts pass emitted 0
  while the text names a parts section".
- **(c) The label vocabulary.** Match "affected … models/parts" with an optional word in between,
  or add "affected adi models". The caption "Product Family / Model Number (N)" is also a strong
  parts caption, and it **states its own count**, so it gives a row-short check for free.
- **(d) The text layer.** A list of `Family / Model` text in columns is cheap to parse
  deterministically, and vision on it would truncate. I'd expect tier 1 to own it, with the
  caption count as the oracle.
- **(e) The `detail=` on the failed post**, as in the 10-22 packet.

## A fixture

The four JSONs are on Chris's machine, in a Downloads folder, and come from **work**. I have not
copied them anywhere. Whether they can become a fixture, scrubbed or not, is Chris's call. Only
the two Title strings and one contact-table string are quoted above.

## Not done

- I did not run doc-tools, and changed no doc-tools code.
- I did not check which tier-1 table-text paths would accept a list with no grid.
- The 1,577 count is the caption's. My regex is approximate.
