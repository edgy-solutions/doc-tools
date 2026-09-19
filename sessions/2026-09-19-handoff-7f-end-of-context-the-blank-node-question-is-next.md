# HANDOFF — doc-tools lane 7f, end of context, 2026-09-19

    to:        c:\Users\cnogr\git\doc-tools  ::  lane/7f          (worktree :: branch)
    cc:        ia-01/lane/01 (orchestrator), ia-74/lane/74, the architect
    from:      doc-tools-f6 [5e05c6]
    read-by:   ____________________  (successor: stamp this before you touch anything)

**ROUTING HAZARD, FIRST LINE, BECAUSE IT BIT NOBODY ONLY BY LUCK.** My session ref is
`doc-tools-f6 [5e05c6]`. **There is a DIFFERENT live session named `doc-tools-7f [f76842]`,
started 9 days ago, and it is not me.** "7f" is the LANE; `doc-tools-7f` is somebody else's
SESSION. A message addressed to the bare name `doc-tools-7f` does not reach this work. This is
the exact hazard Lane 1 warned about ("never route by a bare session name") and it is live in
this repo right now. Route by worktree/branch, or by ref in brackets.

---

## 1. THE EXACT NEXT STEP

**THE BLANK-NODE QUESTION. Measure before proposing — it decides the backfill's scope and
possibly the writer's.** 74 measured the index at **96.2% blank nodes**. The question the
architect put: *does the class query at `ontology_assets.py` select anonymous classes on
purpose?*

Environment, in the repo's DECLARED form. **The declared form changed today** (commit
`0688628`), so use these and not the ones in your memory:

```bash
# 1. install — DECLARED at .github/workflows/build-container.yml:128
uv sync --locked

# 2. run the suite — DECLARED at .github/workflows/build-container.yml:130
uv run -- python -m pytest -q -rs

# 3. the four ontology seals alone, while iterating
uv run -- python -m pytest -q -rs \
  tests/test_ontology_assets_universal_referent.py \
  tests/test_ontology_dual_write_fails_the_asset.py \
  tests/test_ontology_rows_are_retrievable.py \
  tests/test_ontology_assets_blank_node_filter.py
```

**`README.md:129` still says bare `uv sync` and is now STALE against CI.** I changed CI and
did not change the README — deliberately, to keep `0688628` to one file, but it is owed.

Then, in order:

1. **Read `tests/test_ontology_assets_blank_node_filter.py` before measuring anything.** It is
   the whole history and it will stop you re-deriving it. It says the leak was real (441
   phantom `:OntologyClass` nodes from this pipeline) and that it was closed at two layers.
2. **Measure the LIVE index**, not the code. The two do not have to agree and the gap is the
   finding. 74 has the 96.2%; get the same number partitioned by `source_ontology` if you can,
   because that property only exists on rows written after today and its ABSENCE is itself a
   dating signal.
3. **Only then** propose scope for the backfill.

**WHAT I ALREADY KNOW, so you do not spend the measurement on it** — and note carefully which
half is measured:

* **MEASURED (read in source, this session):** the Neo4j-sync class query filters blank nodes
  at TWO layers, deliberately — `FILTER(!isBlank(?uri))` in the SPARQL, plus a Python
  `isinstance(row.uri, rdflib.term.BNode)` check. Belt and braces, and there is a test
  asserting both survive. So *that* query does **not** select anonymous classes on purpose;
  it excludes them on purpose.
* **NOT MEASURED, AND THIS IS THE ACTUAL QUESTION:** the **Weaviate** leg's extraction query
  in `ingest_ontology_to_jena` is a *different* query from the Neo4j one, and **I did not
  check whether it carries the same `!isBlank` filter.** Do that first; it is one read, and if
  the two legs disagree it explains the 96.2% immediately.
* **GUESS, LABELLED AS ONE:** that the index's blank nodes predate the 2026-06-15 two-layer
  fix and are simply never-cleaned residue. I have no evidence for it. The paired cleanup is
  described in the source comment as "a separate operation" that may never have run.

