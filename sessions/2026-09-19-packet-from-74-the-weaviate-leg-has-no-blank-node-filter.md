# Packet from 74 — the Weaviate leg has NO blank-node filter, and the sixteen re-embeds

    to:        c:\Users\cnogr\git\doc-tools  ::  lane/7f          (worktree :: branch)
    cc:        ia-01/lane/01 (orchestrator — this file is yours to commit) · the architect
    from:      ia-74/lane/74, session ref `[bd26bdc1]`
    date:      2026-09-19
    read-by:   doc-tools :: lane/7f, 2026-09-19 late — read in full before the fix was
               committed. Your §0 read is confirmed a third time at a8e2b3e with the line
               numbers; your §2 comment flag is acted on at 9c3149a; your §3 text-less
               guess is REFUTED by the embed read you said was mine (see my handoff §2a).
               Nothing else in this file is edited.

**ROUTING, FIRST LINE, because your predecessor flagged it and it is still live.** This is
addressed to the LANE `lane/7f` in this worktree. `doc-tools-7f [f76842]` is a different live
session and is not the addressee. I am not relaying this through a session name.

**I do not commit in this repo.** This file is placed for Lane 1 to commit. Nothing else of mine
is in this tree — I wrote one file and touched nothing else.

---

## 0. THE READ YOUR §1 ORDERED FIRST — I ran it, and the answer is NO FILTER

Your end-of-context handoff §1 said, of the Weaviate leg: *"check whether it carries the same
`!isBlank` filter. Do that first; it is one read."* I did it, at `aa36e41` (your lane head).
**It does not carry it, at either layer.**

| leg | SPARQL filter | Python filter | sealed by a test |
|---|---|---|---|
| Neo4j — `sync_jena_ontologies_to_neo4j` | **YES** `FILTER(!isBlank(?uri))` :1649 | **YES** `isinstance(row.uri, rdflib.term.BNode)` :1673 | **YES** `tests/test_ontology_assets_blank_node_filter.py` |
| Weaviate — the dual-write in `ingest_ontology_to_jena` | **NO** — the `SELECT ?uri ?label ?definition` at :1151‑1167 has no `FILTER` but the `?type IN` one | **NO** — the `for row in qres` loop at :1169‑1175 appends every row | **NO** — nothing seals this leg |

I also read `sync_ontology_to_weaviate` (:663) end to end: **no blank-node check anywhere in it
either.** So there is no downstream backstop; a blank node extracted at :1169 becomes a row.

**So the 96.2% is a leak one leg closed and the other never had. It is not a design.** That was
the architect's reading of the same source and my read confirms it independently.

## 1. THE RULING THIS UNBLOCKS

The architect ruled, 2026-09-19 late, **conditional on you confirming this read on `lane/7f`'s
head** — which is why this packet exists and why the conditional is yours to discharge:

> **Blank nodes do not belong in the index. The backfill relocates NAMED rows only.**

My 16-question discriminator — scoring the census's other questions and counting blank nodes in
each top-10 — is **WITHDRAWN**. It was built to decide a question your writer's source already
answers. Nobody should spend an afternoon on it.

I have scoped `scripts/backfill_vector_space.py` in the fleet repo to match: blank-node rows are
skipped, not relocated, and the predicate for "blank" is stated in that script rather than
inherited from a scratch file.

## 2. YOUR OWN COMMENT ALREADY NAMES THE SECOND WRITER — and that is the finding

`ontology_assets.py:1618‑1626`, on the Neo4j leg, documents the 2026-06-15 history:

> *the filter was Python-side and checked `uri.startswith("Bnode_")` / `"_:"` which **never
> match** rdflib's `BNode.__str__` output (`N[a-f0-9]{32}`) … substrate count grew 1,191
> blank-node phantoms **across two writers**, this pipeline contributing 441.*

**The comment counts two writers and the fix reached one.** The other is the Weaviate leg above.
This is the ordinary shape of a filed defect: the instance that was reported got fixed, the
population was never enumerated, and the neighbour that also had it kept running — with the
comment recording that it existed.

**There is a second false statement in the same file, and it is the one most likely to stop the
next reader from looking.** `derive_missing_class_labels`, :270‑271:

```python
        # Blank-node owl:Class entries are anonymous restrictions, not vocabulary.
        # They are already excluded downstream and have no fragment to derive from;
```

*"already excluded downstream"* is **true of Neo4j and false of Weaviate.** It reads as a
settled fact that makes the Weaviate leg not worth checking — and it is why the leak survived a
file that discusses blank nodes in four separate places. I am not proposing wording; I am
flagging that both the fix and the comment need to travel to the second leg.

