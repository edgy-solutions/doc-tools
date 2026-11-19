# A document arriving to a review record (FL-REVIEW)

This is doc-tools' main path: a file appears in object storage and, some minutes later, a
person has a review record with rows, flags, reasons and evidence they can act on. It crosses
[CO-EXTRACT](../components/extraction-pipeline.md) and
[CO-ONTOLOGY](../components/ontologies-and-alignment.md), writes to three stores, and ends at
a seam owned by another lane — the gateway's ingest-status row and the reader that serves it.

Two boundaries decide how to read this record. **doc-tools never renders a review**: it
writes `review.json` and announces a stage. And **the stage announcement is where the flow
becomes visible to a person** — a run that succeeds in Dagster while that POST fails leaves a
document that was extracted and that nobody is asked to review.

**This record describes; it proposes nothing.** Statuses are those of
[the README](../README.md). Code line numbers are valid at the code pin
`5eb72e5cefaa4e3b414f4fc3b9f7c0bde4c98bed`; the architecture-records commits since it change
no code. Nothing in this record was run.

## Findings

1. **The flow has two entrances and one body.** The vetted path and the ADR-0041
   ingress-user path are the same function: `make_build_knowledge_graph` builds both asset
   variants over `_build_knowledge_graph_impl`. A change to the body changes both paths, and a
   claim about "the ingest" that is true of only one of them is a claim about the entrance.
   `built`
2. **The domain is the registered content kind's declared domain, never a run tag.** That is
   the architect's ruling of 2026-10-02, written at the resolution site: the kind's declared
   domain is the authority, the manifest's declared domain is the fallback, and when neither
   resolves the asset **raises** `DomainTypeNotResolvableError` rather than defaulting. The
   installed sensor component injects no run tags at all, so a tag-based read would have been
   reading nothing. `built`
3. **A document with no domain is refused, not processed generically.** The raise is the whole
   mechanism: a kind registered with no declared domain is the hazard the comment names, and
   there is no branch that continues with a null domain. `built`
4. **The plugin is chosen from that domain, and an unbranched domain gets the Training
   plugin.** See [CO-EXTRACT §16](../components/extraction-pipeline.md). For this flow the
   consequence is specific: a new domain added without a branch produces a graph and an
   extraction that look complete and teach concepts nobody asked for. `built`
5. **Full text first, then chunks.** `plugin.process_fulltext` runs once over the whole
   document and produces the global nodes; `plugin.augment` then runs per chunk. The order is
   load-bearing for the sustainment path, whose header and parts facts are document-level and
   whose rows are per chunk. `built`
6. **A failure inside a stage is raised *after* that stage's status has been posted.** Each
   error class — `GraphWriteError`, `LinkWriteError`, `AugmentationError`,
   `ProvenanceStampFailedError` — is raised after the post, so the row a person's queue reads
   is already `failed` with a code when the Dagster run goes red. The two signals agree
   instead of racing. `built`
7. **`review.json` is written only by a plugin whose augmentation carries a `review` block.**
   Sustainment does; manufacturing and S1000D-via-PDF do not, and they skip it. A document
   can therefore complete this flow, write a graph, and produce no review record at all — by
   design, not by failure. `built`
8. **`review.json` is an ingest output, not a review store.** It is one `put_object` of the
   first review node's block plus `needs_review`, `review_reasons` and `stats`; its
   `approval_state` is the literal `"pending"` written by the merge. Nothing in doc-tools ever
   reads it back to update it, so a disposition a person makes does not live here. `built`
9. **A failed `review.json` write does not fail the run.** The write is wrapped in a
   `try/except` that logs the error and continues, so the run reports success with no review
   record. The same is true of the extraction payload write immediately before it. `built`
10. **The flow's terminal success stage is `review`, not `complete`.** The postable wire
    vocabulary is `{extracting, review, failed}`. `received` is Lane 1's stamp, and
    `promoted`/`rejected` belong to the human disposition task; doc-tools observes those
    locally and never posts them. So "the pipeline finished" and "a person has been asked" are
    the same event here. `built`
