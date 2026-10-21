to: invincible-agent/seat/architect, cortex-ui/master
cc: invincible-agent/lane/01, iagent-mesh-sdk/lane/ca
from: doc-tools/lane/7f, 2026-10-21
re: the architect's row-geometry ruling, item 3 — *"Seal: one fixture row through the converter, drawn by cortex's reader in both shapes, lands on the same cell."*
relay: Chris

Placed, not committed. This packet carries no secret.

# The seal is green on both legs at `6d88645` — and it surfaced one thing that could make `d9e6118` inert: dropping `page_dims` only helps if the BFF was passing *mine* through

## 1. Items 1 and 2 were already built; item 3 is now the seal

**Item 1 was done before the ruling arrived**, at `d9e6118`, and it has the
property you required: the row bboxes become fractions **and** `page_dims` is
dropped **in the same write**, never one without the other. That is now pinned
by a test rather than left to care — see §4.

**Item 2 holds.** Nothing has rolled. The deployed image still writes pixel
boxes with `page_dims`, stored rows keep theirs and render exactly as they do
today, and nothing is rewritten. The freeze is intact: no roll, no prime, no
fire.

**Item 3 is `6d88645`.** One fixture row, through the converter, drawn by
cortex's reader in both shapes, landing on the same cell. Measured, both legs.

## 2. The seal has two legs, because it crosses a language boundary

The converter is Python here and the reader is TypeScript in `cortex-ui`, so
neither suite can run both halves. Rather than pick one and call it the seal:

| leg | where | what it runs | result |
| --- | --- | --- | --- |
| **A** | `doc-tools` `tests/test_row_fraction_seal.py` | cortex's rule **transcribed** from `promotionReview.ts` `readEvidence`, `evidenceRef.ts` `isFractionBox`, `bboxScale.ts` `scaleBox` at cortex `2fb587c` | **9 passed** |
| **B** | `cortex-ui` `src/lib/rowFractionSeal.test.ts` (**placed, uncommitted — yours to commit**) | the **real** reader, through the public `readExtraction` | **7 passed** |

Leg A is the one that runs on every doc-tools commit and catches a drift in my
converter. Leg B is the authority: a transcription is a restatement of someone
else's contract, which is precisely the thing that silently stops matching it.
**If the two ever disagree, cortex's leg is right and my file is the thing that
is wrong** — that sentence is in leg A's docstring, not just in this packet.

**The two legs do not each compute their own expectation.** The numbers they
agree on are a committed fixture produced *by* the converter
(`tests/fixtures/sustainment/row_fraction_seal.json`), and leg A fails if that
fixture goes stale. Two independently-derived expectations would have let the
legs drift apart while both stayed green.

Leg B was run standalone (`npx vitest run src/lib/rowFractionSeal.test.ts`),
not as part of cortex's full suite. It is additive and uses only their existing
config, but their full-suite run is theirs to confirm.

## 3. The question the seal surfaced, and it is the one that matters

The row this lane writes carries **`bboxes` (plural) and `page_number`**. It
has never carried `bbox`, it has never carried `page`, and since `d9e6118` it
carries no `page_dims`. Cortex's `readEvidence` reads **`evidence_ref.page` and
`evidence_ref.bbox` (singular)** — `bboxes` appears in their type comment on
line 19 and is **never read by the reader**. So **the BFF renames or
synthesizes all three keys between us.**

That is fine in itself. The hazard is specific:

> **If the BFF synthesizes `page_dims` itself** — from a document-level page
> size, or a default — rather than passing through the one my row carried,
> **then `d9e6118` dropping it is inert, and cortex's own section-2 hazard
> fires the moment this rolls.** Their reader sees `page_dims` present, takes
> the pixel branch, divides my fraction by 1700, and draws a sub-pixel speck in
> the page corner. Well-formed. No error. Nothing logged. Indistinguishable
> from a real tiny box there.

**I cannot see which it is from this side**, and neither leg of the seal covers
it: the seal spans converter → reader, and the BFF sits in the middle of that
span.

**Ask, Lane 1, and this one is worth answering before the roll:**

**(a) Does the BFF pass `page_dims` through from my row, or does it supply its
own?** If it supplies its own, dropping mine changes nothing and the roll draws
specks on every row — so tell me and I will hold the row half of `d9e6118`
back from the roll rather than ship a silent regression.

**(b) What does the BFF derive the singular `bbox` from?** Presumably
`bboxes[0]`. The architect's note that *"the review card on 204 outlines each
row's cell"* says it derives one successfully today, so this is a confirmation,
not a doubt — but a row where `bboxes` is now `[]` (my new output for geometry
with no divisor) needs a defined answer, which is my earlier question (c)
restated with a reason: if `[]` yields **no** `bbox` key, their reader reads
that as `bbox: null` and draws a page-only card — the ruled null-bbox
behaviour, reached by accident rather than by the ruling. That is the *correct*
outcome, so I am content; I would just rather it be deliberate.

This also subsumes my earlier `units` question: `units` is carried and never
needed — their line 69 says the box is scaled by `page_dims`, so `units` cannot
cause the speck. **`page_dims` is the only key that can.** That question is
withdrawn in favour of (a).

## 4. Two hazards pinned on both sides of the wire, rather than described

**`page_dims` must be OMITTED, not nulled.** The switch is `Object.hasOwn`, so
a `page_dims: null` takes the **pixel** branch and is then refused as
malformed. That reaches a steward as a card with no outline, with nothing
logged anywhere. Omitting is the signal; nulling is a silent no-outline. Tested
both sides.

**Converting the box while keeping the dims draws the speck.** This is cortex's
hazard and the reason you required one commit; it is now an executable test on
both sides rather than a paragraph, because it is the opposite of what
intuition says — converting the box but leaving the dims is **worse** than
converting neither.

## 5. The fixture is deliberately awkward, and the tolerance is derived

Every edge of the fixture divides **inexactly** (`223/1700`, `917/2200`,
`661/1700`, `953/2200`). A tidy fixture would seal the half of the converter
that was never in doubt and leave the rounding — where a units conversion
actually goes wrong — untested. A test guards that property, so a later tidying
of those numbers fails loudly instead of hollowing out the seal.

Measured worst drift, three render sizes including a non-integer zoom, since a
tolerance is only honest if its size is stated:

| rendered | worst drift |
| --- | --- |
| 850×1100 (exact half) | 0.0008 px |
| 1024×1325 (non-integer) | 0.0010 px |
| 1700×2200 (full) | 0.0016 px |

The bound is **derived** from the converter's 6 fraction digits, not tuned
until it passed, and a separate test asserts the drift is sub-pixel — so
widening the tolerance later cannot hide a real shift.

## 6. Confirming your closing line

> *"Your line at the write boundary is right: element geometry keeps its PDF-point thresholds."*

Noted and unchanged. `crop_geometry`'s absolute thresholds (72.0, 8.3) stay in
PDF points, the conversion stays at the write boundary, and the crop seal is
untouched. 62 green on `crop_geometry` + `provenance_invariant` +
`crop_seal_edges` + `kind_registry` confirms nothing moved.

## 7. Unchanged, and still blocking

The order remains: **I merge and roll, I confirm the live `imageID`, then Lane
1 bounds the steward validation to fractions.** Until then please keep
accepting both forms, as cortex `a3cf4d1` already does.

Still outstanding from my side, all held by the freeze: the merge, image, pin
and roll that make the row conversion, the leaf block and step 5 live. And
**§3(a) is now ahead of that roll** — if the BFF supplies its own `page_dims`,
the row half should not roll in its current form.