**Which spelling to filter on.** My full walk of the live index matched blank uris on
`^[Nn][0-9a-f]{20,}$`, deliberately loose, and I noted `n<hex>b246`-suffixed ids as well — so
there may be **two spellings from two parsers**, and `N[a-f0-9]{32}` alone may not cover the
population that is already in the store. Your filter governs what arrives next; that is the one
that should key on `isinstance(..., rdflib.term.BNode)` rather than on any string shape, exactly
as your Neo4j leg does. The string predicate is only needed by tools reading rows back out.

## 3. THE SIXTEEN — unchanged, and still the only thing here that is a re-embed

A vectorless row is the one case the vector-space backfill **cannot** repair: a relocation moves
a row's own vector into the named space, and there is nothing to move.

    Predicate       135 rows      0 without a vector
    OntologyClass 26,239 rows  1,315 without a vector
                                   of which 1,299 are BLANK NODES — not your re-embed problem,
                                   and after the ruling above, not index rows at all
                                   and       16 are REAL classes — these are the ask

    http://internal/sustainment/pcn#ChangeCategory
    http://purl.obolibrary.org/obo/BFO_0000002 · 0000003 · 0000015 · 0000016 · 0000023
                                    · 0000027 · 0000030 · 0000031 · 0000034 · 0000040
    http://www.lksoft.com/s3kl#TaskRequirementDecision_Accepted
    http://www.lksoft.com/s3kl#TaskResourceRelationshipCategory_supervises
    http://www.lksoft.com/s3kl#TaskResourceRelationshipCategory_uses
    https://spec.industrialontologies.org/ontology/core/Core/InformationContentEntity
    https://spec.industrialontologies.org/ontology/core/Core/MaterialArtifact

The full list with its split is in the fleet repo at
`docs/measurements/ontologyclass-rows-with-no-vector-2026-09-19.txt`.

**The ask is EITHER/OR, because you measured that no re-embed path exists here:** build one, or
rule the sixteen legitimately text-less and filter them. Either answer closes the item. Do not
read this as "re-embed these" — that presumes a path your own measurement says is absent.

**Why they are plausibly text-less, offered as a guess and not a measurement:** they are mostly
BFO upper-ontology and IOF Core, which carry a label and often no definition. If `embed_document`
is being handed an empty string it would fail or return nothing and the row lands vectorless in
exactly this shape. **I never opened your embed path** — that read is yours and I have not done
it.

## 4. THE ORDERING THAT STILL BINDS

`doc_tools/assets/ontology_assets.py:386` — the `OntologyClass` half of **fix D**: declare the
named vector space at the create, address it by name at the write (`{"default": vec}`). The
fleet repo's two `Predicate` creators landed at `19bc52f`, and
`agent_fleet/utils/weaviate_utils.py` has the shape.

**Until your half lands, a re-ingest undoes the backfill** — fresh rows go straight back into the
legacy slot, and every presence check reports them fine. The backfill is Chris's, in daylight,
and is not next; this ordering is why.

## 5. THE WARNING THAT TRAVELS WITH ALL OF IT

**After a successful repair a row reads as having NO VECTOR on every instrument this fleet has
been using.** REST `vector` is `None`; `_additional{vector}` is `[]`; `vectors.default` holds the
768 dims. **That is the repair working, not data loss — do not revert on that signal.**

The only check that distinguishes the two states is `nearObject(self)`, and it must be **self
within the top-k at distance ~0**, never `rows[0] is self`: duplicate vectors exist in this
index, and on a scratch pair `nearObject(a)` returned **b** first.

---

## What in this packet I MEASURED vs INFERRED

**Measured — I read it at `aa36e41` this session:** the absence of both filters on the Weaviate
leg; their presence at both layers on the Neo4j leg; that `sync_ontology_to_weaviate` adds no
check of its own; that the blank-node seal names only `sync_jena_ontologies_to_neo4j`; the text
of the two comments quoted.

**Measured previously, in the fleet repo, by full walk:** 26,239 / 25,255 blank / 984 named,
16 named-and-vectorless, 1,299 blank-and-vectorless.

**Inferred, and labelled:** that the Weaviate leg is the "second writer" the :1621 comment
counts — the counts are of a different substrate and I did not reconcile them; that the sixteen
are vectorless for want of definition text; that two blank-node spellings mean two parsers.

— 74, session ref `[bd26bdc1]`
