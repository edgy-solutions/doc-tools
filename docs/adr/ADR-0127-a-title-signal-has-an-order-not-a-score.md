# ADR-0127 — a title signal has an order, not a score

**Status:** built
**Date:** 2026-10-21 (ruled) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/utils/sustainment_header_trust.py:1713` (`title_signal`), the ruling
stated at `:1733-1736` — a function docstring, which was the **only** written statement of this
ruling before this record. The numbers it refuses to produce live in
`doc_tools/utils/leaf_read.py:131-151` (`_score`, `:410`); pinned by
`tests/test_leaf_read.py:74` and `:286`.
**Related:** [ADR-0126](ADR-0126-the-leaf-read-output-shape.md) (the output shape whose `score`
key this feeds), [ADR-0125](ADR-0125-a-pdf-runs-parse-only-before-the-title-read.md),
[ADR-0124](ADR-0124-header-identity-precedence.md)

## Context

The leaf ruling of 2026-10-21 asks for a `score` on every leaf candidate
([ADR-0126](ADR-0126-the-leaf-read-output-shape.md), item 2). The thing that knows how strong
the evidence is, is the title walk — `doc_type_from_titles` in
`sustainment_header_trust.py`, which the docstring records as 9/9 with 0 ambiguous on the
nine-notice corpus. The obvious implementation is therefore to have the walk return a number.

That is the move this record refuses, and the failure it avoids is specific. The walk is a
**measured** decision path: its 9/9 is a measurement of that code. Put a scoring convention
inside it and the convention becomes part of the measured path, so every later change to the
numbers — a threshold, a recalibration, a fifth signal class — reopens a measurement that was
taken on a different function. Worse, scoring conventions spread: once the walk emits 0.9, a
second caller reads 0.9 as a confidence, and "the first title carrying any signal decides" —
which is a rule about **document order**, not about magnitude — quietly becomes "the
highest-scoring title decides".

`title_signal` was lifted out of the walk's loop body on the same day so a second caller could
reuse it. That lift is what made the question live: the new function had to return *something*
about strength, and what it returns is the decision recorded here.

## Decision

**The strength ORDER of a title signal is the only claim `sustainment_header_trust` makes.
Turning that order into a number is the caller's job, deliberately not this module's, so no
scoring convention can drift into the measured walk.**

- `title_signal(title)` returns `(doc_type, source, signal)`, where `signal` is one of `code`,
  `keyword` or `ambiguous` — a class, not a magnitude. The caller named in the docstring is
  `doc_tools.utils.leaf_read`.
- The order that is claimed, and nothing beyond it (`leaf_read.py:131-151`):
  - a printed **code** outranks a **keyword** — the code is the vendor's own label for the
    document, while a keyword phrase can belong to a different notice entirely;
  - a `Title` element outranks a **pre-`Title`** text element — a recovery for a partitioner
    that types a real headline as `NarrativeText`, not a preference;
  - an **ambiguous** title scores both leaves low and **equally** — it is evidence that the
    document says both, which is a reason to ask, not to rank one above the other.
- The numbers that realise that order (`0.90 / 0.80 / 0.60 / 0.50 / 0.30`) are declared
  **ordinal and not a probability**: nothing is calibrated against an outcome frequency, and
  they must not be read as one, averaged, or thresholded as if they were.
- Candidates sort by score **descending, then by document order** — never by leaf name — so the
  first-signal-wins property of the walk survives into the candidate list rather than being
  undone by it.

## Consequences

- The walk keeps its measurement. A change to the numbers is a change to one caller, and the
  9/9 the docstring records still describes the code that produced it.
- The cost is a **split**: a reader who wants to know how strongly a title ranked must read two
  modules, because the class is decided in one and priced in the other. The docstring names the
  caller explicitly for that reason, and this record is the other half of that pointer.
- The ordinal numbers are a standing hazard precisely because they look like probabilities. The
  comment that says so is the only defence at the point of use, and a consumer outside this repo
  sees only the number — so the ruling is restated here rather than left in a comment.
- A fourth signal class can be added without re-measuring the walk: it needs a position in the
  order and a number in `leaf_read`, not a change to what the walk decides.

## Alternatives considered

- **Return a number from `title_signal`.** This is what the ruling literally asked for, and it
  is the alternative the docstring records as rejected, with its reason: the scoring convention
  would then live inside the measured walk. Recorded as considered and refused.
- **Return no strength information at all**, leaving the caller to re-inspect the title. Not
  recorded as considered. Its shape would be a second reading of the same string in a second
  module, which is the duplication `title_signal` was lifted out to avoid.
