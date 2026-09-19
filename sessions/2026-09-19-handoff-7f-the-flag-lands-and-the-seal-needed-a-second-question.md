# Handoff — doc-tools / 7f, 2026-09-19

to: `ia-01/lane/01`
cc: the architect, `ia-74/lane/74`
from: doc-tools lane 7f
branch: `lane/7f` at `7ac6caa` (one commit, not pushed)

**Read this first: THE RE-SYNC DID NOT HAPPEN, deliberately, and nothing was written to any
store.** The work order's item 3 asked for a re-sync reported with a node read. The architect
withdrew it mid-pass on 74's packet — *"Do NOT re-ingest; the rebuild is Chris's to
authorize."* So what follows is a before-measurement and a commit, not a substrate change.

---

## STATE

    branch          doc-tools lane/7f at 7ac6caa (lane/7f was a stale ancestor of main;
                    fast-forwarded to main, no history lost)
    base            main a738a9c (your two dispatch amendments included)
    scope           doc_tools/assets/ontology_assets.py, definitions.py,
                    doc_tools/utils/ontology_readiness.py (new), four test files
    seals           56 pass across the four ontology-asset test files
    suite           357 pass, 4 skip, 7 fail — all 7 PRE-EXISTING in
                    tests/test_collection_marker.py: the installed iagent-mesh wheel has no
                    `iagent_mesh.interfaces` module. Nothing in this pass touches it.
                    Worth someone's attention; it is not mine and I did not chase it.
    cluster         THREE READS, ZERO WRITES. Detailed below.

---

## WHAT LANDED

### 1. `mesh:universalReferent` reaches the node — YOUR POOL LEG IS UNBLOCKED ON THIS SIDE

`UNIVERSAL_REFERENT_PROPERTY = "universal_referent"`. **That is the string your
parameterisation leg reads.** It is a module constant the MERGE interpolates, so the name you
are given is the name the write uses — the node convention is snake_case and the predicate's
local name is camelCase, so neither side can infer the other and a rename has to move both.

* extraction: `OPTIONAL { ?uri mesh:universalReferent ?universal_referent }` in the same
  SELECT as label and definition — one traversal, so there is no second reader of the graph
  that can disagree with the first about which classes were extracted.
* write: `SET c.universal_referent = cls.universal_referent`, value `True` or **`None`**.
* **ABSENT MEANS FALSE, and it is encoded as null rather than `False` on purpose.** Cypher
  `SET c.p = null` REMOVES the property. So a class that stops declaring the flag stops
  carrying it at the next sync, ~24,000 classes do not grow a property to say nothing, and
  "the flag was dropped" stays distinguishable from "the flag is false". An explicit
  `mesh:universalReferent false` and no triple at all produce the same node.
* the seal you asked for, **as a partition**: a class carrying the flag in the TTL carries it
  on the node; a class without it does not. The readback raises in **both** directions. The
  second direction is the one that matters — a flag written onto every node is exactly the
  ratified-superclass widening `mesh:Thing` was declared as a flag to refuse, and every
  positive assertion still passes while it happens.

**The precondition was measured before any of it was wired**, because `owl:Thing` measured
zero and the same question had to be asked rather than assumed. Against master's
`mesh_system.ttl` (329 triples, 74 named classes): `mesh:Thing` survives the meta filter,
survives the response-shape filter (60 of those 74 ARE response shapes; it is not one),
survives the blank-node filter, lands with label `"Thing"`, carries the flag as
`"true"^^xsd:boolean`, and nothing is `rdfs:subClassOf` it. The `owl:Thing` control is
asserted against `_META_ONTOLOGY_IRI_PREFIXES` rather than against a cluster, so it holds
with no cluster and reds if that prefix is ever dropped — at which point the whole choice
wants re-arguing rather than quietly becoming redundant.

*(That test skipped when I first ran it, with a reason naming the path, because the checkout
predated your merge. It passes now against `51db099`. Thank you for landing it.)*

### 2. The stale "Mechanics" comment

It documented the n10s route — Jena named-graph URI, SPARQL CONSTRUCT,
`n10s.rdf.import.fetch`, relabel `:Resource` nodes — which the docstring six lines below has
said since Session 2 was abandoned, and why. The file carried both stories with the dead one
first and in the more authoritative-looking place. Rewritten to what runs, including two
other stale claims inside it (path-derived domain, "n10s MERGEs by URI").

### 3. Rulings 1–3

**Ruling 1.** The `except` raises and names the substrate as PARTIAL, so an operator can tell
"re-drive this partition" from "re-drive everything". **Plus the half your ruling as written
could not have closed** — you have already accepted this, recording it here for the file:
weaviate-client 4.21.3's batch does not raise on per-object failure, it collects into
`collection.batch.failed_objects` and logs. The exact shape the ruling refuses walks past a
re-raising `except` because nothing ever arrives at it. That channel is now read. The embed
fallback and `write_collection_marker` are untouched and there are tests that refuse a later
widening into them.

**Ruling 2.** Your **second** option: the seal asserts against the ingest run's own record.
The asset is partitioned per file, so one partition IS one manifest entry and the classes
come from the very TTL that partition was handed, in-process. The union over partitions is
the manifest and doc-tools never holds the list. A copy would also be unreadable at runtime —
the dagster-user-code image has no invincible-agent checkout. Partitioned with reasons
attached (`meta_ontology_iri` / `response_shape_weaviate_only`), reconciliation asserted
rather than assumed from the shape of the if/elif/else, and a test that fails if
`CANONICAL_TTL_MANIFEST` ever appears under `doc_tools/`.

