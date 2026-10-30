# Contract: doc-tools → training-consolidation-workbench

**Contract version 5. Status: DRAFT, 2026-10-29.** v5 moves `CanonicalConcept`/`ALIGNS_TO` creation from the workbench's LLM harmonizer to doc-tools' `concepts.normalise` pass (§4.7) and adds `PROPOSED_ALIGNS_TO`. v2 moves the drop to `training/course/` so the path carries the kind (§2); v1's sensor-declared kind had no mechanism. v3 builds Sections from the deck's own section slides, or anchors the LLM's titles to element pages; sets `Course.outline_source`; and replaces the Section subtree on re-ingest. v3 also keys Concept on `id` = hash(domain, normalized name), with `name_normalized` on the node (§3, from #167). v4 extracts concepts in one call per section group (§4.6), writes Section `summary`/`objectives`, TEACHES `related_terms`, candidate `ALIAS_OF` edges between Concepts, and one Weaviate object per Section with notes (§6); slide objects carry `chunk_kind = "slide"`.

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
| `Document:Course:TRAINING` | `id` | `id`, `title`, `filename`, `current_key`, `business_unit`, `discipline`, `audience`, `level`, `delivery_method`, `duration_hours`, `version`, `outline_source` (`"deck"` or `"llm"`) |
| `Chunk:Slide:TRAINING` | `id` | `id`, `number` (int, 1-based), `text`, `elements` (JSON string), `layout_style`, `asset_type` |
| `Section:TRAINING` | `id` | `id`, `title`, `level` (int), `start_page`, `end_page` (int, always `>= start_page`; v2 wrote `0` for open, and v3 never does), `concept_summary` (list of up to 10 names, by COVERS score descending), `summary` (string; absent when the model gave none), `objectives` (list of strings, may be empty). `summary` and `objectives` are nondeterministic (§4.6). |
| `Concept:TRAINING` | `id` | `id`, `name`, `name_normalized`, `domain` = `"TRAINING"` |
| `CanonicalConcept:TRAINING` | `id` | `id`, `name`, `domain`, `source` = `"concepts.normalise"`, `created_at`. Written by the pass (§4.7). A cc the workbench's old harmonizer wrote has no `id` and no `source`; the pass reads it by `coalesce(id, name)` and never sets a property on it. |

Course properties:
- `title` is metadata.json `title`, or the filename stem if there is none.
- `filename` is the original filename, as a label only.
- `current_key` is the S3 key of `current.json` (§5).

Slide properties:
- `text` is the slide's elements, one line each in the form `[<Type>] <text>`. Elements with empty text are left out. It is truncated to 500 characters; Weaviate holds the full text.
- `elements` is the slide's Unstructured `to_dict()` elements, JSON-encoded.
- `asset_type` is the upper-cased extension, for example `PPTX`.

