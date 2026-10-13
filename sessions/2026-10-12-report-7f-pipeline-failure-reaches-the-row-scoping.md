# Pipeline failure must reach the row — the 7f half, scoped and measured

Report, lane 7f, 2026-10-12. Raised by the packet
*"to: doc-tools/lane/7f + ia-01/lane/01 — pipeline failure must reach the row"*.
7f owns the op/sensor side; Lane 1 owns the route/status side.

This is the institutional answer to
[the user-drop halt report](2026-10-12-report-7f-user-drop-halts-on-a-skipped-kind-picker.md)
written earlier today, and it closes that report's worst open end: **a failed
row becomes retryable.** That report established that a re-upload cannot
retrigger an ingest (ETag+key run key plus a sensor cursor absorb it
silently), so the five blocked drops had no recovery path at all.
`POST /ingest/{id}/retry` is one.

## The headline: less was missing than the packet assumes

`failed` is **already** a postable wire stage and the op **already** POSTs it.
`_WIRE_POSTABLE` at `doc_tools/utils/dagster_resources.py:69` is
`{"extracting", "review", "failed"}`, and the op's error boundary calls
`status_resource.update(ingest_id, "failed", detail=str(e))`.

**CORRECTED — I had this wrong, and Lane 1 caught it.** My first reading was
that tonight's traceback therefore *did* reach Lane 1's row, as an unstructured
`failed`, and that the packet's real content was only the payload. False. The
`try:` whose handler posts `failed` opens at `document_parser.py:332`; the
ADR-0041 guard raises at **:253**, and the sidecar read at **:197** — both
*before* that `try`. So the whole sidecar-and-guard family raises **outside the
error boundary** and posts nothing at all. Lane 1's packet says it plainly:
those "are the rows that sit at `received` for ever."

I had checked that `ingest_id` is read (at :206) before the guard fires, and
concluded the stamp could therefore be addressed — but never checked whether
the guard was inside the `try` that does the stamping. A join key in hand is
worthless if no handler runs.

So the packet's content is **both** the payload *and* the stage: for the one
failure the architect named by name, `kind_unregistered`, there is no `failed`
POST today at any level of structure.

## Two things I expected to block this, measured instead of assumed

**1. A false blocker, disproven.** `iagent_mesh.ingest.IngestStatus` is
`model_config = {'extra': 'forbid', 'frozen': True}` with exactly two fields,
`stage` and `detail`. Read literally, that says the packet's four new fields
cannot be sent until the SDK ships them — a blocker on another lane, and the
kind of thing it is tempting to report straight from the model.

Probed against the live sandbox gateway instead, from inside the pod, using a
canonical but **nonexistent** ingest_id so nothing was mutated:

    {stage, detail}                                    -> 404 ingest_not_found
    {stage, detail, reason_code, step, run_id, pin_digest} -> 404 ingest_not_found

Identical. A 404 means request-body validation already passed, so Lane 1's
route does **not** validate with the SDK's `extra="forbid"` model. **The fields
are accepted on the wire today.** Had I reported from the model alone I would
have declared a blocker that does not exist and stalled my own half behind an
SDK bump.

What the probe does *not* prove: that the fields are **persisted**. They are
accepted and currently ignored. Landing the field is exactly Lane 1's half.

**2. A real gap, confirmed. `pin_digest` cannot be filled with what it is
named for.** In the running pod:

    DOC_TOOLS_IMAGE   = []                                              <- empty
    DOC_TOOLS_VERSION = [doc-tools@8725e048429be73450a7b83d2ccd0aa0d76015cb]

`DOC_TOOLS_IMAGE` is absent from the deployment's env (it arrives, when it
arrives, via `envFrom` a ConfigMap). The only running-code identity available
in-process is a **git sha**, not an image digest. So the field is sent with the
best available identifier and a consumer must not parse it as a bare digest.

**The fix is mine and it is small:** add `DOC_TOOLS_IMAGE` to the chart's
ConfigMap so the name becomes true. Not folded into this unit — a chart change
is a `charts/**` diff, which is what the required `corpus-gate` job is
path-gated on, and the pin+report commit already owns that filter tonight.

