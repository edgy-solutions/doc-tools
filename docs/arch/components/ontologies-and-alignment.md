# Ontologies and alignment (CO-ONTOLOGY)

doc-tools holds the semantic half of the pipeline: it ingests ontologies into the triple
store, mirrors the classes into the vector store and into the property graph, writes each
document's facts into graphs chosen by rule rather than by caller, and aligns the concepts a
document teaches against canonical ones.

What it does **not** hold is the vocabulary itself. The TBox extension TTLs moved out of this
repo to eliminate a cross-repo URL coupling, and priming is another chart's Helm Job. A
reader looking for a class definition will not find one here, and that is the design.

**This record describes; it proposes nothing.** Statuses are those of [the README](../README.md),
and line numbers are valid only at the pin listed there. The record shape is provisional.
Nothing in this record was run: it is read from the code, `AGENTS.md` and the test names.

## Findings

1. **The vocabulary is not in this repo.** The TBox extension TTLs (`mro_extension`,
   `maintenance_extension`, `mil_extension`, `idp_extension`, `mesh_system`) live in
   invincible-agent at `setup/ontologies/*.ttl`, and substrate priming — graph constraints,
   vector schemas, foundational ontologies — is that chart's `primeSubstrate` Helm Job.
   `AGENTS.md` states the rule in the imperative: to add a class, edit the TTL there and
   redeploy that chart; do **not** add a TTL or a priming script back into doc-tools.
   `accepted + built` (the move happened; the rule is written)
2. **Three stores, three shapes, one ingest.** `ingest_ontology_to_jena` reads a TTL from
   object storage, derives the labels that are missing, POSTs the triples to Jena, and then
   mirrors the extracted classes into Weaviate. A separate asset mirrors the same classes and
   their `subClassOf` hierarchy into Neo4j via rdflib. The three are not interchangeable
   views: a class absent from one store is absent for whatever reads that store. `built`
3. **The graph a write lands in is chosen by rule, never by a caller.** The vocabulary graph
   is `http://internal/{domain}`; the instance graph is
   `http://internal/{DOMAIN}_INSTANCES`; the per-document graph is `urn:doc:{s3_key}`. The
   code says the instance write is never the bare domain graph, and refuses rather than
   guessing when it cannot choose the instance graph. `built`
4. **A re-ingest appends to the vocabulary graph; the drop belongs to priming.** The
   ontology ingest POST-merges, and the DROP-first behaviour on a re-ingest is
   `clear_ontology_graphs` in **invincible-agent's** `setup/prime_databases.py`, referenced
   from a comment here. Nothing in this repo drops a vocabulary graph. `built` (the merge);
   the drop is another repo's.
5. **The mesh predicate namespace is `http://invincible-agent/mesh#`, and the other one is
   recorded as rejected.** `LABEL_SOURCE_PREDICATE` and `UNIVERSAL_REFERENT_PREDICATE` are
   both in that namespace, and `_REJECTED_LABEL_SOURCE_NAMESPACE = "http://internal/mesh#"`
   is kept as a constant so the earlier mistake — reasoning by analogy from the named-graph
   URI to the predicate namespace — cannot be made silently again. `built`
6. **A derived label is marked opaque rather than passed off as a name.** Label derivation
   splits CamelCase and underscore forms, keeps an alphanumeric standard code whole, does not
   spell out bare boolean operators, and marks a bare code tail `OPAQUE` instead of
   presenting it as a human label. Eight tests pin the cases. `built`
7. **The universal-referent flag is absent-is-None, not absent-is-False.** It is projected by
   the declared predicate IRI, a typed and an untyped `true` are both `True`, and an explicit
   `false` is the same as absent. Every class carries the key, so dropping the flag *removes*
   it rather than leaving a stale `true` behind. `built`
8. **The Weaviate writer refuses a write that would strip a vector.** `batch.add_object(uuid=…)`
   onto an existing id is a whole-object PUT in weaviate-client 4.21.3, so omitting the vector
   erases the stored one rather than leaving it. The writer round-trips first and returns
   either `written_without_vector` or `skipped_would_strip_vector`. A legacy unnamed vector
   counts as a vector to lose, a row that never had one is refreshed, and a store that cannot
   be interrogated is refused and says so. `built`
