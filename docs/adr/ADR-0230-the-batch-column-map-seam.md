# ADR-0230 — the batch column map, and the two header fields lane 1 serves

**Status:** built; one half accepted
**Date:** 2026-10-28 (the order), `contract_version 2` dated 2026-10-30, the header-field ruling
2026-10-31 · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris (the 2026-10-28 order that moved the vocabulary
here); Lane 1 for the served-field half
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/contracts/batch-column-map.md:3-20` — the contract's own status line;
`docs/contracts/batch-column-map.md:286-332` §9, where the 2026-10-31 ruling is recorded at
line 322; `doc_tools/batch/profile.py:140-149`; `docs/contracts/batch-column-map.schema.json:4-5`
**Related:** [ADR-0106](ADR-0106-batch-is-an-operator-cli-not-the-pipeline.md),
[ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md),
[ADR-0233](ADR-0233-the-scrub-ledger-seam.md) (the other seam whose status line and tree have
moved apart), [the extraction-pipeline component record](../arch/components/extraction-pipeline.md)

## Context

A batch export profile is a column map: a steward writes, per output column, which extracted
field fills it. Two failures were live before this contract. First, **the vocabulary had no
owner** — an earlier ask of this lane's had Lane 1 propose it, on the reasoning that nothing of
ours existed. Second, and worse in practice, **a column could name a field that nothing
produces**. The field catalogue is the superset of what doc-tools *produces*, not of what the
extraction route can *serve*, and the difference is invisible in the catalogue's own names: all
eleven `header.*` fields are unserved, each with a null `wire`, and `change_type` and
`effective_date` have zero occurrences in the extractor at all. A profile naming any of them
reads as reasonable and would have surprised somebody at run time, against a batch.

A third failure is a documentation one, and it is the reason this record names no number twice.
The catalogue count in the contract moved three times in days — 29/28, then 32/57, then the
2026-10-30 measurement of **58 fields, 33 served, 25 unserved**. A count hardcoded in prose was
wrong within two days of being written.

## Decision

**A batch export profile is written in one vocabulary owned by doc-tools, and a column naming a
field that nothing produces or nothing serves is refused when the profile is validated, not when
it runs.**

- The vocabulary is **one file in this repo** (granularity, the source selector for the shared
  `extracted_value`, landing for unresolvable values, and the ruled date, `change_type` and
  manufacturer rules). Lane 1 **reviews** it against the ledger route; it does not own it. That
  reversed this lane's earlier ask, and the reversal is the point of `contract_version 2`.
- Shape is JSON Schema (`batch-column-map.schema.json`); the catalogue-dependent rules are code,
  because JSON Schema cannot express them. `doc_tools/batch/profile.py` emits `field-unknown`,
  `field-not-extracted` and `field-not-served` as hard errors at validation time.
- **The validator reads the catalogue file.** No count is asserted anywhere except in a test that
  also reads the file. Count it; never quote it.
- **RULED 2026-10-31: Lane 1 serves two header fields. Which two the ruling does not name, and
  it is still unanswered at the pin** — asked back in the packet of the same date, and carried as
  F-7 in [FOLLOW-UPS.md](FOLLOW-UPS.md). A profile needs no change either way: the validator
  resolves `source.field` against the catalogue and accepts them the moment `served_by` is set.
  Until the answer lands, nobody can say which two columns a profile may now ask for.

## Consequences

- The refusal is the request. Lane 1's stated position (2026-10-30) is *"a field gets served when
  an export profile asks for it, not in advance"*, so the producibility gate is the mechanism by
  which a field becomes servable — a refused profile is how a steward asks.
- A profile can be written and refused; **it cannot yet be run.** There is no exporter, and
  measured at the pin nothing under `doc_tools/` imports `doc_tools.batch`.
- What is genuinely unreachable is named rather than worked around: the document's type, revision
  and publication date, the two source substrings and the two derived prose fields. One of the
  eleven `header.*` fields *is* reachable — `notice.notice_id` is the printed document id, not an
  ingest key — and the earlier, stronger claim that a profile had no access to the printed
  identity was corrected on 2026-10-31 by reading the catalogue's `notes` beside its `served_by`.
- Two catalogue mappings are marked `mapping_unverified`. A profile naming either names something
  whose derivation only the consumer knows.
- **What a reader must not assume from the status line.** "The contract **and a validator**, as of
  2026-10-30" means exactly a schema, a rules module and one worked profile the suite validates.
  It does **not** mean an exporter, a run, or a settled seam: one half of this contract is
  `accepted` and waiting on another lane, and `contract_version 2` is a number in prose, not a
  seal that fails when the tree moves past it. No single place in this repo lists which contract
  is at which version — that row is in [DEBT.md](DEBT.md) as D-4.

## Alternatives considered

- **Lane 1 proposes the vocabulary.** This lane's own earlier ask, reversed by the 2026-10-28
  order. The reasoning behind the ask (nothing of ours existed) was true and was not sufficient:
  the vocabulary is a statement about what *our* extractor produces.
- **Assert the served/unserved counts in the contract.** Taken in version 1 and withdrawn: the
  numbers moved twice within days. The assertion now lives in a test that reads the file.
- **Derive one `change_type` from the `categories` list.** Explicitly not decided here (§7, §11):
  picking the first element silently is the kind of guess the landing rule refuses. A profile
  naming `change_type` is refused today.
- **Have Lane 1 serve all eleven `header.*` fields up front.** Not taken, and not ours to take —
  Lane 1 serves on demand, by ruling of 2026-10-30.
