# ADR-0208 — only the owning lane commits in this repo

**Status:** accepted
**Date:** 2026-10-06 (fleet directive) · recorded 2026-11-18
**Deciders:** the 2026-10-06 fleet directive; placed in this repo by packets from
`ia-01/lane/01` and `ia-gov/lane/gov`, and — as the convention itself requires — committed by
the owning lane (`CLAUDE.md:1-8`)
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `CLAUDE.md:12-16` (§Conventions); the dispatch protocol it rests on is agent memory
`lane-dispatch-protocol-across-the-two-repos`
**Related:** [ADR-0209](ADR-0209-session-files-are-placed-never-committed.md),
[ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md) (the same rule for another
lane's registry), [ADR-0200](ADR-0200-a-stacked-pr-runs-no-ci-gate.md)

## Context

This repository is worked by a fleet of numbered lanes across two checkouts; doc-tools is lane
**7f**. Other lanes **run as live sessions on this machine and will edit this tree while work is
in progress** — in one pass, the orchestrator placed three files into `sessions/` mid-turn and
amended a dispatch twice (agent memory `lane-dispatch-protocol-across-the-two-repos`).

That is useful and is not the problem. The problem is what happens when a visiting lane also
*commits*. Three things are lost at once:

- **Authorship.** The commit carries a lane that does not own the tree and will not be reviewing
  it.
- **Review.** A placed packet committed by its author bypasses the owning lane's reading of it
  entirely; the owning lane discovers the change in `git log`.
- **The working tree's integrity.** Because peers are editing the same directories
  simultaneously, a wide staging command sweeps their in-progress work into someone else's
  commit. `git add -A` is precisely the command that does this, and it is forbidden for this
  reason as well as the usual ones.

## Decision

**Only the owning lane commits in this repo. Packets are *placed*, never committed, by anyone
else.**

- A packet, dispatch, report or correction written by another lane is **placed as a file** in
  this tree. The owning lane commits it, along with its own work, so authorship and review stay
  with the lane that owns the tree (`CLAUDE.md:12-16`).
- The reciprocal holds: this lane places packets in the other repo's `sessions/` and does not
  commit there. A disputed value in another lane's registry is a packet, not an edit
  ([ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md)).
- **Stage by explicit filename.** Never `git add -A`, never `git add .` — peers are editing the
  same tree, and a wide add commits their work under this lane's name.
- Work lands on a lane branch, never directly on `main`.
- A dispatch addressed to a lane this session is not is **misrouted**: place it and relay it, do
  not build it.

## Consequences

- A placed packet sits untracked until the owning lane commits it, so `git status` in this repo
  is routinely full of other lanes' files. That is the expected state, not a mess to clear:
  measured at the pin, **195** untracked paths under `sessions/` alone.
- Every commit in this repo is reviewable by the lane that owns the code, and `git log` answers
  "who decided this" with a lane that can be asked.
- The convention costs a round trip: a peer who finds a real defect cannot land the fix. The
  compensating channel is direct — `SendMessage` to the live session reaches the lane in
  seconds, and that round trip is fast enough to be the normal path rather than a fallback.
- It does not protect against a peer acting on the **cluster** or on a **pushed branch**. Both
  have happened: a peer opened the PR on this lane's pushed commit seconds after the push, and a
  peer rolled the next helm revision thirty seconds after this lane's roll, invisibly in `helm
  history`. The rule covers commits in this tree and nothing wider.

## Alternatives considered

- **Let any lane commit, and rely on review after the fact.** Rejected by the directive: with
  peers editing the same tree concurrently, the first casualty is not authorship but the diff —
  a wide add mixes two lanes' uncommitted work, and the resulting commit belongs to neither.
- **Use branches per lane in one checkout instead of placing files.** Not recorded as
  considered for packets. Lanes do work on `lane/<id>` branches, but a packet is a message, and
  the protocol delivers messages as files in `sessions/` rather than as commits
  ([ADR-0209](ADR-0209-session-files-are-placed-never-committed.md)).
- **A shared `packets/` directory with its own ownership rules.** Not recorded as considered.
  `sessions/` already serves as the inbox, and splitting it would need a second convention for
  which directory a given file belongs in.