---

## 2. STATE

    branch         lane/7f
    head           0688628b43fcba0b5ed7ba9cb7e7c1438b8d5512
    origin         0 behind, 0 ahead  (fully pushed, in sync with origin/lane/7f)
    vs origin/main 0 behind, 5 ahead
    tracked tree   CLEAN — `git status --porcelain` excluding untracked is empty

**UNTRACKED FILES I LEFT, absolute paths, all of them. NONE ARE MINE** — every one predates
this session; I staged only by explicit filename, never `git add -A`:

    C:/Users/cnogr/git/doc-tools/.mcp.json
    C:/Users/cnogr/git/doc-tools/eval_draft.json
    C:/Users/cnogr/git/doc-tools/mfg_corpus_report.json
    C:/Users/cnogr/git/doc-tools/mfg_corpus_report2.json
    C:/Users/cnogr/git/doc-tools/tests/fixtures/            (directory)

Scratch I created, outside the repo, safe to delete, nothing depends on it:

    C:/Users/cnogr/AppData/Local/Temp/claude/c--Users-cnogr-git-doc-tools/8ce5c310-6c8c-4588-96c7-9611a47f91ba/scratchpad/

The five commits, oldest first:

    7ac6caa  feat(ontology): the flag reaches the node, and a partial ingest stops reporting green
    0b0c7d1  docs(sessions): 7f reports back — the flag lands, and the row seal needed a second question
    4531ab0  fix(ontology): fix shape D — declare the named vector space, and write by name
    8f68454  docs(sessions): amend the 7f handoff — fix D landed, and the venv was the other bug
    0688628  ci: test what ships — --locked on both halves, and the comment's conclusion flipped

### PR #1 — GREEN, UNMERGED, and Chris lands main

https://github.com/edgy-solutions/doc-tools/pull/1

    telemetry-contract   pass     12s
    tests                pass   1m03s      402 passed, 13 skipped, 0 failed, 11.05s
    build-and-push       pass  34m17s
    conclusion: success
    uv sync --locked  ->  "Resolved 384 packages in 1ms"    (the locked install, proven in CI)

**THE PR BUILD RAN `push: false`. No image was pushed, no tag moved, nothing deployed.**
Measured two ways: `build-container.yml:468` reads
`push: ${{ github.event_name != 'pull_request' }}`, and the job log prints `push: false`. The
34 minutes was build-only validation across linux/amd64 + linux/arm64.

### CORRECTION TO THE WORK ORDER — merging main does NOT move `:latest` here

The handoff order says to record "that merging main moves `:latest` under imagePullPolicy
Always." **That is not true of doc-tools, and I checked rather than recording it.** Measured:

    charts/doc-tools/values.yaml:6         pullPolicy: IfNotPresent
    charts/doc-tools/values.yaml           NO `tag` default AT ALL — deliberate, with a comment
                                           saying a "latest" default "made this file say the same
                                           word it said six months ago"
    charts/doc-tools/values-sandbox.yaml:34  tag: "d3ca169091854add1223589201784e146c027e2d"
    charts/doc-tools/values-sandbox.yaml:40  pullPolicy: Always
    templates/deployment.yaml:53           `required` — the chart REFUSES to render without a tag

**There is no `:latest` anywhere in this chart.** The sandbox is pinned to an exact sha, and
`pullPolicy: Always` is retained deliberately (the comment says it is now unnecessary against
an immutable tag but changing it in the same edit would give a rollback two variables). So
**merging main changes nothing in the cluster** — the sandbox keeps running `d3ca169` until
somebody re-pins the tag, which the chart makes a required, visible act.

This matters for the successor twice over: it means **no prime can run this branch's code
until the tag is re-pinned**, and it means the fleet-wide `:latest` hazard does **not** apply
to doc-tools. (It may still apply to the iagent chart; that is not mine.)

---

## 3. MEASURED vs INFERRED — per claim

### MEASURED

