# ADR-0151 — semantic tags are late-bound by polling DataHub, through HITL

**Status:** built
**Date:** no ruling date is recorded; carried as standing guidance in `AGENTS.md`
(§Semantic Binding Plane, "Late Binding") · recorded 2026-11-18
**Deciders:** the repo's standing guidance in `AGENTS.md`; no individual is named
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:172-173` (§Semantic Binding Plane 3–4); implemented at
`doc_tools/assets/global_semantic_ingestion.py:9-86`,
`doc_tools/assets/semantic_linker.py:41-84` (`propose_datahub_term`), `:155-177` (the
confidence routing) and `doc_tools/components/datahub_sensor.py:16-70`
**Related:** [ADR-0152](ADR-0152-no-hitl-for-code-controlled-registrations.md) — its sibling and
its deliberate opposite: **data** linkings need a human, **code-controlled** registrations do
not. [ADR-0150](ADR-0150-a-glossary-term-urn-uses-the-short-name.md) (the URN this flow carries),
[ADR-0153](ADR-0153-one-uniform-contract-for-legacy-extractors.md) (what feeds the classifier)

## Context

A semantic tag says "this dataset is instances of that ontology class". Two sources could supply
it: the metadata files in a producing repo (dbt schema files, modelling-tool exports), or
DataHub, where the tag ends up anyway.

Reading the local files is the wrong one, and not because it is harder. A dbt file in a checkout
is a **statement of intent at some past commit** — it may be edited, reverted, or never
deployed, and a tag derived from it describes a repo, not the catalogue a consumer queries. Worse,
it binds this repo to every producer's file layout: each new dialect becomes a parser here, and a
producer who renames a directory breaks our graph without touching anything we own
([ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md) is the general form of
this mistake).

The second half of the problem is who gets to decide. A classifier returning a confidence score
is a suggestion about a business meaning. An automatic write of that suggestion into the
knowledge graph makes a machine's guess indistinguishable, downstream, from a steward's ruling —
and `Dataset` bindings are exactly the case where a human has context the classifier does not.

## Decision

**Semantic tags are late-bound: DataHub GMS is polled for `Dataset` entities carrying an
`ontology_uri` custom property, and no local dbt or metadata file is ever parsed for a tag. Every
`Dataset` linking goes through the `propose_datahub_term` HITL flow before it reaches Neo4j.**

- `ingest_global_semantic_links` polls DataHub by GraphQL for datasets, reads each one's
  `customProperties` for an `ontology_uri`, and proposes from what it finds
  (`global_semantic_ingestion.py:9-86`). The reasoning string it records names the upstream
  pusher rather than a file (`:83`).
- `propose_datahub_term` submits DataHub's `proposeTerms` mutation (`semantic_linker.py:65-84`).
  It **proposes**; it does not attach. The approval is DataHub's, made by a human.
- `apply_semantic_tags` routes by the classifier's confidence (`:161-172`): `>= 0.85` logs
  `AUTO-TAGGING`, `>= 0.50` logs `HUMAN REVIEW`, below that the table is rejected and skipped.
- Only an attached term reaches the graph: `datahub_approval_sensor`
  (`components/datahub_sensor.py:16-70`, registered at `doc_tools/definitions.py:427-432`) polls
  for datasets that now carry a glossary term and dispatches
  `sync_approved_tags_to_neo4j` for each `(dataset, term)` pair.

## Consequences

- The catalogue is the source of truth, and a producer can change its internal file layout
  freely. The cost is a poll: binding latency is the sensor's interval, not an event, and nothing
  here is push-driven.
- **The confidence threshold sorts the statistics, not the write path.** Both the `>= 0.85` and
  the `>= 0.50` branches call the *same* `propose_datahub_term`; they differ only in the log line
  and in which counter they increment (`:161-172`), and `tests/test_semantic_linker.py:37-61`
  pins exactly that — three tables, two proposals. So "auto-tag" in `AGENTS.md:124` names a
  confidence bucket, not an automatic attachment: **nothing in this repo attaches a term without
  a human.** That is stricter than the guidance's wording and is the safer direction, but a
  reader who trusts the word *auto* will misread the flow, so it is recorded here.
- The HITL gate is DataHub's approval, which means its semantics are DataHub's too. The sensor
  does not check an approval state; it reacts to a term being **present** on a dataset. A term
  attached by any other means is synced identically.
- The sensor's `run_key` includes a millisecond timestamp (`datahub_sensor.py:63`), so the same
  `(dataset, term)` pair yields a new run on every tick, and the cursor it writes (`:68`) is
  never read back. The sync is idempotent, so the effect is wasted runs rather than wrong edges —
  but it is not the dedupe a `run_key` normally buys, and this record is not the place that fixes
  it.

## Alternatives considered

- **Parse local dbt / metadata files for tags.** Rejected by the guidance in as many words: *"Do
  NOT parse local dbt or metadata files for semantic tags"* (`AGENTS.md:172`).
- **Auto-attach above a confidence threshold, with no human.** The code as written does not do
  this, and no record of it being weighed and rejected exists — the threshold is in the code and
  its justification is not. Treat the thresholds (`0.85`, `0.50`) as unexplained constants: they
  are cited here, not defended.
