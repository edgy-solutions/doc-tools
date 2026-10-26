to: architect
cc: Chris, doc-tools/lane/tr, invincible-agent/lane/01
from: doc-tools/lane/7f
date: 2026-10-26
re: order complete — v0.2.2 cut, pinned, rolled; tr told; fires running.
    One finding needs a ruling.

# Roll 55 is live. v0.2.2 is running in sandbox.

Order was: *"v0.2.2 at 38b7937, pin, roll, tell tr."* All four are done. The
three header fires are running now. One thing I measured along the way
contradicts what this lane believed about the gate, and it wants your ruling.

## What is live

| | |
|---|---|
| release | **v0.2.2** at `38b793772730f97bba273f837b80bacd7f9b13fd` (#175) |
| index | `sha256:c056fa70…` |
| pin PR | **#177**, squashed as `7d1d923` |
| helm | **revision 55**, `deployed`, 18:47:03Z |
| pod `imageID` | `…@sha256:c056fa701ea3a876c5c79fa2bcd49998ecbf63f78f8cc855d27d212242c9226a` |

**Nothing was rebuilt.** `resolve-release-image` reported
`exists=true, needs_build=false` — v0.2.2 is a tag *added* to the index CI had
already built and gated for `38b7937`, which is why both digest lines moved in
one commit. The pod `imageID` was read back and matches; the code location came
up clean. Both index children were inspected before the edit (amd64
`sha256:4aaaed5a…`, arm64 `sha256:c153d3a0…`), per the arm64 rule.

The values diff was rendered through `scratchpad/preroll_diff.py` before the
roll: **46 changed lines, every one of them the digest** — six version labels,
both container images, both `DOC_TOOLS_IMAGE`, `PCN_GATE_EXPECT_IMAGE`. The
trailing test-connection Pod is a helm hook, which `template` renders and
`get manifest` excludes, so it is not a change. No secret appeared in clear.

Lock taken 18:46:55Z, released 18:49Z once the gates passed. Lane 01's
precheck was clear first: `iagent` rev 218 `deployed`.

## tr is unblocked, and verified rather than inferred

tr's script stops at `SensorNotFoundError` until the sensor is in the deployed
image, so I checked it two ways. `5027cc8` **is** an ancestor of `38b7937`, and
Dagster itself reports, through the webserver's GraphQL, that location
`doc-tools` exposes 15 sensors including:

```
training_sensor                            STOPPED
```

Present, so no `SensorNotFoundError`; stopped, so they can set the high-water
mark before anything ticks. The lock is free and I told them it is theirs
before my fires — their backfill unblocks real decks, my fires are restartable.

## The three fires

Job `pcn-gate-v022-c056fa70`, running on the new pin since ~18:50Z. `--run` is
three sequential fires at ~49 min each, so ~2.5 h. Created from the CronJob,
never hand-run in the code-location pod (whose `DOC_TOOLS_IMAGE` is empty and
would write `measured_image: null` over the authority report). Each fire's
report will record its 2683 red as **"expected, #176 not in pin"**, as ordered
— the gate runs from the image, so #176 takes effect a pin later.

I did **not** hold the roll lock for the fires: the lock serialises rolls, a
standalone Job is not managed by the Deployment, and holding it for 2.5 h would
block tr.

## The finding: `corpus-gate-verdict` skips itself on every pin bump

I told you in the PR that the verdict check would be red and stay red. **It
came back green, and it is green by skipping.** `1 skipped, 6 deselected`,
reason read from the job log at `tests/test_corpus_gate_guard.py:323`:

> report generated_at='2026-10-26T09:33:14Z' measured `sha256:086766d7…`; the
> chart declares `sha256:c056fa70…`. The verdict is therefore NOT evidence
> about this chart.

That is correct reasoning on its own terms. The consequence is the problem: **a
pin bump necessarily moves the chart's digest away from the one the last
nightly measured, so this check disqualifies itself by construction exactly
when a pin is proposed** — the one moment it is meant to speak. It did this on
#177, and it did it on #159, which is the actual reason that pin was "fully
green" with 2683 red the whole time. This lane had recorded a different and
wrong explanation (a report-against-itself digest comparison); that is now
corrected in the handoff.

Meanwhile the required `corpus-gate` job passes — 6 real tests — while emitting
a warning that the report **is a measured FAIL**, and that this

> does not block a merge — currency and identity are what this check asserts —
> but ... it **still blocks the next pin through the corpus-gate-verdict job**.

**That last clause is false.** The mechanism it names never engages on the PR it
is meant to block. So today a red nightly gates nothing at merge time, in
either job, and the warning text asserts a safety net that is not there.

Nothing about this changes the roll — v0.2.2's bytes were gated for `38b7937`
and the fires now running are the real measurement. But two things want your
decision:

1. **Should a red nightly block a pin bump at all?** If yes, the verdict check
   needs to compare against something a pin bump does not invalidate, or the
   gate needs a pre-roll fire on the candidate digest rather than a report
   about the outgoing one.
2. **The warning text should stop claiming a blocker it does not have**,
   whichever way you rule on (1). That one I can fix without a ruling if you
   would rather just have it corrected.

I have not changed either behaviour. Recorded as
`a-pin-bump-makes-the-verdict-check-skip-itself` in project memory.

## Still owed, unchanged

Packet A item 3 (`scratchpad/item3-augmentation-status.patch` on its own branch
off main, plus the contract edit, tests, re-ingesting `_p132`/`_p102`, and a
packet to tr to re-golden); packet B item 1 (the pinned-ref drift seal and the
one-sided-kind arm); packet B item 2 (the four batch-fixture rulings); the
item-2 migration dry run after #167 pins, with wb packeted first. **PR #176**
is green and awaits merge; it lands on the pin after this one. #167 still reads
`mergeStateStatus: UNKNOWN` and wants a look.
