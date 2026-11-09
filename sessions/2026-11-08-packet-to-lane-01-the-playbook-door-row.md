# Packet to Lane 1 — the `playbook` door row: the hold is lifted, and there is no drop seam

**From:** lane 7f (doc-tools)
**Date:** 2026-11-08
**Placed, not committed by you.** Per the fleet convention, this lane commits it
with its own work.

## The short version

`playbook` is now **advertised** by the door. The work order asked 7f to lift
`HELD_OUT` for it in its own PR; **no PR is needed — the lift already shipped**
in #209, so this packet is the whole of what Lane 1 is owed.

## Measured from this tree, not inferred

Run with the repo venv from PowerShell, on `main` as of `b167d43`:

    HELD_OUT keys        = ['xml']
    held_out_entries()   = ['xml']
    playbook ingestable  : True
    playbook processable : True
    ingestable_kinds()   = ('course', 'document', 'doors-export', 'dxf',
                            'engineering-document', 'pcn', 'pdf', 'pdn',
                            'playbook', 's1000d-data-module', 'step-ap242',
                            'work-instruction')
    registry_fingerprint = sha256:99528b3afead62f4   (14 rows)

**The `held_out` row for `playbook` is gone; only `xml` remains.** A consumer
that was suppressing `playbook` on the strength of that row should stop.

## Where it landed

Both commits are in `main` under PR **#209**:

| commit | what |
|---|---|
| `f201b1b` | the `playbook` content kind, built from the merged spec |
| `e604b59` | a chunk per heading with prose of its own, a chunk for the preamble, **and the hold lifts** |

The hold was 7f's, taken 2026-11-07 and **ratified and then lifted the same
day, both by Chris**: it was to stand only until the splitter rule was fixed —
text under a non-leaf heading, and text before the first heading, were in no
chunk and therefore unretrievable. That fix is `e604b59`, and the ruling is that
the door then advertises the kind.

The entry is **kept in `kinds.py` as a comment** rather than deleted, because
the failure mode is the reusable part: *a pass becoming real was enough to
change what this door advertises, and nothing failed when it did.* Arm 1 claimed
the kind the moment the chunker made the pass resolve, with the whole suite
green — which is exactly what the `xml` comment above it predicts, arriving by a
pass being **built** rather than by a parser row being added.

## The part that matters most for Lane 1: there is still NO DROP SEAM

    playbook: domain_type=playbook  ingress_prefix=None  file_suffixes=('.md',)
              passes=('playbook.playbook_outline',)

- **`ingress_prefix=None`.** A playbook arrives by **git clone**, not by a user
  drop. There is no sensor, and no key pattern to match.
- **`file_suffixes=('.md',)` is the repo-scan filter, not a seam gate.** Do not
  read it as "drop a `.md` and it will be ingested". Widening it is a measured
  change, not a tuple edit.
- So: **advertise the kind, do not offer a drop path for it.** A UI or API that
  derives an upload target from an advertised kind will offer one here that
  nothing is listening to. This is the same shape as the kind-routing trap where
  an `inbound/` prefix path derives the kind `inbound` and halts.

`domain_type` is `playbook` and not None on purpose (a domain-less row writes no
graph and no chunks), and it has **its own branch** in the plugin selector in
`semantic_assets.py` — that chain's `else` is `TrainingPlugin`, so an unbranched
domain would get course-concept extraction run over a runbook and look like it
worked.

## What would retire the remaining `xml` hold

Quoting the entry's own `unblocks_when`, which is the standard 7f holds itself
to:

> a user-drop sensor processes a bare `xml` drop through to a parse artifact —
> then delete this entry, **in the same commit as the measurement that justifies
> it**

Status today: `rev188-door-probe.xml` halted at stage 1 (its sibling manifest
declared `xml`, which no arm can run). The ten drops that did complete all five
stages on 2026-10-16 were **`s1000d-data-module`**, which is in and proven by
those ten. A bare `xml` drop has still never been processed end to end, so the
hold stands.

## Nothing is owed back

This is a statement of state, not a question. If Lane 1 is carrying a
`playbook`-suppression rule derived from the old `held_out` row, that is the one
thing to remove.
