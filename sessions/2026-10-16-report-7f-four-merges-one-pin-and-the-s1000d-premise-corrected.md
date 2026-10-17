# 7f report — four merges, one pin, and Lane 1's S1000D question answered

to: architect, Lane 1 — from doc-tools/lane/7f
date: 2026-10-16

## 1. Merged, in the ruled order

| PR | merge commit | what |
|---|---|---|
| #120 | `9b538e7` (squash) | the retry-poller correction |
| #121 | `fe5d4d6` (squash) | rule 7 (IDT crop box), crop rates, seal totals in `latest.json` |
| #118 | `4c7d740` (**merge commit**) | the kinds route, **code-only** per F2 |
| #123 | `af53f15` (squash) | `ingestable_kinds()` + the PUT publisher |

`main` is at **`af53f15`**. Full local suite there: 1697 passed, 12 skipped,
7 deselected.

Two mechanics worth recording, because both cost nothing to get right and are
expensive to get wrong:

- **#118 was merged with a merge commit, not squashed.** The publisher branch was
  stacked on it; squashing would have left #118's commits non-ancestors of
  `main`, and the rebase would then have replayed them as conflicts. Merged, the
  rebase was clean.
- **#122 was auto-closed by GitHub** when its base branch was deleted on #118's
  merge, and `gh pr reopen` is refused once the base is gone. #123 is the same
  two commits rebased onto `main` — which also bought them the CI verdict a
  stacked PR can never dispatch (#122 reported *"no checks reported"*, measured).

## 2. F2 is recorded in the modules, not the chart (`6368dc5`)

`doc_tools/api/app.py` now states that this app is **served nowhere** and why:
the publisher PUTs the list from inside the code-location pod, so doc-tools needs
no HTTP surface. Measured and written down so the docstring is not asserting a
hope: nothing in `charts/` references `doc_tools.api`, and the one container runs
`dagster api grpc -h 0.0.0.0 -p 3030`, starting no ASGI server. No second
container, no Service, and the `containerPort`/probe naming is untouched until a
port exists.

The **standing posture rule** is in the same docstring: the day this app is put
behind a port it ships `REQUIRE_TRANSPORT_AUTH=true` **with a verification key
configured first**. Flipping REQUIRE with no key configured 401s every caller
including a legitimate one, so the key is the first half of that change rather
than a follow-up. `api/kinds.py` points at it.

For the record, since it is what made the port question look urgent: base
`values.yaml` declares `containerPort: 8080` named `http` with httpGet probes on
`/:8080`, while sandbox overrides `service.port` to 3030 and nulls both probes.
So the port name carries gRPC and the probe config is inert rather than wrong.

## 3. Lane 1 — the publisher, and what you need before flipping

`INGEST_DOOR_READS_PROCESSABLE_KINDS` is yours; the publisher only makes the list
available. **The pin that carries it is the image built from `af53f15`.** I will
send the digest once the `main` build pushes it — a green `build-and-push` on a
PR pushes no image, so the digest does not exist until then. Do not infer it.

What the PUT contains, so an omission does not read to you as a bug:

- `kinds` is the **advertised** list: the union of the two processability arms
  **minus** a hold list. Today: `doors-export, engineering-document, pcn, pdf,
  pdn, s1000d-data-module, work-instruction`.
- `xml` is **held out by ruling**, and the payload carries the reason, the
  evidence (`rev188-door-probe.xml` halted at stage 1; the ten that completed
  five stages were `s1000d-data-module`), and `unblocks_when` — a bare `xml` user
  drop processed through to a parse artifact. `claimed_by` is `[]` today: no arm
  can run it either, so the hold is belt and braces. It is written down anyway,
  because the day an `xml` parser row appears, arm 2 would claim it and this door
  would silently start advertising a path no drop has travelled.
- `arms` carries the raw sets unfiltered, so a kind the hold withholds is visible
  as that rather than as an arm that forgot it.

**Every tick publishes**, every 300s, even when nothing changed: a fingerprint
cursor would record what *we* did, which is not evidence of what *your door*
still holds — a restart or a rollback would otherwise never be re-told. A
refused token mint sends nothing (it is retried 3× first); 404 is logged as
"not deployed yet" and 401/403 as an entitlement answer, explicitly not a mint
failure.

## 4. Lane 1's S1000D question — answered, and the premise is half wrong

Driven over `tests/fixtures/s1000d/mrad/*.xml` with the **wired** builder
(`xml_ingestion.py:33` → `parsers/s1000d_rdf.S1000dGraphBuilder`), not read off
the source.

**Does the parser extract fault codes at all? YES.** 421A emits
`mil:hasFaultCode` to a `mil:FaultCode` node carrying
`hasFaultCodeValue "MRAD-ARR-0417"` and `hasFaultCodeText` — exactly the
`bit_code`/`bit_text` pair in `GROUND-TRUTH.json`. The fixture's markup
(`<faultCode faultCodeValue="…">` with a `<faultCodeText>` child) is a
byte-level match for what the code reads.

**Which 8 predicates? There is no 8.** Triples per module: 040A **5**, 520A 9,
320A 11, 421A 12, 720A 14, 941A **48** — twenty distinct predicates, 99 triples
over the six. The identity core is **5** (`rdf:type` ×2 for `mil:DataModule`
plus the classified kind, `rdfs:label`, `hasSNS`, `hasInfoCode`); 040A is
identity-only; 941A alone carries the whole IPD (6 `hasCatalogItem`, `hasICN`,
`hasFigure`, 3 each of `hasItemNumber`/`hasManufacturerCode`/`hasQuantity`).

So **"8 identity triples per module and no fault-isolation content" is not true
of this parser over this content.** A live run reporting a flat 8 for every
module was measuring something else, or ran over different bytes. Worth
establishing which before the builder is changed, or the fix targets a defect
that may not be in the parser.

**What is genuinely absent is the WALK, not the facts.** Every triple above is
per-module. There is no predicate joining a fault code to the DMCs that resolve
it, no Option node, and nothing for `picture_spare`/spare location — so the
ground truth's four options and its `citations` block (fault isolation → 421A,
remove/install → 520+720, IPD → 941A + `ODM-AM-0001`, planning → 320A) have no
representation at all. Each module's own `refersToDataModule` dmRefs allow a
partial reconstruction, which is not a modelled walk.

