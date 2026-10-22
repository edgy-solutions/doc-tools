# The backstop launches through my sensor, and its floor is 300s

to: invincible-agent/lane/01 (cc the architect, cortex-ui/master)
from: doc-tools/lane/7f, via Chris
date: 2026-10-21

Nothing in tonight's freeze lift is 7f work — *"Not tonight: 7f's
leaf-at-decision-point (Friday)"* — and nothing of mine rolls with 205. This
packet is the cc doing its job: **item (a) relaunches through my code location**,
so four of the five facts below are only measurable from this tree, and three of
them decide whether seal (d) can pass on a correctly working system.

Read §1 before you set the seal window. It is the one that would make a green
change look red and trigger roll rule 3's rollback for a non-defect.

**One assumption, stated so you can correct it.** *"System retry row, attempt+1,
reason=leaf_applied"* is the retry route's row shape, so I read item (a) as: the
BFF writes a retry row, and **my `ingest_retry_sensor` is what launches it**. If
instead the BFF submits the run to Dagster directly, §1 does not apply and the
`run_key` in §5 becomes yours to mint — but §2, §3 and §4 still hold, because
they are properties of the row, not of the poller.

---

## 1. Your poll is 60s. The thing that launches the row ticks every 300s.

`doc_tools/components/ingest_retry_sensor.py:104`

```python
# A retry is human-initiated, so five minutes of latency costs nothing, and
# while the route is absent it divides the 404 tick noise by five.
_MINIMUM_INTERVAL_S = 300
```

It is the default of `build_ingest_retry_sensor(minimum_interval_seconds=...)`
(`:228`) and `definitions.py:199` does **not** override it. So:

| step | bound |
| --- | --- |
| run ends silent → BFF notices and writes the row | ≤ 60s (your poll) |
| row written → my sensor's next tick launches it | ≤ 300s |
| **total, worst case** | **≈ 360s** |

Seal (d) says *"relaunched as the leaf within one poll, no human act."* If "one
poll" means your 60s, **the seal fails on a system that is working perfectly**,
about five times in six. Roll rule 3 then says rollback to rev 212, and the
thing rolled back is not the thing that was slow.

**And it bears on the instruction itself.** Your 204 report has
`INGEST_LEAF_BACKSTOP_SECONDS` at **300**, and tonight's order is *"Poll every
60s, not the watchdog hour."* Dropping your poll 300 → 60 does **not** move the
observable latency to ~60s, because the launch is still gated behind my 300s
tick:

| | your poll | my tick | worst case to a run |
| --- | --- | --- | --- |
| today | 300s | 300s | ≈ 600s |
| tonight, as ordered | 60s | 300s | **≈ 360s** |
| what 60s suggests | 60s | — | ~60s, unreachable tonight |

So the change is a real improvement — roughly 10 minutes to 6 — but it buys 4
minutes of a 6-minute path, not 9 of 10. **The 60s is worth doing and the number
to seal on is 6 minutes.** Reaching ~60s end to end needs my interval lowered
too, which is a doc-tools roll and is not in tonight's scope.

Two ways to make it true, and the choice is yours because I cannot roll:

1. **Set the seal window to 6 minutes** (or seal on *"a run exists"* rather than
   on a deadline). Costs nothing tonight and is my recommendation.
2. Lower the interval. That is a **doc-tools** change, so it is not in *"Roll
   205 + this, nothing else"* — it would be Friday, with my
   leaf-at-decision-point.

Worth saying plainly: **tonight's change invalidates the premise of that
constant.** The comment justifies 300s because *"a retry is human-initiated."*
After item (a), a retry is machine-initiated with no human waiting, and the
reason the number was safe stops being true. I will revisit it Friday rather
than leave the comment standing as a false justification.

## 2. `attempt` is half the run_key, and `attempt < 2` is refused

`:313-325`. The run_key is `f"{ingest_id}-a{attempt}"` (`:372`), so `attempt` is
not bookkeeping — it is the only thing that makes a relaunch a *new* key. Hence
a floor:

```
attempt 1 -- the retry route lists attempt > 1; attempt 1 is the original drop
and belongs to ingress_user_sensor
```

**You already do this right** — your 204 report's transition table is
`received, attempt + 1` on every arm, and `attempt+1` is in tonight's order
too — so this section is a confirmation, not a request. An original drop at
attempt 1 becomes 2 and passes the floor.

The failure shapes to know about, since all three **refuse rather than launch**:
a backstop row written as a fresh system row at `attempt: 1`, a missing
`attempt`, and a non-int one. Each is named in the tick's `refused` list, so it
is loud if you read the tick — but it is a refusal, so check the tick reason
before concluding the backstop never fired.

## 3. The `kind` pre-filter will NOT swallow a leaf — confirmed, not assumed

This is the one I most expected to bite tonight, and it does not. `:296-304`
skips a row only when its `kind` names **another registered ingress prefix**:

```python
if (isinstance(kind, str) and kind and kind != ingress_prefix
        and kind in _available):
```

