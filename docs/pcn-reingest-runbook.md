# Runbook — re-ingesting the PCN corpus notices

**Scope.** Re-ingesting one or more of the 9 PCN/PDN corpus notices through the
sandbox pod, **in place** (same S3 prefix). Written 2026-09-24 for the 5-notice
re-ingest that clears the cut-crop backlog; it applies to any later re-ingest of
the same documents.

**Why a runbook exists for this at all.** A re-ingest is a destructive write over
the exact corpus every `docs/` baseline was measured against. It is not a
re-run — it rewrites crop PNGs, `extraction.json`, `review.json` and the chunk
rows. Nothing about it is idempotent by default; it is idempotent only because
specific fixes were made to make it so, and the checks below are what confirm
those fixes are still in place.

---

## CHECK 1 — is `review.json` still safe to overwrite? (DO THIS FIRST)

A re-ingest **overwrites `review.json`** at the same S3 key. That is acceptable
only for as long as the file carries no human-entered state. Verify that before
every re-ingest, with one command:

```bash
grep -rn "approval_state" doc_tools/ --include=*.py
```

**Expected: exactly ONE hit** — `doc_tools/utils/sustainment_merge.py:125`,
assigning the literal `"pending"`.

- **One hit, literal `"pending"`** → `review.json` is an ingest *output*, not a
  review store. Nothing human is lost. **Proceed.**
- **More than one hit, or any assignment of a non-literal value** → **STOP. Do
  not re-ingest.** A second assignment means something now writes a review
  decision into that file, and an in-place re-ingest would destroy reviewer
  verdicts. The re-ingest must then either skip `review.json` or read-merge the
  human fields forward, and that is a change to design, not a runbook step.

Two supporting facts, so the check can be audited rather than trusted:

- `review.json` is written at
  `doc_tools/assets/semantic_assets.py:427-432`, as **Phase 5 of the
  `build_knowledge_graph` asset** — i.e. on the ingest path, every ingest.
- Its key is `{domain}/inbound/{path}/generated/{doc_id}_pdf/review.json`,
  derived from the normalized `doc_id`, so a re-ingest of the same document
  lands on the **same key** and replaces the file. There is no versioning and no
  backup.

Also worth knowing: nothing in this repo *reads* `review.json` back. If a review
UI is ever added on the read side, re-check this even if the grep still returns
one hit — a reader is usually the thing that arrives just before a writer.

> The grep is step 1 and not step 3 deliberately. It is the only check here whose
> failure mode is unrecoverable: the other checks catch a re-ingest that produces
> wrong data, which a further re-ingest fixes, whereas this one catches a
> re-ingest that destroys data no re-ingest can bring back.

## CHECK 2 — is the chunk write idempotent?

Re-ingest without a deterministic chunk uuid **duplicates every chunk row**
(`_index_chunk` used `data.insert` with no `uuid=`, so Weaviate minted a random
one per write). Confirm the deterministic-uuid fix is in the running image, not
merely merged:

```bash
kubectl -n sandbox exec deploy/doc-tools -- \
  grep -n "generate_uuid5" /app/doc_tools/assets/semantic_assets.py
```

No hit → **stop**; the pod predates the fix and a re-ingest will double the chunk
rows. Check the pin in `charts/doc-tools/values-sandbox.yaml` against the merge
commit and roll before continuing.

## CHECK 3 — record the counters you expect to move

After the run, `_index_chunk`'s tally should read `written` for every chunk and
**`skipped_would_strip_vector: 0`**. A non-zero skip count means the embedding
gateway was down during the re-ingest: the rows kept their old vectors (which is
the correct, non-destructive outcome) but the re-ingest did **not** refresh them,
so the notice is only partly re-ingested. Fix the gateway and run it again —
re-running is safe, that being the point of the deterministic uuid.

---

## The re-ingest

Run from `/app` inside the pod. **Not from `/tmp`** — prompts resolve relative to
the working directory, and a wrong cwd used to return zero parts silently. A
missing prompt file now raises `PromptUnavailableError`, so this fails loudly
rather than producing a plausible-looking near-pass, but starting in the right
place is still cheaper than reading the traceback.

Re-ingest **in place**, same prefix. With deterministic chunk uuids the write is
idempotent, so a fresh prefix buys nothing and doubles the S3 artifacts — and it
would also fork the corpus every prior baseline was measured on, which is worse
than the storage.

### Do NOT try to trigger it by re-uploading the PDF

The intuitive move — put the PDF back and let `sustainment_sensor` fire — is a
**silent no-op**, blocked twice over in `dag_tools`' `S3SensorComponent`:

1. `run_key = f"{ETag}-{obj_key}"`. Dagster deduplicates on `run_key`, and
   re-uploading identical bytes produces an identical ETag, so the run request
   is discarded as already-seen.
