# HANDOFF — doc-tools :: lane/7f

Branch `lane/7f`, pushed at `59771d9`, nothing unmerged of its own.

State as of 2026-09-23:
- PR #1 MERGED as `38f3d39`; PR #2 MERGED as `0279d83`.
- Sandbox runs helm rev 12 at image `0279d83`, imageID
  `sha256:71a662f0f41a3cbc1484f0b465c83871b3cf3ec09b2487b0a8cc6aea72606046`
  — VERIFIED against that commit's own build log (run 35804122987), not
  taken on report. `38f3d39` is an ancestor of `0279d83`, so the blank-node
  filter on both legs and fix D are both in the running pod.
- `main` has since moved to `6d04e93`. Two files differ between the running
  image and `main` that are not docs: `doc_tools/plugins/sustainment.py` and
  `charts/doc-tools/values-sandbox.yaml`, both from `b11323e`. The 8192
  vision cap is live via the CHART (helm rev 12); the sustainment.py change
  from that commit is NOT in the running image. Nothing in the MESH prime
  touches that path, but do not read "main is green" as "main is deployed".

## Verified this session
- **The green that merged was at `9a5ae75`, not `bee5b4c`.** Correcting the
  earlier report in this file: `bee5b4c` was green (run 35484058642,
  2026-09-20), but Chris pushed `9a5ae75` ("Remove forge") on top before the
  merge decision, and that is the head PR #1 carried into `38f3d39`. It is
  green on its own run, 35680441996 (2026-09-22): all 3 jobs, `tests` 407
  passed / 13 skipped / 0 failed. The delta between the two heads is one
  24-line deletion, `.forge/skills/check-part-sustainment/SKILL.md`.
- Both PR-event runs printed `push: false` in `build-and-push` — a
  `pull_request` build never pushes an image. The push, if any, belongs to
  the `main` event on `38f3d39`.
- No `if:` anywhere in the workflow, so nothing could have been silently
  skipped in either run.
- Blank-node filter asymmetry (Weaviate leg had neither SPARQL nor Python
  layer; Neo4j leg had both) fixed at `a8e2b3e`, test now asserts both legs
  per-function (`_leg_source`), not module-wide. Verified by single-line
  deletion: each leg's guard fails independently; the OLD guard would have
  stayed green with the Neo4j-only fix — that blindness is why this shipped
  unnoticed for 3 months.
- `n<hex>b<counter>` and `N<32hex>` are the SAME writer (rdflib), two parsers
  (notation3 vs rdf/xml). No second writer; existing `isinstance(BNode)`
  check already covers both spellings.
- `aitool_linker` is MANUAL-ONLY in this repo: sensor commented out
  (`definitions.py:221-226`), no `schedules=` anywhere (repo-wide grep,
  empty), no job selects the asset. Cleared as cause of the 77s
  create→update gap on 3 Predicate rows.

## Read, not measured against a live server
- A Weaviate batch re-write with a failed embed OMITS the `vector` kwarg
  (not `None`) → client replaces the whole object → an existing vector is
  stripped, not left alone (weaviate-client 4.21.3 docstrings + wire
  format, `grpc_batch.py:78-91`). Ruled a LOSS by the architect, not "a
  thinner row." Full trace:
  [sessions/2026-09-19-finding-7f-a-rewrite-strips-the-vector-and-the-linker-is-manual-only.md](sessions/2026-09-19-finding-7f-a-rewrite-strips-the-vector-and-the-linker-is-manual-only.md)

## Standing constraint — DISCHARGED
The finding file above was deliberately uncommitted until the PR #1 merge
decision, so that no commit could move the head the merge gate was measured
at. The decision came; it is now committed by name, on its own, after the
rebase. Nothing else rode with it.

## PCN lane — open, 2026-09-24

**PR #11 OPEN**, branch `pcn/pin-c460ac6-and-crop-seal`, commit `a759a0b`:
https://github.com/edgy-solutions/doc-tools/pull/11 — the `c460ac6` pin (which
had been live on the cluster at helm rev 14 while existing nowhere in git),
`scripts/pcn_crop_seal.py`, the seal wiring in `pcn_corpus_run.py`, the
ground-truth correction, and `docs/pcn-roll-c460ac6-2026-09-24.md`. **Standing
rule amended: a pin edit is committed before or with the roll, never after.**

