# ADR-0233 — the scrub ledger seam is a contract with no scrubber

**Status:** proposed
**Date:** 2026-10-25 (architect order, overnight item 4), answering a design placed for review
2026-10-22; the four policy questions were **unanswered as of 2026-10-25** · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris, for the order. The four policy answers are **this
lane's recommendation, placed for review — not a ruling**
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/contracts/scrub-ledger.md:3-6` — the contract's own status line;
`docs/contracts/scrub-ledger.md:254-262` §7, the four rulings; `:296-299` §9, "No scrubber";
`doc_tools/scrub/ledger.py` (the models — the authority);
`doc_tools/scrub/scrubber.py:1-7` and `:62-73`
**Related:** [ADR-0224](ADR-0224-the-scrub-ledger-is-a-recommendation.md),
[ADR-0205](ADR-0205-a-length-and-a-hash-prefix-never-a-value.md),
[ADR-0177](ADR-0177-config-names-the-case.md),
[ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md),
[ADR-0232](ADR-0232-the-playbook-kind-seam.md) (the other seam whose status line has drifted)

## Context

The documents that measure the extractor cannot be committed. So the tests that matter most run
against files nobody can check into git — and a fixture that cannot be committed is a fixture
that silently stops being run. A *scrubbed* fixture can be committed, but only if two things are
both true: it still tests the extractor rather than the scrubber, and the scrub is auditable.

Four questions decide what a scrub may do, and all four were open when the chain started: is the
manufacturer name allowlisted or scrubbed; are dates allowlisted; may the original→substitute
mapping be retained in object storage; and does a scrubbed fixture enter the **scored** corpus.
None is cosmetic. Scrub the manufacturer and the `mfr` arm of the score measures the scrubber
rather than the extractor. Substitute a date by shape and it is no longer a date, so LTB scoring
comes off scrubbed fixtures entirely. Retain the mapping and the equivalence seal stays
repeatable, at the cost of keeping it. And `enters_scored_corpus: true` **moves the parts
denominator**, which is met exactly at `ac853308`.

Waiting for all four before writing anything would have stalled the chain. Answering them
silently in code would have been worse: a fixture built under a guess, indistinguishable later
from one built under a ruling.

## Decision

**The ledger is landed first, and it records which answer a scrub ran under instead of choosing
one.**

- **A committed ledger carries no original value.** Every original appears as
  `len=N sha256:XXXXXXXX` — the repo-wide convention
  ([ADR-0205](ADR-0205-a-length-and-a-hash-prefix-never-a-value.md)).
- The Pydantic models in `doc_tools/scrub/ledger.py` are **the authority**; the JSON Schema in
  `registry/scrub_ledger.schema.json` is a generated projection of them, with a `--check` mode,
  and is not hand-edited.
- **Every `policy` field is required**, including `policy.authority`, a free-text statement of
  where the answer came from. A fixture states its assumptions instead of inheriting them. The
  worked example's authority reads `RECOMMENDATION ONLY`.
- Because the policy is recorded per ledger, **a ruling that lands later invalidates exactly the
  fixtures whose `policy` disagrees with it — which is a query, not an audit.** That is the whole
  reason the schema could land first.
- The example ledger is **built through the model**, not hand-written: a hand-written example
  carries invented digests, so its coverage check fails for every candidate and the file teaches
  a shape that does not round-trip.

## Consequences

- **The status line has drifted, and this row belongs in [DEBT.md](DEBT.md).** The contract says
  `doc_tools/scrub/` "contains the ledger model and nothing else" and §9 says "No scrubber. No
  tokeniser, no allowlist file, no PDF rewriting". Measured at the pin, that package also holds
  `scrubber.py`, `allowlist.py`, `element_text.py` and `draw.py`, there is a
  `registry/scrub_allowlist.yaml`, and `scrubber.py`'s own docstring says it "implements the
  engine `docs/contracts/scrub-ledger.md` section 9 says was missing". The existing debt row for
  this contract records the status line as accurate; at the pin it is not.
- **What did *not* change is the part that mattered.** The four rulings are still unlanded, and
  the scrubber does not pretend otherwise: `RECOMMENDED_POLICY` carries the authority string
  `RECOMMENDATION, NOT A RULING`, naming the design section that asks the four questions and
  saying that a fixture built under them is invalidated by any ruling that disagrees. The seam's
  status is `proposed` for that reason, and this record does not upgrade it.
- The allowlist carries **no vocabulary in code**: every allowlisted string or pattern is named in
  the YAML, and the module only compiles and matches
  ([ADR-0177](ADR-0177-config-names-the-case.md)). A phrase hard-coded in the module would be a
  second list that can drift from the one a reviewer reads.
- Nothing loads the generated JSON Schema at runtime; it exists for reviewers and non-Python
  consumers. The example fixture is synthetic throughout and describes a document that does not
  exist, so **there is still no real ledger** — the first one needs the four answers.
- No image scrubbing, ever: a document whose text cannot be read is refused.
- **What a reader must not assume from the status line.** "The **contract only**. There is no
  scrubber" is no longer a description of the tree — but neither is its opposite a licence. The
  four recommended answers are *safe*, not *ruled*; a fixture built under them is provisional by
  construction, and reading the recommendation as a ruling is the specific mistake
  [ADR-0224](ADR-0224-the-scrub-ledger-is-a-recommendation.md) exists to prevent.

## Alternatives considered

- **Wait for rulings 1–4 before writing anything.** Rejected: the ledger is not blocked by them,
  precisely because it records the answer in force rather than choosing one.
- **Make the JSON Schema the authority and generate the models from it.** Rejected: the rules that
  matter (shape equality of a substitution, the mapping-policy/mapping-reference agreement) are
  validators, not schema constructs. The direction is models → schema, with `--check`.
- **Hand-write the example ledger.** Tried and withdrawn in the same change: invented digests
  break the coverage check, and the first hand-written replacement was a letter short of the
  original it stood in for, which the shape-equality validator refused.
- **Default `enters_scored_corpus` to `true` so scrubbed fixtures start earning score.** Not
  taken: it moves the parts denominator, and the denominator is the one number the gate's
  comparisons rest on ([ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md)).
