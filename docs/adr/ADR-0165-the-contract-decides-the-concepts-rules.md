# ADR-0165 — the concepts pass implements the contract's rules, not its own

**Status:** accepted
**Date:** 2026-10-30 (architect's ruling) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/passes/concepts.py:13-14` — a module docstring, which was the **only**
written statement of this ruling before this record: *"The direction (Concept -> CanonicalConcept)
is the architect's ruling of 2026-10-30; the rules are contract `training-workbench.md` 4.7."*
**Related:** [ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md) (the rules
this one assigns authority over), [ADR-0177](ADR-0177-config-names-the-case.md) (the same
principle, one level down), [ADR-0164](ADR-0164-one-concept-call-per-section-group.md),
[ADR-0234](ADR-0234-the-training-workbench-seam.md),
[ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md)

## Context

`concepts.normalise` is a thicket of numbers. Contract §4.7 fixes an `align_key` normalisation,
two auto-link confidences (1.0 and 0.95), a four-row signal table with a slope and an intercept
per signal and a different value when no vectors exist, a floor (`propose_min`, 0.70), a
per-course cap (50), a ranking order, a sticky-id rule, a name tie-break, a pinned-concept rule,
a conflict rule and an orphan-sweep condition — every one of them a constant or a comparison in
the code (`doc_tools/passes/concepts.py:45-60` is the first handful).

The failure this prevents is a quiet divergence with a specific shape: these constants are
**tunable-looking**. A `0.70` floor that produces too many proposals invites exactly the change
any engineer would make — adjust the number, watch the count improve, ship it. Nothing breaks,
and the tests move with the code if they are read as describing it. The next time anyone asks
"why 0.70?" the answer is in neither place: the contract says one number, the code says another,
and the contract is what lane wb built its review UI against. It cuts the other way too — a
reader who finds a rule in the code and not in the contract cannot tell whether the contract is
behind or the code is freelancing, and without a stated authority the cheaper reading wins.

This is [ADR-0177](ADR-0177-config-names-the-case.md) — *config names the case; code implements
the mechanism* — one level up: a **contract** names the case, and the pass implements it.

## Decision

**The rules of the concepts pass are contract `docs/contracts/training-workbench.md` §4.7's.
The code implements them; the contract decides them. Where they differ, the contract is right
and the code is a defect.**

- Every constant, threshold, table row, tie-break and ordering in `concepts.normalise` is a
  **transcription** of §4.7, not a choice the pass makes. The code marks them as such:
  `#: Contract 4.7 confidences` at `concepts.py:45`, and
  `#: Strongest first. (floor-with-cos, no-cos fixed) are the table rows of contract 4.7` at
  `:53`.
- **Changing a rule means editing the contract first.** A tuning change to a number in
  `concepts.py` with no corresponding contract change is a defect, however good the measurement
  behind it looks.
- The contract's own change procedure governs: the owning lane edits the file and the other side
  asks by packet (§11). A change the *workbench* wants is a packet to lane tr, not an edit.
- A test over this pass is read as **pinning the contract**, not as describing the code. A test
  that re-states what the code happens to do cannot detect the divergence above.
- This record is about **authority, not implementation**. It does not assert that any particular
  rule is correctly implemented; [ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md)
  is where the pass's build evidence lives.

## Consequences

- **The status is `accepted` and deliberately not `built`, and that is not an oversight.** No code
  implements this decision: there is no check at the pin that compares `concepts.py`'s constants
  against §4.7's table, and this record does not claim there is. What exists is the docstring at
  `concepts.py:13-14` naming the authority and §4.7 cross-references on the constant blocks. The
  rule is enforced by people reading it.
- So the enforcement gap is real and nameable: **a tuning change to a number in `concepts.py`
  will pass CI.** A drift check that read §4.7's table and compared it to `_SIGNAL_CONF`,
  `CONF_EXACT`, `CONF_MUTUAL` and the defaults would close it. None exists at the pin, and it is
  owed rather than done — see [FOLLOW-UPS.md](FOLLOW-UPS.md).
- The contract is a **draft** (version 5, DRAFT, 2026-10-30, at
  `docs/contracts/training-workbench.md:1`), and a draft is still the authority here: "draft"
  describes how settled the rules are, not who changes them. In practice §4.7 will move, and when
  it does the pass follows rather than negotiates.
- A reader debugging a surprising proposal reads §4.7 first and the code second. If they disagree,
  the bug is in the code — and the disagreement is itself a finding, for [DEBT.md](DEBT.md).
- Lane wb can build against the contract without reading this repo, which is the point of having
  one: a rule that lives only in `concepts.py` is one the other side of the seam cannot see
  ([ADR-0234](ADR-0234-the-training-workbench-seam.md)).
- The cost is a slower change. Retuning a threshold is a contract edit plus a packet, not a
  one-line commit — a measurement arguing for a different number goes in the packet.

## Alternatives considered

- **Let the code be the authority and keep the contract as documentation.** Rejected by the
  2026-10-30 ruling. It is the arrangement that makes the divergence above undetectable: a
  document that merely describes code is updated when someone remembers, and lane wb would be
  building against a description rather than a promise. [ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md)
  records the related mistake — treating a checkout as the contract.
- **Generate the constants from the contract**, so the two cannot diverge. Not recorded as
  considered. It is the shape that would make this record `built`: §4.7's signal table is an
  actual table, so a generator or a drift check over it is plausible. The fact that it does not
  exist is why the status is `accepted`.
- **Make the thresholds configuration rather than constants.** Not recorded as considered for the
  signal table. Two rules *are* already settings (`TRAINING_ALIGN_PROPOSE_MIN`,
  `TRAINING_ALIGN_PROPOSALS_PER_COURSE`), the §4.7-sanctioned form — but under
  [ADR-0177](ADR-0177-config-names-the-case.md) a setting names a case, so making the table
  configurable would move the rules *out* of this record's authority, not into it.
- No alternative is recorded for the enforcement question itself — convention or check. The
  record states a convention because that is what the ruling established.
