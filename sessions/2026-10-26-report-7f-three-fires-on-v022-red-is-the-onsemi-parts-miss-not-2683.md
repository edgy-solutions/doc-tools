to: architect
cc: Chris, doc-tools/lane/tr
from: doc-tools/lane/7f
date: 2026-10-26
re: the three header fires on the v0.2.2 pin — FAIL, and NOT on 2683.
    I predicted the wrong row.

# The fires are red on the onsemi parts miss, not on 2683

Job `pcn-gate-v022-c056fa70`, three sequential fires on `sha256:c056fa70…`
(v0.2.2), 145 min wall clock. **Verdict FAIL.** Strict verdict (no
exemptions) also FAIL. Published to `corpus-gate/nightly` as `74c95a891b99`,
**PR #178**.

The gate confirms the roll from the inside: measured digest
`sha256:c056fa70…`, expectation `pods=…c056fa70…`, result **match**.

## Correction first: my "expected, #176 not in pin" framing named the wrong row

You instructed that each fire's report record its 2683 red as *"expected,
#176 not in pin"*. **2683 is not the red.** It did disagree, exactly as
predicted —

    Diodes_PCN_2683_Rev1_EOL.pdf | DISAGREE | doc_id: 'PCN-2683' | 'PCN-2683' | 'PCN #: 2683'

— and it was **EXEMPTED**, `needs_review=True in all three fires`, along with
TI and TYC. The header agreement arm blocked nothing at all. So the
instruction's purpose is served — nobody should read 2683 as a regression —
but the thing that actually failed is unrelated, and I should not have let my
prediction stand as the expected outcome.

## What is actually red

| fire | exit | elapsed | exact/gt | missing |
|---|---|---|---|---|
| 1 | **1** | 2750 s | **513/522** | **9** |
| 2 | 0 | 3108 s | 522/522 | 0 |
| 3 | 0 | 2985 s | 522/522 | 0 |

> Blocking — fire 1: `pcn_corpus_run.py` exited 1 — parts/crop-seal gate not
> met

One notice, one fire:

    onsemi_Generic_IPCN25300X.pdf   10/19   missing 9
      NSR02F30NXT5G NSR02L30NXT5G NSR05F20NXT5G NSR05F30NXT5G NSR05F40NXT5G
      NSR10F20NXT5G NSR10F30NXT5G SNSR01F30NXT5G SNSR05F40NXT5G

**It is a recall miss, not a crop-seal failure.** Every crop-seal gate term is
0 in all three fires (`repaired_cut_tables` 0, `errors` 0). The one asymmetry
is `crops_row_short f1=1 f2=0 f3=0`, and the report flags that itself:
*"FIRES DISAGREED on the same image in the same invocation. These rates are
NOT a property of the image; read the worst case."*

## This is NOT a v0.2.2 regression — it happened this morning on v0.2.1

I checked the outgoing authority report before calling this new. The 09:33Z
nightly, on v0.2.1 `sha256:086766d7…`, **failed the same way on the same
notice**:

| run | image | failing fire | onsemi exact/19 |
|---|---|---|---|
| 2026-10-26 09:33Z | v0.2.1 `086766d7` | fire **2** | **2**/19 |
| 2026-10-26 21:19Z | v0.2.2 `c056fa70` | fire **1** | **10**/19 |

Same document, a different fire each run, a different severity each run. That
is the signature of an intermittent extraction miss, and per the standing
ruling an intermittent cut can never earn the instability exemption.

**It also means the lane's recorded belief that "the parts gate is MET and
headers are the only blocker" is stale.** The parts gate was not met in
either of today's runs, and headers blocked in neither. Corrected in memory.

## The finding that bears on tonight's own work

`needs_review` moved from **3/4/3 of 10** (this morning, v0.2.1) to **10 of
10** (tonight, v0.2.2). This is not a defect — it is the documented, accepted
cost of your 2026-10-24 doc_id precedence ruling, and
`doc_tools/plugins/sustainment.py:1653-1665` says so in terms that predict
precisely this:

> `needs_review=True` is consumed by the corpus gate as an EXEMPTION. So every
> flag raised on an UNSCORED identity field can exempt a notice whose SCORED
> fields are wrong. Flagging doc_id disagreement therefore buys a human a look
> at the right thing and sells the gate a reason to stop looking. That trade is
> the architect's to make and is made.

What the measurement adds is the magnitude. The comment says such a flag *can*
exempt a notice; at 10 of 10 it exempts **every** notice. Three header
disagreements tonight, three exemptions, nothing left the arm can block.

**And that lands on #176, which merged tonight** (`b8a3dd0`, for the next
pin). Its written-value blocking arm routes disagreements through the same
`apply_declaration_rule` / `apply_blank_fire_rule` exemption on
`needs_review`. At a 100% flag rate, the arm you ordered for 2683 is inert the
day it ships: it will measure the written value correctly, find a
disagreement, and exempt it.

I am not changing either behaviour on my own read — the interaction is between
two of your rulings, so the resolution is yours. The options I can see:

1. The exemption keys on a flag **raised for the field under test**, rather
   than on any `needs_review` anywhere on the notice. A doc_id flag would then
   not exempt an `mfr` disagreement.
2. Identity-field flags stop conferring exemption at all, keeping the human
   signal while leaving the gate looking.
3. Accept it, and the header agreement arm is understood to be advisory in
   practice rather than blocking.

## Other things in the run, none of them blocking

- **Header correctness** 15/16, 15/16, **14/16** — fire 3 lost one. "Every
  established header field matched the page in every fire" still holds.
- **TYC** disagrees on `doc_level_ltb_date_source` with two truncated
  snippets: `'06-JUN-2024' | '-2024\n[Unca' | '-2024'`. The date itself is not
  in dispute; the source snippet is being cut.
- **Vision host 400s** (`Failed to load image or audio file`, client
  `VisionBounded`) on the `header_block` region in fire 1, with the plugin's
  retry after. Seen live in the pod; stdout echoes only the last 256 KB of
  each fire log, so a count is not recoverable from the published artifact.
- `text_layer_degraded` 3 of 10, unchanged from this morning.
- Identity: 10 filenames, 10 distinct notices, no collapses, nothing unstable
  on either half.

## What I am not doing without a ruling

Nothing is being re-fired. The onsemi miss wants a cause, and the obvious next
step is to put the two runs' logs for that notice side by side — the
9-missing and the 17-missing cases on byte-identical source. I have not done
that yet. It is a measurement, not a change, so say the word and it is the
next thing I pick up.

PR #178 carries the report. Per the standing finding, the nightly publisher
branch is never rebased, so that PR will conflict rather than merge.
