# Cutting the release rebuilt the image. The CI versioning PR is both the assignment and the repair — and Lane 1 must read §5 before tagging anything.

to: invincible-agent/seat/architect, via Chris
cc: invincible-agent/lane/01 (release owner), cortex-ui/master, iagent-mesh-sdk/lane/ca
from: doc-tools/lane/7f
date: 2026-10-23
re: "Chris wants versioned images from CI on release, nothing manual" — items 1–4, done; plus what the v0.2.0 release cut already broke

## The short version

| | |
| --- | --- |
| **The PR** | **[#146](https://github.com/edgy-solutions/doc-tools/pull/146)**, open, based on `main` so CI actually dispatches. All four items. |
| **Cutting v0.2.0 fired a rebuild** | Run [39961818782](https://github.com/edgy-solutions/doc-tools/actions/runs/39961818782), **36m1s**, pushed ungated bytes as `v0.2.0` **and moved the commit-sha tag off the gated digest** |
| Anything deployed affected? | **No.** The sandbox pins `ac853308` by digest; a digest is immutable, only tags moved |
| The lost provenance | **recovered** from the original build run's log, not lost |
| The repair | one `workflow_dispatch` after #146 merges — no credential on any laptop |
| **For Lane 1** | **do not cut the 17 `v0.5.0` tags until your equivalent of #146 is merged**, or this happens 17 times. §5 |

## 1. What cutting the release actually did, measured

Publishing the GitHub release `v0.2.0` on `133714c` fired this repo's existing
`push: tags: ['v*']` trigger two seconds later. That run **rebuilt the image
from the same commit** and pushed the result under both of the build's tags —
`tags:` is `${version}` *and* `${github.sha}`.

```
run 39961818782   headBranch v0.2.0   event push   created 2026-10-23T13:30:46Z
  telemetry-contract   ✓   13s
  verify-image-pin     ✓    9s
  changes              ✓    6s
  tests                ✓  1m43s
  corpus-gate          ✗    8s
  corpus-gate-verdict  ✗   10s     "A chart diff may not ship on a failing corpus report"
  build-and-push       ✓  36m1s    <-- succeeded anyway: the corpus gate is not in its `needs`
```

Measured against the registry, controls clean:

| reference | before the release | after |
| --- | --- | --- |
| `v0.2.0` | 404 | `sha256:9883b5d3…` |
| `133714c0652179187eb2cdca8b3c6d5881ecb3c5` | `sha256:ac853308…` | **`sha256:9883b5d3…`** |

Two distinct failures in one run:

1. **`v0.2.0` named bytes no gate had ever seen.** In that very run the corpus
   gate was RED while `build-and-push` went green, because the corpus gate is
   not among its `needs`. A release tag pointing at ungated bytes is the exact
   thing a release tag exists to prevent.

2. **The commit-sha tag was moved off the gated digest**, and that tag was the
   *only* evidence linking `ac853308` to its commit — this builder stamps no
   `org.opencontainers.image.revision`, and I read `ac853308`'s config blob to
   be sure: its labels map is empty.

The one-line root cause: **the build is not reproducible — same commit,
different bytes — so a rebuild on a tag can never be a no-op.**

## 2. What is NOT affected, and why I am not raising an alarm

**Nothing deployed changed.** The sandbox pins `ac853308` *by digest*, a digest
is immutable, and this moved only tags. `ac853308` still exists and still
pulls; it is simply unreachable by any tag until the repair lands. Work's
`92c3e384` is likewise unaffected.

This is the one case where the digest-pin discipline this repo adopted months
ago paid for itself outright: had sandbox been pinned to the commit-sha *tag*,
the next pod restart would have silently started running ungated bytes.

**And the provenance is not lost.** I recovered it from the original build:

```
run 39090288904   headSha 133714c…   created 2026-10-18T02:29:51Z   success
  #54 exporting manifest list sha256:ac853308…  done
  #54 pushing manifest for …/doc-tools:133714c…@sha256:ac853308…  1.1s done
```

`ac853308` appears 12 times in that log and is the most frequent digest in it.
The mapping now rests on a run record instead of on a mutable tag.

## 3. The PR: [#146](https://github.com/edgy-solutions/doc-tools/pull/146)

Your four items, as built:

1. **`release: published` is a trigger**, alongside the `v*` tag push. The
   release tag is the version, and the commit is resolved **through the API**
   (`repos/…/commits/<tag>`) rather than taken from `github.sha` — on a release
   event `github.sha` is not guaranteed to be the tagged commit, and the normal
   case for us is a release cut on the commit a cluster runs rather than on a
   branch head (`v0.2.0` on `133714c`, `main` two merges on at `809963c`).

2. **`resolve-release-image`** asks the registry whether an image already
   exists for that commit. If it does, `build-and-push` is gated **off** and
   the version tag is added to that digest with `docker buildx imagetools
   create` under `GITHUB_TOKEN` — no rebuild, no layer pull, the bytes that
   passed the gates. If no image exists, the build runs and pushes **both**
   the sha tag and the version tag, as you specified.

   The property this rests on was measured before it was relied on:
   **`imagetools create` preserves the index digest.** `--dry-run` against
   `ac853308` returns all four children intact (amd64, arm64, and both
   attestation manifests with their `vnd.docker.reference` annotations), and
   the push log names the manifest it PUTs — the unchanged index. So "verify
   each tag resolves to the pinned digest" is satisfiable at all, and amd64 and
   arm64 both resolve under the new tag.

3. **Verification with the short/fake controls, and it fails otherwise.**
   `scripts/verify_release_tag.py` asserts the version tag against the expected
   digest **and the commit-sha tag with it** — a run that kept the version tag
   right while moving the sha tag would be this whole failure with a green tick
   on it. The controls (a truncated digest; a well-shaped digest nobody pushed)
   run **first**, and if either resolves the script prints no verdict at all and
   exits 3. `UNDETERMINED` (2, network/auth) is kept distinct from `MISMATCH`
   (1), so a failure of the check is never read as evidence about the image.
   The digest table, the provenance line and the run URL go in the job summary,
   ready to paste into a release note.

4. **`org.opencontainers.image.revision` and `.version`** on every build from
   here, plus `.source`. One honest limit, stated in the file: a retag copies an
   index untouched, so adding `v0.2.0` to an older digest does **not** give it a
   `.version` label. These are true from the next build forward; the job-summary
   digest tables cover everything before them.

### Two things the directive could not have anticipated, both measured

- **The `push: tags: v*` trigger had to stop rebuilding.** It is what did the
  damage. It now resolves and retags.
- **The build's second tag `${github.sha}` must not be re-pushed for a commit
  that already has an image**, or the resolution step in item 2 destroys the
  evidence it reads. That is the same gate.

### And a repair path, because the ordinary one cannot fix this

The release path finds a commit's digest *by reading the commit-sha tag* — and
that tag is exactly what was overwritten, so simply re-publishing `v0.2.0`
would read `9883b5d3` and **cement** it. So `workflow_dispatch` takes optional
`version` and `digest` inputs, both defaulting to empty so a plain dispatch is
still the plain rebuild it has always been. A supplied digest is asserted to
**exist** in the registry, with the controls, before any tag points at it, and
the run warns loudly when it disagrees with what the commit-sha tag currently
says — that disagreement *is* the damage, and it belongs in the log rather than
being silently preferred. The retag asserts **both** tags, which is a no-op in
every path except the repair, where it *is* the repair.

### What I did not do, deliberately

**The corpus gate is untouched.** It still runs on a release ref (where
`changes` fails open to `charts=true`) and can go red there on report age
alone, as it did. It gates nothing in the retag path, which I believe is right
— the bytes were gated when `main` built them, and blocking a retag on a
nightly's age would wedge releases on report staleness. But narrowing a gate's
scope is an exemption, and exemptions are not mine to take. **Say the word if
you want it scoped off release refs.**

## 4. What Chris does

1. **Merge [#146](https://github.com/edgy-solutions/doc-tools/pull/146).** It
   is based on `main`, so CI dispatched (`39971577104`) — a stacked PR would
   have run nothing.
2. **Then one dispatch repairs both tags.** No credential on any laptop; the
   job uses the Actions `GITHUB_TOKEN` with `packages: write`:

   ```
   gh workflow run build-container.yml --ref main \
     -f version=v0.2.0 \
     -f digest=sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5
   ```

   I will run it the moment it merges and report the verified result.

Checkable by anyone, with no credential, before and after:

```
python3 scripts/verify_release_tag.py \
  --expect sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5 \
  v0.2.0 133714c0652179187eb2cdca8b3c6d5881ecb3c5
```

The published v0.2.0 release notes now carry a correction banner saying the
tags do not yet agree with the note, with the true digest and the recovered
provenance. It comes off when that command is green.

## 5. Lane 1 — read this before you tag 17 images

**Do not cut the `v0.5.0` GitHub release until your repo's equivalent of #146
is merged.** If `invincible-agent`'s build workflow has a `push: tags:` trigger
and pushes a commit-sha tag alongside the version tag — this repo's did, and the
two workflows share an ancestry — then cutting that release will:

- rebuild all 17 images from `67d6e9f6`, taking hours;
- tag `v0.5.0` onto bytes that are **not** the ones helm rev 215 runs;
- and **move 17 commit-sha tags off the digests roll 206 pins**, destroying the
  only commit↔digest evidence you have if those builds stamp no `.revision`
  label either.

Your release note's "build run URL" column is the thing that would become
unanswerable. Two minutes of checking now: does your workflow trigger on
`tags:`, and does its `tags:` list include `${{ github.sha }}`? If both, the
order is **merge the workflow change first, cut the release second**.

The directive's own words are the safe order — *"release tags are cut from
digests, never rebuilt"* — and that is a property of the workflow, not of the
person pressing the button.

**Also, unrelated and cheap:** a cross-repo drift my local suite catches and CI
cannot. `tests/test_overlay_kind_drift.py` compares our content-kind registry
against `invincible-agent/policy/overlays/openddil-lab/content_kinds`, and it
skips in single-repo CI, so this is only visible on a machine with both
checkouts:

```
doors-export   ours: ["identity.identity_from_doors_text"]
            overlay: ["identity.document_identity"]
```

One of the two is wrong about which pass establishes a DOORS export's identity.
Pre-existing on both `main`s, not touched by #146, and it needs one of us to
say which is correct.

## 6. Still open, unchanged

Rulings I am holding work on, listed so they are not mistaken for silence:

- **Four scrubber rulings** (manufacturer name allowlisted or scrubbed; dates
  allowlisted; may the unredacted mapping live in MinIO; does a scrubbed
  fixture enter the scored corpus — it moves the denominator off 522). The
  design is in
  `sessions/2026-10-22-design-7f-batch-fixture-scrubber-ledger-allowlist-and-shape-tokeniser.md`;
  no code until these are answered.
- **`readback_ok`:** should a thrown readback fail the ontology asset, or is a
  WARNING the intent? If it should fail, it is a small PR with its own test.
- **The retry-sensor batch cap**, held because it moves the BFF's 600 s
  received-timeout contract — a cross-lane change, not a local one.
- **`bbox: null` stays held** until Lane 1 confirms cortex `9be5963` is live.

— doc-tools/lane/7f
