# ADR-0220 — the "136 of 402" PDN figure is retracted

**Status:** measured
**Date:** 2026-09-21 (measured and retracted; the figure was published 2026-09-17) ·
recorded 2026-11-18
**Deciders:** the 2026-09-21 corpus measurement, recorded by this lane — the retraction is the
measurement's, not a judgement call
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:22-26` §Domain handoffs caution 1;
`docs/pcn-corpus-validation-2026-09-21.md:75-112` §2 (the reproduction);
`tests/test_table_text_layer.py:124-131` and `:813`;
`doc_tools/utils/table_text_layer.py:731-735` — the retraction is repeated at each site where
the number used to do work
**Related:** [ADR-0221](ADR-0221-the-diagnostic-grades-a-stored-artifact.md) (the instrument
that produced it), [ADR-0222](ADR-0222-the-corpus-validation-is-the-authority.md) (what to read
instead), [ADR-0129](ADR-0129-a-customer-part-number-is-never-an-affected-part.md)

## Context

A diagnostic change of 2026-09-17 (`a67e7f4`) taught the PDN instrument to inherit a parts
table's header across continuation pages, and its commit message reported the consequence as a
finding: **"136 of 402 extracted affected parts (34%) are values that appear ONLY in replacement
columns"** — replacement parts shown to a reviewer as discontinued ones, with a corpus-wide rate
of 1/9 documents rising to 3/9. That number then motivated a production fix, a handoff document,
a docstring and a test module.

Re-measured on 2026-09-21 against the real notices, it does not survive. All 136 values sit on
two pages whose own captions state that those tables contain **no replacement parts** at all:
they are not continuation pages of the preceding paired table, they are separate column-major
lists of discontinued devices, two part families listed side by side. In the grid space the
instrument reads, all three tables are six columns wide — so the diagnostic inherited the
preceding page's `affected | replacement | …` classification onto them and relabelled half of
their genuine discontinued devices as replacement-sourced. The heuristic manufactured the
finding it reported. Both the baseline and the fixed extractor extract those 402 parts
correctly; nothing was ever confused with a replacement on that notice.

What makes this worth a record rather than a correction is where the number lives now. It was
quoted in two handoff documents, in `parts_from_grid`'s docstring and in an extraction comment,
and all of those were corrected in place — but **it survives in the `a67e7f4` commit message,
and a commit message cannot be edited.** That commit is on
`mfg-extraction-investigation`, not on `main`; at the pin the script it changed,
`scripts/pdn_parts_diagnostic.py`, is not in this tree at all. So the number is reachable by
`git log` on a branch, detached from every file that explains it, and it reads like a measured
production defect because that is exactly how it was written.

## Decision

**The "136 of 402 (34%)" figure is a measurement artifact of the diagnostic's own header
inheritance, and it must not be cited again — not as a defect rate, not as motivation, not as
history.** It is quoted here only in order to retract it.

- The figure is **retracted**, not revised. There is no corrected version of it: the defect it
  claimed to quantify was not present on the corpus.
- The retraction is repeated **at every site that used to carry the number**, because a reader
  arriving at the inheritance code or the continuation tests needs it there:
  `doc_tools/utils/table_text_layer.py:731-735`, `tests/test_table_text_layer.py:124-131`,
  `AGENTS.md:22-26`, and the two handoff documents, which strike the sentence through rather
  than delete it.
- **Where it will keep reappearing:** the `a67e7f4` commit message, whose subject line carries
  it ("finds 136 replacements sold as affected parts"); anything quoting that commit; and the
  retraction texts themselves, which a keyword search finds first. A hit on the number is
  therefore never evidence that the number stands — this record and
  `docs/pcn-corpus-validation-2026-09-21.md` §2 are what a hit must be checked against.
- The inheritance behaviour it motivated is **kept**, on its own evidence: inheritance is the
  right reading for a true continuation page, and the caption veto that the same measurement
  forced (`_names_a_different_table`) is what stops it firing on these two pages.

## Consequences

- The production change keeps its guard but loses its headline. Inheritance now stands on
  pinned tests in both directions — a genuine bare list reads all-affected, a continuation of a
  paired table does not — rather than on a corpus rate.
- Anyone looking for the measured defect rate for replacement-column leakage will not find one.
  The honest answer at the pin is that the corpus never showed this defect, and the near miss
  it did show runs the other way (inheritance overriding a caption).
- The retraction costs noise: the number appears more often in this tree *because* it is
  retracted than it would if it were simply deleted. That is deliberate — a deleted number
  still exists in the commit message, where nothing can explain it.
- A future reader of `a67e7f4` on its branch has no pointer back to here. That asymmetry is
  unfixable by us and is the entire reason for this record.

## Alternatives considered

- **Rewrite the history that carries the message.** Rejected as unavailable: the commit is
  pushed and shared, and rewriting a published branch to edit a sentence trades a wrong number
  for a broken ancestry. `docs/pcn-corpus-validation-2026-09-21.md:209-213` records the
  decision in those terms — corrected in every editable place, left standing in the one place
  that is not editable.
- **Delete the number from the handoff documents and the code comments.** Rejected: strike-
  through plus the reason is what stops the figure being independently re-derived by the next
  reader of the same instrument. A silent deletion looks like the measurement was never made.
