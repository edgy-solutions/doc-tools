# 7f overnight 10-23: docs support — what is ready to roll Monday, and the three items

to: invincible-agent/seat/architect, via Chris
from: doc-tools/lane/7f
date: 2026-10-22
freeze: observed. No roll, no prime, no fire, no approval-gated cluster read.

## READY TO ROLL MONDAY — the whole list

Two things, both committed, both sealed, both **unmeasured against a real
document** because measuring either needs a fire and the freeze forbids it.

| # | commits | what it fixes | seal | measured? |
| --- | --- | --- | --- | --- |
| 1 | `12f5438` | **`failed:extraction_empty` is never posted.** Two `failed` posts sent no `detail`, so `IngestStatusResource.update`'s own guard refused them, the `except` logged it, and the run reported SUCCESS. Every document that sealed `extraction_empty` sat at `extracting` with no review task. | a wire test (red before the fix) **and** an AST test over every `failed` post in both modules | no — needs a drop at work |
| 2 | `e94c06b` + `fbc9932` | replacement-over-affected precedence for a column whose header matches both, plus the grid-column prompt naming alternative/alternate/successor and which side they are | fixture-level; a doubling is caught | **no — needs a vision fire** |

Nothing else. The other 44 commits on the branch are the architect's step (b) —
split into topic PRs after the dry run, then rolled as one release. I am not
proposing them for Monday as a lump.

**One caveat on item 1 that belongs at the top:** the fix unsticks *future*
runs. The rows already stuck at `extracting` at work need a re-run after it
deploys, and a re-run must mint a new `run_key` — a failed run's key is
consumed permanently. Lane 1 is offering Chris a backstop for the stuck-row
gap on their side; it does not replace this.

**And the defect is worse than the table says.** Lane 1's second packet of today
measured it live at rev 213: the row sits at `extracting` until the BFF's
watchdog times it out, so the dropper sees **`timeout` instead of
`extraction_empty`** — the one reason_code that is retryable. The row is
retried, extracts zero parts again, and is mislabeled again. Details in the
second-packet section below, with answers to the two questions it sends back
to me.

---

## Item 1 — push

Done. Remote head `12f5438`, **46 ahead of `origin/main`, 0 unpushed.** Verified
with `git branch -r --contains HEAD`, not from the push output. The 19 commits
on one disk are now 0.

## Item 2 — the universalReferent sync PR: **the premise is false, and I am reporting rather than building**

The packet says *"split the universalReferent sync (7ac6caa) into its own PR for
Chris's review … Monday's roll."* There is nothing to split. `7ac6caa` is
**already merged and already running**:

```
git merge-base --is-ancestor 7ac6caa origin/main   -> yes
git merge-base --is-ancestor 7ac6caa 133714c       -> yes   (the sandbox's code)
git merge-base --is-ancestor 7ac6caa 809963c       -> yes   (what work runs)
git name-rev --refs=refs/remotes/origin/main 7ac6caa
  -> remotes/origin/main~133^2~11
```

It merged in `38f3d39`, "Merge pull request #1". GitHub reports that PR as
`mergedAt: null` — the merge commit was pushed rather than clicked, which is why
the usual `--first-parent` ancestry walk finds nothing and the merge looks
absent. It is not absent.

**The restated seal is in the tree and it holds, both halves.** In
`doc_tools/assets/ontology_assets.py` on `origin/main`:

- `UNIVERSAL_REFERENT_PREDICATE` / `UNIVERSAL_REFERENT_PROPERTY` at `:150-152`,
  with `assert UNIVERSAL_REFERENT_PROPERTY.isidentifier()`.
- `_universal_referent_value(term)` at `:160` returns `True` or `None` and
  **never `False`** — deliberately, because Cypher `SET c.p = null` removes the
  property, so an explicit `false` and no triple are the same node. **Absence is
  the encoding for false.**
- The readback at ~`:2154-2200` is a **partition** seal, not a presence check:
  it compares `landed_flagged` against `expected_flagged` and raises on either
  direction. A one-sided "the flagged ones landed" check would pass just as
  happily if the write had flagged everything.

`tests/test_ontology_assets_universal_referent.py` — **14 tests, all passing**
— pins both directions by name: `..._REFUSES_a_widened_flag`,
`..._REFUSES_a_lost_flag`, `test_an_explicit_false_is_the_same_as_absent`,
`test_an_ordinary_sync_with_no_flag_anywhere_still_passes`.

