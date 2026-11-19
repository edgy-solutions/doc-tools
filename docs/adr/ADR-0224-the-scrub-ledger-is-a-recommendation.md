# ADR-0224 — the scrub ledger is a recommendation, not a ruling

**Status:** proposed
**Date:** recommendations placed 2026-10-22; **rulings 1–4 unanswered as of 2026-10-25** ·
recorded 2026-11-18
**Deciders:** nobody yet. The recommendations are this lane's, placed for review; the four
rulings are the architect's and were open at the time of writing
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `tests/fixtures/scrub/ledger_example.json:42` — the fixture's own `policy.authority`
line, which says `RECOMMENDATION ONLY`; `tests/fixtures/scrub/make_ledger_example.py:178`
("RECORDED, NOT RULED") and `:184`, the comment being the only statement of *why* the field
exists; `docs/contracts/scrub-ledger.md:254-272` §7 and `:3-6`;
pinned by `tests/test_scrub_ledger.py:341-353`
**Related:** [ADR-0233](ADR-0233-the-scrub-ledger-seam.md) (the seam: a contract with no
scrubber), [ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md) (what ruling 4 would
move), [ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md)

## Context

The corpus fixtures that measure the extractor are customer documents. They cannot be
committed, so the tests that matter most run against documents nobody can check into git — and a
fixture that cannot be committed is a fixture that silently stops being run. A *scrubbed*
fixture is the way out, and the scrub ledger is what a scrubbed fixture must declare about
itself.

The ledger model and its schema projection landed. The scrubber did not: at the pin
`doc_tools/scrub/` holds the ledger model and nothing else — no tokeniser, no allowlist, no PDF
rewriting — and `tests/fixtures/scrub/ledger_example.json` is synthetic throughout, describing
a document that does not exist.

The reason the schema could land first is also the trap. The 2026-10-22 design asks four
questions, and **all four were unanswered as of 2026-10-25**:

| # | field | the question |
|---|---|---|
| 1 | `manufacturer_name` | allowlisted, or scrubbed? |
| 2 | `dates` | allowlisted? |
| 3 | `mapping` | may the source↔fixture mapping be kept? |
| 4 | `enters_scored_corpus` | does a scrubbed fixture enter the **scored** corpus? |

The example ledger answers all four. It answers them because every `policy` field is
**required**, so a fixture states its assumptions instead of inheriting them — and the answers
it carries are the **safe** ones, not ruled ones: allowlist the issuing manufacturer (the
sensitive party in a *published* notice is the recipient, not the issuer, and scrubbing it makes
the manufacturer arm of the score measure the scrubber); allowlist the dates (date extraction is
date-semantic, and a shape-substituted date is not a date); a one-way mapping, which is safer
and whose cost is that the equivalence seal becomes unrepeatable after the fact; and no entry to
the scored corpus, because entering it would move the parts denominator.

A reader who opens the fixture and finds five filled-in policy fields, a passing equivalence
seal and a passing collision check reads a settled policy. It is not one. The file says so
itself, in a field nothing is forced to read.

## Decision

**The scrub ledger's policy block records which answer a scrub ran under. It does not choose
one, and this record is `proposed` for exactly that reason.**

- `policy.authority` is required free text, and the example's says **`RECOMMENDATION ONLY`**,
  naming the four open rulings and the date they were open on. A ledger whose authority line
  does not name its basis is not a ledger a reader can use.
- The four values in the example are the **safe answers, recorded as safe**. Nothing in this
  tree upgrades them to ruled, and this record must not be cited as the ruling.
- Every `policy` field is required so that a later ruling **invalidates exactly the fixtures
  whose `policy` disagrees with it** — which is a query over ledgers, not an audit of
  documents. That property is the whole argument for landing the contract before the answers.
- No real ledger exists yet, and the first one needs rulings 1–4. A real fixture built on the
  recommendations before they are ruled is a fixture that may have to be withdrawn.
- Ruling 4 is the one with reach outside the scrub chain: `true` would move the scored parts
  denominator ([ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md)), which is met
  exactly at the pinned corpus state. It is not a scrub-local question.

## Consequences

- The contract is usable now, and nothing built on it is safe to call policy. The status line of
  this record is the honest summary: written down, not ruled.
- **The ruling and the artifact disagree in appearance, not in content**: the fixture looks
  decided and is not. One test asserts the `RECOMMENDATION ONLY` string is present
  (`tests/test_scrub_ledger.py:352`), so the disclaimer cannot be quietly dropped — but a test
  cannot make a reader read it. This row belongs in [DEBT.md](DEBT.md) until rulings 1–4 land.
- When a ruling lands, the work is: answer it, re-run the example builder, and query existing
  ledgers for a disagreeing `policy`. The authority line is what makes that query possible.
- Keeping the recommendations visible has a cost — they will be cited as policy, because a
  written answer attracts citation regardless of its authority line. This record exists to be
  the thing that says no.

## Alternatives considered

- **Hold the schema until the four rulings land.** Rejected on the chain's own terms: the
  ledger *records* which answer a scrub ran under rather than choosing one, so it is not blocked
  by the open questions, and the tokeniser and allowlist that follow it are. The cost of
  rejecting it is this record.
- **Leave `policy` optional, or defaulted.** Rejected: a defaulted policy field is an assumption
  inherited silently, and the point of the block is that a fixture states its assumptions. The
  test above pins every field as required.
- **Guess the rulings and mark them ruled.** Not considered as an option. It is named here
  because it is what reading the example without its authority line amounts to.
