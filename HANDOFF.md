# HANDOFF — `doc-tools/lane/7f`

In-flight state only. Durable findings live in project memory; published
reasoning lives in `sessions/`.

## LATEST — 2026-10-25, overnight item 2 is COMPLETE: the `document` kind ships
(PR #168), blocked only on Lane 1's leaf candidate

**Report:** `sessions/2026-10-25-report-7f-the-document-kind-ships-and-the-weaviate-page-ref-would-have-been-inert-in-the-pod.md`
**Ledger:** `docs/contracts/document-kind.md` — the contract a consumer reads.
**Packet:** `sessions/2026-10-25-packet-to-lane-01-from-7f-the-document-kind-needs-one-leaf-candidate-and-three-things-only-you-can-declare.md`

- **PR #168** — `7f/document-kind` (`b102032`), off `main` `3418171`, not stacked, CI
  dispatched. 13 files, +2389. Suite 2131 passed / 12 skipped; the only red is #161's
  pre-existing `doors-export` overlay drift, untouched by this change.
- **`domain_type="document"`, forced by measurement.** A `domain_type=None` row hits the
  `origin_unresolved` return — no domain graph, no label, no chunks, no triples — and
  would ALSO have been refused by the leaf-grant branch (`granted.domain_type`) that is
  meant to route to it. Framed in the row comment as not reopening the 2026-10-02
  format-level ruling (that is about FORMATS; this is about ORIGIN). **Flagged to the
  architect as an assumption: it creates a new domain.**
- **No new seam.** pdf drop → `origin_unresolved` → Lane 1 leaf grant → domain path.
  `ingress_prefix=None` deliberately, because nothing drains an `ingress-user/document/`
  prefix.
- **`review_shape` declined, not deferred.** `ContentKindRegistration` at our pin v0.9.8
  has `extra="forbid"` and no such field; emitting it RAISES at registry load. v0.9.11
  adds it. Asked of Lane 1.
- **Three near-misses found, each of which looked green:** the Weaviate page ref would
  have been **inert in every pod** (`_ensure_weaviate_collection` created properties only
  if the collection did not exist, and `DocumentChunk` exists everywhere — there is now an
  `add_property` branch); the plugin selector's `else` is **`TrainingPlugin`**, so an
  unbranched new domain extracts course concepts from a procedure; and
  `identity.document_identity` reported `ok` while **refusing all four fields**, because
  the fixture's cover page printed `Revision B` with no colon. All three fixed, the second
  recorded for the next new domain.
- **Reported not fixed:** chunks are page-granular, so a page with two headings cites the
  deeper one — fixture page 6 prints `3.2 Stage two` and `APPENDIX A` and cites 3.2.
  ask-the-manual must not promise more precision than a page.

### WAITING ON LANE 1 (blocker): `document` in `allowed_leaves` with a label.
Also asked: the overlay `passes` mirror, `review_shape: document` at v0.9.11, and
`mesh:GeneralDocumentArtifact` as a TTL leaf under `mesh:PDFArtifact`. Until that class
lands it is `PHANTOM_OUTPUTS` entry **seven** — the first backing a domain-declaring row —
and the plugin's SPARQL arm stays empty.

### Next, in the architect's order
3. **Three header-gate fires** — **cannot start now.** It is Sunday 05:55Z, inside the
   forbidden 05:45Z–09:35Z window, and Lane 1 rolls at 09:35Z. They also need **PR #165
   merged and carried by a pin**, or they do not test the cancel fix. Each fire under the
   `sandbox/roll-lock` ConfigMap with a declared `expected_end`, after lane 01's
   `helm history iagent -n sandbox --max 1` precheck.
4. **Batch fixture** — scrubber → schema PR. **The next thing that can proceed without a
   cluster.**
1 (tail). `scripts/neo4j_concept_id_migration.py` still unrun: `NEO4J_*` is pod-env only,
   so the before/after counts the ruling asks for arrive a pin bump later, as a pod Job.


## 2026-10-25, overnight item 1 is COMPLETE: the header cancel is instrumented
and retried (PR #165) and `Concept` is keyed and constrained (PR #167)

**Both halves of overnight item 1 are shipped, each off `main` and not stacked, so each
gets a CI run.**

- **PR #165** — `7f/header-cancel-origin-and-one-retry` (`7a93b93` + `3e52624`). The
  cancel is **our own 90 000 ms `AbortController`**, measured by subtraction: 90.209 s
  between the last timestamped line and the cancel. Not a disconnect, not a sibling
  task-group cancel, not a shared token. `stats["header_pass"]` now persists
  elapsed/bound/attempts/origin — the first header timing this pipeline has ever written
  — and a cancelled pass retries once. A recovered cut deliberately avoids the string
  `header pass failed`, so it cannot claim the gate's header exemption it no longer
  needs. The bound is still 90 000 ms at ~1.6x the healthy worst case (healthy: 19.1–55.0
  s); raising it is a separate judgment I have not taken.
- **PR #167** — `7f/concept-id-and-constraint` (`995a592` + `e27eef9`).
  `:Concept` is keyed on `concept_<16 hex of sha256(DOMAIN \x1f normalized name)>` via
  `doc_tools/utils/concept_identity.py`, MERGEd on the id alone, `name` ON CREATE only,
  and `concept_id_unique` constrains the **id** — never the name, which would collapse
  the same concept name in two domains into one node. 18 new tests, including one literal
  digest so the algorithm cannot drift silently and a drift guard that fails in CI if the
  writer points an unknown edge type at a `Concept`.
  **`scripts/neo4j_concept_id_migration.py` has NOT been run.** It cannot be: `NEO4J_*`
  is pod-env only, so the ruling's before/after counts arrive a pin bump later, as a pod
  Job. Until then the live graph still holds the old name-keyed nodes.
- **Packet to tr placed and committed in my tree** (`e27eef9`), copy placed in tr's
  worktree `dt-tr/sessions/`: what the id is, that salience is per-edge, that a
  cross-domain concept join is no longer possible by name, and the two things I need from
  them (a new Concept edge type goes in `RELINKABLE`; any read-side `{name: ...}` match
  moves to the id or to `name_normalized`).

(Items 2-4 of that order have moved to the LATEST block above.)


## 2026-10-24 — the order is COMPLETE: the narrowing (`5d766c0`), `mfr`
ground truth for all ten (`b5a4bca`), and the re-fire — 15 of 16 header fields pass,
the one red being an aborted header pass on onsemi_IPCN25300X

**Reports:** `sessions/2026-10-24-report-7f-header-identity-pr-162-and-the-passes-direction-pr-161.md`
and `sessions/2026-10-24-report-7f-the-gazetteer-ships-and-the-fire-found-clause-1-writing-questions-as-a-manufacturer.md`

- **PR #162 open** — header identity precedence, off `main` (`8a47f60`), not stacked, so
  it gets a CI run. `apply_text_layer_primacy` in `sustainment_header_trust.py` + two
  sites in `plugins/sustainment.py` (doc_id clauses 1-2; the pipeline call and the
  clause-3 narrative) + `tests/test_header_identity_precedence.py` (26 tests) + the two
  REVERSED tests in `tests/test_doc_id_text_layer_arm.py`.
- **Second commit on that same branch: the gazetteer (`39b47e6`, pushed).** `mfr` is
  matched against `_GAZETTEER_NAMES` first; the shape heuristic applies only where the
  gazetteer does not match, and the furniture/connective lists are NOT loosened (that is
  the point — loosening makes `Devices Affected` name-shaped, and uniqueness is the arm's
  safety). The gazetteer pass REPLACES the candidate set, so a matched gazetteer name is
  the only candidate and a second company printed on the page cannot become authoritative
  under clause 1. Suite 2084 passed, 1 failed (#161's intended red). PR #162 body carries
  the measured tables. **Corrected:** the commit message and the first PR revision said
  the IDT notice prints its name beside `Renesas`; it does not — `Renesas` appears only
  inside a contact e-mail, which both predicates already reject. PR body fixed; the commit
  message is immutable.
- **PR #161 open** — the `passes` direction. Needs nothing further from me. Its red in
  the local suite (`test_overlay_kind_drift`) is the intended one: lane 01's overlay row.
- **Packet placed, uncommitted, in lane 01's tree**:
  `invincible-agent/sessions/2026-10-24-packet-to-lane-01-from-7f-the-doors-overlay-row-needs-the-pin-bumped-in-the-same-commit.md`
  — their `.github/doc-tools.ref` pin must move in the same commit as the row change.

### Open, in priority order

1. **Adopt the roll lock before the next roll.** `sandbox/roll-lock` ConfigMap
   {lane, started, expected_end}, refuse while younger than 90 min, delete when the
   gates pass, runbook says why. Lane 01 writes the lock step; no packet from them has
   landed yet. **And** their ask: `helm history iagent -n sandbox --max 1` first — if it
   reads `pending-*`, wait. My rev 54 at 15:01Z most likely killed prime run `836b27b7`.
2. **The fire is DONE and the order is delivered — but it found a blocker in #162.**
   Report: `sessions/2026-10-24-report-7f-the-gazetteer-ships-and-the-fire-found-clause-1-writing-questions-as-a-manufacturer.md`.
   Job `mfr-fire-7f` deleted; artifacts kept at `scratchpad/mfr_{corpus_f1,score_f1}.json`
   and `scratchpad/mfr_fire1.log`, from pod `imageID`
   `…@sha256:94410165d5555894ad772950c414b06ae66d4ee99aa9961ee2f0e95e28567233`
   (dispatch run 40140001861, built from `39b47e6`), `rc=0`.
   - **Clause 1 wrote `QUESTIONS` (PCN24-029) and `Europe` (onsemi_PD26044X1) as `mfr`**,
     displacing correct, verbatim-printed model values (`Mini-Circuits`, `onsemi`). Both
     come from the shape heuristic, NOT the gazetteer. On `main` the document arm is asked
     only when the model fails the document check, and both pages print the model's answer
     — so this is a regression this PR introduces. **The gate is `clean: true` on this
     fire** (8/9 exact) because only 3 of the ten carry `mfr` ground truth.
   - **RULED AND LANDED — `5d766c0`, pushed.** The architect granted the narrowing as
     proposed, scoped to `mfr`: primacy over the model requires a GAZETTEER match; an
     unmatched candidate corroborates and never displaces; disagreement keeps the model
     value and raises `needs_review` naming both. `doc_id` and the dates keep clause 1
     (pattern-bound arms). `mfr_from_document_tiered` returns `(value, source, tier)`;
     `mfr_from_document` keeps its 2-tuple contract for the recovery callers;
     `_PRIMACY_REQUIRES_GAZETTEER = {"mfr"}` + `_may_displace_the_model` gate one site in
     `apply_text_layer_primacy`. **With no model value the narrowing does not apply** —
     nothing to displace, and narrowing there would blank an `mfr` the corpus writes.
     Agreement from an unmatched candidate is SILENT (spends no review).
     `TestPrimacyOverTheModelRequiresAGazetteerMatch`, 8 tests, both measured strings as
     parameters. Suite: 2095 passed, 1 failed (#161's intended red).
   - **`mfr` ground truth for all ten — `b5a4bca`, pushed.** Seven blocks added to
     `scripts/pcn_ground_truth.json` (ADI, Diodes, EOL-36, both Mini-Circuits, both
     onsemi) in the TYC/TI idiom, every value read off the fire log's verbatim
     `### DOCUMENT TEXT ###` block, each `source` naming the element. Two precedents
     applied and stated in the blocks: a legible wordmark IS a verbatim reading
     (`ANALOG DEVICES`), a garbled logo alt is NOT (`tu cORPORATED`, `@ Electronics`,
     `ONSEM.`, `On semi`); a name only inside a URL or e-mail domain is an inference, not
     a reading (`TT Electronics` for EOL-36 — the fire wrote `mfr_parent: null` there).
     **Rescored retrospectively on the 2026-10-24 fire: `notices_with_gt` 3 → 10,
     `fields_scored` 9 → 16, 13 exact, and `PCN24-029:mfr` + `onsemi_PD26044X1:mfr`
     report as DISTRACTORS by name.** The same fire reported `clean: true` before.
   - **DONE: the re-fire.** Run `40155057765` on `b5a4bca`, `build-and-push` success,
     pushed index digest `sha256:ba9147b1b4b27dca75a97d3631e08ffb30a558f3c9451460c1a080ef87366ec2`;
     pod `imageID` identical; Job `mfr-fire-7f`, `rc=0`, 50 min, Job deleted.
     **The narrowing holds on all ten.** `PCN24-029` reads `QUESTIONS` as `heuristic`,
     `document_displaced_model: False`, writes `Mini-Circuits`; `onsemi_PD26044X1` the same
     with `Europe` / `onsemi`; `EOL-36` is `gazetteer`, `displaced: True`, keeps `SEMELAB`.
     **Parts 522/522 exact.** Header score **13 / 16 exact over 10 of 10 notices**, plus
     `TI:mfr` `alias` (`TEXAS INSTRUMENTS`, the wordmark) and `TI:doc_level_ltb_date`
     `correctly_absent` — 15 of 16 PASS. The one failure is
     `onsemi_Generic_IPCN25300X:mfr` **absent**, and it is clause 3 not clause 1: BAML
     logged `Function ExtractHeader: Operation cancelled` — **measured since as a 90.209 s
     gap against our own 90 000 ms `AbortController`, NOT an instant abort** (the
     banner line carries no timestamp; #165 records elapsed/bound/origin and retries
     a cancelled pass once), `model_value: ""`, no
     document reading because the page prints `onsemi` only in prose and as the garbled
     logo alt `ONSEM.`. The previous fire answered `onsemi` here, so it is intermittent and
     one fire cannot separate instability from recall — that is what three fires are for.
     Report: `sessions/2026-10-24-report-7f-the-narrowing-holds-on-the-corpus-and-the-tenth-mfr-is-an-aborted-header.md`.
     Artifacts (untracked): `scratchpad/n2_{corpus_f1,score_f1,seal_f1}.json`,
     `scratchpad/n2_fire1.log`, `scratchpad/n2_report.md`.
   - The gazetteer's measured effect on these ten is ZERO (the three notices printing a
     known name are all `text_layer_degraded`; EOL-36 matched before; the ADI notice never
     prints its name as a standalone element of an accepted type). Still the right fix.
   - **Still unfixed, reported not touched:** `_identity_values_agree` compares `mfr` on
     `_name_key` EQUALITY, so `TEXAS INSTRUMENTS` vs `Texas Instruments Incorporated`
     reads as a disagreement and spends a `needs_review` exemption on two readings the
     corpus accepts as one. `mfr_agreement.readings_agree` is the instrument that would
     compare them properly.
   - My predicted IDT `exact -> wrong` regression (trailing `.` stripped by
     `_NAME_EDGE_PUNCT` on `Inc.`) did NOT happen — IDT is degraded, so the arm is gated
     off. The mechanism is still live for an ungated page.
   - The dispatch also moved `ghcr.io/…/doc-tools:latest` onto branch code. Harmless for
     this chart (it names no `:latest`) but it is a published tag.

3. **The swallow itself** — a 400 or a null key still loses a notice's whole instance
   graph while Dagster reports SUCCESS. #160 fixed the MPN cause, not the invisibility.
4. The 3 divergent Neo4j notice keys and the migration for existing twins.
5. Lane 01's #159 (v0.2.1 pin) is theirs to roll and waits on Chris's decision about how
   `values-sandbox.secret.yaml` is supplied.

### Contested, unverified

Lane 01 reports Dagster's run monitor failing `836b27b7` at exactly 60 min. My 10-08
reading of the deployed instance config said `DefaultRunLauncher` makes
`monitor_started_run` structurally unable to reap a `STARTED` run. Re-read it out of the
pod before relying on either.

## 2026-10-23 (night), release repair + the v0.2.1 cut + the cleanup

**Report:** `sessions/2026-10-23-report-7f-release-repair-the-v021-cut-and-the-cleanup.md`
**Branch:** `7f/report-2026-10-23-release-repair-and-the-cleanup` (2 commits:
the lane/tr packet `481d72b`, the CLAUDE.md venv/libmagic carry `ba242f9`)

### Done tonight

- **v0.2.1 is cut and verified.** Tag `v0.2.1` → index digest
  `sha256:086766d7304e53574e39ebf4b95bf7e5bb59e8b691c049d8dbfd3b221e8887b2`,
  source commit `b95a550e159ee8832b32fcd53743a18bbce9842e`, release run
  `40056763926`. **`build-and-push` skipped** — the first release here that did
  not rebuild. Cut on `b95a550`, **not** on `main`'s head `a28c094`: the head is
  docs-only (#33), so it has no image and a release there would have rebuilt.
- **Pin packet placed for Lane 1's 207** at
  `invincible-agent/sessions/2026-10-23-packet-to-lane-01-from-7f-v0-2-1-is-cut-and-here-is-the-digest-207-pins.md`
  (placed, not committed). Carries both digests — `image.digest` and
  `expectImage` — and the age-red warning.
- **Cleanup:** 3 PRs closed (#73, #28, #64), 22 stale pin branches deleted with
  every tip SHA recorded, 5 PRs rebased (#145, #99, #100, #102, #125), 1 opened
  (#152). #99 repaired to green; #102 left open with its 8 failures grouped.

- **The v0.2.0 repair is made.** #152 merged as `089a6ad`; re-dispatched
  (run `40057727478`), `build-and-push` **skipped**, `tag-release-image`
  **success**, and both references now resolve to `sha256:ac853308...`, verified
  locally with no credential. The two references were **not** in the same state
  beforehand: `v0.2.0` named the wrong image and the commit-sha tag was **404**,
  so the dispatch moved one and created the other.
- **Report committed and PR #153 open** on
  `7f/report-2026-10-23-release-repair-and-the-cleanup` (`090026e`, rebased onto
  `089a6ad`). Docs only, so `corpus-gate` skips.
- **Section C of the lane/tr packet corrected** and sent to `doc-tools-f3`
  (lane/tr): `S3SensorComponent` passes only `file_url`, so their contract
  section 2 has no mechanism to copy; `path_prefix_strip` /
  `sidecar_manifest_name` are parser fields and `ingress_prefix` is not a
  sensor field at all. Four options given, path-derive recommended.
  `resolve_content_kind` and `document_parser.py` untouched.

### Blocked / next action, in order

1. **tr answered: option 1, the path carries the kind.**
   `training/course/<folder>/<deck>`, kind `course`, domain `training` - Chris
   ruled a kind names the document, not the domain. Contract v2 is in #154
   (`lane/tr`, `e94c92e`), `resolve_content_kind` untouched by either of us,
   **no new precedence level**, so the ADR-0021 amendment question is moot and
   does not need the architect. Collision answer sent: #100 is clean; #99
   collides only on `registry/content_kind_domains.json` (regenerate) and the
   `PHANTOM_OUTPUTS` tuple; #99 is rebased and green, so it should land first.
   Also warned tr of three measured traps - `RULED_DOMAINS` is the ruling
   transcribed and needs dated provenance like the `cad` entry; their two `::`
   passes are held only by `tests/test_passes_registry.py` (both verified
   present in `baml_src` and in both generated clients); and
   `test_no_live_sensor_prefix_path_derives_onto_a_new_row` stays green on a
   docstring edit alone, which is the problem, because nothing asserts
   `_derive_from_path("training/course/...", "training") == "course"`.
   **Nothing of mine moves on this.**
2. **Item 4 - three fires on the v0.2.1 digest**
   `sha256:086766d7304e53574e39ebf4b95bf7e5bb59e8b691c049d8dbfd3b221e8887b2`,
   after Lane 1 rolls it Monday. First measured read of #148/#149/#151 on the
   corpus. Read the pod's `imageID`, not `image`.
3. **`PCN-24_0003`** - re-ingest after the roll. Zero components,
   `needs_review=false` today; #148 says 1,577 parts or a flagged review.
4. **The graph-write ruling (this week, own PR)** - **diagnosis done, written
   up in `scratchpad/graph_write_diagnosis.md`; the PR is spec'd and unstarted.**
   The sites are `doc_tools/assets/semantic_assets.py:1047-1064` (cypher loop
   and sparql loop, each `except Exception` -> `log.error` -> continue),
   `:1066` (pass 2 roll-up, same), and `:1085`, which returns
   `status="processed"` **unconditionally** - that last line is the "went
   green" half. Swallowing is **per query, not per store**, so a partial write
   leaves state that is neither written nor absent; that is why
   `inbound/adi_23_0120` has a Neo4j node and no RDF IRI (cypher loop passed,
   sparql loop did not, independent `try` blocks, no shared verdict).
   `jena_client.execute_update` is NOT at fault - it raises correctly
   (`jena_client.py:235`).
   **THREE BLOCKERS MEASURED AFTER THE DIAGNOSIS - THE PR IS NOT MECHANICAL:**
   (a) **The existing error boundary refuses to stamp.** The wrapper at
   `:1144-1186` would do the "fail the asset" half for free if the loops
   raised - but its first branch is `if posted.get("stage") is not None:` ->
   warn *"not stamping failed"* -> bare `raise`. `posted["stage"]` is assigned
   at `:1005`/`:1015` (Phase 5b), and there is no def boundary between `:560`
   and `:1087`, so **the ordering is unconditional**: a graph-write failure
   always arrives with a stage already posted. A naive "raise instead of
   swallow" therefore gives a red asset, NO `failed:graph_write`, and a row
   parked in `review` - which is `adi_23_0120`'s present state reached by
   another road. The post has to be made at the write site, inside the impl.
   (b) **...and that contradicts a deliberate rule, so it is the architect's
   call.** The comment at `:1152-1158` says a `failed` after a posted stage is
   *"a backwards move on a row a steward may already hold (Lane 1 409s it or
   overrides it)"*. Three ways out, ranked: **reorder the graph writes ahead of
   the Phase 5b post** (largest diff, needs nothing from Lane 1, and makes the
   suppression rule true again instead of arguing with it); post anyway and let
   Lane 1 409 it; or post a non-failed degraded marker (no such stage/field
   exists - Lane 1 422s failure-only fields on any other stage,
   `dagster_resources.py:353-370`). **Surfaced, not decided.**
   (c) **`graph_write` is not an emittable code, and forgetting it fails
   SILENTLY - but the fix is entirely ours, no packet.** It is absent from
   `REASON_CODES` (`doc_tools/utils/ingest_failure.py:25`), and an unknown
   code is neither raised nor dropped - it is **coerced to
   `unexpected_error`** (`dagster_resources.py:342-352`) with a warning from a
   *module* logger, the class that does not reliably reach the Dagster run
   log. I checked the second link before writing a packet to Lane 1 asking
   them to accept the code, and **no packet is needed**: `gateway.py:12795`
   validates `reason_code` against a **shape only**
   (`REASON_CODE_RE = ^[a-z][a-z0-9_]{0,63}$`, `ingest_status.py:148`), there
   is no enumerated set on that side, and `gateway.py:12744` says in terms
   that *"the vocabulary is doc-tools' to own."* `graph_write` matches. So our
   frozenset is self-imposed, the only link that can swallow the code is ours,
   and it is one line in this lane. **The one real blocker is (b), a design
   call.**
   **Still needs the cluster:** why that one write failed. `context.log.error`
   is the Dagster logger so the message IS in the run log if the run is
   retained. Rule out in order: the `doc_id` path fragment reaching
   `safe_iri_local`/an unescaped IRI; a SPARQL syntax error from an unescaped
   literal; an auth or scope refusal (`UnscopedUpdateError` is raised before
   any HTTP request, so it shows with no status).
   **AND A SECOND, WORSE SITE FOUND 40 LINES ABOVE:** `:609-618` logs a
   *warning* on a failed MinIO text read and substitutes
   `[{"type": "Text", "text": "Mock extracted text", ...}]` - the whole graph
   is then built from that literal, every downstream write succeeds, and
   nothing anywhere records that the content was invented. Flagged for its own
   decision, not folded into this PR: the fix is either fail the asset or post
   a degraded marker, and that is a call about whether a text-load failure is
   ever tolerable. In memory as
   `a-failed-text-load-substitutes-a-mock-string`.
5. **The id normalization (own PR, after 4)** - one key, both stores,
   normalized at the write with the function the IRI uses, + a migration for 27
   nodes.

### Standing, not urgent

- **A `sessions/` PR builds an image.** Measured on #153: the docs-only
  heuristic in `changes.decide` matches `^docs/` and nothing else, so a
  `sessions/` path is "not docs" and `code=true`. Every report PR on this lane
  pays ~35 minutes of build, and merging one gives `main`'s head an image that
  a `docs/`-only merge does not. Candidate for the `paths-ignore` change
  already queued for the next pin bump.

- The corpus authority report is 5 days old against a 3-day max — the required
  gate reds on age alone. The nightly holds the cure; its PR can never merge
  unrebased.
- Offered, awaiting a word: the doc-tools half of the two-directional drift
  seal (a job here checking out the overlay at a pinned ref).
- Longer-standing: the ADI PDF as corpus document eleven; what the header pass
  needs for `effective_date`/`change_type`; the site batch fixture; `readback_ok`;
  the retry-sensor batch cap; whether to scope the corpus gate off release refs.

### Late 2026-10-23, after the report commit

- **`C:/tmp/dt-text` worktree REMOVED** (architect's instruction, directed at
  7f). It held branch `pcn/prefer-text-layer` at `addc201`, clean working tree
  - and `git branch -r --contains addc201` returned **nothing**: two commits
  (`addc201` provenance join key, `ff18c7b` prefer the text layer where a
  stored crop cut through glyphs) existed **on this machine only**. Pushed the
  branch first, confirmed `origin/pcn/prefer-text-layer`, then removed. The
  work is now recoverable; whether it is still wanted is someone's call, not a
  deletion. **A clean `git status` says nothing about whether anything is
  backed up** - `worktree remove` takes the only working copy, so
  `branch -r --contains` is the precondition, not `status`.
- **Standing order, all lanes: push the lane branch at the end of every work
  block, PR or no PR.** Measured so it can be relied on: a push of any
  non-main branch here fires **no CI** - `build-container.yml` is the only
  workflow and its `push:` trigger is scoped `branches: [main]`. Pushing
  genuinely costs nothing. `7f/report-...` is pushed at `f7abadd`.
- **The overlay drift seal is RED today, and it is not mine to fix.** Ran it
  with `IAGENT_CONTENT_KIND_OVERLAY_DIR` set (venv, PowerShell):
  `1 failed, 6 passed in 0.49s`, diverging on **one** kind - `doors-export`,
  ours `identity.identity_from_doors_text` vs overlay
  `identity.document_identity`. That is the **one** kind whose passes actually
  dispatch (`doors_ingestion.py` is the only importer of
  `run_passes_for_kind`), so the tuple is not documentary there and a sync in
  the wrong direction would be a live defect: `document_identity` scans
  everything for title-block labels, so a requirement whose OBJECT TEXT reads
  `Contract No: ...` becomes the module identity (`content_kind.py:374-379`,
  sealed by `test_doors_object_text_contract_line_is_not_the_identity`). Lane
  1's `b102f1f9` moves the **overlay** to ours - correct side - and sits on
  `lane/01-207`, **not** an ancestor of that repo's HEAD, so the red clears
  when 207 merges. In memory under
  `overlay-passes-is-documentary-and-the-drift-test-skips-in-ci`.

### 2026-10-24, early — the graph-write cause is MEASURED, and it is not one write

Queried the Dagster event log in sandbox Postgres (db `iagent`, `event_logs` /
`runs`; retention floor 2026-07-13). **11 of 39 retained
`build_knowledge_graph` runs swallowed a graph-write failure — 28% — and all 11
are recorded `SUCCESS`.** Two causes, not one:

- **Neo4j, 10 occurrences, query index 1 every time:**
  `Neo.ClientError.Statement.SemanticError` — `Cannot merge the following
  relationship because of null property value for 'ltb_date':
  (c)-[:REPLACED_BY {ltb_date: null}]->(alt)`.
- **Jena, 1 occurrence, query index 0:** Fuseki `400 Bad Request` at
  `/ds/update` — a **parse** rejection. Not auth (sandbox Fuseki takes anon
  writes), not a missing dataset, not `UnscopedUpdateError` (that raises before
  any HTTP request and would show with no status). Run
  `e98e0f51-f1f1-4bc7-a2a4-17a7daf450b6`, 2026-09-18.

Spread 2026-07-23 -> 2026-10-02 over **5 distinct documents / 11 runs**: onsemi
`IPCN25300X` (4), Diodes `PCN_2683_Rev1_EOL` (3), Diodes `PCN_2683_FULLGREEN`
(2), `TYC-PCN-24-210412` (1), onsemi `PD26044X1` (1). **`inbound/adi_23_0120`,
the document the ruling names, is not among them** — its event is outside
retention, so absence is not evidence either way.

**Every one of the 11 is under `sustainment/inbound/`, the path with no
`ingest_id`.** So `failed:graph_write` has no Lane 1 row to reach in any
observed case; only failing the asset catches them. The "raise outside the
`if manifest.get('ingest_id')` guard" clause of the reorder is the load-bearing
one, not a nicety — this is now measured, not reasoned.

**THE SCOPE QUESTION THIS RAISES (for the architect, with the measurement):**
the Neo4j half is not an error-handling gap, it is **silent data loss with a
known trigger**. Neo4j refuses `MERGE` on a relationship carrying a null
property, and a null LTB date is one of this corpus's most common extraction
outcomes. The replacement graph has been **systematically missing its
`REPLACED_BY` edges wherever `ltb_date` is null, since July, behind green
runs.** Stopping the swallow without fixing the query converts that silent loss
into a **red asset on every notice with a null `ltb_date`** at the first
re-ingest. The query fix is the standard idiom - `MERGE` on endpoints only,
then `SET r.ltb_date = ...` when non-null, never a null inside the MERGE
pattern. **Recommend folding it into the same PR**; shipping the reorder alone
is correct per the ruling but reds out a large share of the corpus on the next
re-ingest, and that should be a choice, not a surprise.

Blast radius not yet quantified in the graph itself: the Neo4j credential is
not in any pod's env (Dagster resource config supplies it), so a
`REPLACED_BY`-vs-notice count is still open. The 28% run rate is the defensible
number today.

**Sandbox is still on `sha256:ac853308...`** (v0.2.0's repaired digest, pod 6d
old): **Lane 1's 207 has not rolled**, so the three v0.2.1 fires remain
blocked. No roll in flight. `k3s-worker6` **Ready** on its new supply.

### 2026-10-24, the graph-write work is SHIPPED as two PRs

- **#153 MERGED** as `03e3d4c` (all checks green, `build-and-push` 37m35s).
  `main` head is now `03e3d4c`.
- **#156 OPEN** - `7f/graph-write-before-the-stage-post`, commit `89f081f`
  (plus `783a552`, wb's addendum, which had to land somewhere). The reorder:
  store writes first, the post last, failures accumulated **per store**,
  `failed:graph_write` naming the store, `graph_write` added to `REASON_CODES`,
  clients closed on the failure path, and the **raise outside the `ingest_id`
  guard** - the load-bearing clause, since all 11 observed failures are on the
  no-ingest_id path. New `tests/test_graph_write_seal.py` (7 tests) incl. a
  structural seal that all three write sites precede the post in the impl
  source. An end-to-end test in `test_ingress_user_stamp.py` drives the impl
  with a failing cypher write. Two existing drivers there had the old order
  baked in (their stub nodes make `to_graph_queries` raise, which the old order
  posted in front of) - both now stub the graph layer, and
  `test_a_failure_after_the_stage_post_...` is renamed since that premise is
  now impossible. CI `tests` green.
- **#158 OPEN** - `7f/replaced-by-merge-null-ltb-date`, commit `e32d8d0`, off
  `main`. The **cause**: `sustainment.py` `edge_cypher` had `ltb_date` inside
  the `REPLACED_BY` MERGE pattern. Now `MERGE (c)-[rep:REPLACED_BY]->(alt)` +
  `SET rep.ltb_date`. **Carries one deliberate semantic change** - the MERGE
  key no longer includes the date, so two rows naming the same (affected,
  replacement) pair with different dates now make ONE edge, last-write-wins.
  Called out in the PR for acceptance or rejection.
- **MERGE #158 BEFORE #156.** #156 alone converts silent edge loss into a red
  asset on every notice with a null LTB date at the next re-ingest. Posted that
  ordering as a comment on #156.
- Local suite on both branches: **1 failed, 1942/1934 passed** - the one red is
  the pre-existing `doors-export` overlay drift, which SKIPS in CI and clears
  when Lane 1's 207 merges.

**Still open on the ruling's item 1:** the **Jena half** (1 of the 11) - a
Fuseki `400` *parse* rejection at `/ds/update`, cause not yet identified; and
**how many `REPLACED_BY` edges are actually missing** - the Neo4j credential is
in no pod's env (Dagster resource config supplies it), so the graph could not be
counted. The re-ingest of the 5 affected notices waits on both PRs and on 207.

**Item 2 (id normalization, one key both stores + migration for 27 nodes) is
next and unstarted.**

---

## 2026-10-24 - #158 and #156 MERGED; #159 unblocked on report currency

**Both graph-write PRs are in `main`.** `21b8a02` (#158, the cause) then
`d70bb0a` (#156, the reorder), merged in the ruled order. `main` is at
`d70bb0a`. Nothing of the ruling's item 1 is outstanding in code.

**#159 is Lane 1's pin PR, not mine** - branch `01/pin-v0-2-1-086766d7`,
checked out in Lane 1's own worktree, so work it through a detached worktree
(`git worktree add --detach <path> origin/01/pin-v0-2-1-086766d7`) rather than
by checking the branch out here.

**What blocked it was report AGE, and nothing else.** The committed
`docs/corpus-gate/latest.json` was `2026-10-18T112531Z` against
`CORPUS_GATE_MAX_AGE_DAYS=3`.

**A FAILED GATE JOB IS A VERDICT, NOT AN OUTAGE - this saved ~70 minutes.**
Today 07:00Z `doc-tools-corpus-gate-29880420` reads `Failed` in
`kubectl get jobs`, and reading that as a broken run is the trap. It ran all
three fires, wrote the report, and PUBLISHED `latest.json` +
`report-2026-10-24T095014Z.md` to `corpus-gate/nightly` (`fb0011c5`). It exits
nonzero on its own RED verdict. Of the six most recent gate jobs, three read
`Complete` and three `Failed`; the three `Failed` are reds, not failures. So
BEFORE firing a 70-minute three-fire set, check `origin/corpus-gate/nightly`
for a report that already measures the live image.

**The landed pair, measured by key, not assumed:** `generated_at`
`2026-10-24T09:50:14Z`; `measured_image` `...@sha256:ac853308...` (the image
the pods RUN); `image_identity` `checked=true, source=pods, result=match,
void_reasons=[]`; `verdict` `fail`. Both files proven byte-identical to the
published blobs with `git hash-object` against the nightly branch.

**WHY A RED VERDICT MERGES, with the split measured both ways.** The required
`corpus-gate` check is
`-m "corpus_gate and not corpus_gate_verdict"` -> schema, non-void, currency,
corpus, identity: **6 passed**. The verdict assertion is
`test_verdict_is_pass`, in the ADVISORY `corpus-gate-verdict` job, and it
**SKIPS** by its own applicability rule because the report measured
`ac853308` while the branch declares `086766d7`. Negative control in the same
tree against the 10-18 report: **1 failed, 5 passed**. The report is what
moves the check.

**#159 MOVES BOTH `digest:` AND `expectImage` IN ONE COMMIT**, which the values
file's own standing procedure forbids ("copying the digest typed in above into
it would make the gate compare this file against itself"). Lane 1 states the
exception in the commit: v0.2.1 is a tag cut by digest on bytes CI already
built, so the expectation is known before the roll, and the pod `imageID` is
still read back after. The precondition holds - the index and BOTH arch
children were verified from their config blobs. **Consequence for the roll:
there is no second roll, so the pod `imageID` read-back is the ONLY thing that
can catch a partial rollout.** `rollout status` reports success while the old
pod still runs, so read `imageID` off the pods and compare it by hand.

**A 60-line provenance block for this pin is written and NOT landed** -
`scratchpad/pin-086766d7.patch`. It is superseded as a pin edit (#159 does the
pin) but its content is not recorded anywhere in the repo: the measured
ancestry `133714c..b95a550` (8 changes, THREE on the extraction path - #148,
#149, #151 - so this pin CAN move the corpus score, unlike the last several),
the index children verified from config blobs, and the finding that **#137,
#139 and #143 each moved the `digest:` line and wrote NO provenance block**, so
for three pins the paragraph sitting against the pin described
`2bf85719`/`f4d6440`, an image that was not deployed. Verified from
`git log -L1136,1136`. Worth landing as its own docs commit after the roll.

### Jena 400 parse cause: FOUND, confirmed, fixed (PR #160)

The ordered "Jena 400 parse cause: next." Cause is an unescaped MPN in an
IRIREF, not Fuseki and not auth.

- `sustainment.to_graph_queries` built `<http://internal/components/{mpn}>` with
  `.replace(' ', '_')` as its only sanitisation. IRIREF (SPARQL 1.1 19.8)
  forbids `<>"{}|^\`` + backslash **and every codepoint <= #x20**.
- `TYC-PCN-24-210412` keeps OCR ditto quotes in 16 of 38 `affected_mpn` values
  (`"4503-5023-00"`); two more are wrapped cells with two MPNs split by `\n`.
- Fuseki's OWN body (confirmed, not inferred):
  `HTTP 400 Encountered " "<" "< "" at line 3, column 3. Was expecting <IRIref>`.
  Probe method: POST to `GRAPH <http://internal/SCRATCH_7F_PARSECHECK>`, then
  `DROP` it. Raw quoted -> 400. Raw newline -> 400. Cleaned control -> 204.
  Never the default graph, never an `_INSTANCES` graph.
- **One bad value loses EVERY triple in its INSERT DATA** (one query per node).
  The 2026-09-18 run logged `SPARQL Queries to emit to Jena: 1`, Fuseki 400'd
  it, the caller swallowed it into `context.log.error`, run status **SUCCESS**.
  Event id `69928` in `iagent.event_logs`, run
  `e98e0f51-f1f1-4bc7-a2a4-17a7daf450b6`, step `build_knowledge_graph`.
- Scope, measured over all 38 live sustainment `review.json`: **16 of 2865 MPN
  rows illegal, all in that one notice** — matching the single retained SPARQL
  failure exactly. DISTINCT from the 11-of-39 swallowed writes (null `ltb_date`
  on `REPLACED_BY`, closed by #158/#156).
- Fix: `safe_iri_ref_component` in `jena_client.py`, **identity-preserving** —
  component IRIs are shared join keys, so re-encoding a legal MPN would fork the
  join. `safe_iri_local`'s regex-strip was not an option (MPNs keep `#`, `/`,
  `,` verbatim). Three helpers now, do not mix: literals / `prefix:local` / `<>`.
- Tests: grammar rule on every emitted IRIREF, an `rdflib` parse as a second
  parser independent of Fuseki (agrees on all three shapes), and a pinned
  identity test. Negative control: ditto test fails on the pre-fix builder
  naming the offending IRI. Suite 1953 passed; the lone
  `test_overlay_kind_drift` doors-export failure is pre-existing and reads only
  YAML none of this touches.
- **NOT fixed, next ruling:** the swallow itself. A 400 that loses a notice's
  whole graph still cannot fail or flag its run.

### In flight at handoff

- Job `pcn-gate-086766d7` — the three fires on v0.2.1 (digest `086766d7`),
  running, ~70 min, first measured read of #148/#149/#151. A `Failed` Job is
  the gate's own RED VERDICT, not an outage: read the published report either
  way, then land the fresh pair. Read #148/#149/#151 **by value and per field**,
  never from an "agree" verdict.
- Then `PCN-24_0003` re-ingest — 1,577 parts or a flagged review, never a silent
  zero. Serialized AFTER the fires so shared LLM/GPU endpoints are not perturbed.

### 2026-10-24 — REPLACED_BY edges are NOT widely missing: 2 of 114

Measured in-pod, read-only, against live MinIO + Neo4j (the `NEO4J_*` keys are
in the pod env after all, which unblocked this).

| | |
|---|---|
| expected pairs, CURRENT `review.json` only | **114** |
| actual `(:Component)-[:REPLACED_BY]->(:Component)` | **112** |
| expected but MISSING from Neo4j | **2** |
| in Neo4j with no expected pair (orphan) | **0** |

Both missing pairs are one throwaway document,
`sustainment/inbound/zz_look/generated/zz_look_pdf/review.json`
(`doc_id` `IPCN25300X-R2`), with `ltb_date: None` **and** `ingest_id: None` —
i.e. the already-identified swallow on a null `ltb_date` down the no-`ingest_id`
path that **#158 fixes**. Per pair the affected `:Component` node exists (1) and
the replacement node does **not** (0): one statement, so the MERGE of the
replacement and the edge die together. Zero orphans means nothing stale was
written either.

**A first pass of this measurement reported `expected=129, missing=17`, blaming
`15 / 15` on a document named `doc-tools@5c355684d0ba8b1841824bae48ba98f5ae237f52`.**
That was a grouping artifact, not a finding: a sweep of
`sustainment/**/review.json` returns 38 objects of which only **27** are
current — the other **11** sit under a versioned `doc-tools@<sha>/` snapshot
directory, so `key.split("/")[-2]` invents that key and double-counts the rows.
Filter `"/doc-tools@" not in key` before counting or grouping. A sha-shaped
group name means the key derivation is wrong, not that a strange document
exists. (Memory: `review-json-exists-in-two-layouts-and-the-parent-dir-is-not-a-doc`.)

So the pending item "how many `REPLACED_BY` edges are actually missing" is
**closed at 2**, and it is the known cause, not a new one. It is *not* evidence
about the 11-of-39 Fuseki losses, which are a different store and a different
swallow.

### 2026-10-24 — the three fires on v0.2.1 (`086766d7`): fires 1 and 2 read

The Job runs **~49 min per fire**, not ~70 min total — f1 finished 15:49, f2 at
16:38, f3 started ~16:38 and should land ~17:27. The ~70 min figure in the
earlier block was wrong. The Job logs nothing until exit (no TTY), but it writes
per-fire artifacts to `/tmp/pcn-gate/` inside the pod
(`corpus_fN.json`, `score_fN.json`, `seal_fN.json`, `fireN.log`) — **read those
to follow progress instead of waiting on the exit.**

| | fire 1 | fire 2 |
|---|---|---|
| parts gt | 522 | 522 |
| parts exact | **522** | **521** |
| missing / spurious / malformed | 0 / 0 / 0 | 1 / 0 / 0 |
| header `exact` of `fields_scored` | **8** of 9 | **7** of 9 |
| header clean | true | true |
| `needs_review` | 3 / 10 | 4 / 10 |
| `text_layer_degraded` | 3 / 10 | 3 / 10 |
| `crops_row_short` | 0 / 10 | 1 / 10 |
| `crops_failed` / `_truncated` / `_near_cap` | 0 | 0 |
| errors | 0 | 0 |

**Parts moved on byte-identical input, hash-confirmed.** The single move is
`onsemi_Generic_IPCN25300X.pdf`, `content_hash`
`sha256:1c38e118c531e7f427f3e126f5b9c4c1f8bde61add47b5ca1c884ce23225430d` in
**both** fires, 19 MPNs in f1 and 18 in f2, the lost row being
**`NSR02F30NXT5G`**. No duplicates in either fire — in `per_notice`, `count` is
the **ground-truth** count (19) while `distinct`/`emitted` are measured, so a
`count 19 / distinct 18` pair is a genuine drop, not a duplicate filling a slot.

**The row-short detector fired as a TRUE POSITIVE here**, and located the loss:
`needs_review=True`, reason *"page 3: tier 1's text layer saw 17 MPN-bearing
row(s) in a table it could not parse, vision returned 16 row(s) for that page —
at least 1 row(s) may be missing"*. The text layer saw the row; **vision is the
lossy leg.** That is a different thing from the known row-short *misfire*.

The one header field that moved is `TI_PCN_20210316000.pdf:mfr`, exact in f1 and
classified **`aliases`** in f2 — consistent with TI mfr being non-deterministic.
`doc_level_ltb_date` is `correctly_absent` in both. 3 notices observed, 3 with
GT, 9 fields scored, nothing hallucinated/wrong/misformatted/unreadable.

**What this report CANNOT measure, so do not claim it does:**
- **#149 (replacement precedence)** — the corpus scorer has **no replacement
  arm**. Nothing here reads on it either way.
- **#151's `doc_id`-from-the-document half** — `doc_id` is not a scored header
  field (9 fields, no `doc_id`). The 90s header bound shows only indirectly, as
  the absence of any timeout-derived filename `doc_id`.
- **#148's salvage** is the only one of the three this report speaks to, via the
  parts totals.

Related: the dropped `NSR02F30NXT5G` is the same MPN as the affected side of the
2 missing `REPLACED_BY` edges measured earlier today (`zz_look`, `doc_id`
`IPCN25300X-R2`, the same notice family). **Two different mechanisms on one
row** — an extraction drop here, a swallowed write there. Do not merge them.

### 2026-10-24 — the gate verdict at `086766d7`: FAIL, and both causes are known

Job `pcn-gate-086766d7` exited **1** after ~2h23m. Published
`latest.json` + `report-2026-10-24T172612Z.md` to `corpus-gate/nightly` as
**`564ef8ad3637`**, verdict **fail**, PR **#110**.

**Identity: match.** measured digest `086766d7…` equals what the pods expect.

| fire | exit | elapsed_s | exact/gt | spurious | missing | malformed |
|---|---|---|---|---|---|---|
| 1 | 0 | 2705.7 | **522/522** | 0 | 0 | 0 |
| 2 | **1** | 2969.8 | **521/522** | 0 | 1 | 0 |
| 3 | 0 | 2834.0 | **522/522** | 0 | 0 | 0 |

Crop seal: every GATE TERM **0** across all three fires (`repaired_cut_tables`
0, `errors` 0). `stored_cut_tables` 2 and `stored_cut_words` 17 are repairs that
succeeded, not failures. Header correctness 8/9, 7/9, 7/9, `clean` in all three,
and *"every established header field matched the page in every fire"* — no wrong
values anywhere.

**Two blocking items, both pre-existing and stochastic. Neither is a regression
from #148/#149/#151.**

1. **fire 2 exited 1** on the single dropped row `NSR02F30NXT5G`
   (`onsemi_Generic_IPCN25300X.pdf`, 18/19), on byte-identical input — two of
   three fires are perfect. Flagged truly by `crops_row_short` + `needs_review`.
2. **`Diodes_PCN_2683_Rev1_EOL.pdf` `doc_id` disagrees across fires:**
   `'PCN #: 2683'` | `'PCN-2683'` | `'PCN-2683'`. Fire 1 leaked the literal
   label into the identity; fires 2 and 3 were clean. It **blocks** because
   `needs_review` is not True in all three fires, so no exemption — the gate
   calls it an *undeclared silent write*. This is the known Diodes label leak,
   recurring, and it is an **identity** field.

Exempted (declared via `needs_review=True` in all three fires): `TI` (`mfr`
case/format variance, `'Texas Instruments Incorporated'` vs `'TEXAS
INSTRUMENTS'`) and `TYC` (`mfr` `'TE Connecvity'` vs `'TE'`, plus
`doc_level_ltb_date` `'2024-06-06'` | `'2024-06-06'` | **`None`** — fire 3 lost
the LTB date entirely; exempted, but it is still a silent recall loss).

Rates, worst case across fires: `needs_review` 4/10, `crops_row_short` 1/10,
`text_layer_degraded` 3/10, `crops_failed`/`_truncated`/`_near_cap` all 0,
errors 0. The report itself warns the fires disagreed, so these are not a
property of the image.

**PR #110 state: `corpus-gate` PASS (the required check), `corpus-gate-verdict`
FAIL (advisory).** So the fresh pair is landed and currency/identity are
satisfied; the red does not freeze merges. Nightly is exactly 1 commit ahead of
`main` with no divergence, so #110 is mergeable — **Chris's merge, not mine.**

**A watcher bug to not repeat:** `jsonpath='{.status.succeeded} {.status.failed}'`
with an empty `succeeded` yields `" 1"`, and `awk '{print $1}'` returns the
*failed* count — so the watcher reported "SUCCEEDED" on a failed Job. Read the
two fields in separate calls, or test for emptiness before indexing.

### 2026-10-24 — PCN-24_0003 re-ingest: #148 PASSES, 1,571 rows, flagged, and all 1,571 in the graph

Run `3e755498`, launched with the document's own prior `runConfigYaml` (partition
tag alone does not carry the path). SUCCESS after ~11 min, `stepsFailed: 0`,
`materializations: 2`. New review.json at
`ingress-user/pdf/9d8e8a6f…/generated/ADI_PCN_24_0003_Rev_-_Form_pdf/doc-tools@b95a550e…/review.json`,
**919,374 bytes against the v0.2.0 copy's 5,212**.

**The bar was 1,577 parts *or* a flagged review, never a second silent zero. Both
legs are satisfied, so #148 is met:**

| | v0.2.0 (`133714c0`) | v0.2.1 (`b95a550e`) |
|---|---|---|
| part rows | **0** | **1571** |
| rows with `affected_mpn` | 0 | 1571 |
| distinct mpn | 0 | 1571 |
| `needs_review` | **False** | **True** |
| `review_reasons` | 0 | 6 |

`doc_id` is `PCN-24_0003` on both — the identity was never the problem here.

**1,571, not the 1,577 #148 predicted.** The arithmetic is in the reasons and
the stats, not a loss: the salvage reports *"the parts pass emitted no parts, and
the text names an affected-parts section — salvaged **1573** Family/Model pairs
from the text layer deterministically"*, and `parts_collapsed_duplicate: 2`.
1573 − 2 = 1571. So the figure to carry forward is 1,571 and the 1,577 in #148 is
not reproduced; nothing in this run accounts for the remaining 6.

**The flag is informative, not a blanket.** Of the 6 reasons, 3 are per-row and
located — `parts[982]`, `parts[1047]`, `parts[1280]`: *"affected_mpn not found
verbatim in OCR text (possible hallucination)"*. 1,568 of 1,571 corroborate
verbatim. `router_text_list_used: true` confirms the deterministic text-layer
route carried this document.

**Two reasons are a separate, still-open miss:** *"header pass failed:
AbortError"* and *"header.mfr not written: the header pass returned none and the
document does not name one itself"*. On the graph node, `mfr`, `revision`,
`pub_date` and `doc_level_ltb_date` are all **empty strings** — this is a header
recall miss on a parts success, the [[fullgreen-ltb-null-is-a-header-recall-miss-with-the-candidate-supplied]]
shape, and it is NOT what #148 was about. Do not read the parts pass as clearing
headers.

**The graph got all of it — and my earlier "zero components" was my own
measurement error.**

- `MATCH (n)-[r]->(c)` returns **0 for every one of the 28 notices**. The edge
  direction is `(:Component)-[:SUBJECT_TO]->(:SustainmentNotice)` — components
  point **at** the notice. An out-degree query reads zero on a fully populated
  notice. `PCN-24_0003` has **1,572 incoming**: 1,571 `SUBJECT_TO` from
  `Component` plus 1 `GOVERNED_BY` from `Document`.
- `Component` carries **only `mpn`** — no `id` property, corpus-wide (checked
  against `PCN-2683`, same signature). So `count(DISTINCT c.id)` returns 0 on
  1,571 real nodes. Key on `mpn`.
- Set diff review ↔ graph: **1571 / 1571, zero in either direction**, and 0 of
  the 1,571 are shared with any other notice. The write is complete and exact.

So `PCN-24_0003` is now the largest notice in the store by an order of magnitude
(1,572 incoming vs `PCN-2683` at 404, then 45, 26, 23, 19).

**What this does not settle.** The swallow is still open: this run is a success
path, so it exercises neither the 400 nor the null-key leg. #160 removes the MPN
cause going forward; a lost instance graph is still invisible behind a SUCCESS.
Item 2's migration for the existing raw/normalized twins is still deliberately
unrun.

### 2026-10-24 — #160 and #110 are MERGED; the roll order is fully discharged

Chris merged both: `d573d24` (#160, squashed) and `d19215f` (#110). Verified the
code landed — `git diff origin/main..HEAD` on my branch showed **7 files, all of
them corpus-gate report artifacts, no code file differing** — so the IRIREF
percent-encoding and the one-normalized-key change are both on `main`
(`sustainment.py:2199` carries the ditto-quote comment). Local branch
`7f/iriref-safe-mpn-the-jena-400-parse-cause` deleted; working on `main`.

#110 merged "unstable": `corpus-gate` (the only required check) green,
`corpus-gate-verdict` advisory red. The two reds it names are both mine and both
known — the crop seal (standing red since the 15th) and Diodes' header
disagreeing across fires. Nothing new.

**The whole roll order is now complete:** v0.2.1 rolled, three fires read by
value, `PCN-24_0003` re-ingested. Headline: **ADI 0 → 1,571 parts**, Chris's
number of the day.

**Stale item to flag upward:** the cross-lane queue still lists *"7f's v0.2.1
roll and its three fires"* as pending. It is done — the fires are in
`scratchpad/gate-086766d7.log` and the 10-24 report is on main via #159.

**My open PRs, five not four.** The queue named #145, #99, #100, #102 and
omitted **#125** (corrects the false "8 triples is Jena's" claim in `kinds.py`).
All five are OPEN with `mergeStateStatus=UNKNOWN` (not yet computed, not a
conflict signal — recheck before assuming).

**Next assigned work: the header text-layer arm.** This repo files no issues, so
it is a PR for me to write, not an existing one. Scope per
[[header-identity-has-no-text-layer-primary]]: `mfr` already has a text-layer
arm (#30, document-wins); **`doc_id` has none**, which is why today's
`header pass failed: AbortError` on 0003 left `mfr`/`revision`/`pub_date`/
`doc_level_ltb_date` as empty strings on a 1,571-row notice. **Open question
before coding: the precedence.** `mfr`'s arm resolved document-wins, but
[[pcn-mfr-residuals-are-not-a-precedence-rule]] says those two residuals do not
generalise — so whether a doc_id text-layer read outranks, defers to, or only
backfills a failed header pass is a ruling, not mine to assume.

### 2026-10-24 — the four-PR sweep: 3 rebased and green, 1 closed, and a drift main is already red on

#125 merged by Chris (`efc3467`). The order was: #145 rebase + re-seal; #99/#100/#102
answer, rebase or close with one line each; CAD (#99) wanted for the work team's
schematics. All four done, `tests=SUCCESS` on the three kept.

**#145 — rebased onto `efc3467` AND un-stranded six commits.** The parenthetical
"(fractions + wire_evidence_ref)" turned out to name real stranded work, not a
rebase detail. Measured before acting:
- `7f/evidence-ref-page-fractions` and `7f/work-instruction-singular` **have no PR
  at all** — never had one.
- #150's squash took the leaf/title half (`leaf_read.py`, `test_leaf_read.py`,
  `test_title_leaf_dispatch.py`, `test_user_drop_runs_parse_only.py` are all ON
  main) and **left the fractions half behind** (`wire_evidence_ref`,
  `_page_fractions`, `to_page_fractions`, `_row_fractions`,
  `test_row_fraction_seal.py`, `test_row_wire_evidence_ref.py`,
  `row_fraction_seal.json` — none on main).
- **`main` already depends on the missing half**: `dagster_resources.py:520` cites
  `leaf_read.wire_evidence_ref` as emitting the ruled shape, and that function does
  not exist on main. A dangling citation in a merged comment.

Cherry-picked all six (49639cd 7c6f211 629b794 a680f7f 1ee5968 2ad3b1d) onto the
rebased #145; clean, one auto-merge in `sustainment_merge.py`. **Re-seal: 256
passed** over the seven affected suites. (#145 alone on main was 98, vs the 92 in
its description — main has gained cases.)

**#99 CAD — rebased, kept.** One conflict in `content_kind.py`'s
`PHANTOM_OUTPUTS`: main's `"training:Course"` (#157) against this branch's two CAD
leaves. Kept both, and corrected the branch comment's ordinal — it claimed STEP/DXF
were "FOURTH and FIFTH" while `mesh:XMLArtifact` holds fourth per the comment
directly above it; now fifth and sixth. **115 passed, 2 skipped, 1 failed.**

**The 1 failure is pre-existing on main — verified, not inferred.**
`test_overlay_kind_drift.py::test_the_shared_kinds_declare_the_same_passes`, run on
`main` at `efc3467`, fails with the byte-identical assertion:
`doors-export ours ["identity.identity_from_doors_text"] vs overlay
["identity.document_identity"]`. **`main` is red locally on this test.** It is
invisible in CI because the seal **skips there** (needs both registries on disk) —
[[overlay-passes-is-documentary-and-the-drift-test-skips-in-ci]], now with a live
divergence rather than a hypothetical one.

**#100 doors — rebased clean, kept, 63 passed.** It **widens** that drift to two
mismatched passes by adding `doors.requirements_rows` to our side; it did not cause
it. **The fix is not mine:** the overlay row lives in `invincible-agent`
(the test names `914c7fa`), lane 01's tree — a packet, not a commit. I did not
align our side downward to a documentary row to make a test pass.

**#102 jena SDK writer — CLOSED, branch preserved.** Attempted the rebase first:
**six conflict hunks over three files**, and the `sustainment.py` ones start at
**line 2193 — on top of #160's IRIREF fix merged hours ago**. Reconciling means
re-deriving that fix inside a new write path, where getting it subtly wrong
reintroduces a silent whole-notice loss. Two of three motivations also moved: the
SDK `upsert` is already graph-scoped, and v0.9.8 fixed writer auth; the remaining
adoption blockers are attribution and a missing human, which this PR does not
address. **#28 was already closed as superseded by #102, so this shelves that too**
— said explicitly in the close. Both branches kept:
`feat/jena-writer-under-rulings` and `lane/7f-jena-ontology-writer`. Revival =
fresh branch off a main that has #160, reusing these tests.

### Queued, both given today

1. **The header identity PR, ruling in hand** (architect, via Chris). Precedence for
   `doc_id`, `mfr`, `pub_date`, `doc_level_ltb_date` alike: (1) a text-layer value,
   when the arm yields one, **is the written value**; the model pass corroborates,
   and disagreement **keeps the text-layer value** and sets `needs_review` with
   **both values in the reason**; (2) the model fills only what the text layer did
   not yield, and every model-filled field marks `needs_review=true`; (3) a model
   `AbortError` with a text-layer value present **is not a failure of the field** —
   with none present the field is **absent** and `needs_review=true`, **never a
   filename**. So a document whose text layer gives `PCN-24_0003` writes it whatever
   the model does. The #30 `mfr` arm is the pattern, and **"document-wins" is the
   general rule, not an exception** — this supersedes my reading of
   [[pcn-mfr-residuals-are-not-a-precedence-rule]] as blocking generalisation.
   One PR, **sealed on 24_0003's own review.json shape**. Item (3) also kills
   [[header-timeout-writes-a-filename-derived-doc-id]].
2. **Roll lock, before my next roll.** A `sandbox/roll-lock` ConfigMap
   (`{lane, started, expected_end}`); every roll script refuses to start while it
   exists and is younger than 90 minutes; the roller deletes it when gates pass.
   Rationale worth keeping: **prime's ingests run in the doc-tools code location, so
   a doc-tools roll during an iagent prime kills the prime.** Lane 1 writes the lock
   step; **7f adopts it in its roll scripts** before the next roll, and the runbook
   says why. Check `sessions/` for lane 1's step before building my own.
