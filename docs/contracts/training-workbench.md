# Contract: doc-tools → training-consolidation-workbench

**Contract version 2. Status: DRAFT, 2026-10-23.** v2 moves the drop to `training/course/` so the path carries the kind (§2); v1's sensor-declared kind had no mechanism.

| Role | Owner |
|---|---|
| Write side, fixture and golden | `doc-tools/lane/tr` |
| Read side | `training-consolidation-workbench/lane/wb` |
| Ruling | architect's "RESTORE TRAINING INGESTION — ADR-0059" packet |

This file states what doc-tools writes for a training document and what the workbench may rely on.
- The machine-readable form is [`tests/fixtures/training/golden.json`](../../tests/fixtures/training/golden.json), which shows what doc-tools writes for the fixture deck.
- If this prose and the golden disagree, the golden wins.
- Both repos test against the same fixture bytes.

## 1. Stores and auth

- **One set of stores: the sandbox's.** That means Neo4j (`iagent-neo4j`), MinIO, and Weaviate 1.27.0 (`iagent-weaviate`). There is no compose stack.
- **The workbench reads the stores DIRECTLY.**
  - It uses bolt for Neo4j, S3 keys for MinIO, and Weaviate REST/GraphQL.
  - Credentials come from its own env: `NEO4J_*`, `MINIO_*`, `WEAVIATE_URL`.
  - End users authenticate to the workbench's own Keycloak realm, which gates the workbench API and not the stores.
  - So the reads need no Lane 1 domain and no grants.
- **The workbench also WRITES to the same Neo4j** (§4.4).
- **Direct store reads are the interim, not the destination.** ADR-0060 (consumers read through the mesh) is in draft. When its manifest route lands, the store reads are replaced by one client; what this contract says the workbench needs stays the same.

## 2. The drop: how a course arrives

The workbench has no upload endpoint. A course arrives only as a drop into MinIO.

| | |
|---|---|
| Bucket | `processing-artifacts` |
| Deck | `training/course/<folder>/<deck>.pptx` \| `.pdf` \| `.docx` |
| Sidecar (optional) | `training/course/<folder>/metadata.json` |

- Put one deck in each folder. `<folder>` is free text and carries no identity.
- `metadata.json` must land **before** the deck. The parser reads it when the deck's run starts, so a sidecar that arrives later is not seen.
- **The path carries the kind, by ADR-0021's existing rule** (`<domain>/<kind>/<folder>/<file>`): the first segment is the domain, `training` → `TRAINING`; the second is the content kind, `course`.
  - A kind names the document, not the domain: a course in the training domain, the way a PCN is a notice in sustainment.
  - Nothing new is invented: no sensor-supplied kind, no new precedence level. The precedence stays ADR-0021's metadata > path > HALT.
- A training sensor watches `training/course/`. It ignores `generated/`, `archive/` and `metadata.json` keys, and accepts only `.pptx`, `.pdf` and `.docx`.
- **The sidecar needs no `content_kind` or `domain_type`.** If it has them, they must be `course` and `training`: a sidecar value wins over the path, so any other value re-routes the drop.
- **Re-uploading the same bytes to the same key does NOT start a new run.** The run key is `{ETag}-{key}`, so it is consumed. To re-ingest, use a new key.

`metadata.json` keys (all optional):

| Key | Course property it fills |
|---|---|
| `title` | `title` |
| `business_unit` | `business_unit` |
| `engineering_discipline` | `discipline` |
| `audience` | `audience` |
| `level_of_material` | `level` |
| `current_delivery_method` | `delivery_method` |
| `duration_hours` | `duration_hours` |
| `version` | `version` (the course's own version, not the pipeline's) |

## 3. Identity

