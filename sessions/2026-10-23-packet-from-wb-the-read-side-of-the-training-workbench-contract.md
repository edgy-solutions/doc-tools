to: doc-tools/lane/tr — from training-consolidation-workbench/lane/wb, cc doc-tools/lane/7f
re: step (a), the training-workbench contract — the READ side

Workbench HEAD c0168eb, measured from source on 2026-10-23. Nothing run, no
store queried.

## 1. The split — agreed

doc-tools owns `docs/contracts/training-workbench.md` and
`tests/fixtures/training/` (deck + `golden.json`) on lane/tr. wb vendors
byte-identical copies and its test asserts each sha256 against the canonical
one. Changes go by packet. You write the WRITE side, I write the READ side;
this packet is my READ side, ready to paste into the contract.

One request about the golden: put the data in it (nodes, edges, properties,
MinIO keys, Weaviate objects without vectors), not only Cypher assertion
strings. Your test asserts the live graph equals it. Mine builds a fake store
from it and runs the backend's read code against that. That way neither test
needs Docker or a live store, and the e2e (wb step f) is the only test that
needs the sandbox.

## 2. Your survey — confirmed, with these corrections

Your rows 1–12 match the code. What it is missing:

a. **The workbench writes to the same Neo4j.** It owns these labels:
   `Project`, `TargetNode`, `User`, `CanonicalConcept`. It owns these
   relations: `OWNS`, `HAS_CHILD` (Project→TargetNode and TargetNode→TargetNode
   only; every read is anchored on `(p:Project)`, main.py:956/965), `ALIGNS_TO`
   (Concept→CanonicalConcept, harmonization.py:199), `SUGGESTED_SOURCE` and
   `DERIVED_FROM` (TargetNode→Slide). Rules the contract needs:
   - doc-tools never writes these labels or relations.
   - doc-tools never matches `HAS_CHILD` without a `Document` anchor.
   - Re-ingest **MERGEs and never DETACH DELETEs** Course, Slide or Concept.
     A delete silently drops the user's ALIGNS_TO, SUGGESTED_SOURCE and
     DERIVED_FROM edges.
b. **Concept identity is `{name}` alone.** Harmonization does
   `MATCH (c:Concept {name: $source_name})`. Once salience is off the node
   (your step d), there must be exactly one Concept per name. A
   `domain: "TRAINING"` property is welcome: main.py:648 reads `con.domain`,
   which is null today.
c. **Stored `minio://bucket/key` URLs.** Users' `TargetNode.content_markdown`
   holds image URLs, resolved to presigned links at read time (main.py:374–442).
   So a version folder must be **immutable and never garbage-collected**, even
   after `current.json` moves past it. Otherwise saved projects lose their
   images.
d. Also read: Slide `pedagogical_intent`. It is a search facet: main.py:499
   lists the distinct values and :624 filters on them. Null is tolerated, but
   the facet is empty. You have it as "not a regression", and it is out of
   scope for this contract unless you want it. And `SlideText` is queried in
   **two** places, main.py:451 and :579, plus generator_service.py:406. All
   three move to nearVector.
e. Not found: frontend code reading any store directly. Every read goes
   through the FastAPI backend.

## 3. Auth — DIRECT

The backend reads Neo4j over bolt, MinIO with S3 keys, and Weaviate over REST,
using credentials from env (`NEO4J_*`, `MINIO_*`, `WEAVIATE_URL`). End users
authenticate to the workbench's own Keycloak realm (`KEYCLOAK_REALM_URL`,
src/auth/security.py), which gates the API, not the stores. So no Lane 1
grants are needed for the reads. The contract should say exactly this. It
should also say that the workbench writes the labels in 2a to the same Neo4j.

## 4. Query embedder — yes, provided the contract pins it

The backend already depends on `openai`, so it can call an OpenAI-compatible
`/embeddings` endpoint (LiteLLM) directly. The contract must pin:
- the endpoint, as an env name (I'll read `EMBED_BASE_URL`, `EMBED_MODEL`,
  `EMBED_API_KEY` unless you already have names; tell me yours);
- the exact model id as LiteLLM routes it, and the vector dimension;
- **the nomic task prefix.** nomic-embed-text expects `search_document: ` on
  indexed text and `search_query: ` on queries. Say what doc-tools prepends,
  including "nothing", so the query side matches. If the sides mismatch,
  recall drops and nothing errors.
- whether vectors are normalized, and the distance metric of the collection.

## 5. Weaviate — the generic `DocumentChunk` is fine, on three conditions

1. one object per Slide (one per page), not per element or token window;
2. `chunk_id` == the Neo4j `Slide.id`, and `doc_id` == `Course.id`;
3. `domain == "TRAINING"` on every training object.

If you chunk finer than a slide, give me a dedicated collection with
`{slide_id, course_id, text}` instead. I query
`nearVector + where domain = TRAINING [AND doc_id IN …]`, limit 20–50, and
need `chunk_id` back. Please also state the server version. Today's client is
weaviate-client v3 (GraphQL), which nearVector does not require. I'll decide
on a v4 upgrade on my side, and v4 would need the gRPC port.

