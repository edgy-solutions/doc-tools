# ADR-0126 — the leaf-read output shape, and who owns the leaf-source mapping

**Status:** built
**Date:** 2026-10-21 (leaf ruling, item 2; extended the same day) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/utils/leaf_read.py:5-10` — a module docstring, which was the **only**
written statement of this ruling before this record. The rulings live at `_page_fractions`
(`leaf_read.py:340-359`) and `leaf_source_for_outcome` (`:389-407`), with
`wire_evidence_ref` at `:362-386`, `MAX_CANDIDATES` at `:155`, the `leaf_source` enum at
`:55-74` and the read outcomes at `:253-260`. Pinned by `tests/test_leaf_read.py` 2–4.
**Related:** [ADR-0125](ADR-0125-a-pdf-runs-parse-only-before-the-title-read.md) (when the
read runs), [ADR-0128](ADR-0128-evidence-ref-is-served-as-is.md) (the same page-fraction
convention for `evidence_ref` generally),
[ADR-0127](ADR-0127-a-title-signal-has-an-order-not-a-score.md) (the scores)

## Context

The title read answers "what is this document?", and it does not always answer. That answer
crosses three boundaries — the manifest, Lane 1's status row, the review card a human sees —
each with a different tolerance for a surprise. Three concrete failures shaped it.

- **A crop with no stated space is unplaceable.** Three spaces are in play: PDF points
  (pdfplumber's), unstructured's layout pixels, and the page raster's own. Two corpus
  notices carry row geometry in **different** spaces, so the space cannot be inferred.
- **An extra key drops the whole list.** The ruled `evidence_ref` shape admits no keys
  beyond `{page, bbox, note?}`. An extra one is a 422 at Lane 1's BFF, and cortex's
  candidate reader drops the **entire** candidate list when one item is invalid.
- **An outcome is not a source.** `title-ambiguous` and `no-title-evidence` are **read
  outcomes**: legal outcomes and **illegal** `leaf_source` values. Assigning either field
  from the other sends an ambiguous read to a status row as a source cortex refuses, quietly
  stopping the chip being drawn. The two are one word apart in Lane 1's `doc_type_source`.

## Decision

**The read returns `[{leaf, score, evidence_ref}]`, best first, max 3; the crop's
coordinates are page fractions; and the outcome→`leaf_source` mapping is `leaf_read`'s.**

- **Candidates only when not confident.** A confident read carries `leaf`, `leaf_source` and
  the deciding title's `evidence_ref`, and no candidates; the list fills **only** when no
  leaf was read. `leaf` and `leaf_source` are **both `None` or both set** — a source without
  a leaf is the state that makes a column lie, so `LeafRead` refuses to hold it.
- **Max 3, ordered by score descending then document order — never leaf name.** The cap is
  applied although two leaves can be named today, so it is already right if the leaf space
  widens; the ordering carries the walk's first-signal-wins property, a document-order one.
- **Page fractions.** `[x0, y0, x1, y1]` in 0..1, origin top-left, plus `page`. Unit-free,
  so **no space key** — the space needed naming because the numbers could not be told apart,
  and a fraction is self-describing. Every value is ≤ 1, so a box that arrived in the wrong
  space is **visible rather than silent**, and a consumer needs no page size, no DPI and no
  PDF to place it. Producers convert before writing, to six decimals, so a test can assert.
- **One conversion, not a copy.** `_page_fractions` **delegates** to
  `provenance.to_page_fractions`, which holds the rules (no divisor, clamp-and-note, refuse
  a degenerate box), because the ruling makes fractions *"the same everywhere evidence_ref
  appears"* and the review rows convert through it too. A second copy is how the leaf crop
  and the row crop disagree on a boundary case that costs the whole candidate list. The
  source space is the divisor's provenance (`BBOX_SOURCE_SPACE_LAYOUT_PIXELS`), not a value.
- **The page is the locator; the box only refines it.** `bbox` may be null, `page` may not:
  a null `bbox` means "stated on this page, no box we can draw". Only a **pageless** ref
  yields no `evidence_ref` at all — which is also the derived-field case, a derived field
  being on no page.
- **`leaf_source` is written once, by `leaf_source_for_outcome`.** `title` → `title`;
  `title-ambiguous` and `no-title-evidence` → **no leaf**, the row holding at
  `awaiting_kind` with the candidates. Nothing else crosses. `declared` and `corrected` are
  **unreachable from any outcome by construction**: a declared leaf came off the drop, a
  corrected one from a person, so a title read minting either would be a provenance lie
  about who decided. The field is written when the leaf is written and stored on the row,
  never computed back out of the stored kind.

## Consequences

- A consumer places a crop with arithmetic and nothing else, and the convention is shared
  with `evidence_ref` generally ([ADR-0128](ADR-0128-evidence-ref-is-served-as-is.md)), so
  there is one space across the review surface, not one per producer. A box in the wrong
  space now **fails visibly** (a value > 1) — the main purchase of dropping the space key.
- The projection is **lossy on purpose**: the richer internal ref stays in the manifest,
  where no shape contract binds it, and only the ruled keys cross. A reader who sees a
  thinner ref on the wire than in the manifest is looking at the design. A boxless ref
  **crosses** rather than being dropped, which an earlier `wire_evidence_ref` got wrong —
  dropping it threw away the half that works.
- The cap does not bite today, since two leaves cannot exceed three; it is kept anyway and
  `test_the_candidate_list_is_capped_at_the_ruled_three` exercises it.
- The two vocabularies remain adjacent and confusable by a human reader. The protection is
  structural, not documentary: `leaf_source_for_outcome` is the only sanctioned crossing,
  the retired names are asserted not to be sources, and the tests assert the walk emits **no
  outcome the mapping does not name** — so a change upstream fails a test here.

## Alternatives considered

- **Name the coordinate space on every ref.** This *was* the design, and the extended ruling
  replaced it. Its argument — three spaces, two corpus notices carrying row geometry in
  different ones — is why a *self-describing* space was chosen, not no convention at all.
- **Keep a second `to_page_fractions` local to this module.** Rejected at the site: two
  copies disagree on a boundary case, and that costs the whole candidate list to a 422.
- **Serve the richer internal ref.** Rejected by the measured consumer behaviour: an extra
  key is a 422, and one invalid item drops the entire list.
- **Derive `leaf_source` from the stored kind.** Rejected by the enum's own comment: a value
  computed back out of the kind cannot tell a read from a declaration from a correction.
- **Let `title-ambiguous` be a fourth `leaf_source`.** Rejected: both no-leaf outcomes mean
  the same to the row — hold at `awaiting_kind` with the candidates — and cortex refuses a
  source outside the ruled three, which would silently drop the chip.
