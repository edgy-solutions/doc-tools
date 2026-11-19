# ADR-0184 — A red line says which fires declared

**Status:** built
**Date:** 2026-11-16 (ruled) · recorded 2026-11-18
**Deciders:** the architect — the code records it as "ruled 2026-11-16" and names no relay
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `scripts/pcn_corpus_gate.py:1040` (`_why_not_declared`, whose docstring carries
the ruling at `:1044-1052`); pinned by
`tests/test_corpus_gate_declined.py:320-355` — a code comment, which was the **only**
written statement of this ruling before this record
**Related:** [ADR-0181](ADR-0181-a-declaration-is-keyed-to-its-field.md) (the predicate this
message explains), [ADR-0183](ADR-0183-declined-is-the-third-bucket.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md),
[`docs/arch/components/corpus-gate.md`](../arch/components/corpus-gate.md)

## Context

The declaration predicate reads every fire ([ADR-0181](ADR-0181-a-declaration-is-keyed-to-its-field.md)).
When it fails, the gate prints a blocking line, and that line is what a reader acts on: the
report is the artefact a merge decision is taken on.

The line used to end `no reason names \`mfr\`` whenever the all-fires predicate failed. The
2026-11-11 report printed exactly that on a notice where **fire 2 named the field precisely
as asked**. Fires 1 and 3 did not, because they corroborated and **published** the value —
they had nothing to declare. So the report accused the producer of never flagging, when the
producer had flagged in the only fire where anything went wrong, and the reader was sent to
the wrong half of the pipeline.

"No fire named it" and "only the fire with the defect named it" are **different states with
different fixes**. The first is a producer that never flagged. The second is a rule demanding
a declaration from fires where nothing went wrong — which is the rule's problem, not the
producer's, and is the shape the declined classification was later written for
([ADR-0183](ADR-0183-declined-is-the-third-bucket.md)).

## Decision

**A blocking line says why the declaration was not found, and names the fires that did
declare.** `_why_not_declared` answers in one of three shapes, checked in this order:

1. **A missing flag first.** If `needs_review` is not true in some fire, the line names those
   fires and calls it an undeclared silent write of that field. This is checked before
   anything about reasons, because a notice nobody was told to review cannot have declared.
2. **Declared in some fires and not others.** The line names the fires that declared **and**
   the fires that did not, and states the rule it is applying: this rule reads the
   declaration in every fire, not only the one that withdrew.
3. **No fire named the field.** The line says so, and adds that a declaration about another
   field is not a declaration about this one.

The message is derived from the same single reader the predicate uses
(`_field_declaration_basis`, `:982`), so the message and the verdict cannot disagree about
what counted. Where the rule is per fire rather than across three, the line names that one
fire instead of "all three fires".

## Consequences

- A red line is now **diagnostic**, and the distinction it draws is the point: the reader can
  tell a producer defect from a rule that is asking too much, without opening a fire log —
  which is the read that leaks document text
  ([ADR-0189](ADR-0189-the-published-report-is-the-authority.md)).
- The line is longer, and it names fire numbers. That is the cost: the report's blocking
  section is harder to skim, and a reader who only counts red lines gains nothing.
- It names the notice and the field, and **no document value**. A message that quoted the
  value it was complaining about would put document text in every report and in every
  transcript that reads one.
- The identity-half blocking line routes through the same function, so the two red lines
  explain themselves the same way, and the identity line additionally names every moving
  field that is undeclared.
- This record and [ADR-0183](ADR-0183-declined-is-the-third-bucket.md) were ruled the same
  day on the same report. They are two halves of one answer: classify the shape that is not a
  defect, and say precisely what is missing in the shapes that still are.

## Alternatives considered

- **Keep the single message.** Rejected on the 2026-11-11 evidence: it was positively
  misleading on a real report, which is worse than terse.
- **Drop the all-fires requirement instead**, so that a declaration in the withdrawing fire
  suffices. Not taken here, and it is a different question — answered for the one shape that
  qualifies by [ADR-0183](ADR-0183-declined-is-the-third-bucket.md), whose four conditions
  are narrower than "any fire declared". Loosening the predicate generally is **not**
  recorded as considered.
- **Print the fire logs on a red instead of a better line.** This is what the gate already
  does when the verdict is not `pass`, and it is the behaviour that leaked document text
  once; a better line exists so that the log does not have to be read.
