# Report — doc-tools/lane/7f to the architect

**The XML path's second RDF write is merged. Pin 3 of 3.** Plus a measurement
nobody asked for that changes what the re-drop will show: the ten MRAD drops are
**six distinct modules**, and two of the duplicate pairs **disagree with each
other**.

---

## 1. The three things the packet asked for

> *Report: the sha, the PCN path helper you mirrored, and whether the write is
> idempotent on retry.*

### The sha

**`f4d6440`** — squash of PR #127 onto `main`, merged `2026-10-17T03:30:36Z`.

### The helper mirrored — the same one, not a second one

| | PCN path (the precedent) | this change |
|---|---|---|
| call site | `doc_tools/assets/semantic_assets.py:787-791` | `semantic_assets.py`, in `upload_to_jena` |
| helper | `JenaClient.execute_update(query, graph_uri=…)` | **the same helper** |
| body | `INSERT DATA { GRAPH <…> { … } }`, pre-scoped by the builder at `doc_tools/plugins/sustainment.py:2003-2053` | same shape |
| graph | `http://internal/SUSTAINMENT_INSTANCES` | `http://internal/MAINTENANCE_INSTANCES` |
| transport | `JenaResource.get_client()` | same |

Reached through `JenaResource.get_client()` — deliberately **not** the raw
`httpx` call that the `urn:doc:` PUT directly above it still uses.
`execute_update` passes an already-scoped body byte for byte and raises
`UnscopedUpdateError` rather than ever sending an unscoped update; a test asserts
`update_is_graph_scoped(body)` so that path cannot be taken silently.

Two properties of the ruling, held explicitly:

- **`_INSTANCES`, never the bare `http://internal/<DOMAIN>`** vocabulary graph —
  the peer prime DROPs that one first on every re-ingest (AGENTS.md:118-140).
  That has already collided once in production.
- **Additive `INSERT DATA` over POST, never PUT.** Every module of the domain
  shares this graph, so a PUT would clobber the others. That is exactly the shape
  the `urn:doc:` write above *can* safely use and this one cannot — the two
  writes in the same function now use deliberately different verbs, and the
  comment says why at the place someone would "simplify" them together.

### Idempotent on retry — yes, and the reason is a dependency worth naming

It does not rest on the write. It rests on a property of the **parser**: the
S1000D builder emits **no timestamp, no uuid and no prov term**, so the triple
set is a function of the input bytes, and `INSERT DATA` of an identical set is a
no-op on a set.

Measured rather than argued — the test applies the real body to an
`rdflib.Dataset` twice:

```
421A module: source graph 12 triples
  after first  ds.update(body): 12
  after second ds.update(body): 12
```

The N-Triples lines are **sorted** before the body is assembled, so a retry body
is *byte*-identical as well (nt serialisation line order is not stable).

**The standing risk, stated so it is not discovered later:** add one volatile
triple to that parser — a generation timestamp, a run uuid, a prov term — and
every retry starts *accumulating* instead of being a no-op. That is a change to
this guarantee, not an addition to a parser, and the comment block saying so sits
at the line where someone would make it.

---

## 2. Two things in the ruling that need your decision — flagged, not resolved

These are in PR #127's body too. Neither is resolved in code; the PR takes the
reading that makes the walk possible and says so.

1. **"Identity/provenance triples stay in `urn:doc:` only" conflicts with "mirror
   the PCN path."** The PCN path writes the document node's `rdf:type` **and**
   both PROV terms (`PROV_GENERATED_AT`, `PROV_DERIVED_FROM`) inside its
   `_INSTANCES` graph block. Measured at `plugins/sustainment.py:2003-2053`. The
   two instructions cannot both be followed literally.

2. **A type-less, label-less subject is not walkable.** If `rdf:type` and
   `rdfs:label` for a DataModule stayed only in `urn:doc:`, a domain-scoped walk
   would read `mil:hasFaultCode` edges off a subject it can neither classify nor
   name — which is the condition this pin exists to end.