2. Object listing starts after `sensor_context.cursor`, so an object already
   behind the cursor is never even listed.

Nothing errors. The sensor just skips, and it looks like the re-ingest "ran".

### Launch the partition explicitly instead

Mirror exactly what the sensor would have built, via the webserver's GraphQL at
`http://iagent-dagster:3000/graphql` (reachable from inside the doc-tools pod):

```
selector      = { repositoryLocationName: "doc-tools",
                  repositoryName:         "__repository__",
                  pipelineName:           "process_document_artifact_job" }
runConfigData = {"ops": {"process_document_artifact":
                         {"config": {"file_url": "s3://processing-artifacts/<key>"}}}}
tags          = [{ key: "dagster/partition", value: <key with "/" -> "__"> }]
```

This is strictly better than a re-upload: it **writes nothing to the source
prefix**, touching only the derived `generated/` artifacts, which is the whole
intent of a re-ingest.

Three things that make the launch safe to trust:

- The run launcher is `DefaultRunLauncher`, so the run executes **in-process on
  the code-location pod** — the doc-tools pod itself, running
  `dagster api grpc -m doc_tools.definitions` on the pinned image. The re-ingest
  therefore provably runs the pinned code, and that is also why the namespace
  contains no dagster run Jobs to go looking for.
- Run **one notice at a time**, even though `QueuedRunCoordinator` permits 2.
  The runs execute inside a pod capped at 4Gi, and `dagster.yaml` records an
  OOMKill of a code-location pod that took its run down with it, leaving the run
  STARTED with all steps IN_PROGRESS for ~8 hours and no failure event — a gap
  `DefaultRunLauncher` cannot close, because it has no worker to health-check.
- A `kubectl exec` that runs the poller can drop without affecting the run. Poll
  from a process **inside** the pod (or re-query by `runId`) rather than
  concluding anything from the exec's exit code.

### Re-ingest the copy that is actually SCORED

Several notices exist as byte-identical copies under multiple prefixes (Diodes
×3, all ETag `abe083fe`; onsemi_IPCN25300X ×7, all `c9674b38`). Identical source
bytes do **not** make the manifests interchangeable: each names its own
`text_location`, and `PREFER` in `scripts/pcn_corpus_run.py` pins which manifest
the score reads. Re-ingesting the wrong copy writes a manifest nothing reads and
moves no number, while looking like a success.

| notice | key to re-ingest |
|---|---|
| PCN23-002 | `sustainment/inbound/PCN23-002.pdf` |
| Diodes_PCN_2683_Rev1_EOL | `sustainment/inbound/diodes_bbox/Diodes_PCN_2683_Rev1_EOL.pdf` |
| Diodes_PCN_2683_FULLGREEN | `sustainment/inbound/Diodes_PCN_2683_FULLGREEN.pdf` |
| onsemi_Generic_IPCN25300X | `sustainment/inbound/onsemi_truthkey/onsemi_Generic_IPCN25300X.pdf` |

Those four are the full set with any `stored_cut` to clear. TYC is **not** in it:
it reads `stored=0` and already scores 26/26 — see the 8/4-vs-9/5 note in
`scripts/pcn_crop_seal.py` for why the backlog was ever described as five.

## Verification

Re-ingest is confirmed by the seal and the score, not by the ingest logs:

```bash
cd /app && python scripts/pcn_corpus_run.py     # identity score + crop seal
```

Run the copy the IMAGE ships, at `/app/scripts/`, not a copy pushed into `/tmp`.
The image contains `scripts/` and `prompts/`, so the in-image harness is provably
the code at the pinned sha — including its ground truth. A `/tmp` copy can be any
vintage, which is how a run gets scored against a denominator that no longer
matches the notice set.

Expect, once all five cut-crop notices are re-ingested:

| signal | expected |
|---|---|
| identity score | **898 / 898** |
| `stored_cut` (crop seal) | **0** |
| `repaired_cut` (crop seal) | 0 — must already have been 0 |
| `crops_row_short` fires | **0** |

`stored_cut` reaching 0 is the definition of a successful re-ingest: it measures
the crops actually in S3, so it is the one number that cannot be satisfied by a
code change alone. If `repaired_cut` is anything but 0, the shipped crop rule
regressed and the re-ingest is writing newly-cut crops — stop and fix that
first, because re-ingesting again will not undo it.

## If it goes wrong

A re-ingest can be repeated. That is true *because* of the deterministic uuid and
the vector-preserving skip, and it stops being true if either is reverted. There
is no rollback for the S3 artifacts — the previous crops, `extraction.json` and
`review.json` are gone once overwritten — so the recovery path for bad output is
always "fix the code and re-ingest", never "restore the old artifacts".