## What the four 7f deliverables actually are

**(a) The op error boundary POSTs the structured failure.** Straightforward.
One addition is mine, not the packet's: the boundary today stamps *only* when
`ingest_id` is already known, and logs a gap otherwise — the sidecar-read
failure happens before the id is read. That gap is closable: the sidecar's
`ingest_id` is `sha256:` + the 64-hex segment of its own S3 key (measured on
the real drop — path `734d9c94…`, sidecar `sha256:734d9c94…`, same), and the
sensor's `s3_filter` guarantees that segment exists. Derived as an explicit
fallback, so the one failure class that could never reach the row now can.

**(c) `kind_unregistered`.** The SDK declares **no** reason-code vocabulary —
`iagent_mesh.ingest` exports `INGEST_STAGES`, `IngestStatus`,
`ContentKindUnregistered`, `_TERMINAL_STAGES`, `_DETAIL_REQUIRED_STAGES`, and
nothing resembling `REASON_CODES`. This repo's standing doctrine for this seam
is *"import the vocabulary, never mirror it"*, so declaring one locally is a
documented exception, to be replaced by an SDK import the moment one exists.
The packet's chosen name is not arbitrary: it matches the SDK's existing
`ContentKindUnregistered` exception, so the vocabulary is derivable rather than
invented.

The classifier matches on guard **message text**, because these guards raise
bare `ValueError`/`RuntimeError` and there is no type to switch on. That is a
real weakness, so each real message is locked by a test: rewording a guard
fails CI instead of silently degrading every failure to a generic code. Typed
exceptions at the raise sites are the right long-term fix.

**(b) The sensor side is not what it looks like.** `ingress_user_sensor` is a
declarative `S3SensorComponent` from **dag_tools**, an external dependency in
`site-packages`, not a function in this tree. **It has no error boundary of
mine to wrap.** So "the sensor POSTs it for pre-op failures" cannot be
implemented as written, and the honest answer is that **(d) the watchdog *is*
the sensor-side mechanism** — not an additional item. A drop that the sensor
never converted into a run is indistinguishable, from this side, from a drop
whose run never started; one reconciler covers both.

**(d) The watchdog is NOT mine — Lane 1 has already built it.** I had scoped a
7f-side reconciler (enumerate S3 drops, check for an extraction artifact and a
run, POST `failed:timeout`) because enumerating rows from Lane 1's per-id route
is impossible. That work is **cancelled**: Lane 1's packet claims the watchdog,
fixes `timeout` as the one reason code they own and write, and sets the bound at
**600 s** (`INGEST_RECEIVED_TIMEOUT_SECONDS`) — deliberately *not* my 30 s
sensor tick, because a run queued behind `max_concurrent_runs` sits at
`received` legitimately (they counted 8 QUEUED runs during the 187c prime).
Their `timeout` is also **provisional**: a later `extracting`/`review`/`failed`
POST from me supersedes it, while every other failure stays terminal and a POST
off it is 409 `backwards_move`.

So `timeout` must be **reserved, documented, and never emitted by this lane**.
Having sequenced it separately rather than building it in one unit is the only
reason it is not duplicated work.

Convergence still holds, with the owner corrected: those five blocked drops are
exactly the rows `failed` + retry is for, and Lane 1's watchdog plus retry is
the "recovering the five" path the earlier report said needed one.

## The deliverable the architect's packet did not contain

Lane 1 found the hole, and it is squarely mine: **`POST /ingest/{id}/retry`
re-opens the row but nothing relaunches the run.** The retry moves
`failed → received` and increments `attempt`, and `ingress_user_sensor` will
never pick the object up again — its LastModified cursor has passed the object,
the cursor advances whether the run succeeded or not, and the run_key
`{ETag}-{key}` is unchanged for unchanged bytes. This is the same mechanism
recorded earlier as "a re-upload cannot retrigger an ingest", now reached from
the other direction: the retry is the legitimate re-trigger, and it is inert.

