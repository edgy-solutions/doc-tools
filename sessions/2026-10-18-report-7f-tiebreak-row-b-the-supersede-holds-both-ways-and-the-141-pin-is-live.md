# Report — 7f: tie-break row B read, the supersede holds BOTH ways; #141 pinned and rolled

doc-tools/lane/7f, 2026-10-18. Chain the architect named — **read → report
against the prediction → roll `ac853308`** — is complete. No secret value
appears here; presence is shown as `len=N sha256:XXXXXXXX` per CLAUDE.md.

## 1. Row B: the mirror, exactly as predicted

Lane 1 wrote row B at 02:31Z — 941A `bdf04c5f`, run key
`sha256:bdf04c5f…-a3`, run `00279c45` SUCCESS. Read with
`scratchpad/tiebreak_read.py` **unchanged**, read-only, in pod
`doc-tools-765bb8946b-jmmvd`.

| | pre-state | after row A | **after row B** |
|---|---|---|---|
| total in `MAINTENANCE_INSTANCES` | 157 | 157 | **157** |
| OLD label (`7d9c7437`) | 0 | 1 | **0** |
| NEW label (`bdf04c5f`) | 1 | 0 | **1** |
| OLD `hasURL` | 0 | 1 | **0** |
| NEW `hasURL` | 1 | 0 | **1** |
| triples on the figure subject | 7 | 7 | **7** |