9. **Two seals, and the second exists because the first is green on a dead pool.**
   `seal_declared_classes_are_rows` reads back that every class the run said it would write is
   a row. `seal_a_written_row_is_RETRIEVABLE` then asks the server to use the vector and
   requires an object to be its own nearest neighbour — because a row seal passes against an
   index that is not there. The retrieval seal runs *beside* the row seal, not instead of it,
   and it is deterministic. `built`
10. **A partial substrate raises instead of falling through.** The dual-write `except` raises
    and the message says the substrate is now partial; the batch error channel is read rather
    than assumed empty. Two things stay best-effort by decision and say so: the embed fallback
    and the collection marker. `built`
11. **Every declared class lands in exactly one bucket, and every exclusion carries its
    reason.** Partitioning is total, so a class cannot be silently dropped between "written"
    and "excluded", and an exclusion without a reason fails a test. Blank nodes and response-
    shape URIs are filtered with their own tests. `built`
12. **Weaviate readiness is a per-domain, per-manifest-entry check that fails loudly.** It
    enumerates the ontology bucket, asks Weaviate how many rows carry each `source_ontology`,
    and **fails** when any declared entry has none. It is not partitioned, so there is one
    verdict for the pool rather than per-domain silence. `built`
13. **Concept alignment is deterministic, and its default mode writes nothing.**
    `concepts.normalise` is keyed on a normalised align key (punctuation, case and spacing
    unified) and calls no model. The env switch `TRAINING_CONCEPT_ALIGNMENT` has four values:
    `dry` (the default), `propose`, `on`, `off`. The function never raises — a failure is
    logged and the ingest continues. `built`
14. **An unknown value of the switch behaves as `on`.** The mode is matched against `dry`,
    `propose` and `off`; anything else falls to the live branch and reports `ok`. A typo
    therefore turns writing on, and no test covers that branch. `built` (the behaviour); the
    test is `not built`.
15. **The pass owns three edge kinds and not the fourth.** It writes auto
    `ALIGNS_TO {status:'auto'}`, open `PROPOSED_ALIGNS_TO {status:'open'}`, and materialises an
    accepted proposal as `ALIGNS_TO {status:'accepted', method:'review'}`. A one-way related
    term does not join a component; it becomes a proposal. `ALIAS_OF` is **not** this pass's —
    it is the training plugin's, written after every `TEACHES`. `built`
16. **`TEACHES` is replaced on a re-ingest and `ALIAS_OF` is not.** The training plugin
    deletes a section's stale `TEACHES` before writing (architect's ruling 2026-10-30, quoted
    at the deletion), while the candidate `ALIAS_OF` edges are merged. So the alias set a
    reader sees is the union of every run, and the `TEACHES` set is the latest run's. `built`

## Settings and defaults

| Setting | Default | Where | What it does |
|---|---|---|---|
| `TRAINING_CONCEPT_ALIGNMENT` | `dry` | `doc_tools/assets/semantic_assets.py:464` | `dry` writes nothing, `propose` writes open proposals and the canonicals they name, `on` writes auto edges, `off` skips. An unknown value behaves as `on` |
| vocabulary graph | `http://internal/{domain}` | `ontology_assets.py:1223` | POST-merged, never PUT from here |
| instance graph | `http://internal/{DOMAIN}_INSTANCES` | `semantic_assets.py:1818` | chosen by rule; refused rather than guessed |
| per-document graph | `urn:doc:{s3_key}` | `semantic_assets.py:1733`, `:1955` | URL-quoted on the ingest path |
| `LABEL_SOURCE_PREDICATE` | `http://invincible-agent/mesh#labelSource` | `ontology_assets.py:120` | the mesh predicate namespace |
| `UNIVERSAL_REFERENT_PREDICATE` | `http://invincible-agent/mesh#universalReferent` | `ontology_assets.py:149-150` | projected as `universal_referent` |

## Gaps

- **An unknown alignment mode turns writing on, untested.** `semantic_assets.py:464-473`.
  The safe reading of an unrecognised switch value would be the default, and this is the
  opposite. `built` (the branch); the test is `not built`.
- **Alignment never raises, so a total failure is a log line.** The docstring says so
  deliberately — an alignment failure must not fail a course ingest — but nothing else
  surfaces it, so a course whose alignment failed is indistinguishable downstream from one
  with nothing to align. `built` (the decision); a surfaced counter is `not built`.