11. **Five failure codes can end this flow, and they are posted with a reason.**
    `graph_write`, `link_write`, `concept_parse`, `extraction_empty` and
    `extraction_failed`. `reason` and `detail` are deliberately one string, because a `failed`
    post with a blank `detail` is **refused** by the validator — and when that happened, the
    `except` logged the `ValueError` and the run went on to report success. Lane 1 measured
    the consequence: every document that sealed `extraction_empty` sat at `extracting` with no
    review task, because the POST never happened. `built`
12. **The stage POST is live, and the function's own docstring says otherwise.** The class
    docstring says the route is live in sandbox, the method docstring still says "validate and
    (for now) log", and the body calls `httpx.post`. The code is the authority: it posts. The
    stale sentence is a gap below. `built`
13. **The stage seam validates before it transports, and never fails the extraction.** The
    stage is validated against the real imported `INGEST_STAGES` (never a mirrored copy), the
    `ingest_id` shape is checked against Lane 1's rule rather than the SDK's, and a bare
    hexdigest is coerced with a warning while anything else raises. A token-mint failure, a
    network error and a non-2xx response are all logged at WARNING and swallowed. `built`
14. **The route authenticates the service, not the user.** It requires a Bearer JWT minted
    under `svc:doc-tools` and 403s any caller whose `authz_id` differs. doc-tools holds no
    user identity on this path. `built`
15. **`extracted_count` and `extracted_total` are not a numerator and a denominator.** They
    are two independent fields in the units the resource names, and reading them as a rate is
    a mistake the resource documents against. `extraction_ref` is the manifest key, which is
    how Lane 1 derives the pipeline version from the artifact instead of trusting a caller.
    `built`
16. **The row contract is domain-generic, and a document with no rows is not failed for it.**
    Whether rows are the review unit is decided by whether any augmentation declares a
    `review` block — not by testing for "sustainment" — because sealing a manufacturing drop
    on a row count it never produces would fail every such drop. `built`
17. **Evidence is referenced, not embedded, and absence is expressed by omission.** A row
    carries `bboxes` as page fractions and an `evidence_ref` in the ruled wire shape served
    verbatim by the reader. `page_dims` and `evidence_ref` are **omitted, never nulled**,
    because the reader discriminates on presence: an absent `evidence_ref` is how it is told
    there is no evidence. `built`
18. **The review record a person reads currently carries raw model output.** The header
    failure path appends `"header pass failed: " + str(last["error"])` to `review_reasons`,
    and the exception echo is written into the item. The prefix is matched as a substring by
    the corpus gate, so it is load-bearing text; the raw tail is not. A ruling of 2026-11-18
    says raw prompts and raw model output stay in telemetry and never enter a record a person
    reads. `built` (the echo); the ruling is `accepted` and its implementation is `not built`.
19. **The pipeline already has the shape the ruling asks for, unused on this path.**
    `ingest_failure.classify(exc)` returns a `(reason_code, reason)` pair bounded at 400
    characters, over a declared `REASON_CODES` set with the codes reserved to Lane 1 excluded.
    The stage POST uses it; the review record does not. `built`

## The flow, step by step