Cluster at helm rev 14, pod `doc-tools-5ccf4db94-tvbll`, imageID
`sha256:d38c3cb0…`. Corpus reads **893/898** by identity (see project memory
[[pcn-corpus-denominator-is-898-not-896]]); seal reports `repaired_cut=0` of 35
tables and `stored_cut=8` — the latter is the re-ingest backlog and stays red.

**PR #12 OPEN** — all three next-PR items plus the runbook, done and pushed:
https://github.com/edgy-solutions/doc-tools/pull/12, branch
`pcn/chunk-uuid-prompt-hardfail-cell-split`. Base is set to
`pcn/pin-c460ac6-and-crop-seal` so the diff shows only its own 14 files
(+1161/−37); **GitHub retargets it to `main` automatically when #11 merges, so
merge #11 first.** Full suite green: **487 passed, 9 skipped.**

1. `_index_chunk` deterministic uuid + three-verdict tally. ✅
2. Prompt resolution hard-fails via `PromptUnavailableError`, re-raised ahead of
   all three broad handlers; `_ensure_prompts_available` validates up front. ✅
3. Tier-1 split rule for comma+newline-joined part-shaped cells. ✅ code + tests,
   **but the TYC 26/26 seal is NOT run** — no local fixture for the notice, so it
   needs a pod run after the roll.

**Three things found while building it, each worth more than the item it came
from:**
- **The `_index_chunk` hard-fail would have silently zeroed every XML chunk
  write.** `index_xml_chunks_to_weaviate` was an unspec'd third caller passing
  chunks with no `chunk_id`; its own per-chunk `except` would have swallowed the
  `ValueError` and materialized successfully with 0 rows. Fixed by stamping a
  content-derived `chunk_id` (`doc_id + section + sha1(text)[:12]`, NOT an
  ordinal — rdflib iteration order is only stable for an unchanged graph) in one
  place in `extract_chunks_from_graph`. Nothing had ever tested that function.
- **PR #11 would have gone red on its own corpus.** The ground-truth correction
  to 898 left `test_shipped_ground_truth_is_self_consistent` asserting 896. Fixed
  in #12.
- **The split rule as first built would have invented a part named
  `see note 4`.** `looks_like_mpn` accepts it (ten chars, two spaces, a digit).
  The fragment floor is now stricter than `looks_like_mpn` on purpose: a rule
  that CREATES values needs a higher bar than one that classifies a value the
  document already separated out.

Then re-ingest the 5 cut-crop notices **in place** (ruled; `review.json` checked
and carries no human state), per `docs/pcn-reingest-runbook.md`, whose CHECK 1 is
the `approval_state` grep. Expected: 898/898, `stored_cut` 0, detector 0 fires.
Interim prediction: after #12 merges and rolls but BEFORE the re-ingest, TYC
should reach 26/26 unaided (its parts come from the text layer; its `stored_cut`
was 0), giving **897/898** with PCN23-002's cut crop the only remaining gap.
Unisolated and left labelled: which table accounts for survey-9 vs seal-8.

**Do NOT merge either PR — Chris merges both in the morning, #11 first.**

## Held / not started (do not build without new authorization)
- The vector-strip writer fix itself — "first writer item after the walks
  draw," explicitly kept out of PR #1. **No longer indefinitely held as of
  2026-09-24** — item 1 above is its trigger.
