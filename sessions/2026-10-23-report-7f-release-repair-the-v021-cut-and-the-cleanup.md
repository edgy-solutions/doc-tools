# Report — 7f: the v0.2.0 repair, the v0.2.1 cut, and the cleanup

**To:** the architect (via Chris), cc `invincible-agent/lane/01`
**From:** `doc-tools/lane/7f`
**Date:** 2026-10-23
**Branch:** `7f/report-2026-10-23-release-repair-and-the-cleanup`

Four items were ordered. Items 1–3 are below. Item 4 (three fires on the
v0.2.1 image) waits on Lane 1 rolling it Monday, by construction.

---

## 1. Repair v0.2.0 — the dispatch found a defect in the repairer itself

The one permitted tag move was dispatched as ordered:

```
gh workflow run build-container.yml --ref main \
  -f version=v0.2.0 \
  -f digest=sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5
```

**It failed, and the failure is worth more than the repair would have been.**
Run [40054727136](https://github.com/edgy-solutions/doc-tools/actions/runs/40054727136):

```
python3: can't open file
'/home/runner/work/doc-tools/doc-tools/scripts/verify_release_tag.py':
[Errno 2] No such file or directory
```

`tag-release-image` checked out `133714c` — the commit `v0.2.0` *names* — which
is two merges before `scripts/verify_release_tag.py` landed in #146. **A job
built to repair old tags could not repair any tag older than itself.** The
tooling a workflow owns lives at the workflow's commit, not at the release's
source commit; those are different trees, and the job had been reading the
wrong one.

Nothing was mutated. The `Errno 2` is in the report-only *before* step, which
runs ahead of `imagetools create`, so `v0.2.0` still names `sha256:9883b5d3…`
and the repair is still available to make.

**PR #152** — *Check out the workflow's own commit in the retag job, not the
release's* — changes that one `ref` to `${{ github.workflow_sha }}` and seals
**both** directions, because they are opposite on purpose:

| job | checks out | because |
| --- | --- | --- |
| `tag-release-image` | `github.workflow_sha` | it runs the workflow's own tooling |
| `build-and-push` | `resolve-release-image.outputs.sha` | it builds the release's source |

Two tests (`test_the_retag_job_checks_out_the_commit_its_tooling_lives_in`,
`test_the_retag_job_runs_scripts_only_from_the_repo_root`) assert each side and
would fail if either were pointed at the other. **Negative control exercised:**
run against `main`'s workflow, the first fails naming
`'${{ needs.resolve-release-image.outputs.sha }}'` — so the test can see the
defect it was written for. 24 passed locally in 0.23s.

**#152 merged as `089a6ad` at 2026-10-24T03:17:11Z**, green on every check
(`corpus-gate` *skipping* — charts unchanged on a workflow-only PR, not a pass).

**The repair is made.** Re-dispatched against `main` so the job ran with its own
fix in place
([run 40057727478](https://github.com/edgy-solutions/doc-tools/actions/runs/40057727478),
[tag job](https://github.com/edgy-solutions/doc-tools/actions/runs/40057727478/job/120764709857),
16 seconds):

```
gh workflow run build-container.yml --ref main   -f version=v0.2.0   -f digest=sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5
```

`build-and-push`: **skipped**. `tag-release-image`: **success**. The one
permitted tag move, and no bytes were built to make it.

**Measured before and after, locally, with no credential** — and the two
references were not in the same state, which the order did not anticipate:

| reference | before the repair | after |
| --- | --- | --- |
| `v0.2.0` | 200 -> `sha256:9883b5d3...` (**wrong image**) | 200 -> `sha256:ac853308...` |
| `133714c0652179...` | **404 - the tag did not exist** | 200 -> `sha256:ac853308...` |

So the dispatch *moved* one tag and *created* the other. That is why the repair
step retags both unconditionally rather than diffing first: the commit-sha tag
was collateral of the original rebuild - overwritten, then lost - and only a
blind retag of both brings a half-destroyed pair back together. Both
absent-digest controls returned 404 in the same run, so the 200s mean a
resolution and not a registry that answers everything.

> *All 2 reference(s) resolve to the pinned digest. No rebuild: these are the
> bytes that passed the gates.*

`corpus-gate` failed on this run too, on report age alone, and does not gate the
tag path - the same red described in section 2.

## 2. Cut v0.2.1 — on `b95a550`, not on `main`'s head, and the reason is measured

The order said *"on main's head"*. Main's head is `a28c094`, which is `b95a550`
plus one documentation file (`docs/pcn-reingest-runbook.md`, #33).

**A docs-only push to `main` builds no image.** `changes.outputs.code` is
`'false'` for that push, and `build-and-push` is gated on it. So `a28c094` has
no image in the registry: a release cut there would have found nothing to tag
and **rebuilt** — which is precisely what #146 exists to stop, and the build is
not reproducible (same commit, different bytes), so the rebuild could not even
be a no-op. Cutting on `b95a550` means the tag names the bytes that commit's
own CI run built and gated. Precedent: `v0.2.0` was itself cut on `133714c`
while `main` was two merges ahead.

**The cut, as ordered — tag, digest, run, pin line:**

| | |
| --- | --- |
| tag | `v0.2.1` |
| target commit | `b95a550e159ee8832b32fcd53743a18bbce9842e` (#151) |
| **index digest** | `sha256:086766d7304e53574e39ebf4b95bf7e5bb59e8b691c049d8dbfd3b221e8887b2` |
| release | https://github.com/edgy-solutions/doc-tools/releases/tag/v0.2.1 |
| release run | [40056763926](https://github.com/edgy-solutions/doc-tools/actions/runs/40056763926) |
| image build run | [40054181959](https://github.com/edgy-solutions/doc-tools/actions/runs/40054181959) (the `b95a550` push: `tests`, `telemetry-contract` and `verify-image-pin` green; `corpus-gate` skipped, charts unchanged) |

**`build-and-push` on the release run: `skipped`.** That is #146 working as
designed and the first time a release of this repo has not rebuilt. The digest
`v0.2.1` names is the digest the `b95a550` push built and tested; the tag was
*added* to it with `imagetools create`, which preserves the index digest.

**Verified, both references, with the positive controls exercised**
(`scripts/verify_release_tag.py` in the `tag-release-image` job):

| reference | HTTP | resolves to | verdict |
| --- | --- | --- | --- |
| `v0.2.1` | 200 | `sha256:086766d7…` | MATCH |
| `b95a550e159e…` (commit-sha tag) | 200 | `sha256:086766d7…` | MATCH |
| a truncated digest | 404 | — | ok (absent, as required) |
| a well-shaped digest nobody pushed | 404 | — | ok (absent, as required) |

> *All 2 reference(s) resolve to the pinned digest. No rebuild: these are the
> bytes that passed the gates.*

`gh release create` fires both the `push` tag trigger and `release: published`,
so two runs reached the tag job ([40056763553](https://github.com/edgy-solutions/doc-tools/actions/runs/40056763553)
and [40056763926](https://github.com/edgy-solutions/doc-tools/actions/runs/40056763926)).
Both succeeded, both skipped `build-and-push`, and both pointed the tag at the
same digest — the operation is idempotent, which is the property that makes it
safe to re-run.

**Pod-ready pin line for Lane 1's 207:**

```yaml
image:
  repository: ghcr.io/edgy-solutions/doc-tools
  digest: "sha256:086766d7304e53574e39ebf4b95bf7e5bb59e8b691c049d8dbfd3b221e8887b2"
```

And the matching gate expectation, which must move in the same commit — a pin
bump has **two** digests to move:

```yaml
expectImage: "pods=ghcr.io/edgy-solutions/doc-tools@sha256:086766d7304e53574e39ebf4b95bf7e5bb59e8b691c049d8dbfd3b221e8887b2"
```

Verifiable from anywhere, with no credential and nothing taken on trust:

```
python3 scripts/verify_release_tag.py \
  --expect sha256:086766d7304e53574e39ebf4b95bf7e5bb59e8b691c049d8dbfd3b221e8887b2 \
  v0.2.1 b95a550e159ee8832b32fcd53743a18bbce9842e
```

**One red on the release run, and it is the known one:** `corpus-gate` and
`corpus-gate-verdict` failed on **report age alone** — *"corpus gate report is
5 days, 15:38:34 old (generated_at=2026-10-18T11:25:31Z), older than
CORPUS_GATE_MAX_AGE_DAYS=3 days"*, with `1 failed, 5 passed, 1 deselected`. No
assertion about the code failed. `tag-release-image` does not depend on it
(`needs: [resolve-release-image, build-and-push]`), so it neither blocked nor
altered the tag. The cure is a fresh authority report, which the nightly holds;
it is not a finding about v0.2.1.

Release notes carry all six PRs grouped by what they change: the release
machinery (#146), the corpus (#148, #149, #151), and diagnosis that was
previously unavailable (#147, #150).

## 3. The cleanup — the count, and what each judgement rested on

| | count | |
| --- | --- | --- |
| PRs closed | **3** | #73, #28, #64 |
| branches deleted | **22** | all stale pin branches, every tip SHA recorded first |
| PRs rebased onto `main` | **5** | #145, #99, #100, #102, #125 |
| PRs opened | **1** | #152 |

Nothing was closed for age. Each one was judged on something measured:

- **#73** — closed; superseded by merged work, with the superseding PR named in
  the closing comment.
- **#28** — closed as superseded by **#102**, on a measured **16-of-17 file
  overlap**, not on a reading of the titles. The pre-close head
  `04f63d7a87ccf2e6238f9b16832250cbab728212` is in the comment, so the work is
  recoverable.
- **#64** — closed only *after* its content was carried into `CLAUDE.md`
  (`ba242f9`). It had added a second top-level section to a file since
  restructured around the fleet conventions; the detail was worth more than the
  diff. The venv rule now carries the libmagic mechanism, the PowerShell
  command, and the diagnostic that follows from it: *a run that produces no
  output is an interpreter-and-shell problem before it is a code problem.*
- **#99** (`feat/cad-kinds`) — rebased, went red on exactly **one** of 1984
  tests (`test_the_generated_rows_are_in_sync_with_the_table`), and was
  **repaired to green**: the two CAD rows were regenerated through this repo's
  venv. Only the generator's header comment moved — no pass, output, suffix or
  domain value changed.
- **#102** (`feat/jena-writer-under-rulings`) — rebased and **left open with
  its 8 failures named and grouped**, six on the #147 stage-post/review wire
  contract and two on its own graph-scoping subject. Two of its three original
  motivations have since moved: the SDK's `upsert` is already graph-scoped, and
  v0.9.8 fixed Jena writer auth. The work is still wanted; the conflict is real
  and nameable, so this is reconciling work, not a re-run.
- **#125** — rebased through a conflict in a published session report, resolved
  to **`main`'s published version** (not with `git checkout --`), with the
  pre-rebase head `c204791401de9d6d67d9c4938dc0105fe994504e` recorded in the PR
  so the dropped same-day Addendum is recoverable.
- **#145**, **#100** — rebased, CI dispatched.

The 22 deleted branches, with the tip SHA each one carried at deletion:

- `chore/pin-sandbox-6023d27` — `eed3871bb6c9`
- `pin/sandbox-85ad4c9d` — `b352fd70fae8`
- `pin/f4d6440-instance-write` — `a0e7967b3794`
- `pin/a72a4a26-corpus-522` — `64feb00bba42`
- `pin/b18d7dc4-corpus-522` — `9ed48247d88c`
- `pin/d16b4402` — `0bea05afc5b2`
- `chore/pin-sandbox-c8dce84a` — `6da57ae467d8`
- `chore/pin-e656fa5` — `aa9b67fce044`
- `chore/pin-877677c` — `ff235adda9ba`
- `chore/pin-sandbox-877677c` — `dd26f993f79f`
- `chore/pin-sandbox-0c46fdb` — `7d12fe905165`
- `chore/pin-sandbox-78f8d10` — `6c8969747ce9`
- `pcn/gate-pin-merge-commit` — `f267a4871271`
- `mesh/pin-sdk-v0.9.5` — `82a7b358b2c7`
- `pcn/pin-49ed4a1` — `0fa21f6c053d`
- `pcn/pin-dbeb546` — `c298dc38f522`
- `pcn/pin-4825646` — `7ef0d029b385`
- `lane/7f-pin-507013f` — `20e5a97b8447`
- `lane/7f-ci-registry-pin-check` — `926c5b6ab0ae`
- `lane/7f-pin-sandbox-by-digest` — `74343dffe238`
- `pcn/pin-c460ac6-and-crop-seal` — `a759a0bb54e4`
- `chore/pin-sandbox-0279d83` — `051d9ed2cc67`

All 22 are pin-roll branches whose pins are long superseded; every one is
reachable by its recorded SHA.

## 4. Also placed tonight, outside the four items

The `restore-training-ingestion` directive asks `tr` and `7f` to coordinate on
`KIND_MAPPING` and the sensor pattern by packet, and says 7f owns nothing
there. That packet is placed — not committed into their tree, placed, per the
first convention — at
`sessions/2026-10-23-packet-to-lane-tr-from-7f-kind-mapping-the-sensor-pattern-and-the-five-traps-that-will-bite-training.md`,
read off `main` at `a28c094` with file and line.

**It carries one correction to a premise in the directive** — and tr's reply
corrected *me* on the same point, so the packet now carries the sharper
version. The ruling says a content kind declares its passes in `KIND_MAPPING`,
"shipping today for pcn/pdn". It is declared today, and **a dispatcher does
exist** (`doc_tools/passes/dispatch.py`, with a real contract: ambiguous or
catch-all pass signatures raise, `UNBUILT_PASSES` returns `status="unbuilt"`,
and a `::` name returns `status="baml"` without calling a model) — but
`run_passes_for_kind` is imported by **exactly one** module,
`doc_tools/assets/doors_ingestion.py`. **The pcn path bypasses it**:
`SustainmentPlugin.process_fulltext` runs both passes in one body, in one run,
and the platform side resolves no pass symbol at all
(`src/iagent/content_kinds.py` never reads `passes`). My first draft of that
section said flatly that declared passes "do not dispatch", which is wrong as
written; the corrected section names doors as the model to copy and
`UNBUILT_PASSES` as the honest way to register a pass that is not built yet.
The operative warning survives: **a golden test that asserts on declared passes
stays green through a pass that never executes.** Assert on artifacts.

**A second correction, to my own §C, found by checking tr's plan rather than
my prose.** tr's contract §2 has the training sensor declaring kind `training`
for its prefix. **There is no mechanism for that in the component it would
use.** `S3SensorComponent` puts exactly one field into the run:
`_build_ops_config` returns `{target_op: {"config": {"file_url": file_url}}}`
and that dict is the whole `run_config`
(`dag_tools/components/s3_sensor/sensor_component.py:122-137`) — no tags, no
extra keys, no kind, and no passthrough field on the model. Underneath that I
had put two fields on the wrong object in §C: `path_prefix_strip` and
`sidecar_manifest_name` are `DocumentParserComponent` fields
(`definitions.py:61`/`:66`), and `ingress_prefix` is not an `S3SensorComponent`
field at all — it belongs to this repo's own `build_ingest_retry_sensor`, and
the key-guard comment beside it is about the two *retry* sensors, not the two
ingress ones. So the `ingress_prefix="training"` my packet told tr to add does
not exist, and is struck.

**The kind reaches `resolve_content_kind` by exactly two channels: the sidecar,
and the path.** The cheapest correct answer needs no new code anywhere —
`_derive_from_path` returns `parts[1]` once `parts[0] == domain_type`, and the
domain and the kind need not be the same word, so `training/course-deck/...`
satisfies the rule that `training/training/...` was rejected for. Second
preference is tr's own `DocumentParserComponent` instance, which is how the
ADR-0041 user-drop path already works. A local sensor builder with its own
`run_config` is third (`ingest_retry_sensor.py:374` is the precedent, and the
op's config schema has to widen too); an SDK change to dag_tools is fourth and
buys nothing the first does not. **And the part that is not mine to decide:**
ADR-0021's precedence is metadata > path > HALT, architect-owned, and a sensor
arm is a third level in a documented two-level chain — delivered as manifest
metadata it is indistinguishable from an explicit sidecar value, so sidecar
cannot be ordered above sensor without a distinct key, and whichever writes
last silently wins. Raised to tr as an amendment to flag upward, not as a lane
decision. `resolve_content_kind` and `document_parser.py` are untouched.

The packet also carries the five traps (a `.pdf` drop resolves to the
*format-level* `pdf` row and runs the identity pass only; a failed run consumes
its `run_key` permanently and deleting the cursor object bricks the sensor; no
sensor injects `domain_type` and a null one crashes rather than defaulting;
`ingestable_kinds()` is a separate gate that wants a real processed drop;
re-ingest is additive, so `current.json` is the only thing that answers which
version is live), and says reuse rather than rebuild for the vector step:
`_index_chunk` already carries the uuid identity rule and the
`skipped_would_strip_vector` guard, and `embed_document`/`embed_query` are a
**prefix pair** that belongs in the contract.

## 5. Held, and what comes next

- **Item 4** — three fires on the v0.2.1 image, the first measured read of
  #148/#149/#151 on the corpus, after Lane 1 rolls it Monday.
- **`PCN-24_0003`** — re-ingest once v0.2.1 rolls. It sits with zero components
  and `needs_review=false` today; the salvage says 1,577 parts **or a flagged
  review**, never a silent zero. That is the first live proof of #148.
- **The graph-write ruling (this week, own PR)** — a failed graph write in
  *either* store fails the asset and posts `failed:graph_write` with the store
  named; then find why `inbound/adi_23_0120`'s triple write failed, and
  re-ingest it.
- **The id normalization (own PR, after that)** — one key, both stores,
  normalized at the write with the same function the IRI uses, plus a migration
  for the 27 existing nodes.
- **The two sensor/kind corrections above are with tr**, who owns the decision;
  nothing here changes until they answer, and `resolve_content_kind` stays as
  it is until then.
- **Offered, awaiting a word** — the doc-tools half of the two-directional
  drift seal: a job here that checks out the overlay at a pinned ref, so the
  drift test runs from both sides rather than one.
- **The corpus authority report is 5 days old against a 3-day maximum**, which
  reds the required gate on age alone and will red Lane 1's pin PR too. The
  nightly holds the cure; its branch is never rebased, so its own PR cannot
  merge. Worth a decision this week: whether to scope the corpus gate off
  release refs, or to fix the nightly's rebase.