### Two blockers on the contract itself

1. **`tests/fixtures/s1000d_mrad/mrad.ttl` does not exist** — not at that path,
   and there is no `.ttl` file anywhere under `tests/`. What exists is
   `tests/fixtures/s1000d/mrad/`: the 6 XML modules, a `README.md`, and
   `GROUND-TRUTH.json`.
2. **`GROUND-TRUTH.json` declares itself DRAFT** — *"DRAFT: ground truth when
   both sides confirm it (ADR-0046 v2 section 9)"* — and carries two unresolved
   `open_questions` of its own: remove/install is one DMC in the consumer's shape
   but two modules here (520 remove, 720 install), and whether option 4 should
   cite the 320A planning interval is open.

I can build the walk against either artifact, but not against a missing one on a
DRAFT whose own open questions decide the shape — that would encode guesses as a
contract. **Needed: the real `.ttl`, or confirmation that `GROUND-TRUTH.json` is
the contract, plus a ruling on those two questions.** With that, "emit the
fixture's shape and prove it by loading MRAD-ARR-0417 live and diffing" is
straightforward and is the next pin.

Also noted, already owed: 320A trips the 3xx no-content-kind warning and
classifies as the bare `mil:DataModule`. Harmless to the walk, still a TBox gap.

## 5. The pin

One pin for all four merges, at `af53f15`. Per the two-digest rule it is
pin → roll → read the pods → write `corpusGate.expectImage` from that reading →
roll again; `expectImage` is never copied from the digest just typed into
`image.digest`. Both rolls should land before 07:00Z, which is the sandbox
nightly's schedule, so the stale-`expectImage` window never contains a gate run.
Chris rolls.

## 6. The pin is ROLLED — both rolls, the seal, and the window

Rolling is now this lane's (`helm upgrade` in the allow list). Reported as asked,
helm rev and pod `imageID` after each.

| roll | commit | helm | pods `imageID` |
|---|---|---|---|
| 1 | `1d40833` (#124) | **rev 46**, `deployed`, 03:09Z | ONE distinct value, `ghcr.io/edgy-solutions/doc-tools@sha256:5846f877ce3e...` |
| 2 | `bbe02ce` (#126) | **rev 47**, `deployed`, 03:16Z | unchanged — same pod, `restartCount` 0 |

**Roll 2 restarting nothing is the correct outcome, not a no-op roll.** Its only
rendered change was the gate CronJob env; the Deployment pod spec was untouched.
Verified from both sides: the pre-roll diff carried exactly one real line
(`expectImage`, `85ad4c9d` -> `5846f877`), and the pod still shows its roll-1
start time with zero restarts.

**Seal: three of three PASS** (`scratchpad/seal_image_identity.py`) — gate
expectation == `DOC_TOOLS_IMAGE` == chart `image.digest` == pods `imageID`.

**`expectImage` was read, not predicted.** Written from the pods after roll 1,
not copied from the digest typed into `image.digest`. It happens to equal it —
that equality is the result being asserted, and had I sourced the value from the
chart the check would have compared the file against itself.

**The red window never contained a gate run.** Seven minutes wide, 03:09Z-03:16Z,
and nearly four hours clear of `0 7 * * *`. That the window was red at all is
established rather than assumed: `expectImage` was ABSENT from roll 1's pre-roll
diff, and an absent field is positive confirmation it is unchanged — pods at
`5846f877` against an expectation of `85ad4c9d`.

**Lane 1:** the digest is
`sha256:5846f877ce3e41a89f7df373a41faa14503991b8928f6a84bb18e49c08a1887b`, live
in sandbox since 03:09Z. This is the pin that carries `ingestable_kinds()` and
the PUT publisher, so `INGEST_DOOR_READS_PROCESSABLE_KINDS` now has a producer
on the other side of it.

Pre-roll diffs and roll logs: `scratchpad/preroll_5846f877.log`,
`scratchpad/roll_5846f877.log`, `scratchpad/preroll2_5846f877.log`,
`scratchpad/roll2_5846f877.log`.
