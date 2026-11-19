# ADR-0234 — the training workbench contract, and which side owns which write

**Status:** accepted (draft)
**Date:** 2026-10-30 (contract version 5, architect) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris — v5 of 2026-10-30 fixed the alignment direction and
confined the workbench's review writes; the ruling arrived as a packet
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/contracts/training-workbench.md:3` — the contract's own status line; `:5-9` the
role table; `:13` the authority rule; `:131-150` §4.4, ownership;
`tests/fixtures/training/golden.json`; `doc_tools/passes/concepts.py`; `semantic_assets.py:458-470`
**Related:** [ADR-0160](ADR-0160-a-concept-is-keyed-on-a-hash.md),
[ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md),
[ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md),
[ADR-0165](ADR-0165-the-contract-decides-the-concepts-rules.md),
[the ontologies-and-alignment component record](../arch/components/ontologies-and-alignment.md)

## Context

Two repos write to one graph. doc-tools' lane tr owns the **write** side of a training ingest —
courses, slides, sections, concepts and the alignment pass — and the training workbench's lane wb
owns the **read** side and a human review surface. They share stores directly: one graph store,
one object store, one vector store, no intermediate service.

Two writers on one graph is the hazard, and not hypothetically. Before v5, canonical concepts were
created by the workbench's own harmonizer **and** by doc-tools' normalisation pass, keyed
differently — the workbench's by `name`, the pass's by `id`. Two `MERGE`s on different keys against
the same intent produce duplicate canonical nodes, quietly, and a review surface built over them
reviews the wrong edges. The second hazard is subtler: a re-ingest that deleted and rewrote its own
subtree would take the users' review edges with it, since those edges end at nodes we also write.

The third problem is authority. A prose contract describing what a consumer may rely on drifts
from what the producer writes and from what the consumer consumes, and the divergence is found by
a consumer reading a field that is no longer there.

## Decision

**Write side is doc-tools' lane tr, read side is lane wb — and where the contract's prose and the
golden disagree, the golden wins.**

- The machine-readable form of the contract is `tests/fixtures/training/golden.json`, which shows
  what doc-tools writes for the fixture deck, and **both repos test against the same fixture
  bytes**. The prose explains; the golden decides.
- **What the workbench may write to the shared graph is three properties**, and nothing else in
  this domain: `status`, `reviewed_by` and `reviewed_at` on an existing `PROPOSED_ALIGNS_TO` edge.
  It never creates or deletes a canonical concept, an `ALIGNS_TO` or a proposal edge, and never
  sets a property on a `Concept`. The pass materialises an accepted proposal on its next run.
- **Canonical concepts and both alignment edges are doc-tools' pass only.** The pass may change
  and delete what it owns — auto edges, open proposals, and canonicals it created — and it never
  touches an accepted edge, a rejected proposal, or a legacy edge with no status.
- **doc-tools stays out of the workbench's labels entirely**: it never writes or even matches the
  project, target-node or user labels, anchors every hierarchy-edge match on a document, and a
  re-ingest **merges rather than detaching and deleting** a course, slide or concept, because a
  delete would drop the users' review edges. Sections and `TEACHES` are the two exceptions, each
  replaced whole in one transaction ([ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md)).
- **The landing is conditional on the workbench switching its harmonizer off** — its
  `harmonize_concepts` asset and unharmonized-concepts sensor — or the two-writer collision above
  is live.
- **Changing it is a packet, not an edit.** The owning lane edits the file; the other side asks by
  packet. Any change to the golden's non-placeholder content bumps `contract_version` and goes to
  wb by packet with the new hashes.

## Consequences

- The seam has a checkable authority at exactly one place — the golden — and a social rule
  everywhere else. That is cheap and partial: **the golden is authoritative for what doc-tools
  writes, and for nothing else.** It cannot say what the workbench consumes, and where the contract
  and the workbench's code have drifted, the contract does not win by being written down. The write
  side is ours to state, the read side is wb's, and a divergence is reconciled by packet.
- `contract_version` is a number in prose: no single place lists which contract is at which
  version — a row in [DEBT.md](DEBT.md).
- The alignment pass is gated by the `TRAINING_CONCEPT_ALIGNMENT` environment variable (`dry` by
  default, with `propose`, `on` and `off`), and it never raises. So a deployment can satisfy every
  word of this contract and write no alignment at all: the gate is a deployment setting, not a
  property of the code.
- Several surfaces are **not promised by v5** and recorded as gaps, not defects: a blank or
  image-only *final* slide gets no slide node, so slide numbers have no interior gaps but can stop
  short of the deck's count; speaker notes are slide text; hidden slides are ingested unmarked.
- The ruling is cited in the tree as `ADR-0059`, which **is not an ADR** — the number was carried
  in the title of an architect's packet, and no such file exists on any pushed branch of this
  repo. It is recorded in [DEBT.md](DEBT.md) as D-6 and deliberately not rewritten.
- **What a reader must not assume from the status line.** "Contract version 5. Status: DRAFT,
  2026-10-30" means neither unimplemented nor implemented: §9's delivery table names which lane-tr
  step makes each surface true, several already landed and one re-keyed later. `DRAFT` marks a
  contract still being revised with its consumer, and is no licence for either side to write what
  the other owns — §4.4 is in force today.

## Alternatives considered

- **Leave canonical-concept creation with the workbench's LLM harmonizer.** Rejected by v5: the two
  writers keyed the same node differently. Ownership moved to doc-tools' normalisation pass and the
  workbench's writes were cut to three properties. (v5 also replaced "five candidates per target"
  with the top `proposals_per_course` ranked pairs per course, default 50.)
- **Have the workbench write the accepted `ALIGNS_TO` itself.** Rejected: it would make the
  workbench a writer of an edge doc-tools owns. It marks the proposal accepted instead.
- **Let a re-ingest detach-delete the course subtree and rebuild it.** Rejected: it would drop the
  users' review and provenance edges. Only sections and `TEACHES` are replaced, and only because no
  workbench relation ends at either.
- **Read through the mesh instead of reading the stores directly.** The intended destination, not
  the current state; direct store reads are recorded as the interim. The contract cites `ADR-0060`
  for it, in draft — a number that is not a record in this repo (see [DEBT.md](DEBT.md) D-6).
