# Packet to the architect, from 7f — the Monday ruling on `_written_equality_key`

**The question, as asked:** *"bring the three TI/onsemi variants and what
`_written_equality_key` would need to treat them as one — that's the question I'll
answer."*

**The short answer, and it is not the one I expected to bring:** for TI it needs
*nothing new*. Ground truth already declares the comparison rule that unifies all
three TI variants, the scorer already implements it, and `pcn_score` is already
imported at module scope in the gate. For onsemi it must **not** treat the variants
as one — ground truth has already ruled the opposite, with a reason. So "treat them
as one" is answerable for TI and refusable for onsemi, and the asymmetry is not a
gap in the rule: it *is* the rule.

What follows is the evidence, then the one real cost, then the two prohibitions this
must not be confused with.

---

## 1. The variants, with provenance

All from the written-header arm (`compare_written_headers`), which compares each
notice's `written_header` across the three fires of one image.

**TI — `TI_PCN_20210316000.pdf`, field `mfr`**

| Fire | 2026-11-08 (`ca3e7d83`) | 2026-11-02 (`4dba8f7`-era) |
|---|---|---|
| 1 | `Texas Instruments Incorporated` | `TEXAS INSTRUMENTS` |
| 2 | `Texas Instruments Incorporated` | `TEXAS INSTRUMENTS` |
| 3 | `TEXAS INSTRUMENTS` | `Texas Instruments` |

The 2026-11-02 set is **case-only**, and #206's fold now unifies it — that fix
works. The 2026-11-08 set is not case-only: `Texas Instruments Incorporated` vs
`TEXAS INSTRUMENTS` differ by a word. The model sampled into a shape the fold
deliberately excludes, which is why the red did not clear.

**onsemi — `onsemi_Generic_IPCN25300X.pdf`, field `mfr`, 2026-11-08**

| Fire | Value |
|---|---|
| 1 | `ONSEM.` |
| 2 | `onsemi` |
| 3 | `onsemi` |

Six days earlier, on three fires, onsemi **agreed**. This disagreement is one fire's
misread, not a standing divergence.

## 2. What `_written_equality_key` does today

Added by #206 (`scripts/pcn_corpus_gate.py`):

```python
def _written_equality_key(v):
    if isinstance(v, str):
        return json.dumps(v.casefold())
    return json.dumps(v, sort_keys=True, default=str)
```

It folds **case only** — whitespace deliberately not collapsed. Its own docstring
names tonight's TI list *verbatim* as a difference it still separates **on purpose**:

> `['Texas Instruments Incorporated', 'Texas Instruments Incorporated', 'TEXAS INSTRUMENTS']`

So the gate is behaving exactly as written. This is not a defect report.

## 3. The asymmetry: ground truth has already ruled on these exact strings

**TI's `accepted` block** is an ACCEPTED-VERBATIM SET, ruled 2026-10-12, and all
three observed strings are keys in it:

- `Texas Instruments Incorporated` — *"the canonical form, as printed in the footer band beside the PCN number"*
- `Texas Instruments` — *"also verbatim on page 1 … and the company's own common name"*
- `TEXAS INSTRUMENTS` — *"The LOGO WORDMARK, all caps: printed on page 1 and read verbatim by the vision pass"*

**Every one of tonight's three TI variants is a declared-correct reading of that
page.** And the block's `_rule` states the comparison rule outright:

> *"comparison is canonical-after-alias — a written string is mapped to its canonical
> form FIRST, and only canonical forms are compared. The set is CLOSED."*

**onsemi's `accepted` is `null`.** There is no accepted set; only the exact string
`onsemi` passes. And `ONSEM.` is a key in the **`not`** block:

> *"the LOGO's alt text, `[Image] ONSEM.` on pages 1 and 4; pages 2 and 3 render the
> same logo as `[Image] l onset l i.`. A garbled logo alt is a **failed read of a
> wordmark, not a reading of a name**: it is NOT the TYC case, where `TE Connecvity`
> is accepted because it is the printed name with one ligature dropped and still
> carries it."*

So: TI's variants are one value by a ruling already made. `ONSEM.` is not `onsemi`
by a ruling already made. **No single string transform can serve both** — and none
should have to.

## 4. The same gate already says "correct" and "disagreement" about the same strings

This is the part I would most like ruled on, because it is a contradiction inside one
report rather than a preference between two policies.

The **correctness** arm (`scripts/pcn_corpus_gate.py:895-925`) scores written headers
against ground truth through `pcn_score`, and blocks on `pcn_score.HEADER_FAILURES`:

```python
HEADER_FAILURES = ("distractor", "wrong", "misformatted", "unreadable", "absent", …)
# `alias` is a PASS and is deliberately absent from HEADER_FAILURES
```

An accepted non-canonical spelling scores `alias`, which is a **pass**. So all three
TI strings already pass the correctness arm. The written-agreement arm is the only
thing blocking them — on strings the same gate, in the same run, certifies as correct.

That arm's own code carries the precedent for the fix, in a comment about this exact
hazard:

> *"From the scorer, not a second copy: this was a hardcoded tuple of the same five
> statuses, so a failure class added to pcn_score would have been scored there and
> silently ignored HERE — a new way to fail that blocks nothing."*

The correctness arm already learned not to keep its own copy of the rule.
`_written_equality_key` is the copy that remains.

## 5. What it would take — the candidate, and its one real cost

**The candidate:** resolve each written value to its ground-truth canonical form
first, then compare the resolutions. `score_header_field` already returns exactly
what is needed:

| Status | Returns | Key becomes |
|---|---|---|
| `exact` | — (value *is* canonical) | the canonical form |
| `alias` | `canonical = expected` | the canonical form |
| `misformatted` | `canonical = expected` | the canonical form |
| `distractor` / `wrong` / `unreadable` | no `canonical` | **the raw string, unchanged** |

Applied to tonight's data:

- **TI:** exact → canonical; alias → canonical; alias → canonical. **One key. AGREE.**
- **onsemi:** `onsemi` → exact → canonical. `ONSEM.` → declared `distractor`, **no
  canonical, keeps its raw string.** **Two keys. DISAGREE — correctly.**

**No new table, no new vocabulary, no new dependency.** `import pcn_score` is already
at module scope in the gate (line 46); `accepted_forms` and `declared_distractors`
already exist; the `accepted` and `not` blocks already carry the rulings.

**The one real cost, stated plainly:** `compare_written_headers` cannot do this
today, because it is not given the ground truth. Its signature is
`compare_written_headers(from_corpus, expected=None)`, and at the call site (line
1685) `expected` is **a set of filenames** — the union of the corpus keys, used only
to compute `unrecorded`. Resolving needs the per-notice, per-field specs
(`gt["notices"][notice]["headers"][field]`). That is a plumbing change to the
signature and the call site, plus confirming the written arm's filename keys and the
scorer's notice keys are one namespace. It is not a one-line change to the key
function, and I am not going to describe it as one.

**The behavioural cost:** the written arm stops being measurable without ground
truth. Today it compares three fires to each other and needs nothing else; after
this it reads the same ground truth the correctness arm does. For a notice ground
truth says nothing about, there is no canonical form to resolve to and the arm must
fall back to the current fold. That fallback is where a future surprise would live.

## 6. Two prohibitions this must not be confused with

I checked both, because each reads at first glance like a standing rule against the
candidate. Neither is.

1. **`pcn_corpus_gate.py:763` — *"there is no alias table and none may be added."***
   This is about **field names** (`mfr`, `doc_id`, `pub_date`) being shared
   vocabulary between `witness_regions.py:83-88` and `pcn_ground_truth.json`. It
   forbids an alias table for *field names*. It says nothing about resolving field
   *values*, and the value-resolution ladder it does not govern is already in use by
   the correctness arm in the same file.

2. **The accepted set is CLOSED.** The candidate adds **no** spelling to any accepted
   set. It only consumes the sets as they stand. A spelling not listed stays `wrong`,
   and `wrong` keeps its raw string, so it still reads as a disagreement.

## 7. What the ruling decides

Tonight's verdict was `fail` on `mfr`, parts arm clean. Under the candidate:

- **TI's written disagreement clears** — for a declared reason, and it would have
  cleared on 2026-11-02 as well.
- **onsemi's written disagreement stays**, on `ONSEM.`, as ground truth requires.
- onsemi's **correctness** blocker stays regardless (fire 1 wrote a `distractor`), so
  onsemi still blocks on more than one condition. **The gate does not go green on
  this change** — one of four blockers clears.

So the options, as I see them:

- **(a)** Resolve through ground truth before comparing, and accept the plumbing and
  the no-ground-truth fallback. Makes the two arms agree; costs a signature change.
- **(b)** Widen `_written_equality_key`'s fold to collapse more (e.g. drop corporate
  suffixes). Cheap, and I recommend against it: it is a second hand-rolled copy of a
  rule ground truth already owns, it would need a suffix list nobody has ruled on,
  and it cannot express the `ONSEM.` refusal — a fold aggressive enough to unify
  `Texas Instruments Incorporated` with `TEXAS INSTRUMENTS` has no principled reason
  to keep `ONSEM.` apart from `onsemi`.
- **(c)** Leave it. The arm is then permanently red on a notice whose every observed
  spelling the same gate certifies as correct, and the red is sampling-dependent —
  it will come and go with the model, which is the worst property for a gate.

My recommendation is **(a)**. The decisive fact is that the comparison rule in (a) is
not a new policy: TI's `accepted._rule` already says *"a written string is mapped to
its canonical form FIRST, and only canonical forms are compared."* The written arm is
the one place in the gate that does not do that.

I have not implemented any of this. The question is yours to answer.

---

**Measured from the tree at `d708e58`**, `scripts/pcn_corpus_gate.py` and
`scripts/pcn_score.py`, plus the `ca3e7d83` fire of 2026-11-08 and the 2026-11-02
three-fire record. Variants quoted from the fire reports; rationales quoted verbatim
from `scripts/pcn_ground_truth.json`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