- **SECOND WRITER ITEM: `_index_chunk`** (`semantic_assets.py:42-73`), held
  under the same order — **now authorized as item 1 of the next PR.** Read and confirmed 2026-09-23, a DIFFERENT shape from
  the vector strip, not a restatement of it:

      insert_kwargs = {"properties": properties}
      if vector is not None: insert_kwargs["vector"] = vector
      client.collections.get(name).data.insert(**insert_kwargs)

  Three facts, in the order they compound. (1) It is `data.insert`, not a
  replace or an upsert. (2) **No `uuid=` is passed**, so Weaviate mints a
  random one — unlike the ontology writer, which keys on
  `generate_uuid5(str(uri))` and is therefore idempotent for named classes.
  (3) On embed failure the `except` sets `vector = None` and the row is
  written anyway, by deliberate design ("BM25 queries still work, and a
  follow-up backfill can populate vectors once the gateway is restored").

  Together those make an ORPHAN VECTORLESS CHUNK: the row has no stable
  identity, so the promised backfill cannot find it to repair it, and a
  re-ingest does not overwrite it — it adds a second copy. The docstring's
  own remedy is unreachable by the row it is written about. Callers:
  `semantic_assets.py:333` and `:373`, and `xml_ingestion.py:294` imports it.
  Same "backfill" promise the vector-strip finding counted unredeemed.

  Two more facts, found 2026-09-23 after the item was first recorded, both of
  which change what fixing it costs:
    * **The caller counts an orphan as a success.** `xml_ingestion.py:375-383`
      wraps the call in `try/except` and does `written += 1` on return. The
      vectorless fallback returns normally, so the run's own written-tally
      reports a row that has neither a vector nor an addressable id. The
      comment directly above that line states the fallback out loud ("BM25
      still works, backfill later") — so the tally is not an oversight, it is
      counting what the design intends. Nothing downstream distinguishes the
      two kinds of written.
    * **A test pins the defect.** `tests/test_semantic_assets.py:185`,
      `test_index_chunk_inserts_via_v4_data_insert`, asserts
      `data.insert.assert_called_once_with(properties=props)` — exact kwargs.
      Passing a `uuid=` fails it. So the held fix is a code change AND a test
      change, and the test that has to change is the one whose name claims to
      describe correct behaviour. Note also what it does NOT cover: it hands in
      a MagicMock client and never exercises the embed path, so the vectorless
      branch — the branch that creates the orphan — has no test at all.
  The fourth call site is `xml_ingestion.py:381` (`:294` is only the import).

  **The architect has ruled on the SHAPE of the fix (2026-09-23) — still not
  authorized to build, but no longer open to design when it is:**
    * **The tally splits.** A count that includes rows with no vector and no
      id is a count of INSERTS, not of searchable chunks. The fix reports
      `written` and `written_without_vector` separately, and the second is
      what the run declares as its own degradation. Same rule as the PDN
      `needs_review` reason strings: name the degraded case, never hide it
      inside the success number.
    * **The test at `:185` changes in the SAME commit as the code**, because
      it is a seal written to match the code instead of the contract.
    * **The changed test needs its own mutation check**: removing `uuid=`
      from the insert must turn it RED. A test that passes both with and
      without the fix has re-pinned the defect at a new address.
    * **The embed-failure branch gets its first test then too** — it is the
      branch that creates the orphan and it currently has no coverage.
- `aitool_linker.py:602-606` `data.replace` on `Predicate` — same stripping
  shape, unbitten (135 rows, 0 vectorless), architect's ruling, held.
- The 16 vectorless BFO/IOF_Core rows + the `IOF_Core` double-manifest
  collision (`prime_databases.py:174` and `:229`) — folded into the vector-
  strip item above, belongs to Lane 1's held manifest work, not this lane's.
- Local test suite hang (python-magic blocks at import on win32, 27/40 test
  files unrunnable here) — recorded as debt. **"GREEN" MEANS CI AT A NAMED
  SHA, AND NOTHING ELSE.** Carried forward at the architect's instruction
  2026-09-23. No local run is evidence here; any claim of green must name the
  run id and the sha it ran on. The `bee5b4c`/`9a5ae75` correction above is
  what happens when that discipline slips by one commit.
- **PR #7 — the docs-only build skip. NOT THIS LANE'S WORK. DO NOT RE-DO.**
  Resolved 2026-09-23. PR #7 turned out to BE the PCN lane's PR
  (`feat/pcn-row-count-detector-router-tests`, open), and it already carries
  the change. The architect's item 4 as written — "paths-ignore on the
  build-and-push JOB" — is not expressible; `paths-ignore` lives only under
  `on.<event>` and would skip all three jobs. The architect has since
  corrected that himself. **The PCN lane's PR #7 is the reference
  implementation; read it rather than redesigning it.** What it does:
    * A new `changes` job runs `git diff --name-only BASE...HEAD` (three
      dots, against the merge base) and publishes `outputs.code`.
    * `build-and-push` gains `needs: [..., changes]` and
      `if: needs.changes.outputs.code == 'true'`. `telemetry-contract` and
      `tests` are untouched and still run on every PR, docs-only included.
    * The ignore list is an ALLOWLIST of one entry, `^docs/`. `charts/` is
      deliberately NOT in it, for the reason this lane would have given:
      `values-sandbox.yaml` is how a commit reaches a running pod *without*
      an image. The 8192 vision cap is live in sandbox as a values change
      only — that is the worked example, and it is in the PR's comment.
    * It fails open in every ambiguous branch (non-push/PR event, tag push,
      zero base sha, unreachable sha, failed diff, EMPTY diff). Worst case
      is an unnecessary build, never a silent skip.
  The "no `if:` anywhere" property recorded above is now spent — but spent
  the right way: a gated job reports as **skipped** in the run, which is
  visible, where `paths-ignore` would have made the run **absent**. That is
  the distinction the `3db8dbb` incident was about, and it survives.

- **CONSEQUENCE OF PR #7 FOR EVERY PIN THIS LANE NARRATES — read before the
  next roll.** Once that merges, **not every commit on `main` has an image.**
  A docs-only merge to main skips `build-and-push`, so no `:<sha>` tag is
  ever pushed for it. Every runbook sentence of the form "pin the chart to
  the merge sha" (including the one in this lane's own re-pin runbook, and
  the agreed PCN sequence "pin commit to the merge sha") becomes conditional:
  **pin to the last sha whose `main` build actually pushed**, confirmed from
  that run's job log, not to whatever merged most recently.
  The failure mode if that is missed is worth naming, because it is NOT the
  one the chart was hardened against. `values.yaml` uses
  `required "image.tag is required..."`, which refuses to render when the tag
  is ABSENT. A tag that is present but was never built renders perfectly and
  fails at the kubelet — `ImagePullBackOff` on a manifest-unknown, minutes
  later, on a release Helm already reported as successful. See
  [[latest-tag-hides-which-code-is-deployed]]: the refusal covers untagged,
  not never-built.

- **The docs-only skip is UNPROVEN and both lanes know it.** PR #7's own CI
  exercised `code=true` only; the skip branch has never run. It fails open,
  which is the safe direction. The first docs-only PR is the test, its body
  should say so, and **if the build runs anyway on that PR, that is the
  finding** — not a non-event.

## Owned by other lanes
- Lane 74 (fleet repo): reading the gateway/frontend re-post endpoint that
  actually explains the 77s Predicate gap (my own saga-inference guess was
  withdrawn per architect's correction — see finding file §3).
- Lane 1 (orchestrator): the manifest work above; "fleet settled" is the
  other of the two words Chris is waiting on.

## Pre-existing untracked (not touched, not mine)
4 items: `eval_draft.json`, `mfg_corpus_report.json`,
`mfg_corpus_report2.json`, `tests/fixtures/`.

## The MESH prime — measured before it runs, 2026-09-23
Narration written, nothing run. Predictions taken off
`invincible-agent/setup/ontologies/mesh_system.ttl` itself so the run can be
read against a number rather than a hope: 75 named `owl:Class`, 63 of them in
the response-shape closure, so **12 groundable classes reach Weaviate while
75 reach Neo4j** — the two stores MUST move by different amounts. Zero
`owl:Restriction` and zero real blank-node structures, so the blank-node skip
count must read **0**. Exactly one class carries `mesh:universalReferent`:
`mesh:Thing`, which is the flag path PR #1 built and the cluster has never
exercised.

TWO THINGS THE ORDER DOES NOT YET ACCOUNT FOR, both in the runbook:
- `prime_databases.py` has **no per-entry flag** — `--upload-only`,
  `--trigger-ingest` and `--wait-for-ingest` all iterate the full manifest.
  A single-file prime has to be driven at the bucket + the one Dagster
  partition (`mesh__mesh_system.ttl`), not through the script.
- **A red retrievability seal costs the Neo4j leg.** The seal RAISES, after
  the Jena POST and after the Weaviate write, and
  `sync_jena_ontologies_to_neo4j` is `deps=[ingest_ontology_to_jena]` — so a
  red leaves MESH in Jena and Weaviate, absent from Neo4j, with `mesh:Thing`
  still missing. Half-landed, and not visible from "the run failed".
  I also do NOT think that red is certain: the seal probes a row THIS RUN
  wrote, fix D writes by name into the space the index actually reads, and
  what `collections.exists` short-circuits is the CREATE, not the write. The
  standing warning was written about the pre-fix writer. Unsettled; the prime
  is what settles it.

## Open questions for Chris
- Whether/when to authorize the vector-strip writer fix ("the walks draw")
  and `_index_chunk`. Both still NOT authorized as of 2026-09-23.
- Whether a red retrievability seal on the MESH prime should be re-driven at
  all. The module has NO auto-retry on the Jena POST by design (an ambiguous
  ReadTimeout could double the graph), so re-firing the partition is a
  decision, not a recovery.

## OVERNIGHT STANDING ORDER — 2026-09-23
The prime is **Lane 1's to run, not Chris's and not this lane's.** The runbook is
placed at
`invincible-agent/sessions/2026-09-23-packet-to-01-the-mesh-prime-runbook-measured-before-it-runs.md`
addressed to `ia-01/lane/01` (left UNTRACKED there, matching the three
`packet-from-ca-*` siblings dated the same day — placing it was the order,
committing another lane's repo was not).

7f is standing by for: both counts before and after, the `mesh:Thing` row, both
seal lines VERBATIM, and the run id.

**THE ONE THING THIS LANE IS AUTHORIZED TO RUN.** If the retrievability seal
reds, materialize `sync_jena_ontologies_to_neo4j` ALONE, partition
`mesh__mesh_system.ttl`, with:

    ops:
      sync_jena_ontologies_to_neo4j:
        config:
          file_url: "s3://ontologies/mesh/mesh_system.ttl"

Nothing else. Verified in source before accepting the contingency, because the
asset's NAME argues against all three properties that make it work:
- **It does not read Jena.** The `n10s.rdf.import.fetch` implementation was
  replaced; it now fetches the TTL from S3 and parses with rdflib — the same
  source the ingest reads. A failed Jena leg does not starve it and a red seal
  does not block it.
- **It re-resolves domain itself** (`config.extra_metadata` → S3
  `x-amz-meta-domain` → raise), so with empty `extra_metadata` it takes `MESH`
  from the object metadata.
- **It is idempotent** (MERGE on URI, SET-not-create) and ends in a verification
  readback that raises both on a class that MERGEd but is not there and on a
  universal-referent partition that does not match the TTL's — so the recovery
  re-checks the payoff read on its own.
`file_url` is REQUIRED on `S3FileConfig` (no default), so an empty-config launch
is rejected before it starts. Verified against the rev the IMAGE installs, not
the local checkout: `uv.lock` pins dag-tools at
`95c7dc211191dbeb5d28dadcbbf5899f1b4a8cf2` and CI syncs `--locked`, while the
local `dag-tools` working copy sits ahead at `6c8363a` — the field is required
at both, but only the first one is evidence. Do NOT re-fire the whole partition to repair a
red: that re-POSTs to Jena, the one leg with no auto-retry and no clear.

Writer fixes stay held, on this run and as a reaction to it.

NEXT TASK (unchanged by the PR #7 work, which is not this lane's):
Chris runs the MESH prime from the runbook — embed gateway first,
then the one partition, counts either side, then the seals. When he reports
the numbers and the seal lines, draft the two packets: `ia-74/lane/74` and
`ia-01/lane/01`, both carrying the landed count, which is what unblocks 32's
probe and the backfill. Then record the retrievability-seal outcome here,
because it settles a question the code comment and the standing warning
currently answer differently. Do not start the vector-strip writer fix or
`_index_chunk` without an explicit new order.
