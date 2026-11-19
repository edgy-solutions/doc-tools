# ADR-0129 — a customer part number column is never an affected part

**Status:** built + measured
**Date:** 2026-10-29 (ruled, for every notice) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/utils/table_text_layer.py:100-122` (the vocabulary and its measurement),
`:135` (`_is_customer`), `:373-393` (the veto inside `pair_columns`), `:405`
(`customer_columns`); `scripts/pcn_score.py:200-282` (`split_customer_cell`,
`score_customer`, `customer_totals`); `scripts/pcn_corpus_run.py:181-193` (the re-label of the
denominator); `tests/test_customer_alias_column.py:1-25`; `tests/test_table_text_layer.py:387`
**Related:** [ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md) (cite a score with
its denominator), [ADR-0190](ADR-0190-ground-truth-ti-page-two-is-devices-only.md),
[ADR-0180](ADR-0180-raw-verdicts-are-advisory.md)

## Context

A sustainment notice's parts table often prints the customer's own id for the part beside the
manufacturer's. The column header says "Customer Part Number", and `part number` is exactly what
the affected-part vocabulary matches — so before the ruling that column read as a **second
affected part column**, and one notice in the ten-notice corpus had ten entries in its ground
truth that were not affected parts at all.

Two distinct harms follow, and they pull in opposite directions, which is why one rule is not
enough. If the column is read as affected, a part number the manufacturer never announced is
asserted as affected — and an asserted part lands on a **shared component IRI**, which
re-ingesting cannot withdraw. If the column is merely vetoed and dropped, the field a customer
most needs — their own id beside the manufacturer's — is thrown away, and the corpus silently
counts it as nothing.

The question was left open by the 2026-09-21 corpus validation (§69-72) and was closed for
**every notice** on 2026-10-29.

## Decision

**A "Customer Part Number" column is never an affected part. It is the customer's alias for the
row's affected part, and it gets all three of its own things: its own field, its own column, and
its own denominator.**

- **Its own field.** `customer_mpn` on the row, paired positionally to `affected_mpn`,
  reviewable and exportable through the field catalogue. The alias is read and emitted, not
  discarded.
- **Its own column.** The veto lives in `pair_columns`, not in `_is_affected` — because
  `_is_affected` also feeds `find_title_row`, so vetoing there would change which row is the
  header. `customer_columns(header, pairs)` then returns the customer column for each pair. A
  customer column **alone** yields no pair at all: with no affected part for the alias to belong
  to, nothing is emitted, which is the fail-safe direction.
- **Its own denominator.** Ground truth carries `customer_mpns` per notice, scored by
  `score_customer`, and `customer_totals` sums **only over the notices that declare the
  column**. A notice with no customer column is `None`, which means *"this notice has no
  customer column"* — **not** a zero, and not a row in the denominator.
- **The score is ADVISORY and cannot fail the corpus gate**, and that is part of the ruling
  rather than a convenience. The parts verdict names its own keys so this one cannot leak in.
- A customer id is **not** a part: it is never written to the graph, so a spurious one here is a
  reporting defect and not corpus contamination — a second reason the two columns are scored
  apart rather than added.
- Classification requires **three** cues together: a customer cue, a part cue, and a header cell
  short enough to be a column name (`_MAX_CUSTOMER_HEADER_LEN`, `_MAX_CUSTOMER_HEADER_SPACES`).
  This is measured, not stylistic — see below.

## Consequences

- **The corpus denominator moved, and the move is a re-label.** One notice falls from 26 to 16
  affected parts and the corpus from **522 to 512**. Numerator and denominator fall together by
  the same ten, so a **rate** at 512 is comparable to one at 522 while a **count** is not: an
  extractor scoring 522/522 scores 512/512. Reports citing 522 keep their denominator; cite a
  score with the denominator it was measured against
  ([ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md)). Nothing left the record — all
  ten strings are still enumerated, under the field that says what they are.
- Two of the ten notices declare a customer column. The second is TI, whose eleven aliases sit
  on a page `find_tables()` returns **zero** tables for under both the `lines` and the `text`
  strategy (measured 2026-10-10 and again 2026-10-29). **That is why advisory is load-bearing**:
  a blocking recall target here would publish a red that no change to the extractor could clear.
  Promoting it later is therefore not a tightening, it is a self-inflicted gate.
- The three-cue rule is measured against the corpus, which carries exactly **three** header
  cells containing "customer": the real column; a *Customer Drawing* column, a drawing number
  sitting between the two part columns, so a "nearest customer column to the right" rule pairs
  the wrong one and yields nothing; and a ~600-character paragraph `find_tables()` returned as a
  header cell, which the **length** bound excludes. Each cue earns its place by a failing case.
- A customer cell can hold **more than one id for one affected part**. Tier 1 carries such a cell
  verbatim on purpose — splitting in the extractor would duplicate the affected part and move
  the parts denominator — so the split happens in the scorer (`split_customer_cell`), at the one
  place that compares ids to a list. Without it that notice reads 6 exact / 2 spurious / 4
  missing against a ground truth of 10 it in fact emitted in full.
- Ground truth refuses to hold a value in both lists: an id in `mpns` and `customer_mpns` raises,
  because a value cannot be an affected part and that part's own alias at once.

## Alternatives considered

- **Add the customer headers to `ALIAS_HEADERS`.** Rejected explicitly, and the reason is the
  shape of the whole decision: an alias column is **declined** — dropped, unread — while a
  customer column is **read and emitted** as its own field. Same veto, opposite fate, so it is a
  separate vocabulary and not three more entries in an existing one.
- **Veto inside `_is_affected`.** Rejected: `_is_affected` also feeds `find_title_row`, so the
  veto would change header-row detection as a side effect.
- **Pair the nearest customer column to the right of the affected column**, with no part cue.
  Measured and rejected: it pairs the drawing-number column on the notice that has both.
- **Score the customer column with the parts, in one total.** Rejected by the advisory ruling and
  by the graph argument: a wrong value has different consequences in each column, and one of them
  sits on a page no tier can read.