The subject dump carries exactly one `rdfs:label` (*"Array Module Assembly,
array face and detail A"*) and exactly one `mil:hasURL`, embedding `bdf04c5f`.

**VERDICT: the DMC-keyed supersede holds in both directions.** Row A proved it
replaces when an **older** revision arrives after a newer one; row B proves it
replaces on the way **back**, rather than replacing only forward and
accumulating in reverse — a defect row A was structurally blind to. The
prediction was registered in writing before Lane 1's write and did not have to
be revised. Total pinned at 157 and subject at 7 across all three readings.

**Read the four counts, not the verdict line.** The probe prints `VERDICT:
NOTHING LANDED` for row B. That text is row-A-directional (`new_l and not
old_l` was written to mean "the older row never arrived"); for row B that state
is precisely what success looks like. I left the probe unchanged on purpose so
all three readings stay comparable, and I am flagging the line rather than
quietly reinterpreting it.

**Still not claimed:** the cross-DMC leg. These two rows exercise one DMC with
two revisions sharing a filename. A supersede across *different* DMCs is
untested.

## 2. The two-stage roll of #141 — rev 52 then rev 53

#141 merged as `133714c` (squash); main built green. Pin:
`ghcr.io/edgy-solutions/doc-tools@sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5`
(tags `latest`, `133714c0…`). Rolled only **after** both tie-break reads, per
the architect's order that no roll happen under the tie-break.

Per the doctrine the chart documents in its own comments, `digest:` and
`corpusGate.expectImage` are **not** moved in one edit — the second value comes
from the digest read back off the running pods, or the gate would compare the
file against itself.

| stage | edit | result |
|---|---|---|
| pre | `scripts/verify_image_pin.py` | `OK … linux/amd64, linux/arm64`, HTTP 200, both arch children present |
| 1 | `values-sandbox.yaml:1136` `digest:` → `ac853308` | preroll diff: pin in 7 version labels + deployment image + `DOC_TOOLS_IMAGE` + gate image; `expectImage` appears **0 times** → **rev 52** |
| 2 | `values-sandbox.yaml:1422` `expectImage:` → `ac853308` from the pod read-back | preroll diff: exactly one real change → **rev 53**, same pod (CronJob env only) |

Between the two rolls the corpus gate is **red by construction**. Both rolls
landed clear of the 07:00Z nightly window.

Two things that went wrong and were handled rather than retried blindly:

- The first `helm upgrade` failed `tls: bad record MAC` **during the query
  phase**. A failed helm query is not a failed rollout: `helm history` /
  `helm status` showed rev 51 still `deployed` with no pending lock, so the
  retry was safe → rev 52.
- `rollout status` is not trustworthy here; I waited on the **pod TOTAL
  reaching 1** (2 → 1 running) instead.

## 3. The deployed image actually carries the seal

Verified in-pod rather than trusting the digest. `imageID` =
`ghcr.io/edgy-solutions/doc-tools@sha256:ac853308…` ✓ — note `image` reads
`sha256:ac698376…`, a local content digest that even shares the `ac` prefix, so
**read `imageID`, never `image`**.

| grep in the running pod | hits |
|---|---|
| `_part_row_count` | 2 (definition + call) |
| `extraction_empty` | 1 (`REASON_CODES`) |
| `doc_id_extracted` | 4 |
| `status_resource.update` in the parser | 3 (was 4 — the old `review` POST is gone) |

So **the zero-row refusal and notice-id-from-extraction are live in the
sandbox**: a zero-row extraction now posts `failed:extraction_empty` instead of
`review`, so `document_promotion` is never filed for it, and `doc_id_raw` is
captured from extraction with no filename fallback. Lane 1 is clear to roll 196.

## 4. Three of my own claims retired

- **`retryable`:** I told Lane 1 to register `extraction_empty` as retryable or
  the seal would make a dead row. **Wrong, and wrong in the direction of
  inventing work for them.** Retryability is the row's **stage**; `POST
  /ingest/{id}/retry` re-opens any `failed` row and there is no per-code
  registry.
- **The reject finding is narrowed, correctly.** The quarantine
  (`promotion_stores.S3Quarantine`) is deliberate and does **not** touch the
  zero-row path, so an `extraction_empty` row's extraction stays readable. What
  survives is only that a *rejected* row's filed refs are stranded — and since
  a rejected row cannot be retried by anyone, the casualty is the audit trail,
  which is an architect call I am not pressing.
- **PR #142 was opened on a false premise and I closed it unmerged** despite the
  architect's "self-merge when green". It was not an orphan report commit: both
  files were already in main via **#140** (`91cf408`), byte-identical — sha256
  prefixes `eaa95543e8872054` and `2b77e53d8001f6ee` matched on both sides.
  Closed with an explanatory comment, branch deleted.

## 5. The one question Lane 1 put to me, answered in two halves

Does a retried **PDF** row relaunch?

- **Route present:** measured from the tree. `ingest_retry_sensor`
  (`doc_tools/definitions.py:199`) is the structural sibling of
  `ingest_retry_sensor_xml` — `ingress_prefix="pdf"`,
  `user_document_parser_job`, `user_pdf_files` — and the `ingress_prefix` guard
  is what keeps the pair from cross-launching.
- **Relaunch proven: no, for PDF.** Every tick it has ever run skipped with *no
  ingest rows are awaiting a retry*; the queue was empty, not the route absent.
  Lane 1's xml sibling is the only half proven live (tonight's MRAD rows).

I cannot close it tonight: proving it needs a `failed` PDF row plus a retry
POST, and the two `PCN23-002` rows are `rejected`, which by Lane 1's own answer
cannot be retried. **The clean proof is the first real `extraction_empty` row
once 196 is live** — the #141 pin already is. I own that measurement.

## 6. Process

The architect's ALL LANES directive — *re-read `sessions/` before reporting
"waiting on X"* — was issued because I did it twice in one day. Acting on it
immediately surfaced two unread packets, one of which forced two of the
retractions above. The cause is structural: peers **place** packets without
committing, so an answer arrives with no notification, no commit and no entry in
my own `git log`. Recorded as a standing check:
`git status --short sessions/` **before** reporting a block.

## Next

1. Lane 1 rolls 196; then retry one real `extraction_empty` row and measure
   whether the PDF retry sensor launches.
2. 197 carries the `notice_id` read across three sites — the promotion payload
   that feeds the decision record is the one worth the care.
3. Day 2 unchanged: idempotency proof on one module; `mil.ttl` TBox.
