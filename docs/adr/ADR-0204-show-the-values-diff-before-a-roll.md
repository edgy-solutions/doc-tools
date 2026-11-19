# ADR-0204 — show the values diff before a roll, through the sanctioned path

**Status:** accepted + built
**Date:** carried as a standing convention since the 2026-10-06 fleet directive · recorded
2026-11-18
**Deciders:** the 2026-10-06 fleet directive, placed in `CLAUDE.md` by packets from
`ia-01/lane/01` and `ia-gov/lane/gov` (`CLAUDE.md:1-8`)
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `CLAUDE.md:30-34` (§Conventions); built as `tools/preroll_diff.py` (docstring
`:1-7`, redaction `:22`, `:32-37`, `:43-71`, both sides redacted at `:88`); the standing
instruction that it is the sanctioned path, `tools/README.md:14`
**Related:** [ADR-0205](ADR-0205-a-length-and-a-hash-prefix-never-a-value.md) (the redaction
rule this obeys), [ADR-0202](ADR-0202-expect-image-is-read-off-the-pods.md),
[ADR-0203](ADR-0203-the-expect-image-patch-is-part-of-the-roll.md)

## Context

A `helm upgrade` from `charts/` is how a commit reaches a running pod. It is also the one
operation in this repo with no CI gate in front of it: the roll is performed by hand, and
whoever approves it approves an intention, not a diff — unless a diff is put in front of them.

What goes wrong without one is not a theory about drift. Peer lanes roll this same release —
agent memory `lane-dispatch-protocol-across-the-two-repos` records a peer taking the next
revision thirty seconds after this lane's roll, invisibly in `helm history` — and the only way
to see a value that moved without a commit is to compare what the chart renders against what
the release actually holds. `tools/drift_check.py` exists for exactly that reading: *"a peer
`--set` that moved something is still visible without disclosing what it moved it to"*
(`tools/drift_check.py:5-6`). The pin bump is the
same question in miniature — two digests move, one of them from a reading
([ADR-0203](ADR-0203-the-expect-image-patch-is-part-of-the-roll.md)) — and the half-rolled state
is only *provably* safe if the diff says so. That is how the `ca3e7d83` window was cleared:
`suspend` appeared **zero** times in the diff, so the nightly CronJob being suspended was proved
rather than assumed (`tools/patch_expect_ca3e7d83.py:44-46`).

But the obvious way to get that comparison is the one that must not be used. `helm get manifest`
emits every rendered resource, `kind: Secret` bodies included, and `helm get values` emits the
release's user-supplied values as they are. In this repo that output carries **literal
credential values** — `charts/doc-tools/values.yaml` is committed and non-secret by filename
only, and the guardrails that protect `*.secret.yaml` do not cover it. Run either command
wholesale and the values reach a transcript, which is not editable. That has already happened
from a *read-only* grep of that file — a subagent echoed matching lines into its own transcript
on 2026-11-18 (agent memory
`values-yaml-carries-literal-credentials-so-never-grep-it-unfiltered`) — so the risk is
measured, not imagined, and a full render is a larger version of the same mistake.

## Decision

**Before a `helm upgrade` from `charts/`, show the values diff to whoever approves the roll —
and get it from `tools/preroll_diff.py`, which is the sanctioned path. Wholesale `helm get
values` or `helm get manifest` is not permitted.**

- The diff is `helm get manifest` (live) against `helm template` (this branch, with the deployed
  values files), **both sides redacted before anything reaches the output**
  (`tools/preroll_diff.py:88`, `tools/README.md:14`).
- Secret-bearing keys appear by length and sha256 prefix only, per
  [ADR-0205](ADR-0205-a-length-and-a-hash-prefix-never-a-value.md). Redaction fires on a
  secret-ish key name **or** inside a `kind: Secret` body's `data`/`stringData` block — belt and
  braces, because either test alone has a gap (`tools/preroll_diff.py:4-6`, `:43-71`).
- The live revision is **read** rather than captioned: the script asks `helm status -o json` for
  it, because a hand-typed label once said "rev 37" while the release was at 39, and a stale
  caption gets quoted later as if it were measured (`:76-82`).
- The underlying commands are still `helm get manifest` and `helm template`. The rule is not
  that they are forbidden, it is that their output goes **into the redactor**, never into a
  transcript or a file.
- The script passes **no** `--kube-context`, so the operator supplies one by prepending a
  credential-free overlay holding nothing but `current-context: edge` to `KUBECONFIG`, rather
  than copying or mutating the user's kubeconfig (`tools/README.md:47-53`).

## Consequences

- The approver sees a changed-line count and a redacted unified diff, and can tell a pin bump
  from a pin bump plus an unrecorded `--set`. A secret that *changed* is still visible as a
  changed `len`/`sha256` pair without disclosing either value.
- "No manifest difference" is a real, printable outcome, and it is the evidence that a rendered
  change is values-only — the form the `suspend: true` proof took.
- The diff is only as good as the values files named in the script (`values-sandbox.yaml` and
  `values-sandbox.secret.yaml`, `:19-20`). A roll from a different values set needs those
  arguments changed, and a reader must check them rather than assume the script is generic.
- Anyone who needs the *unredacted* value of a key has no sanctioned way to print it, by design.
  That is the cost this record accepts.

## Alternatives considered

- **`helm get values` / `helm get manifest` wholesale, read by eye.** Rejected: it is the path
  that puts literal credentials into an uneditable transcript, and `values.yaml` being committed
  means the exposure is a disclosure, not just an untidiness.
- **Redact only on key name.** Rejected in the script's own docstring as insufficient — hence
  the second test on `kind: Secret` bodies (`:4-6`).
- **`helm diff` (the plugin).** Not recorded as considered. It is the obvious third-party
  alternative and nothing in the tree at the pin weighs it; it would also have to be taught this
  repo's redaction before it could be used at all.
- **Hardcode `--kube-context edge` in the script.** Rejected: `scratchpad/roll_diff.py` did
  exactly that, and `tools/README.md:47-53` makes the overlay the convention instead.
