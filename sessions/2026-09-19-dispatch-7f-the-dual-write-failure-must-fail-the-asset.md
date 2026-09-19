# Dispatch — doc-tools / 7f: the dual-write failure must fail the asset

to: `doc-tools` (7f)
from: Lane 1 (`ia-01/lane/01`), orchestrator, on the architect's 2026-09-19 work order
date: 2026-09-19

**There is no live 7f session.** This is filed and left. Read it when one starts; nothing in it
is time-sensitive, and nothing in it has been started by anyone else.

This is the first file in `doc-tools/sessions/`. The ruling that created it: **each repo carries
its own `sessions/` inbox**, and the census derives per-lane inbox counts from the lane's own
worktree. `doc-tools` had no inbox, so dispatches to 7f had nowhere to land.

---

## AMENDMENT, same day, BEFORE YOU OPEN ANYTHING

**`doc_tools/assets/ontology_assets.py` has uncommitted work in the tree** — growing while I
watched it, 207 insertions when I first looked and 624 twenty minutes later. It implements the
`mesh:universalReferent` → Neo4j carry: `UNIVERSAL_REFERENT_PREDICATE` +
`UNIVERSAL_REFERENT_PROPERTY = "universal_referent"` at module top, an `OPTIONAL { ?uri
mesh:universalReferent ?universal_referent }` in the class query, the property SET alongside
`label` / `definition` / `domain` in the MERGE, a readback seal on it, and a corrected
"Mechanics" comment. That matches item 1 of the doc-tools work order step for step.

**IF THESE LINES ARE YOURS, COMMIT THEM ON YOUR OWN BRANCH PROMPTLY. IF THEY ARE NOT, STOP AND
REPORT.** The earlier wording of this amendment told the reader not to touch the file — which,
if you are the author, warned you off your own work. That was wrong and this replaces it. The
file is almost certainly a live doc-tools session mid-task, and unfinished is not orphaned: its
author is live and will commit it. The reason to commit promptly is only that uncommitted work
is invisible to every other clone, not that anyone else should take it.

**Lane 1 will not commit these lines on the author's behalf, whoever the author turns out to
be.** Nothing on disk names them; the evidence is timing and content only.

**None of that work is one of my three rulings below** — do not count item 1 as delivered by
them, and do not redo it either.

**MY LINE NUMBERS BELOW ARE STALE BY ROUGHLY +58.** They were read against the committed state
at `031195f`. The one that matters: the Weaviate dual-write swallow I cite at `:734` is now at
**`:792-795`**, and `:734` today is an unrelated comment about retry doubling. Ruling 1 is
**still unbuilt** — I re-checked, the `except` still logs and falls through to the success
`MaterializeResult`. Confirm every number against the file before you cut; that was true when I
wrote it and is more true now.

---

## Why you are getting this

The class-system exists to refuse a partial ingest. Right now it reports one as a success. Three
rulings follow from that, and all three are yours.

Everything below was read in this tree at `main` on 2026-09-19. Line numbers are from that read;
confirm them before you cut, they drift.

---

## Ruling 1 — a failed Weaviate dual-write must FAIL the asset

`doc_tools/assets/ontology_assets.py`, in `ingest_ontology_to_jena` (def at :501), around
**:734-744**:

```python
    except Exception as e:
        context.log.error(f"Weaviate Dual-Write failed: {e}")

    return MaterializeResult(
        metadata={
            "domain": domain,
            "graph_uri": graph_uri,
            "triples": len(g),
            "s3_path": f"s3://{bucket}/{obj_key}",
        }
    )
```

The `except` catches, logs at error, and **falls through to the same `MaterializeResult` the
success path returns**. Dagster sees a materialised asset. Jena has the triples, Weaviate has
nothing, and the run is green.

**The ruling: that `except` re-raises, or the asset returns a failure.** A partial ingest reported
as success is precisely the failure the class system exists to refuse — the graph is authoritative
for what EXISTS, the vector store for what can be GROUNDED, and a run that populates one and not
the other leaves the mesh in a state no consumer can detect from the outside.

Note the asymmetry you are fixing: the Neo4j leg (`sync_jena_ontologies_to_neo4j`, :801) already
raises on failure, deliberately, and its docstring says why — n10s has a silent-zero failure mode,
so "failures raise". The Weaviate leg was written to the opposite convention. **One store's write
failure is fatal and the other's is a log line, in one pipeline.** That is the whole defect.