Lane 1 offered three shapes and deliberately recommended none.
**Shape 1 is the one that fits, and my own measurement is why:** Lane 1 adds a
service-only `GET /ingest/retries` listing rows at `received` with
`attempt > 1`, and this side launches them with run_key
`{ingest_id}-a{attempt}` — an attempt-scoped key, so Dagster's dedup stops
being the thing that swallows a retry.

Crucially it does **not** mean modifying `ingress_user_sensor`. That is an
external `dag_tools` component with no seam of mine (the same finding that
reshaped deliverable (b)), so the retry poller is a **new, standalone Dagster
sensor** that never touches S3 or the cursor at all. Shapes 2 and 3 both invert
the ownership that makes this tractable — 2 puts Lane 1 inside my bucket
layout, 3 couples Lane 1 to my job's config shape — and Lane 1 said they would
rather not, for the same reasons.

Shape 1 obligates Lane 1 to build a route, so the choice is stated here for
confirmation rather than sent as a commitment on another lane's behalf.

## What review caught after the build: one emittable code could never post

`ingest_id_malformed` was in the emittable vocabulary and **structurally
unpostable**, and the mechanism is worth recording because it is the same
shape as the boundary error above — a join key in hand that no handler can use.

`canonical_ingest_id()` raises *without assigning*. So when the ingest_id guard
is the thing that failed, `ingest_id` still holds the sidecar's **malformed**
value. It is truthy, so a plain `ingest_id or <path fallback>` selects it; the
resource's own canonical check — one of its pre-existing raising validations —
then refuses it; and the handler's never-mask-`e` wrapper swallows the refusal.
Classification was correct, the POST was attempted, and nothing reached the row.

Measured, not reasoned: `canonical_ingest_id` on a uuid classifies as
`ingest_id_malformed`, and the path-derived fallback for the same drop resolves
to the canonical id — the **same row** the malformed value was trying to name,
which is why the fallback is not the substitute row
`canonical_ingest_id`'s own docstring forbids.

Fixed with one shared `resolve_join_key(candidate, source_object_key)` used by
both handlers, which prefers a candidate **only when it is already canonical**.
Three tests lock it, including the uuid / bare-hex / truncated / wrong-case /
empty / non-string cases and a drift check that the mirrored canonical pattern
still equals `ingest_id.INGEST_ID_RE`.

**The general lesson, twice in one unit:** a code in the vocabulary is not a
code that can be emitted, and an emitted code is not one that reaches the row.
Each link wants its own measurement.

## Sequencing, stated rather than implied

Unit A (classifier, resource payload, op boundary, tests) and Unit A2 (the
boundary around the sidecar/guard region, Lane 1's four wire rules, `timeout`
reserved) are **built and green**: 1605 passed, 16 skipped, 7 deselected, from
a baseline of 1580.

What is deliberately NOT built: the watchdog, which is Lane 1's (above), and
the retry relaunch, which waits on the shape decision. Neither can be verified
end-to-end from this side yet, because **Lane 1's `failed` field and retry
route are on an unmerged branch**. The 7f side can be built and unit-tested in
full; it cannot be confirmed against a live row until their half lands. That
limit is on the unit, not on the tests: every assertion here is about what this
lane PUTS on the wire, which is the part this lane owns.

Also still open from the prior order: tonight's three fires are in flight, and
the pin plus its report must be committed **together** so the required check
sees a report stating 522. That is unchanged by this packet.

## One unresolved reference

**"both in 188" resolves to nothing.** There is no issue, PR, or milestone 188
in `doc-tools`, and no issue 188 in `invincible-agent`. It is a forward
reference to something not yet filed, or a fleet-level identifier outside
GitHub. I cited the packet text in the PR body rather than guessing a link —
say which it is and I will attach it.

## Evidence discipline

The gateway probe ran **inside** the doc-tools pod via `kubectl exec -i`, so no
token was minted locally and no credential was materialized. Pod env was read
by **key name only**, never by value, except `DOC_TOOLS_IMAGE` and
`DOC_TOOLS_VERSION`, which are not secrets and are quoted above because the
whole finding is which of them is empty. No YAML was dumped from the
secret-bearing CronJob. All Python ran through this repo's venv.