What landed writes the module's **whole** triple set to `_INSTANCES`. Nothing
provenance-bearing moves by doing so, and that is a measurement rather than a
judgement: **the builder emits no prov term at all**, and the ingest provenance
on this path **is the graph name** (`urn:doc:<s3_key>`), not a triple. If the
intent was narrower, say so and I will split the set — but then type and label
have to reach the domain graph some other way, or the walk cannot run.

---

## 3. The graph state before the re-drop — measured in the pod, read-only

Queried through `JENA_*` from `doc-tools-secrets` inside
`doc-tools-668c9f67ff-k4k6h` (those keys arrive by `envFrom`, so they are
invisible to a `kubectl get pod -o jsonpath` of `env[*].name` and the query has
to run in the pod). No credential printed.

**`http://internal/MAINTENANCE_INSTANCES` does not exist yet — 0 triples.** So
the re-drop's effect is `0 → N` and fully measurable, with no prior state to
disentangle. For contrast, the pair this change replicates is already there:

| graph | triples |
|---|---|
| `http://internal/SUSTAINMENT` (vocabulary) | 10922 |
| `http://internal/SUSTAINMENT_INSTANCES` | 1990 |
| `http://internal/MAINTENANCE` (vocabulary) | 4959 |
| `http://internal/MAINTENANCE_INSTANCES` | **0** |

### The number to expect, predicted before the fact

| quantity | value |
|---|---|
| sum over the ten `urn:doc:` graphs, duplicates included | **193** |
| **distinct** triples across them — the union | **112** |
| distinct subjects across them | **20** |

The union is what `MAINTENANCE_INSTANCES` must hold after all ten are re-dropped,
because the write is additive on a set. **112, not 193, and not 99.** If the
post-re-drop count comes out at 193 the write is accumulating duplicates and the
idempotency claim above is wrong; if it comes out near 99 it is the local
fixtures, not the dropped bytes, that reached the graph. Both failures are
distinguishable from success by one count.

---

## 4. Unasked-for finding: the ten drops are six modules, and two pairs disagree

Per-graph counts of the ten `urn:doc:` graphs, deployed:

| DMC | drop 1 | drop 2 | local fixture |
|---|---|---|---|
| 941A | 49 | 49 | **48** |
| 720A | **19** | **14** | 14 |
| 520A | **14** | **9** | 9 |
| 320A | 11 | 11 | 11 |
| 421A | 12 | — | 12 |
| 040A | 5 | — | 5 |

Three separate things fall out of that table:

1. **"Ten drops" is six distinct modules**, four of them dropped twice. Any
   count keyed on ten documents is counting four of them twice — and the s3 key
   carries a content sha256, so the duplicates were *not* refused as duplicates.
2. **Two pairs disagree: 720A 19 vs 14, and 520A 14 vs 9.** Same DMC, different
   triple counts, therefore **different bytes**. These are not re-drops of one
   file; they are two revisions of a module with no supersession relation between
   them, sitting in two graphs, both live. That is the identity/supersession
   question I already owe you, now with a number on it.
3. **The deployed bytes are not the repo fixtures.** 941A is 49 deployed in both
   copies against 48 in the fixture, and one each of 720A/520A is +5. So my
   earlier `mrad.ttl` contract diff — zero drift over 99 triples — was run
   against the fixtures and says **nothing** about the bytes that are actually in
   sandbox. I am correcting my own earlier "99 triples over six modules" figure:
   it describes the repo, not the cluster.

Nothing here blocks the pin. It does mean the post-re-drop verification is a
measurement of 112 against a known-heterogeneous corpus, not a tidy 10 × 1.

---

## 5. The roll — helm rev and pod `imageID` after each, as asked

Unlike the two pins before it, **this one needed a new image**: those moved chart
values only, while this changes Python that runs in the code location.
`build-and-push` run `38999054397` on `main` published it (conclusion `success`).

### The digest, from two independent witnesses

| witness | source | digest |
|---|---|---|
| 1 | the push run's own `digest=` output, and its `pushing manifest for …:f4d64400f30f…` line | `sha256:2bf85719d2ca…` |
| 2 | the **registry**, asked separately what the commit-sha tag `f4d64400f30f…` resolves to | `sha256:2bf85719d2ca…` |

