# Design note — the pre-roll fire

For the lane operator who has to run one. A pre-roll fire is a corpus-gate run
against a *candidate* image, before anything is rolled, whose report is then
carried into the pin PR so the required gate arm has something that measures
the digest the PR types. This note is the design: why the shape is what it is,
what each step is defending against, and the traps that are in it because they
already happened here.

Everything below is read off this tree at `f421d7b`, not recalled.

## Why a fire per pin, and not one fire per week

The required arm (`tests/test_corpus_gate_guard.py`, selected in CI as
`-m "corpus_gate and not corpus_gate_verdict"`) asserts that the report
committed at `docs/corpus-gate/latest.json` measures the digest pinned in
`charts/doc-tools/values-sandbox.yaml`. It is a staleness check, not a quality
check. So:

- **A pin bump is red the moment it is typed**, and stays red until its own
  report is cherry-picked in. That red is the guard working, not a defect —
  PR #208 is in exactly that state right now, by construction.
- **A report cannot be reused across digests.** There is no "close enough":
  the comparison is on the digest string.

This is the whole reason the fire exists as a separate, deliberate, 2.5-hour
operation rather than something the roll does on the way past.

## The shape

One command puts the Job up and then refuses to trust it:

    scripts/pcn_gate_prefire.py --image <ref>@sha256:...

- `--image` is **required and must be a digest** (`require_digest`); a tag is
  refused with exit 2. A tag can move between the typing and the pull, and then
  the report names an image the gate will never see again.
- `--namespace` defaults `sandbox`, `--cronjob` defaults
  `doc-tools-corpus-gate`, `--timeout` defaults 180s.
- `--job-name` and `--publish-branch` both default to the digest's first 12 hex:
  `pcn-gate-preroll-<short12>` and `corpus-gate/preroll-<short12>`.

It builds the Job from the CronJob rather than from a manifest of its own —
`kubectl create job --from=cronjob/doc-tools-corpus-gate --dry-run=client
-o json` — then overrides exactly two things: the image, and
`PCN_GATE_PUBLISH_BRANCH`. **The CronJob is the single definition of what a
gate run is**, so a fire cannot drift from the nightly by having been typed
separately. (The CronJob itself is `suspend: true` in both `values.yaml` and
`values-sandbox.yaml` — the clock is off by ruling, and the field stays only
because the API server rejects a CronJob without a `schedule`. It exists to be
the template.)

It then **applies** rather than creates, so re-running the same fire reports a
clean conflict instead of leaving half a Job behind.

### The corroboration, and why it is the point of the script

After apply it polls the pod's `imageID` every 5s to `--timeout` and compares:

| Outcome | Exit | What happens |
| --- | --- | --- |
| `CORROBORATED imageID <digest>` | 0 | the fire is trusted; let it run |
| `MISMATCH ...; deleting job` | 3 | the Job is **deleted** |
| delete failed after a mismatch | 4 | names the by-hand `kubectl delete` |
| `UNPROVEN: no imageID within Ns` | — | Job left **running** on purpose |

The mismatch branch is load-bearing and the script says why in its own words: a
Job that survives a mismatch "spends 2.5 hours of vision calls measuring an
image nobody asked about, and then publishes a report saying it measured the
candidate." That is the failure this script exists to prevent — not a crash, a
**plausible report of the wrong thing**. The failed-delete path is louder than
the mismatch itself for the same reason.

`UNPROVEN` deliberately does *not* kill the Job: a slow pull is not a mismatch,
and killing a good fire at the 180s mark costs another 2.5 hours.

## Never run `--dry-run` into a transcript or a file

`--dry-run` prints the rendered Job manifest, which carries **42 inline env
entries including live `LANGFUSE_SECRET_KEY` and `LANGFUSE_PUBLIC_KEY`
values**. It is there to inspect the overrides, and the overrides are already
printed to stderr as `override <field>: <old> -> <new>` without it. If the
manifest genuinely has to be read, pipe it through a filter that prints **key
names only** — never values, and never to a path. A transcript is not editable
after the fact; this repo has already put three live credentials into one.