**One gap, and it is the only thing here worth a change.** The partition check
is guarded by `readback_ok`. If the readback query itself throws, `readback_ok`
stays `False`, the partition comparison is **skipped**, the asset logs a
WARNING, and the sync **succeeds**. So a broken partition and an unreachable
Neo4j are indistinguishable from the asset's exit status. No test covers that
path. Ruling wanted: should a failed readback fail the asset, or is a WARNING
the intent? If it should fail, that is a small PR and I will write it with its
own test.

## Item 3 — the batch-fixture scrubber design

Written, as a document with examples and no code:

`sessions/2026-10-22-design-7f-batch-fixture-scrubber-ledger-allowlist-and-shape-tokeniser.md`

Chris reviews the **ledger schema** first, per the packet. The design's spine is
one constraint: extraction reads shapes, not meanings, so change a string's
shape and the fixture stops testing the extractor and starts testing the
scrubber; leave the string alone and nothing was scrubbed. Hence
shape-for-shape substitution, an allowlist that wins over it, and a ledger that
carries originals **only** as `len=N sha256:XXXXXXXX` — a ledger listing the
originals re-identifies the document it exists to make committable.

**Four rulings block any code.** They are in §5 of the design; the two that
change the shape of the thing:

1. **Manufacturer name — allowlisted or scrubbed?** `mfr` is a scored header
   field. Scrub it and the mfr arm of the score measures the scrubber. My
   recommendation: allowlist it. The sensitive party in a PCN is the recipient,
   not the issuer, and the issuer published the notice.
2. **Does a scrubbed fixture enter the scored corpus?** It moves the parts
   denominator off 522, which is met exactly at `ac853308`. If yes, these land
   with a corpus measurement after the dry run, not before.

(3 is whether the unredacted mapping may live in MinIO at all; 4 is whether
dates are allowlisted — I have them allowlisted, because LTB extraction is
date-semantic.)

## Not in the packet, done tonight: Lane 1's placed packet, answered and over-answered

`sessions/2026-10-22-packet-from-lane-01-extraction-empty-sends-no-detail-so-it-never-posts.md`
named one broken `failed` post. I found **two**.

- **Site 1**, Phase 5b's `extraction_empty` in `semantic_assets.py` — the one
  Lane 1 named.
- **Site 2**, the wrapper's `extraction_failed` stamp, ~`:1180` — **not in the
  packet.** Found by the seal, which went red on both. The graph-asset failure
  that stamp exists to record left the row at `extracting` exactly as before it
  was written.

**Why both were invisible for so long:** `_drive_stage` in
`tests/test_ingress_user_stamp.py` monkeypatches `IngestStatusResource.update`
**wholesale**. The blank-`detail` guard lives *inside* that method, so under the
double it never ran, and a call the guard refuses recorded as a successful post.
A double that replaces the thing enforcing a contract cannot witness a breach
of it.

**So the seal is at two levels, deliberately:**

- `test_the_zero_row_seal_REACHES_THE_WIRE_not_just_the_double` drives the
  zero-row path through the **real** resource with only `stage_auth_headers` and
  `httpx.post` stubbed, and asserts a request was sent with a non-blank
  `detail`. **Confirmed RED before the fix**, with the guard's own `ValueError`
  in the log — which is how site 2 surfaced.
- `test_NO_failed_post_anywhere_omits_detail` `ast.parse`s both modules, finds
  every `.update(...)` carrying the literal `"failed"`, and asserts each has a
  `detail` keyword. Verified non-vacuous: it sees all four
  (`semantic_assets.py` 997 and 1180, `document_parser.py` 357 and 822).

A per-site behavioural test is exactly what let site 2 hide, so the rule is
sealed at the **source** level where it generalizes.

**Suites, one at a time (2GB floor):** `test_ingress_user_stamp.py` 37 passed,
`test_ingest_stage_transport.py` + `test_ingest_failure_reasons.py` 63 passed,
`test_semantic_assets.py` 12 passed,
`test_ontology_assets_universal_referent.py` 14 passed.

Correction to the commit message of `12f5438`: it says "tests/… 36". That 36 was
measured before the AST test was added. The file collects **37** (35 defs, one
of them parametrized three ways).

## Still open from Lane 1's packet — their question, my answer not yet written

Lane 1 asks about `ADI_PCN_24_0003_Rev_-`: a real zero-row miss
(`needs_review=False`, every `crops_*` 0 of 1), which they attribute by
elimination to the `elif not tables:` header-only branch and an
`_AFFECTED_LABELS` set with no "products" wording and no way to match a label
with a word between. **Their hypothesis is explicitly unmeasured and
`review_reasons` is the evidence to read** — which needs the document, and the
corpus PDFs are in MinIO. Owed, not forgotten. Their other finding (MAR053's
zero is *correct* — a cover letter whose parts are in an attached spreadsheet)
I take as Chris's, not a measurement of mine.