| # | Step | Component | Status | Evidence |
|---|---|---|---|---|
| 1 | A file appears under a watched prefix | storage, outside this repo | `built` | the prefixes are generated from the kind registry — [CO-EXTRACT §2](../components/extraction-pipeline.md) |
| 2 | Lane 1 stamps `received` for a user drop | gateway, **another lane** | `built` elsewhere | `dagster_resources.py:186-190` — doc-tools observes it locally and never posts it |
| 3 | A sensor tick lists the prefix, mints `{ETag}-{key}`, adds a dynamic partition and launches a run | `S3SensorComponent`, **installed package** | `built` | identical bytes mint the same key and launch nothing; a key consumed by a failed run stays consumed |
| 4 | The parse asset downloads the object | CO-EXTRACT | `built` | `document_parser.py:397`; on failure it writes `mock document content` and continues — [CO-EXTRACT §10](../components/extraction-pipeline.md) |
| 5 | `unstructured` partitions it at `hi_res`; tables and images are cropped; pages are rastered | CO-EXTRACT | `built` | `extraction.py:69-87`; `document_parser.py:436-442`, `:533-535` |
| 6 | The ingest id is taken from the sidecar or minted from the bytes, and provenance is stamped | CO-EXTRACT | `built` | `document_parser.py:663-664`, `:683`, `:707-709` |
| 7 | The versioned manifest is written, then the mutable pointer | CO-EXTRACT | `built` | `document_parser.py:754-756`, `:768-784` — pointer strictly last |
| 8 | The graph asset resolves the domain from the registered kind, or raises | FL-REVIEW | `built` | `semantic_assets.py:758-775`; ruling 2026-10-02 at `:523` |
| 9 | The plugin is selected from the domain | CO-EXTRACT | `built` | `semantic_assets.py:932-969`; the `else` is Training |
| 10 | `process_fulltext` produces the document-level nodes | FL-REVIEW | `built` | `semantic_assets.py:1004` |
| 11 | Each chunk is augmented; failures are collected, not swallowed | FL-REVIEW | `built` | `semantic_assets.py:1102`, failures at `:1099`, `:1107` |
| 12 | Chunks are indexed into the vector store | CO-ONTOLOGY | `built` | `semantic_assets.py:186` |
| 13 | Facts are written to the per-document graph and the instance graph, chosen by rule | CO-ONTOLOGY | `built` | `semantic_assets.py:1733`, `:1818` |
| 14 | Concept alignment runs, gated by the env switch, and never raises | CO-ONTOLOGY | `built` | `semantic_assets.py:458-476`; default `dry` writes nothing |
| 15 | `extraction.json` is written | FL-REVIEW | `built` | `semantic_assets.py:365`, `:1295-1306`; a failed write only logs |
| 16 | `review.json` is written — only if an augmentation carries a `review` block | FL-REVIEW | `built` | `semantic_assets.py:1315-1338`; a failed write only logs |
| 17 | The stage is posted: `review`, or `failed` with one of five codes | FL-REVIEW → gateway | `built` | `semantic_assets.py:1469`, `:1482`, `:1505`, `:1531`, `:1544`, `:1694`; transport at `dagster_resources.py:443-465` |
| 18 | A person opens the review and dispositions it | **another lane** | `not built` here | `approval_state` is written as `"pending"` and doc-tools never reads it back |
| 19 | `promoted` / `rejected` are stamped by the disposition task | **another lane** | `built` elsewhere | observed locally only; never posted from here — `dagster_resources.py:188-190` |

## Gaps

- **Two writes on this path fail silently.** `extraction.json` and `review.json` are each
  wrapped in a logging `try/except`, so a storage error yields a successful run with no
  extraction payload or no review record. `built` (the behaviour); a check is `not built`.
- **A stale docstring says the stage seam only logs.** `dagster_resources.py:247` still says
  "validate and (for now) log" and calls the transport "the real transport this no-op stands
  in for", while the body posts. A reader deciding whether a stage reaches Lane 1 can read the
  wrong answer from the function they are looking at. `built` (the transport); the docstring is
  wrong at this pin.
- **The review record carries raw model output.** `sustainment.py:773`, `:818`, `:2487`. The
  2026-11-18 ruling says it must not. `accepted`; `not built`.
- **A `needs_review` count has no asset check.** It is surfaced as a Dagit warning, and the
  code names a formal `asset_check` as a follow-up. `built` (the warning); the check is
  `not built`.
- **Nothing reconciles the three sinks for one document.** A document can land in the graph
  and not in the index, or the reverse, and this flow has no step that compares them. The
  ontology seals cover the class pool, not a document's chunks. `not built`.

## Not established from code