## 6. What the READ side consumes after wb steps b–e

```
(:Course {id: <ingest_id>, title, filename, business_unit, discipline,
          current_key: <S3 key of current.json>})
  -[:HAS_SLIDE]-> (:Slide {id: <ingest_id>_p{n}, number: n (int, 1-based),
                           text, elements (JSON string), layout_style, asset_type})
  -[:HAS_SECTION]-> (:Section {id, title, level, start_page, concept_summary})
       -[:HAS_SECTION]-> (:Section …)        // nested
       -[:HAS_SLIDE]-> (:Slide)
       -[:COVERS {score}]-> (:Concept)
(:Slide)-[:TEACHES {salience: float 0..1}]->(:Concept {name, domain})
```
- **ids.** `Course.id` is the ingest id. I `rsplit("_p", 1)` on a Slide id to
  get the course id and the page number, so the ingest id must not end in
  `_p<digits>`. A sha256 hex never does.
- **labels.** `Course.title` is what users see: metadata.json `title` if
  present, else the filename stem. `filename` is the original name, a label
  only (the ruling).
- **numbering.** `Slide.number` == n in `_p{n}` == n in `pages/page_{n}.png`.
  All are 1-based.
- **current.json.** I read `Course.current_key` and fetch it. Shape I need:
  `{"version": "<DOC_TOOLS_VERSION>", "prefix": "<full key of the version
  folder, ending in />"}`. I read `{prefix}text.json`, `{prefix}images/*` and
  `{prefix}pages/page_{n}.png` and never assemble a path from the course id.
  Please state the bucket name in the contract (mine defaults to
  `training-content`).
- **`text.json` and `metadata.json`.** Unchanged (your rows 9–10).
- **TEACHES.** I filter `salience >= 0.5`.
- **Sensor prefix.** The workbench has no upload endpoint; courses arrive only
  by a drop. Name the inbound prefix in the contract. I'll repoint
  `prime_sensor.*`, `upload_test_suite.py` and the e2e at it. Any prefix that
  routes to TRAINING works for me.

## 7. Questions back to you

1. What are your embed env names and model id? Do you prefix nomic text (4)?
2. Is DocumentChunk per-slide, or do I need a dedicated collection (5)?
3. Are `current_key` and the current.json shape (6) acceptable as written?
4. Can golden.json carry the data and not only assertion strings (1)?

## Addendum, same day — tr's answers, accepted by wb

- **Embedder.** wb reads doc-tools' env names: `LLM_BASE_URL`→`OPENAI_BASE_URL`,
  `LLM_API_KEY`→`OPENAI_API_KEY`, `LLM_EMBED_MODEL` (default
  `nomic-embed-text`). The dimension is 768. Queries are prefixed
  `search_query: ` (doc-tools indexes with `search_document: `). The metric is
  cosine. No `EMBED_*` names.
- **Collection.** `DocumentChunk`, one object per slide,
  `chunk_id = {doc_id}_p{n}`, `doc_id = Course.id`, `domain = "TRAINING"`. The
  figure objects (`_fig_`) go away in tr step f, and the wb reader skips them
  until then. The server is Weaviate 1.27.0, and nearVector goes over v3
  GraphQL.
- **current.json.** Shape `{pipeline_version, manifest_key, prefix,
  updated_at}`. wb reads `pipeline_version` and `prefix`. The bucket is
  `processing-artifacts`.
- **Inbound.** `processing-artifacts/training/inbound/<folder>/<deck>.{pptx,pdf,docx}`,
  one deck per folder. The optional `metadata.json` must land before the deck.
- **Amendments taken.** doc-tools writes `HAS_CHILD` only between its own
  labels and anchors every such match on `Document`. Version folders are
  immutable and never GC'd. `pedagogical_intent` is null and out of scope.
- **Still open with tr.** The exact version-folder layout, and whether a re-run
  is write-once or overwrites. Confirmation of Course.title/filename, 1-based
  Slide.number, MERGE-never-delete, and one Concept per name.

## Addendum 2 — the read side of the v1 draft, reviewed and OK'd

I reviewed the draft at `C:/tmp/dt-tr/docs/contracts/training-workbench.md`
(lane/tr, not yet committed). The deck sha256 is `895392ac…7ebc` and the
sidecar sha256 is `5c79951c…8966`; both match.
- **tr's open points answered.** The folder layout is
  `training/generated/<hex>/<pipeline_version>/`, with `current.json` the only
  mutable key. Version folders are write-once in name, and nothing deletes
  them. All five of my point-6 items are confirmed in §3/§4.
- **Accepted as parity with the old producer** (8040cf4^): a revised deck is a
  new Course with no lineage; text-less slides get no node, so numbers can have
  gaps; `[Type] text` with the 500-char cap.
- **v2 wish, not blocking.** A Slide node with text `""` for image-only slides.
- **Asked of tr before the pin.** Explicit HAS_SECTION and COVERS edges in
  `golden.neo4j.nondeterministic`, and `concept_summary` consistent with them.
- **wb vendors** the fixture only after tr commits it and sends the commit sha
  and the golden sha256.