Section properties:
- `title` has its section number removed.

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
(:Slide)-[:TEACHES {salience, related_terms}]->(:Concept)  salience: float in [0, 1], ON THE EDGE; related_terms: list of strings
(:Concept)-[:ALIAS_OF {status: "candidate", source: "related_terms", course_id}]->(:Concept)
(:CanonicalConcept)-[:ALIGNS_TO {status, method, confidence, source, updated_at}]->(:Concept)
(:CanonicalConcept)-[:PROPOSED_ALIGNS_TO {status: "open"|"rejected", confidence, method, evidence, cos}]->(:Concept)
```

The alignment edges run CanonicalConcept → Concept, as the workbench's code reads them. (The workbench's own copy of this contract says the reverse at its line 118; that is a correction to make there.) Their rules are §4.7.

How the computed edges are derived:
- **Section → Slide**: a Section reaches every Slide with `start_page <= number <= end_page`, or `number >= start_page` when `end_page` is 0. A nested Slide is reached by its parent Section too.
- **COVERS**: `score` is the mean TEACHES salience over the Slides the Section reaches, and `frequency` is how many such Slides there are. All saliences count here; the workbench applies its `>= 0.5` filter only to TEACHES.
- **TEACHES `related_terms`**: the model's other names for the concept as it taught it on that Slide (abbreviations, synonyms), stripped, empty strings dropped. A list, `[]` when none.
- **ALIAS_OF**: for each TEACHES `(concept, term)` where `normalize(term) != normalize(concept.name)`, one edge from the Concept to the Concept whose `id` is `hash(domain, normalized term)`, with `status = "candidate"`, `source = "related_terms"` and `course_id` = the Course id.
  - The edge is written **only to a Concept that exists at write time** (this run's, or an earlier course's). A term that names no Concept writes nothing and creates no Concept.
  - It is **never a merge** of the two nodes; it is a candidate for the normalisation pass.
  - One edge per pair. A re-ingest never deletes it, like Concepts themselves (§4.4).

### 4.3 Overlay names come from data

- doc-tools writes the generic structure (`Document`, `Chunk`, `HAS_CHILD`) for every kind.
- The training kind's persistence descriptor adds `Course`, `Slide` and `HAS_SLIDE`, and puts the salience on TEACHES.
- Neither side renames anything by hand.

### 4.4 Ownership: what doc-tools never touches

The workbench writes these labels and relations to the same Neo4j:
- labels `Project`, `TargetNode`, `User`;
- relations `OWNS`, `HAS_CHILD` between Project and TargetNode, and `SUGGESTED_SOURCE` and `DERIVED_FROM` (TargetNode → Slide).

`CanonicalConcept`, `ALIGNS_TO` and `PROPOSED_ALIGNS_TO` are shared since v5, and doc-tools writes them **only as §4.7 says**. What the pass owns, and may create, change and delete: auto `ALIGNS_TO` edges (`status = "auto"`), open proposals (`status = "open"`), and `CanonicalConcept` nodes whose `source = "concepts.normalise"`. What the workbench keeps is the decisions:
- **Accepting a proposal** = delete the proposal, delete the Concept's auto `ALIGNS_TO`, write `ALIGNS_TO {status: "accepted"}`.
- **Rejecting** = `SET p.status = "rejected"`.
- The pass never changes or deletes an `ALIGNS_TO` whose status is not `"auto"` (an accepted one, or a legacy one with no status), or a rejected proposal.
- The workbench stops writing `CanonicalConcept` from its harmonizer: its `harmonize_concepts` asset and `unharmonized_concepts_sensor` must be turned off when this lands, or two writers MERGE CanonicalConcepts on different keys (the workbench's by `name`, the pass's by `id`).

doc-tools follows four rules here:
1. **doc-tools never writes, and never MATCHes, `Project`, `TargetNode` or `User`**, and never writes `OWNS`, `SUGGESTED_SOURCE` or `DERIVED_FROM`. It MATCHes `CanonicalConcept` only in the pass (§4.7).
2. **doc-tools writes `HAS_CHILD` only between its own labels**: Document/Course, Chunk/Slide and Section.
3. **Every doc-tools `HAS_CHILD` match is anchored on a Document** (or a Section reached from one). The workbench's Project-anchored reads never see these edges.
4. **A re-ingest MERGEs; it never `DETACH DELETE`s a Course, Slide or Concept.** A delete would silently drop the users' `ALIGNS_TO`, `SUGGESTED_SOURCE` and `DERIVED_FROM` edges. Sections are the exception. A re-ingest builds the new outline completely, then in one transaction `DETACH DELETE`s this Course's `Section:TRAINING` nodes (those reached by `HAS_SECTION` from it, or whose `id` starts with `{Course.id}_s`) and writes the new ones. No workbench relation ends at a Section, so no user edge is lost. The same run rewrites `HAS_SECTION`, Section → Slide and `COVERS`. If the build fails, the old Sections stay and the run fails.

A consequence of rule 4: re-running the same bytes with a different LLM answer can leave a stale TEACHES edge to a concept the new answer dropped. That is accepted.

### 4.5 The outline

A Course's Sections come from `structural.outline` (`doc_tools/passes/structural.py`). **Page numbers are element `page_number`, never the LLM's.**

- **Deck path.** A slide is a section header when its elements, ignoring `PageBreak` and empty or whitespace text, are exactly one: a `Title` at `category_depth` 0 (or none) whose text is a number then a heading, such as `1.1.1 Pumps`.
  - The level is the number of dot-separated components, the `title` is the heading without its number, and `start_page` is the slide's page.
  - If the deck has any such slide, the outline is built from those slides alone and no LLM is called (`Course.outline_source` = `"deck"`).
  - A title slide (two Titles), an agenda slide (several elements), a content slide (a Title plus a body) and an unnumbered single-Title slide are not headers.
- **LLM path.** Otherwise the LLM outline supplies titles and nesting only (`outline_source` = `"llm"`). Its `level`, `start_page` and `end_page` are ignored.
  - The outline is walked in order, with a cursor at page 1. An LLM section is anchored to the smallest page at or after the cursor that holds a `Title` element with the same title (compared after NFKC, with a leading section number, a trailing ` (n)` counter and case removed). The cursor moves to that page.
  - A section with no such page is dropped and its anchored children move up to its parent, one level shallower. A section equal (title and page) to one already kept, as chunk overlap produces, is dropped.
  - An LLM path that anchors nothing is a legitimately empty outline, not a failure. A failed LLM call on any chunk fails the build.
- **Nesting.** A section nests under the nearest earlier section with a smaller level, or under the Course. A numbering gap (`1` then `1.1.1`) nests under the nearest shallower section and keeps its own level.
- **End pages.** A section's `end_page` is the `start_page` of the next later section whose level is the same or shallower, minus 1; if there is none, it is the deck's last page. It is never below `start_page`, so an empty section ends on its own page, and it is never `0`.

### 4.6 Concept calls

Concepts, TEACHES `related_terms`, figure references and Section notes come from `ExtractSectionConcepts` (`baml_src/training.baml`), one call per group of slides, planned by `doc_tools/utils/concept_groups.py`:
- A slide belongs to the DEEPEST outline section whose page range holds it (of two at one depth, the later start). Slides outside every section are unsectioned.
- Consecutive slides of one section form a run. A run longer than 8 slides (`MAX_SLIDES`) is split into near-equal pieces (20 slides give 7, 7, 6).
- Runs are packed, in page order, into calls of at most 8 slides **without splitting a run**. So a section is split only when it alone is longer than 8, and short sections share a call, each under its own `=== Section: <title> ===` marker. A nested child splits its parent's run, so a parent can appear twice in one call.
- The text sent is `=== Slide N ===` blocks under those markers. The reply has one entry per slide and one note per section marker.
- `TRAINING_CONCEPT_CONCURRENCY` (default `1`, minimum `1`) is the number of calls in flight at once. Results are assembled in call order whatever the completion order.
- **One retry.** A call that raises, or whose reply lacks an entry for any slide of the call, is retried once. After that, a raise fails every slide of the call; a missing slide fails that slide alone. Reply entries for slides not in the call are ignored; for a duplicated slide the first wins. A failed slide makes the run end `failed:concept_parse` (writes for the other slides still happen). A salience outside `[0, 1]` is clamped.
- **Section notes are best effort and never a failure.** They are paired with the call's section markers by position when the counts match, else by title (case and whitespace folded). Unpaired notes are dropped and an unsectioned run gets none. A section split across calls merges its notes in page order: summaries joined by a space, objectives concatenated and de-duplicated.
- The Section `summary`/`objectives` and TEACHES `related_terms` are nondeterministic; the golden shows their shape only.

### 4.7 Concept alignment

`concepts.normalise` (`doc_tools/passes/concepts.py`) unifies the Concepts of a domain into CanonicalConcepts. It is deterministic, calls no LLM, and never merges Concept nodes or writes `ALIAS_OF`. Inputs: Concept names, TEACHES `related_terms`, and the Weaviate vectors of the Slides that teach each Concept.

- **Key.** `align_key(name)` is the §3 normalisation, then every non-alphanumeric character becomes a space, then whitespace collapses: `Hydraulic-Pump`, `HYDRAULIC PUMP` and `Hydraulic/Pump` share a key; `Lockout/Tagout` is `lockout tagout`.
- **Auto links** (undirected): `exact` (same key, confidence 1.0) and `mutual_related_terms` (a term of A has B's key AND a term of B has A's key, 0.95). A **component** is a connected set of auto-linked Concepts; a Concept with no link is a component of one (`self`, 1.0). Each member's edge carries the strongest method incident to it.
- **One CanonicalConcept per component, with sticky ids.** The cc id is, in order: the single cc the component's pinned members already share; else the cc held by most members' auto edges (tie: smallest id; a cc never serves two components); else `canonical_` + the first 16 hex of sha256(`domain`, `\x1f`, align key of the chosen name). The chosen name is the member with the most TEACHES edges, then the shortest, then the smallest. `name` is set only when the pass creates the cc or the cc's `source` is `concepts.normalise`. Every unpinned Concept ends with exactly one auto `ALIGNS_TO`.
- **Pinned.** A Concept with any incoming `ALIGNS_TO` whose status is not `"auto"` is pinned: never given an auto edge, and a stale auto edge of its own is removed. If a component's pinned members name two or more ccs, the unpinned members get no auto edge and one proposal to each of those ccs (counted as a conflicting component).
- **Proposals** are never applied by the pass. A pair in different components that is not co-taught (not taught on the same Slide) and has a lexical signal is proposed in both directions (`cc of B -> A` and `cc of A -> B`), each `{status: "open", confidence, method, evidence (sorted signals), cos}`:

  | signal (strongest present) | with cosine | without vectors |
  |---|---|---|
  | `related_term_one_way` (a term of one has the other's key) | 0.5 + 0.5·max(cos,0) | 0.70 |
  | `plural` (keys meet after stripping a trailing `s` or `es` from tokens of 4+ characters) | 0.5 + 0.5·max(cos,0) | 0.80 |
  | `acronym` (a 2-6 character one-word key equals the initials of the other, 2+ tokens) | 0.4 + 0.5·max(cos,0) | 0.60 |
  | `token_overlap` (Jaccard of token sets ≥ 0.5, sharing a token of 4+ characters) | 0.2 + 0.6·max(cos,0) | 0.40 |

  Kept at `confidence >= TRAINING_ALIGN_PROPOSE_MIN` (default 0.70); at most 5 per target Concept, highest first. Not proposed: a rejected `(cc, Concept)` pair, a target already pinned to that cc.
- **Cosine** is between concept vectors: the mean of the L2-normalised vectors of the Slides that teach the Concept (objects with `chunk_kind = "section"` are skipped). It ranks; it never creates a link.
- **Scope.** Records and components always span the whole domain. A run for one Course (`course_id`, the per-course run at the end of an ingest) writes only for components containing a Concept that Course teaches, and proposals only where one side is taught by it. The fleet run (`scripts/normalise_concepts.py`, `normalise_concepts_job`) writes everything.
- **Orphans.** A cc is `DETACH DELETE`d only if its `source` is `concepts.normalise`, it has no `ALIGNS_TO` of any status, and no relationship except open `PROPOSED_ALIGNS_TO`.
- **Switches.** `TRAINING_CONCEPT_ALIGNMENT` = `dry` (default: plan and log, write nothing), `on`, `off`. The default stays `dry` until the workbench has turned off its `harmonize_concepts` asset and `unharmonized_concepts_sensor`; the switch to `on` is a values change, made by packet; `TRAINING_ALIGN_PROPOSE_MIN`. A failure of the per-course run does not fail the ingest: it is logged as an error and recorded as `concept_alignment = "failed:<ExcType>: <msg>"` in the run's output metadata (`ok`, `off` or `dry` otherwise). The job's `dry_run` defaults to `true`.

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
- **Properties.** `text`, `doc_id`, `chunk_id`, `domain` (TEXT); `page` (INT); `heading`, `section_id`, `chunk_kind` (TEXT). On a TRAINING object `chunk_kind` is `"slide"` or `"section"`; objects written before v4 carry no `chunk_kind`.
- **One object per Slide that has text.** For each:
  - `chunk_id` == `Slide.id`
  - `doc_id` == `Course.id`
  - `domain` == `"TRAINING"`
  - `text` == the slide text, untruncated
  - `chunk_kind` == `"slide"`
  - the object uuid is `weaviate.util.generate_uuid5(chunk_id)`
- **One object per Section that has notes** (a non-empty `summary` or at least one objective; only when the outline was built). For each:
  - `chunk_id` == `Section.id`, and the object uuid is `generate_uuid5(chunk_id)`
  - `doc_id` == `Course.id`, `domain` == `"TRAINING"`, `chunk_kind` == `"section"`
  - `page` == the Section's `start_page`, `heading` == its title, `section_id` == its id
  - `text` == the title, then the summary, then `Objectives:` and one `- ` line each, parts separated by a blank line, empty parts left out
  - a re-ingest deletes the Course's old section objects (`doc_id` and `chunk_kind = "section"`) before writing these.
- **A slide query must now exclude section objects** (`chunk_kind = "section"`): they carry the same `doc_id` and `domain`, and a `nearVector` query on those alone returns them. Objects written before v4 carry no `chunk_kind`, so `== "slide"` would drop them. **Unmeasured:** whether Weaviate's `NotEqual("section")` keeps an object that has no `chunk_kind` at all. Until that is measured on a cluster where the property exists, a reader must not assume it does; re-ingesting a course gives every one of its objects a `chunk_kind`.
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
- **Ownership block (v5).** `neo4j.never_written` lists only `Project`, `TargetNode`, `User` and `OWNS`, `SUGGESTED_SOURCE`, `DERIVED_FROM`; `neo4j.written_only_by` names `CanonicalConcept`, `ALIGNS_TO` and `PROPOSED_ALIGNS_TO` as written only by `concepts.normalise` (§4.4, §4.7).
- **Placeholders.** `<pipeline_version>` and `<iso8601>` match any value.
- **Volatile element keys.** The keys in `volatile_element_keys` are stripped from both sides before `elements` is compared (temp path, mtime, element hashes).
- **`nondeterministic`** (sections, concepts, teaches). Sections are no longer free example data: they are what the real `structural.outline` pass derives from `neo4j.outline.fallback`, the pinned LLM reply (`recorded: false` until a sandbox reply is recorded), and the deck's element pages. A re-run compares its LLM titles to the pinned ones and reports the difference, rather than overwriting. Concepts and teaches are LLM-derived EXAMPLE data. doc-tools asserts their SHAPE only: labels, id grammar, `start_page` naming a real slide, salience in [0, 1], one Concept per `(domain, normalized name)` (§3). wb loads it all as fake-store data. The example includes a salience under 0.5 (slide 4, "Hydraulic pressure") and a concept shared by two slides.
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
| Section page numbers from element metadata, never from the LLM (`structural.outline`); `Course.outline_source`; Section subtree replaced on re-ingest | g |
| COVERS / `concept_summary` stay a post-graph hook (`execute_pass2_rollup`) | h |
| per-section concept call, Section notes, related_terms, ALIAS_OF, section objects | i (#PR A) |
| `concepts.normalise`: CanonicalConcept, auto `ALIGNS_TO`, `PROPOSED_ALIGNS_TO` (§4.7); per-course call on ingest, fleet script and job | j (#PR B) |

## 10. Known gaps (not promised by v5)

- **A slide with no text gets a Slide node with `text` `""` and no Weaviate object, unless it is the last slide.** Unstructured emits a `PageBreak` element after every slide but the last. So a blank or image-only slide mid-deck still has an element on its page, but a blank or image-only *final* slide has none and gets no Slide node at all. The result is that `Slide.number` has no interior gaps but can stop short of the deck's slide count, and the workbench must tolerate that. This was measured on the fixtures `empty-blank-slide` (p5), `image-multi-per-slide` (p4) and `image-only-deck` (p5). **It still gets `pages/page_{n}.png`**: the page render counts the deck's slides, not its elements. So `pages/` can hold one more PNG than there are Slide nodes. Hidden slides are rendered too, because the export sets `ExportHiddenSlides`, and `page_{n}` always equals slide `n` of the deck. wb may counter this in a packet.
- **Speaker notes are slide text.** Unstructured emits a slide's notes as `NarrativeText` elements on that slide, ahead of its body in reading order. A slide whose only text is its notes is a text slide (fixture `empty-whitespace-and-notes`, p3 and p4).
- **Hidden slides are ingested like any other.** No Slide property marks them (fixture `long-with-hidden-slides`, p30, p31 and p90).
- **A section slide is detected only as a single numbered Title.** A header slide that also carries speaker notes, or whose title is unnumbered, is not detected. If no slide in the deck is detected, the deck falls back to the LLM; if others are, that section is simply missing from the outline.
- **An LLM section whose title is no slide Title is dropped.**
- **docx page numbers.** Unstructured gives docx a `page_number` only if the file has `w:lastRenderedPageBreak`; otherwise everything lands on page 1. pptx (slide index) and pdf are exact. docx is best-effort in v2.
- **`Slide.pedagogical_intent` is not written.** The facet is empty.
- **ALIAS_OF reaches only Concepts that existed when the course was written;** a later course that adds the target does not back-fill the edge (the normalisation pass will).
- **Synonyms with no shared token and no related term are never proposed.** A proposal needs a lexical signal (§4.7); the cosine alone proposes nothing.
- **Concept vectors are Slide centroids,** so the cosine only ranks candidates; it is not a similarity of the concepts.
- **The per-course alignment run reads the whole domain,** so its cost grows with the fleet. The summary logs seconds per phase (`load`, `plan`, `apply`).
- **No lineage between revisions** of the same course (§3).

## 11. Changing this contract

- The owning lane edits this file. The other side asks by packet.
- Any change to `golden.json`'s non-placeholder content bumps `contract_version` and goes to wb by packet with the new hashes.
