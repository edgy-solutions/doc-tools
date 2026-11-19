# ADR-0182 — The written arm compares canonical forms, not strings

**Status:** built + measured
**Date:** 2026-11-08 (ruled; PR #213, shipped #216) · recorded 2026-11-18
**Deciders:** the architect — the code records it as "RULED 2026-11-08" and names no relay
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `scripts/pcn_corpus_gate.py:365-367` (the ruling and the unifying statuses),
`:400-445` (`_written_equality_key`), `_canonical_form` at `:379`, the report's own sentence
at `:2711-2717`; pinned by `tests/test_corpus_gate_written_agreement.py:124-148` — code
comments and a test docstring, which were the **only** written statement of this ruling
before this record
**Related:** [ADR-0180](ADR-0180-raw-verdicts-are-advisory.md) (why this is the blocking
arm), [ADR-0107](ADR-0107-no-fetch-mode-and-the-scorer-never-normalises.md),
[ADR-0183](ADR-0183-declined-is-the-third-bucket.md),
[ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md)

## Context

The written arm asks one question: did the three fires **read the same name**? It compares
the `written_header` each fire recorded, over `doc_type`, `mfr`, `pub_date` and
`doc_level_ltb_date` (`WRITTEN_ARM_FIELDS`, imported from `pcn_header_agreement` rather than
copied so the two instruments cannot drift). `revision` is excluded because the standing
ruling is that the revision half never blocks, and `doc_id` because the identity arm already
blocks on it — one fact, one gate.

Compared as **strings**, the arm answered a different question than the one it was asked. A
field that ground truth declares a shouted form and a title-case form of the same
manufacturer name both verbatim-correct for a notice was scored by the gate as a
disagreement on identical bytes, while `pcn_score.score_header_field` credited every one of
those reads. The gate was holding a fire to a standard the score does not — and a case-folding
rule adopted on 2026-11-02 fixed only the subset where the difference was case alone.

## Decision

**Two written values agree when the scorer resolves them to the same canonical form.**

- Each read is mapped through **`pcn_score.score_header_field`** against the notice's ground
  truth, and compared by what it resolves to.
- The unifying statuses are written out longhand: **`exact`, `alias`, `misformatted`**. This
  is deliberately **not** `pcn_score.HEADER_FAILURES`' complement — `misformatted` is in
  `HEADER_FAILURES`, it fails correctness, and it unifies **here** anyway, because a mangled
  spelling of a form ground truth accepts is still a reading of the same name. The two arms
  ask different questions of one status. `pending` unifies under neither: ground truth
  records no established value, so there is no canonical form to resolve to.
- The alias tables are **not copied**. A gate holding its own list would drift from the score
  the day a form is added, so the scorer is called.
- **No `try`/`except`** around the scorer. A spec it raises on is a malformed ground-truth
  declaration, and swallowing that into a quiet string comparison would turn a broken ground
  truth into a passing gate.
- **With no spec** — ground truth declares nothing for the notice or the field — the
  comparison is exactly what it was before the ruling: case is folded, and **only** case.
  Whitespace is deliberately not collapsed, so two differently-spaced values still read as
  different. Non-strings keep their exact comparison; `None` never reaches here, the blank
  arm takes it first.
- The two key spaces cannot collide: a canonical key is a JSON list, a string key is a JSON
  string.
- The arm keeps its teeth. `distractor`, `wrong` and `unreadable` resolve to **no** canonical
  form and fall through to the string key, so a declared trap spelling still blocks. Two
  fires that wrote the same *failing* string still agree — they read the field the same way,
  and whether that reading is right is the correctness arm's question.

## Consequences

- **Measured.** Shipped in PR #216 and measured on the rolled pin `e73d8b08` (recorded in
  agent memory `the-gate-written-arm-and-mfr-agreement-contradict-each-other`): the notice
  this ruling was written for now **agrees**, the parts arm is 512/512 on all three fires,
  and one notice's `mfr` was left as the only written blocker — three entries, all
  undeclared. The change did not recur on 2026-11-15, where the strict run passed with no
  exemptions, so it has not been exercised again since.
- The gate's standard is now **the scorer's** standard. A ground-truth edit that adds an
  accepted spelling silently changes what the written arm calls agreement — which is the
  point, and the reason the arm must never keep its own list.
- A report written before 2026-11-08 carries **no** `written_agreement.canonical` key. Its
  absence means strings were compared, **not** that nothing was; the renderer reads it with
  `.get` and says so in the report, which prints how many fields on how many notices had a
  declaration to resolve against.
- The evidence prints **what each fire wrote**, never the key it was compared by. A reader
  who sees three different strings in a disagreement line is reading values, not keys.
- Where ground truth is silent the arm is stricter than where it speaks. That is intentional:
  a notice ground truth says nothing about is held to the stricter reading, and
  `tests/test_corpus_gate_written_agreement.py:124-148` pins exactly that fallback beside
  the unifying case.

## Alternatives considered

- **Compare strings, with case folded.** This is the 2026-11-02 rule the ruling partly
  reverses. Rejected: it separates readings the score credits, so the gate blocked a pin on a
  difference the measurement authority does not recognise.
- **Keep an alias table in the gate.** Rejected: two lists of accepted spellings drift, and
  the day they drift the gate and the score disagree about the same fire.
- **Unify on `HEADER_FAILURES`' complement.** Rejected explicitly in the code: that tuple
  answers correctness, and `misformatted` has to unify here while still failing there.
- **Fold whitespace as well as case in the no-spec fallback.** Not taken: two fires that
  wrote differently-spaced values did read the field differently, and that stays a
  disagreement.