The same rule governs reading the pod's env: filter on key names, never
`grep -i <word>`, which matches inside a value.

## Timing, and the lock that nothing enforces

- A fire measured **2h22m-2h34m** wall clock on this corpus. The work is ~99%
  blocked on network — vision and header calls — and was sized from the 07:00Z
  run at 4 millicores / 633 MiB.
- `activeDeadlineSeconds: 21600` (6h) and `startingDeadlineSeconds: 3600`. The
  deadline is four times a fire; it is a runaway stop, not a schedule.
- **The 90-minute roll-lock convention is shorter than one fire.** A fire taken
  under a 90-minute lock overruns the lock by an hour, every time. Hold
  `sandbox/roll-lock` for the measured duration plus the publish, or say
  plainly that the fire runs unlocked.
- `sandbox/roll-lock` is a ConfigMap **asserted by the operator and verified by
  nothing** on this path. The only script in the tree that requires naming a
  holder is `scripts/neo4j_concept_id_migration.py --under-lock LANE/ISO8601`.
  The fire does not check it. Do not read a quiet fire as a held lock.
- `concurrencyPolicy: Forbid` is on the **CronJob**, so it governs scheduled
  runs only. Two hand-applied fires of **different** digests have no guard at
  all and will run concurrently; two of the *same* digest collide on the job
  name and the apply reports it. This is the live edge of the hazard below.

## Four traps, each one already paid for

1. **Two fire scripts wrote the same log paths**, and six fires were read as
   three. Give each fire its own log path, named from the digest the way the
   Job and the branch already are, and count the fires before reading any rate.
2. **A pod Job with no TTY logs nothing until it exits.** Mid-fire silence is
   not a hang and not progress. Watch the pod's phase, not its logs.
3. **`PROMPT_SOURCE` can void the score** by taking prompt text from Langfuse
   instead of the tree. Confirm it before trusting a number, because the run
   will otherwise succeed and report a rate for a prompt nobody reviewed.
4. **`--from-logs` is weaker than `--run`**: it loses wall clock and
   reconstructs the exit. Reduce from the run while the run is still there.

## What lands, and in what order

The in-pod publisher reads `PCN_GATE_PUBLISH_BRANCH` from the env (it takes no
argv) and puts **one commit onto a long-lived machine-owned branch** with a
standing PR — never a push to the default branch, which has no protection and
no required checks. It reads back any `report-*.md` already on the branch that
has not reached `main` and carries it forward, so a second fire does not strand
the first one's report.

Then, by hand, in this order:

1. Cherry-pick the report onto the pin PR. The pin PR's red clears only when
   `docs/corpus-gate/latest.json` names the pinned digest.
2. Move `corpusGate.expectImage` **from the pod's own `imageID`** — in the same
   PR as the report. Never copy the typed `digest:` into it: that makes the
   gate compare the file against itself. This is the two-stage rule, and it is
   in force.
3. A pre-roll report carries `image_identity.checked: false` **by design**. It
   is not a gap, and a guard that treats it as one is wrong; that has been
   contradicted once already.

Note that **anything under `docs/corpus-gate/` sets `charts=true`** and
dispatches both gate arms. That is correct for a report. It is why this design
note sits at `docs/` root instead: a note about firing should not dispatch the
gate.

## What this note does not settle

- **Whether the fire may run unlocked.** The lock is unenforced and shorter
  than the fire. Someone has to rule: extend the convention to the measured
  duration, or state that a pre-roll fire is exempt because it writes only to a
  machine-owned branch.
- **Concurrent fires of different digests.** Nothing prevents them today. If
  two candidates ever need measuring in one window, that needs a guard before
  it needs a schedule.
- **Exemptions.** A one-fire BLANK is exemptable; an intermittent cut never
  earns the instability exemption. A fire that produces one is a fire to
  repeat, not a fire to argue about.

## What never leaves

Rates, counts, digests and file paths may be shown. No document value, no
filename from a private set, no site identifier, and no credential — not even
its presence, except as `len=N sha256:XXXXXXXX`.