**Do not widen this into the embed path.** Inside `sync_ontology_to_weaviate` (:332) there is a
second, *correct* best-effort at :471-478: `embed_document` failure writes the row without a
vector and says so, because BM25 still answers and a backfill can populate later. **That one is a
degraded row, not a missing one, and it must stay best-effort.** The distinction the ruling turns
on is *row missing* vs *row present but thinner* — keep it.

`write_collection_marker` (:399-401, "Best-effort; never raises") is in the same category. Leave it.

---

## Ruling 2 — the manifest→Weaviate-row seal, and it belongs here

**Every class a manifest TTL declares is a row in the `OntologyClass` collection.** Derived from
the manifest, run after ingest. Not a hand-written list of classes — a hand-written list of a
population is a sample, and this one would go stale on the next TTL.

**Two things will bite you, and neither is visible from the ruling as stated:**

**(a) The basis is not "every declared class" — there are two deliberate exclusions.**
`sync_ontology_to_weaviate` filters twice before writing:

- `_is_meta_ontology_iri(uri)` — PROV-O / RDFS / OWL / SKOS terms, corpus noise, filtered per the
  2026-06-27 contamination finding.
- `uri in response_shape_uris(g)` — response shapes, **Weaviate only**. The comment at :353-370 is
  emphatic that this must never be mirrored into the Neo4j sync: Contract D refuses a registration
  whose output class has no `:OntologyClass` node, and `find_compatible_verbs` matches
  `(scope)-[r]->(o:OntologyClass)`, so filtering Neo4j would silently vanish every verb.

So the seal's expected set is `declared − meta − response_shapes`. **Partition it:** every declared
class lands in the expected set or in an exclusion list *with the reason attached*, and a class
that is in neither fails the seal rather than being skipped. If you write it as "skip the ones we
filter", the seal stops being able to tell a deliberate exclusion from a dropped row — which is
the bug it exists to catch.

**(b) The manifest is in the OTHER repo.** `CANONICAL_TTL_MANIFEST` lives in
`invincible-agent/setup/prime_databases.py:170`. doc-tools has no copy.

This is the two-mirrors shape, and it is the sharpest one we have: a seal *here* derived from a
list *there* is complete on its own side and blind to the row that exists in only one master.
**Do not solve it by copying the manifest into doc-tools** — that mints the second master and the
drift becomes invisible to both repos. Either read the manifest from a single declared source, or
make the seal assert *against the ingest run's own record* of what it was handed. **Say which you
chose and why, in the commit.** If neither is available to you, file that back to Lane 1 as a
blocker rather than picking the copy.

---

## Ruling 3 — the readiness sentinel becomes per-domain

Today the sentinel answers "is Weaviate up". The ruling: **one class per manifest entry, per
domain.** A sentinel that checks a single well-known class is a *store liveness check wearing an
ingest check's name* — it is green the moment Weaviate answers, including when the MAINTENANCE
domain ingested nothing at all.

That is not hypothetical here: the safety classes were re-ingested **once, by hand**, and the
sentinel was green on both sides of that. It could not tell.

Derive the domains from the manifest, not from a literal. Same partition discipline as Ruling 2.

---

## What is NOT yours, so you do not chase it

**The `mro:MaintenanceWorkOrder` cause is withdrawn.** Lane 1 held a task to add an `iof_mro.ttl`
manifest row; the architect withdrew it on 2026-09-19 and I confirmed the premise three ways
before filing this:

- `agent_fleet/ontology_service/iof_mro.ttl` is **self-described as a dummy** — "Dummy IOF /
  MIMOSA Maintenance Reference Ontology (MRO) extract … In production, replace with the full IOF
  MRO ontology." It is a runtime fixture for the ontology reasoner microservice, a different
  consumer entirely.
- `IOF_MRO` is **already in** `CANONICAL_TTL_MANIFEST` (`prime_databases.py:179-184`) and already
  points at the real upstream `Maintenance.rdf` from `iofoundry`, not at the dummy.
- Lane 74 reached the same finding independently at `f18bc9a`: *"I cited a DUMMY as the standard —
  the work-order class is `iof-constr:MaintenanceWorkOrderRecord`."*

The class resolves when the MAINTENANCE ingest lands — **which is Ruling 1 above.** That is the
connection: the reason the work-order class is missing is not a missing manifest row, it is an
ingest that failed into a green run.

---

## Reporting back

File your handoff in this directory. If you land Ruling 1 alone, say so — it is the one that
unblocks a diagnosis elsewhere, and it is worth landing before the two seals.

Lane 1 is `ia-01/lane/01`. Route by the lane pair, never by a bare session name — two live
sessions share `invincible-agent-28`.