- **How long this flow takes, end to end, for any document.** No measurement in this repo, so
  no step above is `measured`. `NE-03`.
- **Whether a stage POST succeeds in any environment**, and what fraction of runs lose it. The
  failure is a WARNING log line, and nothing counts it. `measurement`.
- **What the reader renders from `review.json`.** The wire shape is ruled and served verbatim,
  but the rendering is another lane's code and was not read. `another repo`.
- **Whether a document that produced no `review.json` is visible to anyone.** The stage posts
  `review` whether or not a review record was written, since the two are separate branches.
  Which queue that lands in is Lane 1's. `another repo`.
- **The two `review.json` layouts.** This repo writes one shape; a second layout exists in the
  tree's history and under earlier pins, and which readers still accept which was not
  established here. `unread`.

## Sources

All paths are in this repo at the code pin named above, except where a row says otherwise.

| Claim | Source | Decision | Evidence | Status |
|---|---|---|---|---|
| One body, two entrances | `doc_tools/assets/semantic_assets.py:486`, `:1597` | `ADR-0041` | — | `built` |
| The domain is the kind's declared domain; neither resolving raises | `semantic_assets.py:53-57`, `:520-555`, `:758-775` | architect's ruling 2026-10-02, quoted at `:523` | `tests/test_ingest_id_and_domain_ruling.py` | `built` |
| Full text once, then per-chunk augmentation with collected failures | `semantic_assets.py:1004`, `:1099`, `:1102`, `:1107` | — | — | `built` |
| The four error classes raise after their stage post | `semantic_assets.py:30`, `:53`, `:293`, `:302`, `:311` | — | — | `built` |
| `review.json` only for an augmentation with a `review` block; one put; a failed write only logs | `semantic_assets.py:1308-1338` | — | — | `built` |
| `approval_state` is the literal `"pending"`, and nothing reads it back | `doc_tools/utils/sustainment_merge.py:303` | — | — | `built` |
| `evidence_ref` and `page_dims` are omitted, never nulled; the reader discriminates on presence | `sustainment_merge.py:296-308` | ruled wire shape, served verbatim by the reader | — | `built` |
| The postable vocabulary is `{extracting, review, failed}`; `received`, `promoted`, `rejected` are not posted | `doc_tools/utils/dagster_resources.py:70`, `:178-190`, `:374-377` | SDK v0.9.8 aligned the vocabularies | `tests/test_ingest_stage_transport.py` | `built` |
| Five failure codes; `reason` and `detail` are one string because a blank detail is refused | `semantic_assets.py:1469`, `:1482`, `:1505`, `:1521-1535`, `:1694` | Lane 1's rule at `ingest_status.update_status`; measured by Lane 1, packet 2026-10-22 | — | `built` |
| The POST is live via `httpx`, non-fatal on every error | `dagster_resources.py:443-465` | — | — | `built` |
| Validation before transport: real `INGEST_STAGES`, Lane 1's id shape, bare hexdigest coerced | `dagster_resources.py:237-268` | import the vocabulary, never mirror it | — | `built` |
| The route requires a `svc:doc-tools` Bearer JWT and 403s others | `dagster_resources.py:180-183`; `doc_tools/utils/mesh_identity.py:189` | — | — | `built` |
| `extracted_count` and `extracted_total` are independent, not a rate; `extraction_ref` is the manifest key | `dagster_resources.py:260-264`; `document_parser.py:605-620` | `ADR-0034` | — | `built` |
| The row contract is domain-generic | `semantic_assets.py:1449-1457` | — | — | `built` |
| The raw-echo sites in the review record, and the load-bearing prefix | `doc_tools/plugins/sustainment.py:773`, `:793-795`, `:815-818`, `:2482-2487` | ruling 2026-11-18 | — | `built` (the echo); the ruling is `accepted` |
| A bounded `(reason_code, reason)` classifier already exists, unused by the review record | `doc_tools/utils/ingest_failure.py:25`, `:76`, `:89`, `:184`, `:198` | — | — | `built` |