**Ruling 3.** New unpartitioned asset `weaviate_ontology_readiness` + `ontology_readiness.py`
(pure). Per ENTRY, expectation off MinIO, four states. Both of the calls you routed up are
implemented as agreed, and pre-today rows report `UNATTRIBUTED` rather than `INGESTED` — I
have not backfilled `source_ontology` to make it green, per your instruction.

**One gap stated rather than hidden:** Ruling 2's seal cannot see a manifest entry whose
partition never RAN, because there is no run to fail. That is exactly what Ruling 3 covers.
The two are complementary by construction, not redundant.

### 4. 74's packet — the retrievability assertion, and why it changes Ruling 2

**74 is right and it is the most important thing in this handoff: my manifest-to-row seal
would be GREEN on the sandbox right now.** Every row present, every row countable, every row
carrying a readable vector, and the vector half of every hybrid search returning nothing.

So `seal_a_written_row_is_RETRIEVABLE` runs **beside** the row seal, never instead of it —
they ask genuinely different questions and deleting either loses a distinct failure.
`nearObject(self)` on one deterministic vector-bearing row per run: an object is its own
nearest neighbour, or the index is not there. A vector-less probe row (the embed fallback
fired) is reported as an **unmade measurement**, not a pass — blaming the index for the
gateway is how a seal starts pointing at the wrong thing.

**THIS WILL RED EVERY ONTOLOGY INGEST UNTIL THE WRITER IS FIXED AND THE POOL REBUILT.** That
is correct and I am flagging it loudly so nobody reads the first red as a new breakage: an
ingest that produces unsearchable rows has not produced a grounding pool. The failure message
names 74's packet and quotes the server's own error so the red is self-explaining.

**The writer itself is KNOWINGLY UNFIXED.** The bare `collections.create` carries a long note
saying so, naming the packet, and naming the reason: that a bare create on client 4.21.0 is
what emits the named space is 74's **inference**, explicitly not measured, and the two
candidate repairs are not interchangeable. Picking on the inference is picking blind, which
is the one thing the packet asks nobody to do. **I am waiting on 74's scratch-collection
result**, per the architect. The note exists so the next reader who finds a bare create with
a detector pointing at it does not "fix" it on the guess.

---

## THE CLUSTER READS — THREE, ALL READ-ONLY

    MATCH (c:OntologyClass) WHERE c.uri STARTS WITH 'http://invincible-agent/mesh#'
      -> 73
    MATCH (c:OntologyClass {uri:'http://invincible-agent/mesh#Thing'}) RETURN ...
      -> no rows. THE NODE DOES NOT EXIST.
    MATCH (c:OntologyClass) WHERE c.universal_referent IS NOT NULL RETURN count(c)
      -> 0

**That is the before-measurement, and it is the honest one to hand you.** The after belongs to
an authorized prime, for three reasons and any one of them is sufficient:

1. the architect withdrew the re-ingest;
2. the deployed `dagster-user-code` image predates this commit, so a Dagster-triggered run
   today would produce the old six properties regardless;
3. per 74, a re-ingest into the current schema writes rows that still cannot be retrieved.

I had a port-forward open and a script ready to run the real asset against the live Neo4j. I
stopped it. **A by-hand re-sync is what Ruling 3 exists because of** — the safety classes were
re-ingested once by hand and the sentinel was green on both sides. Doing it again to produce a
screenshot for this handoff would have been the same act with better intentions.

**What I can tell you without it:** the write path is sealed end-to-end against a recorder
standing in for the driver — the flagged class reaches the MERGE as `True`, the unflagged ones
as `None`, every class carries the key, and the partition seal refuses a widened flag and a
lost one. The one link the tests do not cover is that Neo4j's `SET c.p = null` removes the
property, which is a documented store semantic. **That link, and only that, is what the node
read would have closed.** It is one query on the next authorized prime:

    MATCH (c:OntologyClass) WHERE c.universal_referent IS NOT NULL
    RETURN c.uri, c.label, c.universal_referent;
    -- expect exactly one row: http://invincible-agent/mesh#Thing | Thing | true

---

## TWO FINDINGS THAT ARE NOT MINE TO FIX

**A. `mesh:Thing` was not on master when the work order said it was.** Resolved by you at
`51db099`. Recorded because the work order stated it as fact and it was checkable in one
command; the precondition check is the reason it surfaced before anything was built on it.

**B. `IOF_Core` is in the manifest twice and the rows collide.** You confirmed it and added
the sharper half: the names differ and the s3_keys differ, so a duplicate check keyed on
either comes back clean and wrong — only the `url` exposes it. The row UUID is
`generate_uuid5(uri)` with no domain in it, so the two partitions write one row and the last
writer owns `domain`. Yours; you are filing it to the architect.

---

## WHAT I WOULD PICK UP NEXT, in order

1. **74's scratch-collection result → fix the OntologyClass writer.** Blocked, not forgotten.
2. **The rebuild.** Chris's to authorize. Note the sequencing: the writer fix alone leaves
   every existing row in the legacy slot, so the retrievability seal stays red until both.
3. **Your re-ask on the docs walk.** 74 raises it and I think it deserves a real answer before
   a roll: is `mesh:explain`'s exclusion from the pool a referent problem, or the same dead
   vector half wearing a referent's clothes? The universal-referent leg may be right on its
   own merits — the flag now reaches the node either way, so nothing is wasted — but "the
   defect survives a working vector search" is a measurement nobody has made.

Lane: doc-tools/7f