| claim | how |
|---|---|
| `mesh:Thing` survives every filter and carries the flag | parsed master's `mesh_system.ttl` (329 triples, 74 named classes) through the REAL filters; label "Thing", `"true"^^xsd:boolean`, nothing `subClassOf` it |
| 60 of those 74 classes ARE response shapes | same run; `mesh:Thing` is not one |
| `owl:Thing` is filtered as meta | `_is_meta_ontology_iri` returns True — asserted against the filter, needs no cluster |
| Sandbox baseline: 73 `mesh#` nodes, `mesh:Thing` ABSENT, ZERO nodes carrying `universal_referent` | three cypher-shell reads, read-only |
| weaviate-client 4.21.3's batch does not raise on per-object failure | read the installed wheel, `collections/batch/base.py:722` |
| `.venv` held `iagent_mesh-0.3.1` while pyproject/uv.lock both pin v0.9.1 | dist-info directory name |
| `uv lock --check` passes | exit 0, lock clean, run independently after Lane 1 |
| `uv export` emits the lock's resolved commit | `...@557976d2f1…` matches `uv.lock`'s `#557976d2f1…` exactly |
| `uv export --locked` changes no version | byte-identical across all 1,448 requirement lines, header line aside |
| No re-embed path exists in doc-tools | all 17 assets, all 3 files in `scripts/`, and both `.data.replace` call sites (`aitool_linker.py:604`, `collection_marker.py:155`) — properties-only, no vector |
| "backfill" promised 4× in 3 writers | `ontology_assets.py:847`,`:859`; `semantic_assets.py:67`; `xml_ingestion.py:380` |
| The chart has no `:latest` | above |
| PR build pushed nothing | workflow line + job log |

### INFERRED — not measured, treat as guesses

| claim | why it is a guess |
|---|---|
| Fix shape D's *mechanism* (bare create on 4.21.x emits the named space) | 74 inferred it, then their scratch-collection run measured it. **I did not personally verify either.** I implemented to the architect's ruling. |
| Neo4j's `SET c.p = null` removes the property | documented store semantic. **My tests do not cover it** — they stop at what the asset sends to the driver. This is the one link the withdrawn node read would have closed. |
| The index's blank nodes predate the 2026-06-15 fix | no evidence. See §1. |
| The 4 stray packages came from something outside `uv` | they are absent from `uv.lock` and from Lane 1's venv; the actual installer is unidentified |

### REPORTED TO ME, not measured by me

* 74: the index is **96.2% blank nodes**; **16 real classes are vectorless today**.
  **Note this REVISES the ~1,315 figure** I was given earlier and repeated to Lane 1 — if
  1,315 was the raw vectorless count and 16 is the count of *real* classes among them, the
  difference is the blank nodes, which is itself a strong hint for §1. **Do not carry 1,315
  forward without re-deriving it.**
* 74: `Predicate` and `OntologyClass` both broken, `DocumentChunk` the working control.
* Lane 1: shape D mirrored for `Predicate` at `14b23c2` on lane/01.

---

## 4. RULED vs OPEN

### Ruled, and built

* **Work order 2026-09-19 §1** — the sync carries `mesh:universalReferent`; seal is a
  partition; `Mechanics` comment corrected. `7ac6caa`.
* **Dispatch 7f, Rulings 1–3** (Lane 1, on the same work order) — dual-write failure fails the
  asset; manifest→row seal derived from the run's own record, not a manifest copy; readiness
  sentinel per domain **and per entry**. `7ac6caa`.
* **Ruling 1, extended** — Lane 1 ACCEPTED my correction that the batch error channel must be
  read, since a re-raising `except` never sees per-object failures.
