# ADR-0123 — the stage post is a run's last act, and stages never move backwards

**Status:** built
**Date:** 2026-10-23 (architect ruling) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/assets/semantic_assets.py:1433-1441` — a code comment, which was the
**only** written statement of this ruling before this record; the post itself begins at
`:1442` and the phase comment that places it at `:1422-1432`. Pinned by
`tests/test_graph_write_seal.py`, in particular
`test_every_store_write_precedes_the_stage_post_in_the_impl`.
**Related:** [ADR-0122](ADR-0122-extracted-count-is-not-a-fraction.md) (the two fields the
post carries), [ADR-0120](ADR-0120-ingest-id-is-one-canonical-spelling.md) (no `ingest_id`,
no post), [ADR-0140](ADR-0140-one-named-graph-per-document-replaced-whole.md),
[the document-to-review-record flow](../arch/flows/document-to-review-record.md)

## Context

Lane 1 turns a `review` stage post into a `document_promotion` task: a human is handed the
document to approve or reject, and the disposition builds a decision record. So the post is
not telemetry. It is the act that summons a steward.

Two things were wrong with where it used to happen.

**It was posted from the parser.** The parser has no row count — the count Lane 1 serves
comes from `review.json`, which does not exist until the graph asset runs. Measured: two
zero-row extractions of the same notice (both 606-byte PDFs, `extracted_count=2`,
`extracted_total=1`, **0 part rows** — one because the header pass raised a BAML validation
error, one because no `Table` element was detected) filed a `document_promotion` task
anyway. A seal on `extracted_count == 0` catches neither of them, because the count was 2.

**It was posted before the writes.** The post sat in front of the cypher loop, the SPARQL
loop and the Pass 2 roll-up, each of which **logs and continues** on error. So `review`
could be, and was, posted for a document the graph did not hold: a steward opens the task,
and the content the task is about is not there.

A stage that has already said `review` cannot then say `failed` — Lane 1's row moves
forward. Posting early therefore does not merely report early; it **forecloses** the honest
report.

## Decision

**The ingest stage post is a run's last act, after every store write has either succeeded
or failed. Stages never move backwards.**

- The post lives in the graph asset, not the parser, because that is where the row count
  exists at all.
- It runs **after** the cypher loop, the SPARQL loop and the Pass 2 roll-up. Every store
  write precedes it, and that ordering is pinned by a source-level assertion rather than
  left to review.
- A failed graph write posts **`failed:graph_write`**, with the failing store(s) named and
  counted in the detail, and **`review` is never posted for it**. A failed link write posts
  `failed:link_write` the same way.
- **No degraded marker.** A half-written document is not a state a steward can act on, so
  there is no third disposition between "here it is" and "it failed".
- The failure reasons are **ordered**, and the order is an argument, not a coincidence: a
  store write failing means the document is not in the graph *at all* and subsumes a lost
  chunk, so `graph_write` / `link_write` win over `concept_parse`; but `concept_parse`
  beats `extraction_empty`, because a raised augmentation is the **cause** and zero rows is
  the **symptom**, and posting the symptom sends a steward to the wrong place.
- `reason` and `detail` are set from one string. A `failed` post with a blank `detail` is
  refused by the seam's own validation, so the two cannot be allowed to drift apart.
- **No `ingest_id` means no post.** The vetted `sustainment/inbound/` path has no
  `ingest_id`, so there is no Lane 1 row to address and it stays unposted — an absence, not
  a failure.

## Consequences

- A steward is never handed a document the graph does not hold. That is the whole purchase.
- The post is now the **last** thing a run does, so anything that fails after it is
  unreportable on this seam by construction. The ruling accepts that: there is nothing
  after it.
- A reason code is load-bearing and bounded. `graph_write` and `link_write` are members of
  `REASON_CODES`; the seam **coerces** any code outside that set to `unexpected_error`, so
  an unlisted code silently loses its meaning on the row rather than being rejected. Two
  tests pin each of those two codes as known for exactly that reason.
- The detail is capped at 500 characters and names only the stores that failed, so a
  reader can tell a Neo4j-only failure from a Jena-only one without reading a stack trace.
- The ordering rules mean the posted reason is not always the first error raised. A reader
  reconstructing a run from the row must consult the ordering, not assume chronology.
- The ordering is sealed **in the source**, not by driving the implementation: the full
  path needs S3, Neo4j, Weaviate, an LLM and Jena, and no test in this repo stands those
  up. So the seal reads the implementation's source and asserts every write precedes the
  post. That is weaker than an executed ordering and is recorded as such here.

## Alternatives considered

- **Seal on `extracted_count == 0` and keep the post in the parser.** Rejected by the
  measurement: both zero-row extractions carried `extracted_count=2`, so the seal catches
  neither. This is the alternative the measurement was taken against.
- **Post `review` early and correct it with a later `failed`.** Rejected by the ruling's
  own second half — stages never move backwards. Lane 1's row has already filed the
  promotion task; a later correction does not unfile it.
- **Post a degraded marker for a half-written document.** Rejected at the site: a
  half-written document is not a state a steward can act on, so the marker would create a
  queue nobody can clear.
- **Keep the post in the parser and pass the row count forward.** Not recorded as
  considered. Its shape would have been the parser reading an artifact a later asset
  writes, which inverts the dependency the asset graph already expresses.