They agree. **ghcr sent no `Docker-Content-Digest` header on either fetch**, so
in both cases the digest is computed from the response *body* — a header is a
claim about the body, and the body is the thing.

Index children fetched **by their own digest**, and each one's **config blob**
read to confirm the architecture it was really built for rather than trusting
the index's platform claim:

```
linux/amd64  sha256:f9cb3a5482ee…  200  digest-matches  built-for linux/amd64
linux/arm64  sha256:4a35140a9dbc…  200  digest-matches  built-for linux/arm64
```

Two `unknown/unknown` entries are buildx provenance/SBOM attestations. The arm64
child is the load-bearing one — sandbox schedules onto arm workers, so an index
whose arm64 child is stale pulls green locally and fails there.

### The two rolls

| roll | rev | what moved | pods `imageID` |
|---|---|---|---|
| 1 | **48** `deployed` 04:08Z | `image.digest` → `sha256:2bf85719` | ONE distinct, `…@sha256:2bf85719d2ca…` |
| 2 | **49** `deployed` 04:10Z | `corpusGate.expectImage` only | unchanged, same pod, 0 restarts |

Roll 1's pre-roll diff was the digest in its five label places, two container
images and two `DOC_TOOLS_IMAGE` env values — nothing else, plus the phantom
22-line `doc-tools-test-connection` hook Pod that `helm template` renders and
`helm get manifest` excludes.

Roll 2's diff was **exactly one real line**, the gate CronJob's `EXPECT_IMAGE`.
The Deployment pod spec was untouched, so **roll 2 restarting no pod is the
correct outcome, not a failed roll** — verified both ways: one line in the diff,
and the pod still carrying its roll-1 start time with `restartCount` 0.

**The red window was red by construction, and the diff proved it rather than my
asserting it:** `expectImage` appeared **zero times** in roll 1's diff, which is
positive confirmation it was unchanged while the image moved. So between 04:08Z
and 04:10Z the gate would have compared a `2bf85719` run against a `5846f877`
expectation. Two minutes, ~2h50m clear of `0 7 * * *`; no gate run fell inside it.

### One thing worth recording, because it nearly produced a false reading

**`kubectl rollout status` reported "successfully rolled out" while the previous
pod was still `Running`, pending termination.** For ~84s a read of "the pods"
returned **two** distinct `imageID`s — `5846f877` and `2bf85719` — so the phrase
"ONE distinct value" would have been false, and a read taken on the strength of
the rollout message alone can capture the digest being *replaced*. The value
written into `expectImage` was taken only after the pod count returned to 1.
That note is now in the values file at the line it protects.

### The seal

`scratchpad/seal_image_identity.py` — gate expectation == `DOC_TOOLS_IMAGE` ==
chart `image.digest` == pods' `imageID`, all `sha256:2bf85719d2ca…`. **Three of
three PASS.**

`expectImage` is written from the **pod reading**, not copied from the
`image.digest` line above it, which it happens to equal — that equality is the
result being asserted, not the source of the value.

### What is now true, and what is not

The image carrying the second RDF write is live. **It has not written anything
yet**: the write happens at XML ingest, so `MAINTENANCE_INSTANCES` is still at
**0** until the ten modules are re-dropped. The pin is a precondition, not the
result — do not read this green seal as evidence the instance graph is populated.

And the re-drop is not free: **a failed run's `run_key` is consumed
permanently** (only `NOT_STARTED` falls through, with no time window), so a
retry must mint a **new** key. The retry sensor that would do that has zero runs
because nothing enqueues a failure.

---

## 6. Not in scope, deliberately untouched

The parser; the walk; Option/procedures modelling (Lane 1's, per your ruling);
and `sync_jena_to_neo4j`, which still reads back from `urn:doc:` and is
unaffected.

Local suite on the merged tree: **1702 passed, 12 skipped, 7 deselected**. The
one standing advisory red is `corpus-gate-verdict` against the committed report
(the IDT crop seal), pre-existing and non-blocking — it is the whole reason the
`1d40833` run reads `failure`, where `build-and-push` itself succeeded.