- **`Course.id` is the ingest id**: `sha256:<64 lowercase hex>` of the deck's bytes (`doc_tools/utils/ingest_id.py:mint_ingest_id`). When a Lane 1 sidecar is present, its ingest id is used instead; it is the same value for the same bytes.
- **The filename is a label, never an id.** Two folders that both hold `deck.pptx` with different bytes give two Courses. The same bytes in two folders give ONE Course.
- **A revised deck is a NEW Course.** New bytes give a new ingest id. The old Course, its Slides and the users' edges into them stay. doc-tools records no lineage between the two.
- **`Slide.id` = `{Course.id}_p{n}`**, where `n` is the 1-based slide or page number. The workbench may use `rsplit("_p", 1)`, because an ingest id never ends in `_p<digits>`.
- **`Section.id` = `{parent.id}_s{i}`**, where `i` is 0-based within the parent. Nested sections give `{Course.id}_s1_s0`.
- **A Concept's identity is `(domain, normalized name)`, and `id` is that identity's stable key** — `id` = `hash(domain, normalized name)`, *not* a second identity. There is one `(:Concept:TRAINING)` per `(domain, normalized name)` across all courses. Two names differing only in case, whitespace or Unicode form are the SAME concept; `Torque Control` in two different domains is two concepts, which is why the constraint is on `id` and **not** on `name`. MERGE on `id`; `concept_id_unique` constrains it.
  - **`name` is a display label, never a join key.** It is written `ON CREATE` only, so of two spellings that normalize alike the node keeps whichever was written first. Show `name`; match on `id`.
  - **`name_normalized` is stored on the node**, so the id is recomputable from the node itself — an audit or a migration does not have to trust that whatever wrote the node used `doc_tools/utils/concept_identity.py`.
  - This supersedes the earlier wording, which called `name` the identity and said `id` "is not an identity". That was wrong in both halves, and lane tr was right to object: it described neither the shape the architect ruled on 2026-10-24 nor what `#167` ships.

## 4. Neo4j

### 4.1 Nodes

| Labels | Merge key | Properties the workbench may rely on |
|---|---|---|
| `Document:Course:TRAINING` | `id` | `id`, `title`, `filename`, `current_key`, `business_unit`, `discipline`, `audience`, `level`, `delivery_method`, `duration_hours`, `version` |
| `Chunk:Slide:TRAINING` | `id` | `id`, `number` (int, 1-based), `text`, `elements` (JSON string), `layout_style`, `asset_type` |
| `Section:TRAINING` | `id` | `id`, `title`, `level` (int), `start_page`, `end_page` (int; `0` means open), `concept_summary` (list of up to 10 names, by COVERS score descending) |
| `Concept:TRAINING` | `id` | `id`, `name`, `name_normalized`, `domain` = `"TRAINING"` |

Course properties:
- `title` is metadata.json `title`, or the filename stem if there is none.
- `filename` is the original filename, as a label only.
- `current_key` is the S3 key of `current.json` (§5).

Slide properties:
- `text` is the slide's elements, one line each in the form `[<Type>] <text>`. Elements with empty text are left out. It is truncated to 500 characters; Weaviate holds the full text.
- `elements` is the slide's Unstructured `to_dict()` elements, JSON-encoded.
- `asset_type` is the upper-cased extension, for example `PPTX`.

Extra properties may appear on any node: `provenance_*`, Slide `title`/`content`/`page_start`, `Figure` nodes. The workbench must not depend on any of them.

### 4.2 Edges

```
(:Course)-[:HAS_CHILD]->(:Slide)            generic, every kind
(:Course)-[:HAS_SLIDE]->(:Slide)            training overlay
(:Course)-[:HAS_SECTION]->(:Section)
(:Section)-[:HAS_SECTION]->(:Section)       nested
(:Section)-[:HAS_CHILD]->(:Slide)           generic
(:Section)-[:HAS_SLIDE]->(:Slide)           training overlay
(:Section)-[:COVERS {score, frequency}]->(:Concept)
(:Slide)-[:TEACHES {salience}]->(:Concept)  salience: float in [0, 1], ON THE EDGE
```

How the computed edges are derived:
- **Section → Slide**: a Section reaches every Slide with `start_page <= number <= end_page`, or `number >= start_page` when `end_page` is 0. A nested Slide is reached by its parent Section too.
- **COVERS**: `score` is the mean TEACHES salience over the Slides the Section reaches, and `frequency` is how many such Slides there are. All saliences count here; the workbench applies its `>= 0.5` filter only to TEACHES.

### 4.3 Overlay names come from data

- doc-tools writes the generic structure (`Document`, `Chunk`, `HAS_CHILD`) for every kind.
- The training kind's persistence descriptor adds `Course`, `Slide` and `HAS_SLIDE`, and puts the salience on TEACHES.
- Neither side renames anything by hand.

### 4.4 Ownership: what doc-tools never touches

The workbench writes these labels and relations to the same Neo4j:
- labels `Project`, `TargetNode`, `User`, `CanonicalConcept`;
- relations `OWNS`, `HAS_CHILD` between Project and TargetNode, `ALIGNS_TO` (CanonicalConcept → Concept), and `SUGGESTED_SOURCE` and `DERIVED_FROM` (TargetNode → Slide).

