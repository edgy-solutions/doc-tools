# ADR-0209 — session files are placed, never committed

**Status:** accepted
**Date:** 2026-11-12 (ruled) · recorded 2026-11-18
**Deciders:** ruled 2026-11-12 for every repo in the fleet; the ruling names no person and, at
the pin, **has no written statement in this tree** — the date comes from the
[2026-11-16 decision census][census] row this record is written from
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** the convention it extends, `CLAUDE.md:12-16`; the dispatch protocol, agent memory
`lane-dispatch-protocol-across-the-two-repos`; the consequence, already recorded in
[DEBT.md](DEBT.md) §4 and [the index](README.md)
**Related:** [ADR-0208](ADR-0208-only-the-owning-lane-commits.md) (the rule this extends),
[ADR-0210](ADR-0210-worktrees-live-outside-the-scratchpad.md),
[the ADR index](README.md) — the directory that exists because of this record's cost

[census]: ../../sessions/ "placed, never committed — see DEBT.md §4"

## Context

Each repo in this fleet carries its own `sessions/` inbox. Dispatches from other lanes arrive
there as markdown files; reports and handoffs are filed back into the same directory, addressed
to a lane pair. It is a message queue implemented as a directory, and a lane reads **its own
checkout's** inbox, not the master tree's (agent memory
`lane-dispatch-protocol-across-the-two-repos`).

Two properties of that traffic make committing it wrong. It is **another lane's authorship** —
committing it would do by the back door what [ADR-0208](ADR-0208-only-the-owning-lane-commits.md)
forbids at the front. And it is **in-flight**: a dispatch may be amended after it is read, and
its line numbers go stale within hours (one was off by +58 against the working tree the same
day). A committed copy of an amended message is a second source of truth for an instruction.

## Decision

**Session files are placed, never committed, in every repo.** Ruled 2026-11-12.

- A packet, dispatch, report or handoff is **written into `sessions/`** and left untracked. It
  is delivered by being there, and relayed by `SendMessage` to the live session, not by a
  commit.
- The same applies across repos: to reach another lane, place the packet in the master tree's
  `sessions/` and relay the path; expect the orchestrator to copy it into that lane's own
  checkout.
- In-flight state has a separate home and is ignored outright: `HANDOFF.md` is in `.gitignore`
  (`.gitignore:73-75`) as *"one lane's working notes"*. Durable findings go to project memory,
  published reasoning to `sessions/`.

## Consequences

- **This is the cost, and it is the reason this whole directory exists.** The arguments, the
  alternatives and the measurements behind this repo's decisions live in `sessions/`, and
  because the ruling is not retroactive, **the decision history is half committed**: a clone
  gets the reasoning up to 2026-11-09 and nothing placed after it — including the
  2026-11-16 decision census these records are written from, which is itself untracked. The
  decisions keep arriving; the arguments behind them stop. That is census Gap 3, recorded in
  [DEBT.md](DEBT.md) §4. It is why each record here carries its own Context and
  *Alternatives considered* in full rather than a link to a session file, and why the
  [index](README.md) opens by saying so.
- Commit messages carry more than usual weight in this repo as a partial substitute; `135e0a4`'s
  body is the design of the DECLINED rule. That is a mitigation, not a record.
- The ruling is **not retroactive and the tree shows both states**: measured at the pin, **93**
  session files are tracked and **195** are untracked. Every tracked one is dated on or before
  2026-11-09 — the ruling of 2026-11-12 is honoured for everything since, and the earlier files
  are history, not a violation.
- **Where the ruling and the tree disagree:** the workflow still describes these files as
  committed — *"`sessions/` PASSES THAT TEST ON THE SAME GROUND `docs/` DOES, and is here
  because this lane's reports are committed there (one or two per work block)"*
  (`.github/workflows/build-container.yml:128-130`). The build-skip allowlist entry for
  `^sessions/` is harmless either way (an untracked file is in no diff), but the sentence is now
  false, and the row belongs in [DEBT.md](DEBT.md) as a stale statement.

## Alternatives considered

- **Commit session files so the reasoning ships with the clone.** Not recorded as ruled out on
  its merits, and it is the obvious alternative: it would close census Gap 3 directly. What
  stands against it is in this record's Context — authorship and amendability — and the question
  of *where the decision history is allowed to live* was left open by the census, which asked
  for a ruling on it. [DEBT.md](DEBT.md) §4 states the choice as open: either commit the history
  in some form, or accept that these records **are** the history.
- **Commit only the final reports, not the dispatches.** Not recorded as considered. It is the
  narrower version of the above and has the same unanswered question behind it.
- **Keep `sessions/` out of the repo entirely.** Rejected in practice: the inbox must be where
  the lane working the checkout will see it, and peers place files by path.