* **Fix shape D** (architect, on 74's scratch-collection result) — declare the named space at
  create, write by name. `4531ab0`.
* **CI** (architect, this order §2) — `--locked` on both halves, own commit, no re-lock.
  `0688628`.

### Open, and whose

| open | whose |
|---|---|
| The blank-node question | **YOURS. §1.** |
| Backfill of the 26,239 rows / the 16 vectorless real classes | 74 scopes; **Chris authorizes** |
| A re-embed path (none exists) — and it is NOT ontology-specific; `DocumentChunk` and `semantic_assets` carry the same unredeemed promise | scope only, **build nothing until the walks draw** |
| An authorized prime + re-pin of `values-sandbox.yaml` tag, to put `universal_referent` on a real node | **Chris** |
| Lane 1's pool leg (reads `universal_referent`) | ia-01/lane/01 — they will not build until the confirming query returns |
| Does `mesh:explain`'s pool exclusion survive a working vector search? | ia-01/lane/01, ahead of the pool leg |
| `IOF_Core` twice in the manifest, colliding on `generate_uuid5(uri)` | ia-01/lane/01 → architect |
| `test_the_imported_sdk_IS_the_pinned_artifact` | **OWED, held until four walks draw** |
| `README.md:129` stale vs CI's declared `uv sync --locked` | owed, small |
| engine-o `/health` is a config read, not an ingest check | ia-01/lane/01 |

### The confirming query — for the next authorized prime

```cypher
MATCH (c:OntologyClass) WHERE c.universal_referent IS NOT NULL
RETURN c.uri, c.label, c.universal_referent;
-- expect exactly ONE row: http://invincible-agent/mesh#Thing | Thing | true
```

---

## 5. WHAT I GOT WRONG, AND WHAT CAUGHT IT

1. **I said the 7 `test_collection_marker` failures were "possibly fallout from the v0.9.0 →
   v0.9.1 pin move."** Wrong. The pin was correct; the venv held a four-releases-stale
   artifact. **Caught by Lane 1**, who measured it from the other side. Their route was module
   subsetting; the dist-info names the version outright, which is the better instrument and
   they adopted it.
2. **I flagged the stale CI comment to Lane 1 as theirs.** It was doc-tools'. **Caught by Lane
   1**, who checked their own repo and found `build-containers.yml` (plural) already using
   `--locked`. Then I found a second dead justification they had not checked, which reversed
   the comment's conclusion — so the correction ran both ways.
3. **I nearly hand-ran a re-sync into the sandbox Neo4j.** Port-forward open, script written.
   **Caught by the architect's withdrawal**, and on reflection by Ruling 3's own premise: the
   safety classes were re-ingested once by hand and the sentinel was green on both sides.
   Doing it to produce a screenshot for a handoff is that act with better intentions.
4. **I claimed `uv export --locked` "changes nothing" before checking.** The first diff came
   back DIFFERENT. **Caught by running the diff instead of asserting it** — the delta was my
   own stderr capture plus the header line; content was identical across 1,448 lines. The
   claim was right and the confidence was not yet earned.
5. **The work order told me `mesh:Thing` was on invincible-agent master. It was not** — it was
   on two lane branches. Caught by `git merge-base --is-ancestor`, run because the precondition
   check was ordered before the build. Lane 1 then merged it at `51db099`.
6. **This order's own `:latest` premise does not hold for doc-tools.** Caught by reading the
   chart instead of recording the claim. See §2.

**The pattern in all six, and it is the session's real finding:** a justification that was true
when written, is load-bearing, and nobody re-measured it. The stale `Mechanics` comment, the
stale CI comment, the stale venv, the stale work-order premise, the stale `:latest` assumption.
**Re-measure the premise you are handed, especially when it is stated as settled.**

---

## 6. STANDING

* **Nothing touches a shared store without Chris.** No re-sync, no ingest, no prime, no
  backfill, no re-embed. This session wrote to no store: **three cluster reads, zero writes.**
* **No instrument work until four walks draw.** The pinned-artifact seal is specified and
  deliberately unbuilt.
* **Never release commits you did not write.** PR #1 is UNMERGED and stays that way; Chris
  lands main. The five commits on `lane/7f` are mine and are pushed.
* **Expect the red.** `seal_a_written_row_is_RETRIEVABLE` will fail every ontology ingest until
  74's backfill lands. That is correct — an ingest producing unsearchable rows has not produced
  a grounding pool — and it is not a regression.

Lane: doc-tools/7f
