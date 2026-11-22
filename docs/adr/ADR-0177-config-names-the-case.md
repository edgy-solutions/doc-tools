# ADR-0177 — config names the case; code implements the mechanism

**Status:** accepted
**Date:** 2026-10-30 (ruled, standing rule for all repos) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** agent memory `config-names-the-case-code-implements-the-mechanism`, which is outside
this repository; the audit against this tree in
`sessions/2026-10-30-report-7f-the-no-hardcoded-case-rule-audited-against-this-tree.md` — the
census marks this row ⚑: before this record, the rule had **no statement anywhere in this
repo's documentation**
**Related:** [ADR-0174](ADR-0174-an-overlay-field-is-data-not-code.md) (the rule passing, in one
place), [ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md),
[ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md),
[ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md),
[ADR-0209](ADR-0209-session-files-are-placed-never-committed.md)

## Context

A ruling arrives naming cases: *"pcn and pdn droppable by alert-processors"*. The cheapest way to
satisfy it is a branch — `if kind == "pcn"` — or an enum of workflows, or a wire type whose field
is called `pcn_review_shape`. The code works, the ruling is satisfied, and the PR is small.

The cost lands later and on someone else. Every named case becomes a branch to find when the next
case arrives; a deployment that needs its own case cannot configure itself without a code change
or a fork; and a registry copied into code drifts from the one the server serves, silently,
because both look authoritative and nothing compares them.

The trap is specific and easy to fall into: **a ruling that names a case is the first row, not a
constant.**

## Decision

**Nothing in an API, wire type, route, engine or UI hard-codes a workflow, document kind, domain,
group, program, recipient, or a customer's shape. Code implements the mechanism; config names the
case.**

Those things are configuration: a registry row (kinds, task kinds, rules), a declaration served
on the wire (options, consequences, labels, review shapes), a policy-rail row (grants, audiences,
approvers), or an overlay (profiles, templates, mappings).

Four tests, to run on your own diff **before opening a PR**, naming which one a decline rests on:

1. A new wire type uses **generic nouns** (item, kind, rule, recipient), with the domain term
   carried as a **value** from config.
2. A new behaviour is reachable by **adding a row, not a branch**. If you wrote
   `if kind == "pcn"` or an enum of workflows, it is wrong.
3. A deployment can add **its own case** without a code change, in an overlay never committed.
4. The registry or declaration your code reads is **the one the server serves**, not a copy.

Ruled 2026-10-30 as a standing rule for **all** repos, not doc-tools alone. Its status here is
`accepted` — a convention in force — not `built`: no test in this tree enforces it.

## Consequences

- **This record is the rule's first statement in this repository's documentation.** Its written
  homes were agent memory, which is outside the repo and outside git, and the 2026-10-30 audit
  report under `sessions/`. Measured at the pin, that audit report *is* tracked (93 files under
  `sessions/` are) — so the rule was committed, but only as one report among ninety-three, in a
  directory [ADR-0209](ADR-0209-session-files-are-placed-never-committed.md) calls placed rather
  than committed. A reader of `docs/` had no way to reach it.
- **This tree fails two of the four tests today, and the architect queued both rather than
  ordering a retrofit** (2026-10-30): *"both findings are queue items after the batch chain:
  runtime reads the registry once the platform serves it; the domain if/elif ladder becomes
  passes keyed by domain … Not a retrofit now."* So the ruling and the code disagree knowingly;
  the row belongs in [DEBT.md](DEBT.md).
- **Test (4) fails.** The runtime's registered-kind list is derived from the in-code
  `KIND_MAPPING` table — `doc_tools/utils/ingest_failure.py:146-151` (`_registered_kinds`). The
  direction is code → registry, not registry → code: `registry/content_kinds/*.yaml` is
  *projected* from that table by `scripts/generate_kind_registrations.py`
  (`doc_tools/utils/content_kind.py:45-53`, `doc_tools/utils/kind_registrations.py:1-11`).
  Nothing under `doc_tools/` reads a served registry; this waits on the platform **serving** it.
- **Test (2) fails.** A new domain needs a new `elif` in
  `doc_tools/assets/semantic_assets.py:932-964`, where the plugin is selected by
  `domain_type == "manufacturing"` / `"maintenance"` / `"compliance"` / `"sustainment"` /
  `"document"` / `"playbook"`. The fix's named shape is passes keyed by domain, cited in the
  memory as `ADR-0059` — **a number that resolves in no repo on this workstation**, already in
  [DEBT.md](DEBT.md) — not a row-per-domain of this lane's design.
- **Do not open either finding as work before the batch chain lands** — queued, not undiscovered.
- The rule corroborated a live decision independently: its "declaration served on the wire (…
  labels, review shapes)" clause supported declining `label` and `review_shape` in this repo's
  mirrored kind rows, and the ownership collision it tilted toward the platform was ruled that way
  the same day — [ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md).
- Where the rule is already satisfied it is invisible, which is part of why it needed writing
  down: [ADR-0174](ADR-0174-an-overlay-field-is-data-not-code.md) is test (3) passing, and
  nothing in that design announces which rule it is an instance of.
- The cost is a generic layer where a specific one would be shorter to write and to read; the
  rule buys the difference between a mechanism and a hard-coded customer.

## Alternatives considered

- **Satisfy a case-naming ruling with a constant or a branch.** This is the rejected option, and
  the memory names it as *"the trap that is easiest to fall into"*. A ruling that names a case is
  the first row.
- **Retrofit this tree to pass tests (2) and (4) now.** Explicitly declined by the architect on
  2026-10-30, quoted above — queued behind the batch chain, with each finding's shape named.
- **Scope the rule to new code only, leaving existing ladders alone permanently.** Not recorded
  as considered; the queue decision is a deferral with named successors, not an exemption.
- No alternative is recorded for the rule itself; it was issued as a standing fleet rule rather
  than chosen from options.
