# The TI `mfr` red is two modules disagreeing, in writing, about the same three strings

lane 7f, 2026-10-29. Measured on the `01f016e4` pre-roll fire
(`docs/corpus-gate/report-2026-10-29T023748Z.md`). **No code changed. One
decision is needed and it is not mine to take.**

## What I was asked to do, and why it was already done

The overnight directive's item 3 was "the per-field exemption fix". That fix is
**already in `main`** — `8ccda54`, "the header exemption is keyed to the FIELD
under test", landed inside the #179 squash (`96d7b70`). It needed no code; it
needed the pin, because the deployed image `c056fa70` (= `38b7937`, #175)
predates it.

**Tonight is its first measurement in a deployed gate, and it worked.** The
blocker reads:

> needs_review=True in all three fires but no reason names `mfr` -- a
> declaration about another field is not a declaration about this one

That is precisely the behaviour `8ccda54` was built for: before it, a `doc_id`
reason — narrated on every notice since the doc_id precedence ruling — would
have bought this notice an exemption for `mfr`. So item 3's first half is
delivered and proved. What remains is the red it exposed.

## The red

| | fire 1 | fire 2 | fire 3 |
|---|---|---|---|
| TI `mfr` | `Texas Instruments Incorporated` | `Texas Instruments Incorporated` | `TEXAS INSTRUMENTS` |

The same report says, about those same three values:

- **Header correctness: `clean: True` in all three fires** — "every established
  header field matched the page in every fire".
- **Identity-half unstable across fires: (none)** — and `mfr` is one of the two
  identity halves.
- **Blocking: the written arm, on `mfr`.**

So one report asserts both that the value was right in every fire and that the
fires disagreed about it. Two of three arms accept these readings; one blocks.

Both readings are in the ground truth's **ACCEPTED-VERBATIM SET** for this
notice, with reasons, at `scripts/pcn_ground_truth.json`:

- `Texas Instruments Incorporated` — "the canonical form, as printed in the
  footer band beside the PCN number"
- `TEXAS INSTRUMENTS` — "The LOGO WORDMARK, all caps: printed on page 1 and read
  verbatim by the vision pass … Accepted for exactly the reason `TE` is"

## The part that makes it a decision rather than a bug

**`doc_tools/utils/mfr_agreement` was written for exactly this shape and states
a ruling that the gate's written arm does not follow.** Its docstring, on the
2026-10-09 TYC finding:

> A three-fire corpus run on 2026-10-09 wrote mfr=`TE` in fire 1 and
> `TE Connectivity` in fires 2 and 3 … So the instability was in the
> **COMPARATOR** — an exact string compare that treated three correct readings
> as three different answers — not in the witness. **The 2026-10-09 ruling:
> compare canonical-after-alias, never the raw string.**

Measured through the venv, on the real values:

| comparison | `readings_agree` |
|---|---|
| `Texas Instruments Incorporated` vs `TEXAS INSTRUMENTS` | **True** (canonical: the full form) |
| `TE` vs `TE Connecvity` | True |
| `Vishay` vs `onsemi` | False |
| `TE` vs `Texas Instruments` | **False** — the trap rule 3 exists for |

The product has used this module since (`sustainment_header_trust.py:1166,
1270`). **The corpus gate has never imported it.**
`compare_written_headers` compares with
`json.dumps(v, sort_keys=True, default=str)` — raw equality — and is handed no
ground truth at all.

**But the written arm's raw comparison is test-pinned, with these very
strings.** `tests/test_corpus_gate_written_agreement.py` uses
`mfr="TE Connecvity"` / `"TE"` / `"TE"` as its disagreement fixture, under the
2026-10-26 ruling that "the blocking arm compares the WRITTEN value". So **the
two modules contradict each other in writing about the same trio**: one says
they are three correct readings of one name, the other pins them as a blocking
disagreement.

I wrote the canonical-after-alias change to see what it costs: 97 lines,
`scratchpad/option-a-alias-comparator.patch`, **7 tests fail**. Five of the
seven fail only because they share one fixture helper, `_mfr_disagree()`, and
are really testing the per-field exemption logic — they need *any* genuinely
disagreeing pair. Only two pin the substance. **I reverted it**
(`git show HEAD:… > …`); the tree is green, 80 passed.

## Why the block is currently unsatisfiable

A written-value disagreement is exempt only if a review reason names the field.
The product narrates nothing about TI's `mfr` because **nothing went wrong** —
the witness corroborated it in all three fires. So no product change clears
this red and no declaration is forthcoming: as it stands it is a **permanent
block on a correct document**. That is the same shape as the identity-arm
contradiction fixed in #187 earlier tonight, which is why I stopped rather than
pushed.

## Three options, and what I would do

**D — compare through the ACCEPTED-VERBATIM SET (my recommendation).** Block
unless every fire's value is in that notice's curated accepted set. It is
per-document *evidence*, not a heuristic; it cannot equate two manufacturers;
the correctness arm already trusts that set; and the ground truth's own `_rule`
already says comparison is "canonical-after-alias", with a folded-only match
reported `misformatted`. A value outside the curated set still blocks, which is
the case this arm exists for.

**A — compare with `mfr_agreement.readings_agree`.** Makes the gate internally
consistent (2 of 3 arms already do this) and follows an existing written
ruling. Costs the 2026-10-26 raw-comparison choice and the 7 tests. The patch
is written and saved.

**B — canonicalize in the product before writing.** Fixes the *cause*: if every
fire wrote the fullest form there is no disagreement, and the gate keeps its
teeth exactly as ruled. `canonical_reading` already exists and is already used.
Risk: it changes a steward-visible published value, and the mfr arm is delicate
— loosening it has blanked an `mfr` before.

A and D tolerate publishing two different strings for one manufacturer.
B stops it. **I would do D for the gate and consider B separately**, because D
is about what the gate may *conclude* and B is about what we *publish*; they are
not alternatives so much as different questions.

## What this does not block

Nothing. Both rolls are live (helm 56 and 57), `expectImage` equals the pod
`imageID`, all four held PRs are merged, and the nightly is suspended, so the
red is visible and costs nothing while it waits for a ruling. `corpus-gate`
(the only required context on `main`) is green; `corpus-gate-verdict` is red on
this and is advisory.
