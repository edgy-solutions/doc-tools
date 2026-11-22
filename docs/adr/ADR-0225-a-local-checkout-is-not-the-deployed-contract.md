# ADR-0225 — a local checkout is not the deployed contract

**Status:** measured
**Date:** measured 2026-10-27 (the drift seal), 2026-09-27 (the import-provenance arm);
carried as standing lane knowledge before either · recorded 2026-11-18
**Deciders:** a property of how this fleet is read and deployed, not a choice — recorded because
every one of its failures looks like a successful read
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** ⚑ the census records this rule's only statement as **lane memory**. At the pin its
sharpest written forms are a test docstring and a script header, each covering one arm:
`tests/test_overlay_kind_drift.py:50-73` (a sibling working tree is not the peer repo's
registry) and `:45-48` (a committed tree is not the fleet);
`tests/test_corpus_import_provenance.py:1-17` with `scripts/pcn_corpus_run.py:35-44` (code
copied into a pod is not code the pod imports); `tests/test_corpus_gate_guard.py:593-605` (the
job runs the image the chart pins). Stated as a rule in `docs/arch/README.md:57`,
`docs/arch/NOT-ESTABLISHED.md` NE-17 and [FOREIGN.md](FOREIGN.md)`:15-19`
**Related:** [ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md),
[ADR-0202](ADR-0202-expect-image-is-read-off-the-pods.md),
[ADR-0221](ADR-0221-the-diagnostic-grades-a-stored-artifact.md),
[ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md)

## Context

Three different reads in this repo have been wrong in the same way, and none of them looked
wrong.

**A sibling checkout read as the peer repo's registry.** The cross-repo kind seal compares our
kind rows against the platform's deployment overlay, which lives in a neighbouring repository.
It used to read whatever was in the sibling working tree. Measured 2026-10-27, that tree sat on
another lane's in-progress branch, **149 commits behind `origin/master`** — so the seal was
reporting one lane's work-in-progress as the platform's registry. The red it showed named a kind
that, at `origin/master`, **agrees**; the divergence that actually existed was a different kind
whose overlay omits one of our declared passes, and the seal never mentioned it. A tree that far
behind could as easily have produced a green that did not exist.

**A candidate tree read as the code that ran.** On 2026-09-27 two corpus measurements were void
because a candidate tree copied into the pod was never imported: the pod sets `PYTHONPATH=/app`,
the driver lives in `scripts/`, so `sys.path[0]` holds no `doc_tools` and `/app` wins. One arm
raised an `AttributeError` for a symbol only the candidate defined, and was caught. The other
was a baseline-vs-candidate A/B in which **both arms ran the same `/app` code and agreed with
each other** — a confident number about a change that never ran.

**A committed tree read as the running fleet.** Even with both repositories read at a commit, a
green seal says the two *registries* agree; it says nothing about what the pods serve, because
the merge can be newer than the deployed image. The same gap has its own shape in the corpus
gate: the gate runs the image the **chart** is pinned to, so code landing in this tree cannot
appear in a report until a pin bump carries it into the gate image.

In all three, the read succeeded. Files opened, a diff computed, a number printed.

## Decision

**A local checkout is not the deployed contract. A value owned by another repo is read from
that repo's `origin/master` — `git show origin/master:<path>` — and a value the fleet serves is
read from the fleet.**

- **Another repo's value:** read at a ref, never from a sibling working tree. Where the read is
  automated, it is pinned: the seal resolves the overlay from the sha in
  `tests/pins/invincible-agent.ref`, from the pinned commit's **objects** via `git archive`
  locally, and in CI from a checkout of that sha with the ref proved to equal the pin. No seal
  reads "whatever branch is checked out." The census records the repair as PR #181.
- **Our own code, in a pod:** copying a tree in is not enough. The candidate is imported only
  with `PYTHONPATH` set ahead of `/app`, and the corpus driver prints `extractor = <path>`
  twice, beside the score, for exactly this reason — read it before quoting a number.
- **The fleet:** what the deployed overlay sets, as opposed to what `charts/` declares, is not
  established from any tree (NE-17). An image claim is read back off the settled pods
  ([ADR-0202](ADR-0202-expect-image-is-read-off-the-pods.md)), and a job's behaviour is the
  behaviour of the image its chart pins, not of this working tree.
- **A measurement's baseline carries the same burden.** The 2026-09-21 extraction validation
  hashed the module in the running pod and showed it byte-identical to `origin/main` — a proof,
  not an assumption ([ADR-0222](ADR-0222-the-corpus-validation-is-the-authority.md)).
- Because the guarded failure is behaviourally perfect, the guard is on **reported provenance**:
  the path is computed, printed, printed again beside the result, and a mismatch says so in
  words.

## Consequences

- Cross-repo checks cost a pin and a fetch. A missing fetch fails in CI and skips only where
  CI's own env var is absent, and the pin is bumped in a one-line PR carrying the drift report.
- A pinned seal is deliberately **behind** the peer repo. Green means "agreed at the pin", and
  the gap between the pin and the peer's `origin/master` is real; it is bounded and visible,
  which an unpinned read is not.
- Every number measured in a pod needs its provenance line read before it is quoted. That is
  friction on every measurement, and it is the price of the 2026-09-27 pair of void runs.
- Facts about the deployed overlay, substrate priming and the peer's ADR namespace stay `not
  established` in this repo's architecture records rather than being filled in from a sibling
  checkout. A reader gets "not ours" instead of a plausible wrong answer.

## Alternatives considered

- **Vendor a snapshot of the peer's registry into this repo.** Rejected: it recreates the
  cross-repo coupling that moving the TBox TTLs out removed, and a stale snapshot is worse than
  no check, because it goes green against a copy nobody updates. A pinned fetch beats a copy.
- **Read the sibling working tree but warn when it is behind.** Not recorded as considered. The
  obvious shape — compare the sibling's `HEAD` to its `origin/master` and warn — still leaves
  the seal comparing against a branch, and the 2026-10-27 measurement shows the failure is not
  only staleness but *whose* branch it is.
- **Seal the deployed fleet instead of the registries.** Not available from a test: it needs a
  cluster read, which these checks deliberately do not do. The fleet gap is recorded as
  not-established rather than asserted.