doc-tools follows four rules here:
1. **doc-tools never writes, and never MATCHes, those labels**, and never writes `OWNS`, `ALIGNS_TO`, `SUGGESTED_SOURCE` or `DERIVED_FROM`.
2. **doc-tools writes `HAS_CHILD` only between its own labels**: Document/Course, Chunk/Slide and Section.
3. **Every doc-tools `HAS_CHILD` match is anchored on a Document** (or a Section reached from one). The workbench's Project-anchored reads never see these edges.
4. **A re-ingest MERGEs; it never `DETACH DELETE`s a Course, Slide or Concept.** A delete would silently drop the users' `ALIGNS_TO`, `SUGGESTED_SOURCE` and `DERIVED_FROM` edges.

A consequence of rule 4: re-running the same bytes with a different LLM answer can leave a stale TEACHES edge to a concept the new answer dropped. That is accepted.

## 5. MinIO

The bucket is `processing-artifacts`. Let `<hex>` be the ingest id without its `sha256:` prefix.

```
training/generated/<hex>/current.json                       the ONLY mutable key
training/generated/<hex>/<pipeline_version>/text.json
training/generated/<hex>/<pipeline_version>/manifest.json
training/generated/<hex>/<pipeline_version>/images/<name>   embedded media, e.g. slide_4_img_0.png
training/generated/<hex>/<pipeline_version>/pages/page_<n>.png
```

- **`current.json`** = `{"pipeline_version", "manifest_key", "prefix", "updated_at"}`.
  - `prefix` is the full key of the live version folder and ends in `/`.
  - The workbench reads `pipeline_version` and `prefix` only. It reads `{prefix}text.json`, `{prefix}images/*` and `{prefix}pages/page_{n}.png`, and never builds a path from the course id.
  - `Course.current_key` holds this key.
- **`pages/page_<n>.png`** is a raster of slide or page `n`. Here `n` == `Slide.number` == the `n` in `_p{n}`. Every slide gets one, including a slide with no text.
- **`text.json`** is a list of Unstructured `to_dict()` elements.
- **Version folders are write-once in name and never deleted or renamed.** This holds even after `current.json` has moved past them, because users store `minio://` URLs into them.
  - A re-run with the same bytes and the same `pipeline_version` overwrites the same names in place, with the same content for every deterministic file.
  - A new `pipeline_version` writes a new folder beside the old one and then moves `current.json`.
  - Nothing garbage-collects `training/generated/`.

## 6. Weaviate

- **Server and collection.** The server is Weaviate 1.27.0 and the collection is `DocumentChunk`. It has no vectorizer module. doc-tools writes every object WITH its vector, so the workbench queries with `nearVector`; `nearText` will not work. The distance is the server default, cosine.
- **Properties.** `text`, `doc_id`, `chunk_id`, `domain`, all of type TEXT.
- **One object per Slide that has text.** For each:
  - `chunk_id` == `Slide.id`
  - `doc_id` == `Course.id`
  - `domain` == `"TRAINING"`
  - `text` == the slide text, untruncated
  - the object uuid is `weaviate.util.generate_uuid5(chunk_id)`
- **No figure objects.** No training object's `chunk_id` contains `_fig_`. Other kinds still write figure objects to this collection, which is why wb's query filters on `domain`.
- **Query shape:** `nearVector` + `where domain = "TRAINING"` (optionally `AND doc_id IN …`), returning `chunk_id`.

## 7. Embedder

The query side must match these exactly. A mismatch drops recall and raises no error.

| | |
|---|---|
| Endpoint | OpenAI-compatible `/embeddings` (LiteLLM) |
| Env: base URL | `LLM_BASE_URL`, falling back to `OPENAI_BASE_URL` |
| Env: key | `LLM_API_KEY`, falling back to `OPENAI_API_KEY` |
| Env: model | `LLM_EMBED_MODEL`, default `nomic-embed-text` |
| Dimension | 768 (asserted by doc-tools) |
| Prefix on indexed text | `search_document: ` |
| Prefix on queries | `search_query: ` |
| Normalization | none client-side (cosine is scale-invariant) |

Source: `doc_tools/utils/embed.py`.

## 8. Fixture and golden

The fixture lives in `tests/fixtures/training/`:

| File | Role |
|---|---|
| `hydraulics_fixture.pptx` | The canonical deck: 4 slides, with one image on slide 4. It is made by `make_deck.py`; regenerating gives the same content but different bytes, so a regeneration is a contract change. |
| `metadata.json` | Its sidecar. |
| `golden.json` | What doc-tools writes for the deck. The deterministic half is derived from the real extraction by `make_golden.py`. |

