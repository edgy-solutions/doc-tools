# ADR-0114 — `xml` is held out of the door until a drop proves the path

**Status:** accepted + measured
**Date:** 2026-10-16 (ruled) · recorded 2026-11-18
**Deciders:** the architect
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/api/kinds.py:74-76` (the ruling) and `:78-89` (why a hold list and not arm
math), with the published entry at `:91-104` carrying `"ruled": "2026-10-16"` — a code comment,
which was the **only** written statement of this ruling before this record. Pinned by
`tests/test_processable_kinds_publisher.py:83-91` and `:94-102`
**Related:** [ADR-0115](ADR-0115-the-playbook-hold-is-lifted.md) (the same mechanism, the other
way), [ADR-0101](ADR-0101-processable-kinds-are-published-not-served.md) (how the list reaches
Lane 1), [ADR-0116](ADR-0116-a-sensor-cannot-declare-a-kind.md)

## Context

The advertised list this image publishes — `ingestable_kinds()` — is the union of two arms: the
kinds every declared pass of which resolves through `doc_tools.passes.dispatch`, and the kinds
with a parser class in the user-drop routing table. Arm membership answers *"does a pass exist
for this kind?"*

That is not the question the door's consumer is asking. Lane 1's door uses the list to decide
what it may route, and what matters there is whether a **drop** of that kind has ever travelled
the path end to end. The two questions came apart on `xml`. Measured on 2026-10-16: the one bare
`xml` user drop halted at stage 1 — its sibling manifest declared `xml`, which no arm can run —
while ten `s1000d-data-module` drops completed all five stages of the XML graph sync job.

So `s1000d-data-module` belongs in the list on evidence, and `xml` does not. Today the arms
already agree that `xml` is unrunnable, so the list would omit it anyway — **which is precisely
why the omission has to be written down**. The day a parser row for `xml` is added, arm 2 starts
claiming it, this door starts advertising a path no drop has ever travelled, and the whole suite
stays green. That is the same failure that later arrived on `playbook` by a pass being built
rather than a parser row being added ([ADR-0115](ADR-0115-the-playbook-hold-is-lifted.md)).

## Decision

**`xml` is held out of `ingestable_kinds()` by ruling, until a user-drop sensor actually processes
a bare `xml` drop; `s1000d-data-module` is in, proven by ten.**

- The advertised list is the arms' union **minus** a hold list. `arms` stays in the payload
  unfiltered, so a kind an arm claims and the hold withholds is visible as exactly that, rather
  than looking like an arm that forgot it.
- The hold is **a list with a named releasing measurement, not arm math.** Arm membership is
  evidence about a *pass*; this list is evidence about a *drop*. That distinction is the whole
  point of the record: the hold does not become unnecessary when the arms happen to agree with
  it, because the arms can change without any drop having been measured.
- **The measurement that would release `xml`:** a user-drop sensor processes a bare `xml` drop
  through to a parse artifact. Then the entry is deleted **in the same commit as the measurement
  that justifies it**. The payload publishes that condition as `unblocks_when`, because the door
  cannot read git.
- **That measurement has not been taken.** At the pin the entry is still present, `claimed_by` is
  empty — no arm can run `xml` today — and the published `ruled` date is still 2026-10-16. The
  release condition is therefore recorded, and open.
- Every hold is published with a `reason`, the `evidence`, `unblocks_when`, `ruled` and
  `claimed_by`. An omission with no reason reads as a bug to the consumer, and Lane 1 would be
  right to file it as one.

## Consequences

- The door advertises less than the arms can run, on purpose, and the difference is legible in
  the same payload rather than reconstructible from two.
- `claimed_by: []` says the hold is belt and braces **today**. Saying so is more useful than
  implying the hold is what keeps `xml` out — and it means the hold's value is entirely in the
  future case, which is why removing it as redundant would be wrong.
- The hold carries a maintenance duty: the releasing measurement and the deletion are one commit,
  so whoever takes that measurement also owns the payload change. A measurement taken without the
  deletion leaves the door understating what it can do, with no instrument that notices.
- The payload stays deterministic — no timestamps, no counters, no caller data — so a consumer
  can diff two publishes and see a hold appear or retire.

## Alternatives considered

- **Let the arm math decide, with no hold list.** Rejected in the comment: it gives the right
  answer today and the wrong one the moment a parser row for `xml` is added, silently, with the
  suite green.
- **Hold `s1000d-data-module` as well**, since arm 1 excludes it. Rejected by measurement: ten
  data modules completed all five stages on 2026-10-16, and serving arm 1 alone would have told
  Lane 1's door that an S1000D data module cannot be processed ten minutes after ten of them
  were.
- **Omit a held kind silently**, without publishing the hold. Rejected: an omission with no
  reason is indistinguishable from a bug at the consumer's end.
- **Release `xml` on the strength of the parser table** once a row exists. Rejected by the ruling
  itself — a row is a pass, not a drop. The only thing that retires this hold is a processed
  drop.
