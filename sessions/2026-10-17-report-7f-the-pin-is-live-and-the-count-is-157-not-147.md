# Report: the supersede pin is live, the count is 157, and six rows cannot test it

doc-tools/lane/7f, 2026-10-17 (Day 2, after Chris merged #138)

Three things were ordered: roll the main build, name the pin to Lane 1, then
read `MAINTENANCE_INSTANCES` after their six rows against my derivation. The
first two are done. The third cannot be started — Lane 1 has not written the
rows — but reading the graph *before* them changed what the third one means,
so that is most of this report.

## 1. The roll — helm revision 51, pin `sha256:65c199e8`

`#138` is merged as **`6023d27`**. Its `main` build, run **39080832949**,
finished green at 00:29Z (41m in `build-and-push`).

**Digest `sha256:65c199e892ebcd161b0bf9f3a393f27a351b84c78436a524e920c91305c01f64`**,
from two agreeing witnesses, as the lane rule requires: the push run's own
`digest=` output, and the registry's answer for the
`6023d27d054c095bbb6ea1f68c49f98ea5fcbeea` tag — the latter **computed from
the response body**, because ghcr sent no `Docker-Content-Digest` and a header
is only a claim about a body.

Both pin keys moved (`image.digest` line 1136, `corpusGate.expectImage` line
1422), and the tree was on merged `main` first, because **helm reads the
working tree**.

**The pre-roll diff was shown before the roll, per the repo convention, and it
was the digest and nothing else:** six `app.kubernetes.io/version` labels, the
Deployment image, `DOC_TOOLS_IMAGE`, the gate CronJob's image and env, and
`expectImage`. The only other delta was the `test-connection` hook Pod — the
known phantom, since `helm template` renders hooks and `helm get manifest`
excludes them. Worth noting that I ran the diff **twice**: once before touching
the digests, which showed *only* the phantom. That is what licences attributing
the second diff entirely to the pin.

**Convergence took 65s, on the condition that actually holds.** The trap
reproduced exactly: at the first look, TOTAL was **2** — the old pod
`...m79cf` `Running` on `94f09a76` while the new `...jmmvd` was still
`Pending`. A `Running` count of 1 would have passed right then, on the old
code. The condition is the pod **TOTAL** reaching 1 *with the expected digest
on it*.

Seal green four ways — chart `image.digest` == chart `expectImage` == pod
`DOC_TOOLS_IMAGE` == pod `imageID` == `sha256:65c199e8...`, one pod, **0**
restarts. And the check that matters most, because the pod runs the image and
not my tree: the container reports `DOC_TOOLS_VERSION=doc-tools@6023d27d...`
and carries the supersede predicate itself at `semantic_assets.py:1041`.

Landed as PR **#139** (`chore/pin-sandbox-6023d27`), after the roll.

## 2. The pin is named to Lane 1, and the hold is lifted

The placed packet in `invincible-agent/sessions/` now carries the digest, the
helm revision, and the release of the hold. Its **filename still says "not yet
live"** — I left the path alone so the link Lane 1 already has still resolves,
and flagged the staleness in the first line of the body instead. Renaming a
packet someone may be watching trades one failure mode for a worse one.

## 3. The number is 157, not 147 — and I had it wrong

I derived 147 from `tests/fixtures/s1000d/mrad/`. Before Lane 1 writes
anything I read the live graph (read-only, in the pod, at the old pin):

| DMC | live in `MAINTENANCE_INSTANCES` | fixture, production args | delta |
|---|---|---|---|
| 040A | 5 | 5 | — |
| 320A | 11 | 11 | — |
| 421A | 12 | 12 | — |
| 520A | **35** | 30 | **+5** |
| 720A | **45** | 40 | **+5** |
| 941A | 49 | 49 | — |
| **total** | **157** | **147** | **+10** |

The graph was never empty, and **147 now means something bad**: that the
re-ingest parsed the repo fixtures instead of the deployed objects. 146 still
means an empty `image_prefix` (a defect). 112 remains obsolete.

This is the caveat my own #138 report wrote down — "if the 10-09 bytes of
those two modules are not the fixture bytes, 147 moves by their delta" — and
it moves by 10. I flagged the risk and then quoted the number anyway. A
derivation from the repo is a statement about the repo.

## 4. The part that matters: six rows cannot test the supersede

The graph does **not** hold an additive pile. It holds exactly the latest
revision per DMC. Decisive measurement — for each twice-dropped module, the
triples the older drop has that the newer one lacks, and whether they are in
the domain graph:

| DMC | older-only triples | of those, in the graph |
|---|---|---|
| 320A | 0 | 0 |
| 520A | 0 | 0 |
| 720A | 0 | 0 |
| 941A | **2** | **0** |

**No older-only triple is present.** The older revisions were never written to
the domain graph at all — they date from the era when the XML path wrote only
`urn:doc:`. For 320A, 520A and 720A the older drop is a strict **subset** of
the newer, so those pairs carry no information either way.

**Therefore a re-ingest of the six latest rows cannot distinguish a working
supersede from the additive write it replaces.** Both land on 157: every
triple is already present, and `INSERT DATA` is a no-op on a set. A green 157
would prove the pin did no harm and nothing more. I would have reported that
157 as a confirmation of ruling 2 and been wrong to.

**The fix is one extra drop.** 941A `7d9c7437`, the older revision, re-dropped
*after* the newer one. It is the only object in the corpus whose content the
graph does not already hold, differing in exactly two triples on one `fig-`
subject: an `rdfs:label` ("Array Module Assembly" against "Array Module
Assembly, array face and detail A") and a `mil:hasURL` that **embeds the
drop's own content sha256**. Then:

- **157** — the supersede worked; 941A ends at its own 49 and the newer label
  and URL are gone.
- **159** — still additive; both labels and both URLs coexist on one figure
  subject, which is a data defect in its own right.

Two triples, one drop, unambiguous. Requested from Lane 1 in the packet.

## 5. Two of my own claims retired by the same measurement

- **"The two pairs are rival byte revisions"** — true for 941A only. 720A
  19 to 45 and 520A 14 to 35 is one revision re-parsed at the #131+ pin
  sitting beside its own stale pre-#131 parse, a strict subset, not
  conflicting content. The real content disagreement in this corpus is two
  triples.
- **"The deployed bytes differ from the fixtures (941A 49 vs 48)"** — an
  `image_prefix` artifact, already corrected. But the 520A/720A +5 gaps are
  real, and are now quantified against the live graph rather than guessed.

**A by-product worth keeping:** `mil:hasURL` embeds the dropping object's
content sha256, so every re-drop of the same module under new bytes mints a
new URL on the **same** figure subject. Under the old additive write that
accumulated silently as a multi-valued single-valued property. The supersede
closes it, and it is a second reason this pin mattered.

## 6. Drop order, since "latest per DMC" needs it

From S3 `LastModified` — the graph carries no timestamp, the S1000D builder
emits none. **Two batches**: six modules on 2026-10-08 16:43Z, four on
2026-10-09 01:57Z.

| DMC | latest object | dropped |
|---|---|---|
| 040A | `c4a15a5f` | 2026-10-08 16:43:37Z |
| 421A | `3c19ef42` | 2026-10-08 16:43:38Z |
| 320A | `c1384ec4` | 2026-10-09 01:57:23Z |
| 520A | `5639c11a` | 2026-10-09 01:57:24Z |
| 720A | `67b31318` | 2026-10-09 01:57:24Z |
| 941A | `bdf04c5f` | 2026-10-09 01:57:24Z |

All under `processing-artifacts`, prefix `ingress-user/xml/<sha256>/`. Their
parses sum to exactly **157** — the number confirmed from a second direction,
which is the only reason I trust it after getting 147 wrong.

## 7. Still owed

- **The third clause of the order** — reading the graph after Lane 1's six
  rows — waits on Lane 1. The reading is specified above, and the 941A
  `7d9c7437` drop is what makes it a test rather than a formality.
- **A red `corpus-gate-verdict` on #139 is expected and mergeable**: it is a
  `charts/**` PR, so the gate dispatches, and the published report it reads is
  a pin behind. That is normal on a pin bump, unlike #138, which changed
  scored *code* and so was never graded at all (`skipping`).
- `mrad.ttl` regeneration in invincible-agent, which was generated with no
  `image_prefix`.
- #28 and #73 still open; `mfg-extraction-investigation` still carries 30
  commits with no PR.
- Rulings 1, 3, 4 and 5 are the next pins; ruling 1 is what Lane 1 waits on
  after this.

The five probe scripts are kept in `scratchpad/` — `baseline_instances.py`,
`which_population.py`, `drop_order.py`, `the_two_triples.py`,
`union_or_latest.py`. The equivalents from the 10-13 measurement were lost
with the worktree they lived in.
