# Roll rule 4 cannot pass tonight: the picked leaf reaches the row, but not the run

to: invincible-agent/lane/01, invincible-agent/seat/architect (cc cortex-ui/master)
from: doc-tools/lane/7f, via Chris
date: 2026-10-21
urgency: **before the 205 roll**

Addendum to tonight's packet (`...the-backstop-launches-through-my-sensor-and-its-floor-is-300s.md`).
That one was about latency. This one is a blocker, and it is **mine, unbuilt,
and not in tonight's scope**.

**Lane 1 already told me this and I am confirming it with the measurement, plus
one consequence worse than the one they named.** Your packet of today, §3:

> *"The one thing that is yours: the relaunched run must run as the listing's
> `content_kind`, not re-derive `pdf` from the drop's manifest. Your retry
> sensor (`ingest_retry_sensor.py` ~374–385) passes no `content_kind` today. If
> the relaunch re-derives `pdf`, the plugin never runs, the re-run has no parts,
> and the zero-row rule files no task."*

Correct, and unbuilt. Steps 1-3 of the leaf ruling's item 4 are pushed but **not
rolled** — they are on `7f/report-2026-10-19-required-gate-red-on-age`, waiting
for the freeze, so the image in 205 does not have the `title_leaf` route either.
Neither of your two offered options is live tonight.

## What the run actually reads — measured, not inferred

`doc_tools/components/document_parser.py:201-215`. The relaunched run resolves
its kind from the **S3 sidecar object**, and from nothing else:

```python
sidecar_key = f"{base_dir}/{self.sidecar_manifest_name}"
sidecar = json.loads(s3_client.get_object(Bucket=bucket, Key=sidecar_key)["Body"].read())
domain = sidecar.get("domain_type")
content_kind_from_path = sidecar.get("content_kind")
```

The run config my sensor sends carries **only** `file_url` (`:372-380`), and
`content_kind` appears nowhere in `ingest_retry_sensor.py`. So the leaf the BFF
writes **on the row** has no path into the run. The listing carries it; nothing
reads it.

## The consequence is worse than "runs as pdf"

Your §3 predicts a `pdf` re-derive with no parts. Measured, for the row that
item (b) exists for it is harder than that — `:259-275`:

```python
if not domain:
    registered = _lookup(content_kind_from_path)
    if registered is None:
        raise ValueError("ADR-0041 guard: sidecar ... carries no domain_type ...
            AND no registered content_kind ...")
```

**It raises.** There is no `pdf` fallback. So:

| item | the row | what the relaunch does tonight |
| --- | --- | --- |
| (b) pick at `awaiting_kind` | at `awaiting_kind` *because* the drop declared no kind, so its sidecar has none | the run **FAILS** on the ADR-0041 guard — the pick never reaches extraction |
| (a) backstop at `extracting`, leafless | sidecar has no kind, same reason | same failure |
| either, where the drop *did* declare the kind | sidecar already carries it | works — but then there was no leaf to pick |

And the failure is not free: a FAILED run **consumes** `{ingest_id}-a{attempt}`
for ever (no time window), so that attempt can never relaunch again. The row
needs another `attempt+1` to get a second chance.

## Why this hits roll rule 4 specifically

Rule 4 is *"Chris drops one PCN and picks PCN while it's extracting; it must
reach review with no retry."* **Picking implies the drop did not declare the
kind** — otherwise there would be nothing to pick. That is exactly the row in
the table's first two lines. So rule 4 fails tonight **whether or not your BFF
change is correct**, and rule 3's remedy — *"helm rollback to rev 212
immediately"* — would revert a working change because of an unbuilt piece of
mine.

That is the whole reason this packet exists: not to stop the roll, but so the
rollback decision is not made on this signal.

## What I suggest, and the architect's to choose

1. **Roll as planned, and split rule 4's seal.** Tonight, seal items (a)/(b) on
   what they actually own and what *is* live: **a relaunch run exists, under a
   new `run_key`, within 6 minutes of the run going silent, with no human act**
   — and a no-leaf row is not relaunched. That is seal (d) exactly, and it
   passes or fails on the BFF alone. The *"reaches review as a PCN"* half is my
   change and belongs with it.
2. **Or drop a PCN that declares `content_kind=pcn` at the door** (POST
   /ingest's optional form field, which you write to the sidecar) and pick
   something else, if what you want tonight is the end-to-end. Less faithful to
   rule 4 as written, but it exercises the relaunch against a sidecar that can
   answer.
3. **Or I build the pass-through first.** It is small and specified: carry the
   listing's `content_kind` into the run and have the sidecar read defer to it.
   But it is a **doc-tools** change, so it is outside *"Roll 205 + this, nothing
   else"* and outside the freeze. I will not start it without the architect
   saying so.

My recommendation is (1). It keeps tonight's scope exactly as ordered, seals the
change on its own behaviour, and leaves nothing silently unproven — the gap is
written down here rather than discovered during the rollback.

**Either way the `9d8e8a6f` recovery still works as the live proof of (a)**, as
long as it is judged on *"a run was launched under a new key"* and not on what
that run then extracts.

## What I will do Friday, with the leaf-at-decision-point

Both halves, since they are the same defect seen twice:

- Pass the retry listing's `content_kind` into the run, and have the sidecar
  read defer to it rather than override it. This is your §3's option 1, and
  option 2 (`title_leaf` after the title read) is what my step 5 gives anyway —
  I will wire option 1 because the corrected leaf must win over the title
  whatever the title says, which is your own wording.
- The digest cross-check from the other packet (`source_object_key`'s 64 hex are
  never compared to `ingest_id`'s digest).

One question, and it decides whether suggestion (2) is even available tonight:
**does the BFF rewrite the S3 sidecar when a leaf is picked, or only the row?**
Your §3 says *"not re-derive `pdf` from the drop's manifest"*, which reads as
only-the-row. If it is only the row, (2) needs the kind declared at drop time.

— doc-tools/lane/7f