- **`ALIAS_OF` accumulates across re-ingests.** `TEACHES` is replaced and `ALIAS_OF` is
  merged, so the alias set is a union of runs with no pruning. `built` (both behaviours); the
  prune is `not built`.
- **Three stores can disagree and nothing compares them.** The readiness asset checks Weaviate
  against the ontology manifest; no equivalent compares Jena with Neo4j, or either with
  Weaviate's class rows. `built` (the Weaviate arm); the cross-store comparison is `not built`.
- **The vocabulary's drop path is in another repo.** A reader of this repo cannot see what a
  re-ingest removes, only what it adds. `built` elsewhere.

## Not established from code

- **Which ontologies are actually loaded in any environment**, and whether the manifest the
  readiness asset enumerates matches what priming uploaded. Both are read from a running
  system, which these records do not do.
- **Whether the Neo4j sync's body covers the same class set as the Weaviate mirror.** The
  asset's docstring and dependency are read here; its body was not read line by line.
- **Whether `init_neo4j_n10s` is still on any path.** It was not traced at this pin; the sync
  asset's docstring says rdflib extraction, not n10s.
- **The full property list of the `OntologyClass` collection.** Only the properties named in
  the findings above were read, and a property added to the create path is inert on an
  already-created collection — so the shipped list and a deployed pool's list can differ and
  this repo cannot say which is which.
- **Whether any `mil:*` term is present in a deployed vocabulary graph.** The namespace is
  declared in `AGENTS.md:110`; what is loaded is a cluster fact.
- Which alignment rows of the outside references this component answers to. The rows
  suggested below are this lane's reading, not the arch lane's. `proposed`

## Place in the mesh