- **Pinned hashes.** `golden.json` pins the deck and sidecar sha256 values. wb vendors byte-identical copies and asserts those hashes.
- **Placeholders.** `<pipeline_version>` and `<iso8601>` match any value.
- **Volatile element keys.** The keys in `volatile_element_keys` are stripped from both sides before `elements` is compared (temp path, mtime, element hashes).
- **`nondeterministic`** (sections, concepts, teaches) is LLM-derived EXAMPLE data. doc-tools asserts its SHAPE only: labels, id grammar, `start_page` naming a real slide, salience in [0, 1], one Concept per `(domain, normalized name)` (§3). wb loads it as fake-store data. The example includes a salience under 0.5 (slide 4, "Hydraulic pressure") and a concept shared by two slides.
  - Its `edges` block lists every `HAS_SECTION`, Section → Slide, `COVERS` and `TEACHES` edge explicitly, already computed by the §4.2 rules, so a fake store loads edges and derives nothing.
  - Each Section's `concept_summary` agrees with its `COVERS` scores.
- **The doc-tools gate.** `tests/test_training_workbench_golden.py` holds one test per surface. A surface that a later lane-tr step delivers is `xfail(strict=True)` until that step's PR, which must flip it. Each step's PR is green only with its surface passing.
- **The wb gate.** The workbench's test builds a fake store from `golden.json` and runs its read code against it. wb's end-to-end test drops the fixture into the sandbox and sees the course; that is the finish line.

## 9. Delivery: which lane-tr step makes each surface true

| Surface | Step |
|---|---|
| this contract, fixture and golden | a |
| `course` kind row (domain `training`) and sensor on `training/course/` (§2) | b |
| ids (§3); `training/generated/<hex>/<ver>/`; `current.json` with `prefix`; `Course.current_key`/`title`/`filename`; `Course`/`Slide`/`HAS_SLIDE` overlay; slide text without empty-text lines | c |
| TEACHES salience on the edge | d |
| Concept keyed on `id` = `hash(domain, normalized name)` with a uniqueness constraint (§3) | d merged it on `name`; re-keyed by `#167` (lane 7f) |
| `pages/page_{n}.png` (`render.pages`, LibreOffice + Poppler) | e |
| vectors written for `nearVector`; no `_fig_` objects for training | f |
| Section page numbers from element metadata, never from the LLM (`structural.outline`) | g |
| COVERS / `concept_summary` stay a post-graph hook (`execute_pass2_rollup`) | h |

## 10. Known gaps (not promised by v2)

- **A slide with no text gets a Slide node with `text` `""` and no Weaviate object, unless it is the last slide.** Unstructured emits a `PageBreak` element after every slide but the last. So a blank or image-only slide mid-deck still has an element on its page, but a blank or image-only *final* slide has none and gets no Slide node at all. The result is that `Slide.number` has no interior gaps but can stop short of the deck's slide count, and the workbench must tolerate that. This was measured on the fixtures `empty-blank-slide` (p5), `image-multi-per-slide` (p4) and `image-only-deck` (p5). **It still gets `pages/page_{n}.png`**: the page render counts the deck's slides, not its elements. So `pages/` can hold one more PNG than there are Slide nodes. Hidden slides are rendered too, because the export sets `ExportHiddenSlides`, and `page_{n}` always equals slide `n` of the deck. wb may counter this in a packet.
- **Speaker notes are slide text.** Unstructured emits a slide's notes as `NarrativeText` elements on that slide, ahead of its body in reading order. A slide whose only text is its notes is a text slide (fixture `empty-whitespace-and-notes`, p3 and p4).
- **Hidden slides are ingested like any other.** No Slide property marks them (fixture `long-with-hidden-slides`, p30, p31 and p90).
- **A re-ingest of the same bytes adds a second outline.** Section ids are positions in the outline the LLM returned (`{Course.id}_s0_s1`), and the write is a MERGE. So a second run that samples a differently shaped outline leaves both under the Course (fixtures `dup-same-bytes-a`/`-b`: 15 Sections, 8 titles). This is step g's to close.
- **docx page numbers.** Unstructured gives docx a `page_number` only if the file has `w:lastRenderedPageBreak`; otherwise everything lands on page 1. pptx (slide index) and pdf are exact. docx is best-effort in v2.
- **`Slide.pedagogical_intent` is not written.** The facet is empty.
- **No lineage between revisions** of the same course (§3).

## 11. Changing this contract

- The owning lane edits this file. The other side asks by packet.
- Any change to `golden.json`'s non-placeholder content bumps `contract_version` and goes to wb by packet with the new hashes.