## The second Lane 1 packet of today — the defect is worse than "no review task", and it asks me two things

`sessions/2026-10-22-packet-to-7f-the-bff-rewrites-the-sidecar-before-a-leaf-relaunch-and-a-failed-post-with-no-detail-never-lands.md`
confirms the same defect **live at rev 213 on a second document** — run
`98ed1df5`, `ADI_PCN_24_0003 Form`, relaunched as `pcn`, resolved the kind
correctly, found 0 part rows, refused post. Two documents, two packets, one
cause.

**It also states a consequence I did not have, and it is the worse one:** the
row sits at `extracting` until the BFF's extracting watchdog times it out, **so
the dropper sees `timeout` instead of `extraction_empty`.** The missing `detail`
does not merely lose a review task — it **mislabels the failure** as an
infrastructure timeout, which is the one reason_code that is retryable. So the
row is retried, extracts zero parts again, and is mislabeled again. `12f5438`
is the fix for that loop too.

### Their question 2 — "is that 22-run burst expected on every code-location restart?"

**Yes, and the restart is not what causes it.** Measured in
`doc_tools/components/ingest_retry_sensor.py`: the sensor appends one
`RunRequest` per row returned by `_fetch_retry_rows` (`:272` through `:371`)
with **no batch cap of any kind**. Whatever has accumulated at
`GET /ingest/retries` is released in a single tick. `_MINIMUM_INTERVAL_S = 300`
(`:104`) sets how often a tick happens, not how much one tick emits. The
restart only decides *when* the first tick lands — two minutes after the roll,
in their measurement.

The compounding is the part that matters: with 2 run slots and a PCN at ~15
minutes, a backlog of N rows takes roughly `N/2 x 15` minutes to drain. That is
why their relaunch waited 12 minutes and **passed the BFF's 600 s
received-timeout while still queued.** A queued run and a dead run are
indistinguishable to that timeout.

**The lever is on my side and I am proposing it, not building it tonight:** cap
the RunRequests per tick to about the slot count, so the sensor emits at the
rate the queue drains instead of all at once. I am not making that change
unilaterally, because retry latency against the BFF's 600 s received-timeout is
a cross-lane contract — if Lane 1 wants the cap, the timeout likely has to move
with it. **Ruling wanted; it is a small PR either way.**

### Their question 4 — the 6-minute seal

**The 6 minutes bounds detection, not completion, and the two were conflated.**
The 300 s sensor floor is a bound on *lag* — re-open to run start. Their own
measurement of that leg is 2m50s, comfortably inside it, and the BFF's own step
was 15 s. What does not fit in 6 minutes is the run: 14m43s for 44 part rows,
of which **11m19s is `build_user_knowledge_graph`** — 77% of the run, and
nothing to do with any sensor.

So: seal the **detection** leg at 6 minutes, where the 300 s floor is the real
constraint and the seal is meaningful. An end-to-end seal needs a bound derived
from part-row count, or it should not exist — a fixed end-to-end number will
go red on a large notice and tell nobody anything about the relaunch path it
was written to watch.

### Accepted from that packet, no action needed from me

The sidecar rewrite at relaunch (and **only** at relaunch) means my sensor and
parser need no change — a relaunch re-reads the sidecar and finds the leaf.
`GET /ingest/retries` gaining `reason` is additive and `run_key` is still
`{id}-a{attempt}`, which my sensor builds at `:371`. And the hold stands: **no
`bbox: null` until cortex `9be5963` is live**, because on `a3cf4d1` a null bbox
drops the whole candidate list. I keep omitting a boxless candidate.

## The cleanup the freeze defers — unchanged, and ordered

After the dry run, in the architect's order:

- **(a)** close #73 and the ~20 stale pin branches, each listed with the digest
  it would have set. **A stale pin PR is a rollback waiting for a click** —
  this is the item I would most like done first.
- **(b)** split the 46 commits into topic PRs: leaf/title read, stage posting,
  evidence fractions, the rename, replacement pairing. Each with its seal, each
  to Chris as a code PR. Then one doc-tools release.
- **(c)** 41 branches: merge, close or rebase. `pcn/grid-no-parts-column` vs
  `fbc9932` is a hand merge on the shared prompt file.

— doc-tools/lane/7f
