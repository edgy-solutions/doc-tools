to: architect
cc: Chris, doc-tools/lane/01
from: doc-tools/lane/7f
date: 2026-10-27
re: nightly corpus gate — items 1 and 4 shipped; items 2 and 3 deadlock on a
    constraint this repo already documented. One ruling needed.

# The clock is off. The trigger that replaces it cannot be built as specified.

Items **1** and **4 (requests/limits)** are implemented and pushed on
`7f/gate-triggers-suspend-nightly`, off `main` at `b8a3dd0` so it draws a CI
verdict. Items **2** and **3** cannot be built as written, for a reason the
corpus-gate guard's own docstring states and refuses. Item **4
(`failed:vision_timeout`)** is blocked on Lane 1's wire, not on me.

## What the load actually was, since it is the premise of the order

Measured on the 07:00Z run, mid-fire-2, before changing anything:

- The gate pod: **4 millicores**, 633 MiB. Its node at 19% CPU.
- Fire 1 took ~51 min (3060 s). Model calls account for **3035 s of it — 99%**.

| client | model | calls | total | max |
|---|---|---|---|---|
| VisionBounded | `gemma4-32k:31b` | 46 | 2412 s | 281 s |
| VisionBounded | *(unknown)* | 1 | **300.0 s** | 300.0 s |
| HeaderBounded | `gpt-oss-128k:120b` | 10 | 323 s | 41 s |

So the cost is **images**: 47 vision calls per fire, ~140 per run, every night,
over the same ten notices, against an endpoint that serves one model at a time.
103,919 tokens in and 53,742 out in one fire. Your premise holds, and the
numbers are now in the values file next to the switch.

The `VisionBounded <unknown>` at exactly **300.0 s** is a timed-out call that
returned no model name — one per fire, live in today's run. That is the thing
item 4 names.

## Item 1 — done

`corpusGate.suspend: true`, templated as `suspend: {{ .Values.corpusGate.suspend }}`
and set explicitly in **both** `values.yaml` and `values-sandbox.yaml`. Explicit
in the sandbox file as well as the default because that file is what decides
what the live cluster does, and a reader of it must not have to infer the clock
from a default that could later move.

**The schedule key stays**, and this is not me softening the order: the API
server rejects a CronJob with no `schedule`, so deleting it would make the chart
unrenderable. `suspend` is the field that decides. The CronJob is kept for its
Job template, which is what `kubectl create job --from=cronjob/...` copies — the
sanctioned fire path, and now the only way a run starts.

Rendered and linted: `suspend: true`, `schedule` inert, `concurrencyPolicy:
Forbid` unchanged, chart lints clean, 89 passed / 2 skipped across the chart and
gate guard suites.

## Item 4, requests/limits — done

Before this the container had **no requests and no limits at all**. Unbounded,
and first to be evicted under node pressure, which for a 145-minute run means
losing it at minute 140. Set from the measurement with deliberate headroom:
requests `100m` / `1Gi`, limits `2` / `4Gi`. The requests are a scheduling
floor, not a sizing — the work is 99% blocked on network. The memory limit is
far above the 633 MiB observed on purpose: an OOM kill late in a run destroys
three fires of GPU time, so the limit is there to bound a leak, not to size the
job.

## Item 3 is the deadlock this file already refuses

> *"a pin bump with no report for its digest is refused, which is what forces (a)."*

`tests/test_corpus_gate_guard.py`, lines 24–31, under the heading **WHY THIS
FILE DOES NOT ASSERT THE REPORT NAMES THE INCOMING DIGEST**:

> A report for digest D can only exist after D has been built and rolled — and
> rolling D *is* the pin commit under review. Requiring the report to already
> name the digest of the diff that produces it would make every new pin
> permanently unmergeable (the report for pin N+1 cannot exist until pin N+1
> merges).

That is item 3, verbatim, written down as the thing not to do. The circularity
is real and I confirmed its mechanism in the chart:

`charts/doc-tools/templates/corpus-gate-cronjob.yaml:58` and its
`DOC_TOOLS_IMAGE` env at :103 **both** render from
`include "doc-tools.image" .` — the chart's own pin. A Job created from the
CronJob therefore measures **the digest the chart already pins**, never a
candidate. The template comment says so itself, explaining that a `chart=`
expectation "would compare a value with itself and always match."

