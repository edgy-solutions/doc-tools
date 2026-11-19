# ADR-0111 — a disputed registry value goes to lane 01 as a packet, not an edit

**Status:** accepted
**Date:** 2026-10-30 (ruled) · recorded 2026-11-18
**Deciders:** the architect
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/utils/kind_registrations.py:37-49` (the ruling quoted at `:42-45`) and
`tests/test_kind_registry.py:413` — a code comment and a test docstring, which were the **only**
written statement of this ruling before this record
**Related:** [ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md) (the
ownership line this procedure defends), [ADR-0208](ADR-0208-only-the-owning-lane-commits.md) (the
same principle for commits in a tree)

## Context

[ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md) splits a content
kind's fields between two repos. A split like that is tested by its first disagreement, and the
first one was real: invincible-agent's SDK changelog for v0.9.11 told this lane to fill
`arrives_as` into `KIND_MAPPING`'s rows (2026-10-21), three days before the ownership ruling of
2026-10-24 moved that field to the platform. Two written instructions, in two repos, pointing
opposite ways.

The cheap move is to do the work: the field exists on the model, the values are known here, and
filling thirteen rows is a small, green, satisfying commit. What it actually produces is a
*fait accompli* — the disputed field now has a value in this tree, the overlay has another or
none, and whichever side later turns out to own the field inherits a divergence that was created
while the question was open. Reverting it is a second commit against a live registry, and the
reader of either repo cannot tell which value was ruled and which was assumed.

## Decision

**A disputed registry value goes to lane 01 as a packet, not an edit: ownership is settled before
a file is touched.**

- Where the owner of a value is in dispute, this lane **declines to write it**, says so in the
  code, and reports the disagreement. It does not settle a cross-repo question by being first to
  edit a file.
- The values themselves still have to reach the platform. They travel as a **packet** — the
  per-kind values for `domain`, `arrives_as`, `review_shape` and `label`, carried to Lane 1, who
  fills them into the registry the server actually serves.
- The decline is **pinned by a test**, so it survives the next reader, and the test arm is
  permanent rather than a placeholder: *"Your decline + test stay."*
- The ruling that closed this case is the authority over the older changelog line, which is
  **superseded**, not reconciled.

## Consequences

- A disputed field stays empty while the dispute is open. That is a visible gap in a live
  registry, and it is the price: an empty field with a test behind it is recoverable, a wrong
  value in two repos is a migration.
- The values move at packet latency rather than at commit latency. Nothing in this tree can
  shorten that, and a kind is not fully routable until Lane 1 has filled its platform fields.
- The procedure only works if the decline is *reported*. A silent decline looks exactly like an
  oversight, which is why the comment and the test arm exist and why the packet is the deliverable
  rather than the omission.
- It generalises: the same rule applies to the overlay's `passes`, where ownership runs the other
  way — the fix is to update the overlay row, never to narrow this registry to match it
  ([ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md)).

- This record is `accepted`, not `accepted + built`. What code at the pin holds is the *decline*
  and the test that pins it; the packet itself is a working convention between lanes, with no
  artifact in this tree a test could check. The only mechanised half is the refusal.

## Alternatives considered

- **Fill the rows as the changelog instructed and let the ruling sort it out afterwards.**
  Rejected: it settles a cross-repo ownership question by editing a file, and it is the exact
  path that produced the collision. The 10-30 ruling endorsed the decline retrospectively, which
  is the evidence that declining was the cheaper branch.
- **Open the question and block on it — write nothing, send nothing, wait.** Not recorded as
  considered as a distinct option; the packet *is* the non-blocking form of it, since the values
  reach Lane 1 while the file stays untouched.
- **Have the architect's ruling live only in the session record** rather than in the code and a
  test. Rejected by the test arm's existence: the ruling is quoted where the decision is
  implemented, because a ruling a reader cannot find is a ruling the next reader overturns by
  accident.
