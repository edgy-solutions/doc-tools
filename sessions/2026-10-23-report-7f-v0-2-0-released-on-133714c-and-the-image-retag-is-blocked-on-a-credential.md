# doc-tools v0.2.0: the GitHub release is cut. The image retag is blocked on a credential, and only on that.

to: invincible-agent/seat/architect, via Chris; cc invincible-agent/lane/01 (release owner)
from: doc-tools/lane/7f
date: 2026-10-23
re: release v0.5.0 / doc-tools amendment — tag v0.2.0, not v0.5.0

> ### ⚠️ SUPERSEDED IN PART, later the same day — the retag was never only blocked, it was pre-empted
>
> Two statements below were true when measured and are **false in the registry
> now**. Both have the same cause: publishing this release fired the repo's
> `push: tags: ['v*']` trigger, and run
> [39961818782](https://github.com/edgy-solutions/doc-tools/actions/runs/39961818782)
> spent 36m1s **rebuilding** `133714c` and pushed the result under both of the
> build's tags.
>
> | what this report says | what is true now |
> | --- | --- |
> | `v0.2.0` → 404, "nothing was mutated" | `v0.2.0` → `sha256:9883b5d3…`, **ungated bytes** (`corpus-gate` was RED in that run while `build-and-push` went green) |
> | §2(b) `133714c…` → `ac853308` | `133714c…` → **`sha256:9883b5d3…`** — the commit-sha tag was moved off the gated digest |
>
> So §2(b)'s conclusion is stronger than it reads: the commit-sha tag was not
> merely *the only* evidence for the mapping, it was **destructible** evidence,
> and it was destroyed within the hour. The mapping is recovered — from the
> original build run,
> [39090288904](https://github.com/edgy-solutions/doc-tools/actions/runs/39090288904),
> whose log records `exporting manifest list sha256:ac853308…` and pushes it as
> `…:133714c…@sha256:ac853308…` — but it now rests on a run record, not on a tag.
>
> **Nothing deployed changed.** The sandbox pins `ac853308` by digest and a
> digest is immutable; only tags moved.
>
> What else to read instead of the "one command" in §2: that request is
> withdrawn. **No credential is needed on any laptop.** The registry write now
> happens in CI with `GITHUB_TOKEN`, per
> [PR #146](https://github.com/edgy-solutions/doc-tools/pull/146), which also
> makes a release tag an `imagetools` retag of the gated digest instead of a
> rebuild. The verify harness moved from `scratchpad/verify_release_tag.py` to
> **`scripts/verify_release_tag.py`** in that PR; every invocation quoted below
> should read the `scripts/` path. The full account is
> `sessions/2026-10-23-report-7f-cutting-the-release-rebuilt-the-image-and-the-ci-versioning-pr-is-the-repair.md`.
>
> Everything in §1 (the release itself, the tag, the two commit-count
> corrections) and §2(a) (`imagetools create` preserves the index digest, all
> four children) stands unchanged.

## The short version

| item | state |
| --- | --- |
| **GitHub release `v0.2.0` on `133714c`, with notes** | **DONE** — https://github.com/edgy-solutions/doc-tools/releases/tag/v0.2.0 |
| git tag `v0.2.0` → `133714c0652179187eb2cdca8b3c6d5881ecb3c5` | **verified**, by `git rev-list -n1 v0.2.0` |
| **GHCR image tag `v0.2.0` → `ac853308`** | **BLOCKED on a push credential.** 401 from GHCR. Nothing was mutated. |
| verification harness + short/fake controls | **built and run**; controls clean, `v0.2.0` currently 404 |

**One thing Chris has to do, and it is one command.** Everything else on my half
is finished.

## 1. The release is published

- Tag `v0.2.0`, title **"Measured Extraction"**, on
  `133714c0652179187eb2cdca8b3c6d5881ecb3c5`. Not a draft, not a prerelease,
  marked Latest. Published 2026-10-23T13:30:44Z.
- Notes written in the v0.1.0 style, covering the areas the amendment named:
  the corpus gate, content kinds, the retry sensors, S1000D, the instance
  write — plus extraction-quality work and the fixes.
- The notes carry the provenance table (source commit, index digest, both
  platform children, build time, chart version, helm revision) so Lane 1's
  `docs/releases/v0.5.0.md` can cite doc-tools v0.2.0 without re-deriving any
  of it.

### Two corrections to the amendment, both small, both in the notes

1. **It is 472 commits to `133714c`, not 474.** 474 is the count to `main`'s
   head (`809963c`). `main` is two merges further on than the commit being
   tagged:

   ```
   git rev-list --count v0.1.0..133714c     -> 472
   git rev-list --count v0.1.0..origin/main -> 474
   ```

   Those two merges change **no** file under `doc_tools/`, `prompts/`,
   `baml_src/`, `registry/` or `scripts/`, which is the same measurement that
   makes work's `92c3e384` the same extraction code. The notes say 472 and
   explain the gap.

2. **Two of the seven areas the amendment listed are NOT in `133714c`,** so the
   notes say so explicitly rather than claiming them:
   - **Evidence refs.** Row provenance ships in v0.2.0 as an absolute page +
     bbox in the Phase 5 `review.json`. The `evidence_ref` wire shape and the
     page-fraction conversion are **on the active branch only** — measured:
     `git grep -c evidence_ref 133714c` finds it in session *reports* and in no
     file under `doc_tools/`; on `HEAD` it is in five modules.
   - **Steward corrections.** The only `steward` in the `133714c` tree is a
     prose comment at `ontology_assets.py:1123`. The correction-record contract
     is agreed and the platform's Neo4j half is live, but the RDF half is not
     in this image.

   A release note that claims unshipped features is worse than no release note,
   and these two would have been read by work's approvers as shipped.

## 2. The image retag is blocked, and the method is proven correct

### What is blocked

```
docker buildx imagetools create \
  -t ghcr.io/edgy-solutions/doc-tools:v0.2.0 \
     ghcr.io/edgy-solutions/doc-tools@sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5
```

```
pushing sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5
  to ghcr.io/edgy-solutions/doc-tools:v0.2.0
ERROR: ... unexpected status from PUT request to
  https://ghcr.io/v2/edgy-solutions/doc-tools/manifests/v0.2.0: 401 Unauthorized
unauthorized: unauthenticated: User cannot be authenticated with the token provided.
```

**Why:** this machine's `gh` token carries scopes `gist, read:org, repo,
workflow` — **no `write:packages`** — and docker holds no `ghcr.io` login. The
`repo` scope is why the GitHub release above succeeded and the registry push did
not. I did not go looking for a credential elsewhere; credentials are yours.

### Two things that failure already established, which are worth having

**(a) The method preserves the digest, so the tag will satisfy "verify each tag
resolves to the pinned digest".** This was the real risk — a retag tool that
re-serializes an index produces a *different* digest, and the tag would then
point at equivalent bytes but not at the pinned object. It does not:

- `imagetools create --dry-run` returns an index with **all four children
  intact** — `linux/amd64 766a1beb`, `linux/arm64 f62bf415`, and both
  attestation manifests with their `vnd.docker.reference` annotations.
- the real run's own log line names the manifest it PUTs:
  `pushing sha256:ac853308… to …:v0.2.0`. It is the **index** digest, unchanged.

So amd64 and arm64 both resolve, as the directive requires, and the tag will
resolve to `ac853308` exactly.

**(b) The commit↔digest mapping is proven, by tag resolution rather than by
metadata.** Measured today:

```
133714c0652179187eb2cdca8b3c6d5881ecb3c5  ->  sha256:ac853308f4b176ea5...8ed5
```

The commit-sha tag resolves to the pinned index. This matters because
**`ac853308` carries no OCI labels at all** — I read its config blob: `labels:`
is empty. There is no `org.opencontainers.image.revision` to read, so the image
cannot name its own commit and the tag is the only evidence. **That is exactly
the gap item 4 of the directive closes**, and it is not hypothetical: it is why
answering "which commit built this digest" took a tag walk rather than one
label read.

### What I need from Chris — one command

With a PAT carrying `write:packages`, either of these does it. **Do not paste
the token into a shell argument;** pipe it, so it does not land in history:

```
# 1. log in once (reads the token from a file or from stdin, not from argv)
<token-file>  |  docker login ghcr.io -u <github-user> --password-stdin

# 2. the retag -- registry-only, no build, no pull of layers
docker buildx imagetools create \
  -t ghcr.io/edgy-solutions/doc-tools:v0.2.0 \
     ghcr.io/edgy-solutions/doc-tools@sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5
```

Then the verification, which is read-only and anonymous — **I can run this
myself the moment the tag exists**, no credential needed:

```
.venv/Scripts/python scripts/verify_release_tag.py \
    v0.2.0 \
    133714c0652179187eb2cdca8b3c6d5881ecb3c5 \
    sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5
```

It runs the short/fake controls **first and refuses to report anything if they
pass**, then asserts each reference against the expected digest and exits
non-zero on a mismatch. Run against the registry as it stands right now:

```
controls (both MUST be 404):
  ok      http=404  short digest  sha256:00000000...
  ok      http=404  digest that does not exist  sha256:dededededededed...

references:
  http=404  v0.2.0                                     -> <none>
  http=200  133714c0652179187eb2cdca8b3c6d5881ecb3c5   -> sha256:ac853308f4b1...8ed5

  MISMATCH  v0.2.0
  MATCH     133714c0652179187eb2cdca8b3c6d5881ecb3c5
exit=1
```

Red, correctly, because the tag does not exist yet. **`v0.2.0` is a clean 404 —
nothing has been clobbered and no partial state was left behind by the failed
push.**

### The alternative, if you would rather no PAT existed on a laptop

A `workflow_dispatch` job that retags by digest using the Actions
`GITHUB_TOKEN` with `packages: write`. It needs no human credential, it leaves a
run record for the release note's "build run URL" column, and it makes every
future release tag a one-click operation instead of a local one.

Two honest caveats: it is a change to `.github/workflows/`, so it is a code PR
for your review; and a `workflow_dispatch` workflow is only dispatchable once
it is on the default branch, so it has to merge before it can be used — which
the freeze permits, since the freeze is on rolls. **I have not written it.** Say
the word and it is a small PR; otherwise the one command above is faster today.

## 3. Item 4 of the directive, for my half

*"every image carries `org.opencontainers.image.revision` and `.version`
labels"* — noted as ruled, and `ac853308` confirms the need: no labels at all
today. This repo's only workflow is `.github/workflows/build-container.yml`, so
it is one `labels:` block on one build step. **It is a code PR, and I am holding
it for the Monday batch** rather than slipping a workflow change in beside a
release — unless you want it sooner, in which case it goes out on its own.

## 4. For Lane 1's `docs/releases/v0.5.0.md`

Cite doc-tools as:

| field | value |
| --- | --- |
| repo | `ghcr.io/edgy-solutions/doc-tools` |
| tag | `v0.2.0` *(pending the retag above)* |
| digest (index) | `sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5` |
| source commit | `133714c0652179187eb2cdca8b3c6d5881ecb3c5` |
| GitHub release | https://github.com/edgy-solutions/doc-tools/releases/tag/v0.2.0 |
| chart | `doc-tools-0.1.5`, live at sandbox helm revision 53 |
| build run URL | **not resolvable from the image** — no revision label; the run is the one that pushed the `133714c…` tag |
| at work | `sha256:92c3e384…`, the linux/amd64 child of the index built from `809963c`; **same extraction code** as `ac853308` |

**One flag for the values-keys section of your doc:** doc-tools' sandbox values
pin the image in **two** places — `digest:` and the gate's `expectImage:` — and
they move in two separate rolls by design. A deployment that supplies one and
not the other gets a gate comparing the file against itself. Worth a line in
"values keys a deployment must supply".

— doc-tools/lane/7f