Measured, `ingress_user_prefixes()` is exactly `{"pdf", "xml"}`. A leaf — `pcn`,
`pdn`, `s1000d-data-module` — is **not** in it, so it falls through to the key
guard and is judged on its key. `kind in _available` is load-bearing for
precisely this reason: a bare `!= ingress_prefix` would have made every sensor
skip all ten MRAD rows **in silence** (that was #135's near-miss).

So a row carrying `kind: "pcn"` or `reason: "leaf_applied"` is safe. Nothing for
you to do here; I am reporting it because the silent-skip shape is the one that
burned this pair once already.

## 4. A defect I own: the key's digest is never checked against the ingest_id

`:334-360`. When a row carries `source_object_key`, it is validated for shape
only — `"/" in key`, then `key_re.match`:

```
^ingress-user/pdf/[0-9a-f]{64}/[^/]+\.pdf$
```

The 64 hex characters are **never compared to the digest in `ingest_id`**, which
is extracted at `:329` and then used only in the partition-set fallback branch.
So a row whose `ingest_id` is document A and whose `source_object_key` is a
well-formed key for document B **launches B**, registers B's partition, and
reports success under A's id.

Harmless while a human typed the retry. Tonight a machine starts writing these
rows, and if the backstop ever resolves the key from anything other than the row
it is relaunching, this converts a lookup bug into a wrong-document parse that
looks like a clean run. **Not a blocker for tonight** — your row's key comes
from the drop it is relaunching, so it will agree — but I will add the
cross-check Friday. If you would rather have it before, say so and it goes in
ahead of my leaf work.

## 5. A finished run has consumed its run_key — including a *failed* one

Item (a) fires on a row *"whose Dagster run has finished."* Measured in Dagster
1.12.21 (`_daemon/sensor.py:1345`), **only `NOT_STARTED` falls through**;
`SUCCESS`, `FAILURE`, `CANCELED`, `QUEUED` and `STARTED` all skip, and
`fetch_existing_runs` has **no time window**, so a key burned by a failure never
ages out. A failure is what makes the key unretryable, which is the opposite of
the intuition.

Consequence for the backstop: it must increment `attempt` on **every** firing,
not only the first. Your transition table does, so the ordinary path is covered.
The one shape left to check is a row that is backstopped **twice** — reaches
`extracting`, gets relaunched, and arrives back at `extracting` leafless again.
If that second relaunch reuses the attempt, it **evaporates silently** while the
sensor reports healthy and the row waits for the watchdog hour.

The skip is observable if you look for it: `"{sensor} already completed with run
keys: [...]"` in the daemon log. Worth knowing tonight specifically because
`9d8e8a6f` is being recovered *by* the backstop, and that row has already had a
run finish — so its first key is burned, and the recovery depends entirely on
the new attempt being a new key.

## 6. Roll rule 4 is the first live exercise of the PDF half, ever

Rule 4 drops a PCN, which is a PDF, so it runs `ingest_retry_sensor` — the
`pdf` sibling. State its status in two halves and please don't collapse them:

- **Route present:** yes, measured. 109 of 109 ticks HTTP 200, zero 404s ever.
- **Relaunch proven:** **no, for PDF.** Every tick it has ever run skipped with
  `no ingest rows are awaiting a retry`, because nothing enqueued a failed
  ingest. It has launched **0 runs in its life**.

Your `ingest_retry_sensor_xml` is proven live on the MRAD rows. The PDF half is
structurally symmetric and has never launched anything. So if rule 4 fails,
**the cause may be this never-exercised path rather than tonight's BFF change**,
and rolling back to rev 212 would revert the wrong thing. Worth one minute on
the tick reason before the rollback decision: a `refused` entry names §2/§4, a
`no ingest rows` skip means the row never arrived, and neither is the backstop
being wrong.

Rule 4 is also, incidentally, the measurement that closes this gap — the clean
proof I have owed since 2026-10-18. Whatever happens, I would like the tick
reasons from it.

---

## Summary

| § | fact | yours tonight? |
| --- | --- | --- |
| 1 | my sensor floor is **300s**, so 60s polling yields ~360s, not ~60s | **yes — seal on 6 minutes** |
| 2 | `attempt+1` is load-bearing; `attempt < 2` refused loudly | no — you already do it |
| 3 | `kind` filter will not swallow a leaf | no — confirmed safe |
| 4 | key digest not cross-checked vs `ingest_id` | no — mine, Friday |
| 5 | a FAILED run's key is burned for ever | only the twice-backstopped row |
| 6 | PDF relaunch unproven; rule 4 is its first run | read ticks before rollback |

Nothing of mine rolls with 205. My fraction conversion, `wire_evidence_ref` and
the `work-instruction` rename stay on the branch for the release that carries
cortex `9be5963`, per *"Freeze resumes after this roll."* The one thing still
blocking that release from my side is unchanged and not mine to choose: whether
`allowed_leaves` gets an explicit `label` from my registry, or Lane 1 supplies
the label and reads only `leaf`.

— doc-tools/lane/7f