So item 2(a) — *"the pin-bump script fires the Job against the new digest"* —
has no mechanism today. There is also no pin-bump script: `scripts/` holds
`pcn_corpus_gate.py`, `pcn_gate_publish.py`, `verify_image_pin.py`, nothing else.

A second wall sits behind the first. Even granted an image override, a pre-roll
fire has **no pods running the candidate digest**, so `corpusGate.expectImage`
cannot be a pod `imageID` reading — and the architect's own 2026-10-02 VOID
ruling makes an unreconciled report `verdict: "void"`, which
`test_verdict_is_pass` refuses. A report that can satisfy item 3 and a report
that can exist before the merge are, as specified, mutually exclusive.

### The three ways out, and the one I would take

1. **Pre-roll fire with an explicit image override** (`--set`-style, or a
   `PCN_GATE_IMAGE` the fire script passes), plus a declared `pre_roll` mode in
   `image_identity` whose expectation is the candidate digest resolved **from
   the registry/release**, not read from the chart diff — otherwise it is the
   self-comparison the template comment warns about. Item 3 then becomes
   satisfiable, and the VOID rule needs one narrow, named exception.
   **This is the only option that delivers item 3 as you wrote it.**
2. **Keep the order's effect, invert the step order:** merge the pin, roll, fire,
   and record the verdict in a small follow-up PR. This is exactly what last
   night was, and your item 2(b) already blesses it. Cheapest, no new
   mechanism, but the pin merges before it is measured — which is the thing
   item 3 was trying to stop.
3. **Roll the candidate out-of-band before the merge** (`--set image.digest=`),
   fire, then merge. No code, but sandbox runs an unmerged pin for ~2.5 h.

I recommend **1**, with **2** as the interim so nothing is blocked while 1 is
built. I have not started 1: which of the three it is changes what gets built,
and building the wrong one here means a trigger that looks live and is inert —
this repo has shipped that shape more than once.

## The consequence of item 1 that the order does not cover, and it bites in 2 days

`test_report_is_not_stale` is **in the required check**, not the advisory one:
`pytestmark = pytest.mark.corpus_gate` covers the file, only
`test_verdict_is_pass` carries `corpus_gate_verdict`, and
`.github/workflows/build-container.yml:826` selects
`-m "corpus_gate and not corpus_gate_verdict"`. `CORPUS_GATE_MAX_AGE_DAYS`
defaults to **3**.

The committed authority report is `generated_at 2026-10-26T09:33:14Z`. It goes
stale at **2026-10-29T09:33:14Z**.

With the clock off, nothing refreshes it. From Thursday morning, **every PR
touching `charts/` or `docs/corpus-gate/` is red on the required check** — and
the only cure is a gate fire, which under the new rules needs a pin bump, whose
PR is itself blocked by the same red. The practical result is the opposite of
the order's intent: instead of a nightly GPU run nobody reads, **every pin bump
requires a ~2.5-hour fire against the OLD image first**, purely to reset a
clock.

I did not touch the staleness arm. It is one line, but which line depends
entirely on your answer above — if item 3 lands, digest-match replaces age
outright and the age arm should go; if it does not, age has to be loosened,
which the same docstring warns against as a "well-meaning loosening." Either
way it is a ruling, not a judgement call, so it is yours. **It needs to land
before Thursday 09:33Z or merges stop.**

## Item 4, `failed:vision_timeout` — blocked on Lane 1, packet sent

`doc_tools/utils/ingest_failure.py` holds `REASON_CODES` as a closed frozenset,
and its own comment states the trap: *"dagster_resources coerces any code
outside this set to `unexpected_error`."* Lane 1's wire rule is stricter still —
anything they do not accept is **422 `invalid_reason_code`**. So adding
`vision_timeout` on my side alone produces either a coerced
`unexpected_error` or a 422 on every emission.

I have packeted Lane 1 for wire acceptance. The **counted** half has three
candidate homes (the gate report's per-fire counters, the crop-seal totals, or
the ingest reason code) and they are not equivalent: a counter in the wrong one
is documentary. I will wire it the moment the code is accepted, to the ingest
path, unless you want it on the gate report instead.

## Not done, deliberately

- Today's 07:00Z run was **left alone** to finish, per your note. It is the
  first nightly to measure v0.2.2; it started 07:00Z and was mid-fire-2 at
  08:36Z.
- Nothing rolled. The PR rides the next pin, as ordered.
- The staleness arm, the trigger script, and the reason code: all above.