| Aspect | What the code and chart show | Suggested alignment row |
|---|---|---|
| Purpose | ingest a vocabulary into three stores, write document facts into rule-chosen graphs, and align concepts to canonical ones | [DoD S2](https://github.com/edgy-solutions/dag-tools/blob/lane/arch-alignment/docs/arch/alignment/dod-dmra.md) — semantic services `proposed` |
| Where the vocabulary comes from | not here: invincible-agent's TTLs, primed by its Helm Job. doc-tools consumes and mirrors it | [DoD S4](https://github.com/edgy-solutions/dag-tools/blob/lane/arch-alignment/docs/arch/alignment/dod-dmra.md) — data and metadata profiles `proposed` |
| Identity | class IRIs are the ontology's; the mesh predicates are in `http://invincible-agent/mesh#`, and a document's graph is named by its source key | [DoD S1](https://github.com/edgy-solutions/dag-tools/blob/lane/arch-alignment/docs/arch/alignment/dod-dmra.md) `proposed` |
| Quality | the seals are the quality instrument: declared classes are rows, and a row is retrievable | [DoD S13](https://github.com/edgy-solutions/dag-tools/blob/lane/arch-alignment/docs/arch/alignment/dod-dmra.md) `proposed` |
| Security role | none. It holds store credentials and makes no access decision | — |
| Plane | data management: it maintains the semantic substrate the operational and analytical planes read | [NATO L3](https://github.com/edgy-solutions/dag-tools/blob/lane/arch-alignment/docs/arch/alignment/nato-dcra.md) `proposed` |

## Sources

All paths are in this repo at the pin in [the README](../README.md), except where a row says
otherwise.

| Claim | Source | Decision | Evidence | Status |
|---|---|---|---|---|
| The TTLs and priming are invincible-agent's; do not add one back here | `AGENTS.md:54` | retired 2026-06-17 (`setup_env.py`); the move is stated as a rule | — | `accepted + built` |
| Ontology ingest: label derivation, Jena POST, Weaviate mirror | `doc_tools/assets/ontology_assets.py:247`, `:739`, `:1110`, `:1407` | — | `tests/test_ontology_label_derivation.py` (8 cases) | `built` |
| Neo4j mirror of classes and `subClassOf`, by rdflib, depending only on the Jena ingest | `ontology_assets.py:1719-1730` | closes the Session-1 DAG-wiring break (module docstring) | — | `built` |
| The three graph URIs, and that the instance write is never the bare domain graph | `ontology_assets.py:1223`; `doc_tools/assets/semantic_assets.py:1733`, `:1756`, `:1816`, `:1818`, `:1955` | — | — | `built` |
| The vocabulary graph is POST-merged; the drop is invincible-agent's `clear_ontology_graphs` | `AGENTS.md:142`, `:152`; comment at `ontology_assets.py:1266` | — | — | `built` (here); the drop is elsewhere |
| The mesh namespace, and the rejected one kept as a constant | `ontology_assets.py:104-130`, `:120`, `:124`, `:149-152` | recorded at `:104-108` | `tests/test_ontology_assets_universal_referent.py::test_the_projection_binds_by_the_declared_predicate_iri` | `built` |
| Universal referent: absent is None, an explicit false equals absent, every class carries the key | `ontology_assets.py:160`, `:149-152` | — | `tests/test_ontology_assets_universal_referent.py::test_absent_is_None_not_False`, `::test_an_explicit_false_is_the_same_as_absent`, `::test_every_class_carries_the_key_so_a_dropped_flag_is_REMOVED`, `::test_THE_SEAL_flagged_carries_it_unflagged_does_not` | `built` |
| A vectorless write is refused when it would strip a stored vector | `ontology_assets.py:681-695` | — | `tests/test_ontology_writer_never_strips_a_vector.py::test_an_existing_row_WITH_a_named_vector_is_refused`, `::test_a_LEGACY_unnamed_vector_also_counts_as_a_vector_to_lose`, `::test_an_existing_row_that_never_had_a_vector_is_REFRESHED_not_refused`, `::test_a_store_we_cannot_interrogate_is_REFUSED_and_says_so`, `::test_the_writer_SKIPS_the_row_whose_vector_it_would_strip` | `built` |
| Two seals; the retrieval seal exists because the row seal is green on a dead pool | `ontology_assets.py:513-520`, `:564-575` | — | `tests/test_ontology_rows_are_retrievable.py::test_THE_MEASURED_SUBSTRATE_FAILS`, `::test_an_index_that_answers_WITHOUT_the_row_also_fails`, `::test_the_seal_runs_BESIDE_the_row_seal_not_instead_of_it`, `::test_the_seal_asks_the_SERVER_to_use_the_vector`, `::test_the_probe_is_deterministic` | `built` |
| A partial substrate raises; the batch error channel is read; two paths stay best-effort | `ontology_assets.py` dual-write arm | — | `tests/test_ontology_dual_write_fails_the_asset.py::test_the_dual_write_except_RAISES_instead_of_falling_through`, `::test_the_raise_says_the_substrate_is_now_PARTIAL`, `::test_the_batch_error_channel_is_READ`, `::test_the_embed_fallback_STAYS_best_effort`, `::test_write_collection_marker_STAYS_best_effort` | `built` |
| Partitioning is total and every exclusion carries a reason; blank nodes and response shapes filtered | `ontology_assets.py:325`, `:378`, `:455` | — | `tests/test_ontology_dual_write_fails_the_asset.py::test_every_declared_class_lands_in_exactly_one_bucket`, `::test_every_exclusion_carries_its_REASON`; `tests/test_ontology_assets_blank_node_filter.py`; `tests/test_ontology_assets_response_shape_filter.py` | `built` |
| Weaviate readiness fails when a declared manifest entry has no rows; not partitioned | `ontology_assets.py:1502-1512` | — | — | `built` |
| The alignment switch, its four modes, the `dry` default, and that it never raises | `semantic_assets.py:458-476` | — | `tests/test_concept_normalise.py::test_align_key_unifies_punctuation_case_and_spacing`, `::test_align_key_lockout_tagout` | `built` |
| An unknown mode behaves as `on` | `semantic_assets.py:464`, `:472` | — | none found | `built`; the test is `not built` |
| The pass owns auto, open and accepted `ALIGNS_TO`; a one-way term becomes a proposal; `ALIAS_OF` is not its edge | `doc_tools/passes/concepts.py:6-19`, `:140` | — | `tests/test_concept_normalise.py::test_one_way_related_term_does_not_join_it_becomes_a_proposal`, `::test_exact_key_joins_one_component_and_mutual_terms_join_another`, `::test_a_component_keeps_its_auto_cc_when_a_new_member_joins` | `built` |
| `TEACHES` is replaced on re-ingest; `ALIAS_OF` is merged after every `TEACHES` | `doc_tools/plugins/training.py:485`, `:501-515`, `:543` | architect's ruling 2026-10-30, quoted at `:501` | — | `built` |
