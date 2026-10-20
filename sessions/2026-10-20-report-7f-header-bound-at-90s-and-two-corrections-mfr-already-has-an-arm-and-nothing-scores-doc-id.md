# 7f — the header call is bound at 90s and seeded; two corrections: mfr already has a text-layer arm, and nothing scores doc_id

to: the architect, via Chris
from: doc-tools/lane/7f
date: 2026-10-20 (cluster timestamps are UTC)

## Answer in one line

Items 2 and 3 are landed and green (`da7c1ee`). Item 1 splits in two once
measured: for **mfr the arm already exists** and fires exactly where the ruling
wants it, and for **doc_id it is net-new and the corpus gate cannot score it at
all**.

## 1. What landed — items 2 and 3 (`da7c1ee`)

| part of the ruling | what the code does now |
|---|---|
| bound at 90 s | the header pass reads **`HEADER_REQUEST_TIMEOUT_MS`, default `90000`** |
| never retry | **no change needed** — measured: one `ExtractHeader` call per notice per fire, there was never a retry |
| field absent on a cut | `needs_review=True` was already set; what was missing was the **doc_id absence**, below |
| a filename never reaches the identity triple | `build_identity` is now passed the claim, not the key |
| seed the call | `seed: 0` on the request |

**The bound got its own env key, and that is load-bearing.**
`LLM_REQUEST_TIMEOUT_MS` is read in three places and one of them is the
**vision** client. `charts/doc-tools/values-sandbox.yaml:1268-1277` sizes
`VISION_MAX_TOKENS: 8192` *against the 600 s default* — its own words: *"at the
measured 17-21 tok/s, 8192 tokens is ~400-480s against the 600s
LLM_REQUEST_TIMEOUT_MS default. Raising this much further trades a DETECTED
truncation for an undetected timeout."* So lowering the shared key to 90 s
would have converted a detected parts-pass truncation into an undetected
parts-pass timeout. The shared key and its default are untouched; 90 s applies
to the header pass only.

**90 s against the measurement:** healthy p100 **36 300 ms** (10-19, 15/15
calls, 19 274-36 300 ms), so 90 s is ~2.5x the healthy worst case. The cut
previously observed was 300 001-300 008 ms. Nine of those on 10-18 is ~2 700 s,
about a whole fire's runtime spent returning nothing; the same nine now cost
~810 s.

**The filename fix is two lines and no new concept.** `build_identity` already
refused to form a key on a falsy doc_id, and its docstring already said its
inputs are *"the raw values as extracted"* — the caller was handing it the
key-safe, **filename-seeded** `doc_id`. It now passes that value only when
`doc_id_extracted` is truthy. That field already existed (the 2026-10-17 display
clause): set before the key fallback, `None` on a cut. The **key fallback itself
stays** — `doc_id` is the workflow id, the MinIO prefix, the graph IRI and the
provenance index and must never be null. And `written_header` now reports doc_id
from the identity record, so a cut notice writes an **absence** where it used to
write a filename a consumer could not distinguish from a real notice number.

Proof that no key moved: the formed key was compared against
`notice_identity.py` loaded from `HEAD` — byte-identical
(`te connectivity␟pcn-2683␟a`). 49 tests pass in the written-header suite,
including a new one that fails if a filename ever reaches the written header
again.

## 2. CORRECTION to my 10-19 report — mfr already has a text-layer arm

I reported that implementing the ruling was net-new extraction code because no
text-layer extractor existed for `mfr`. **That was wrong, and the error was
mine**: I read the pipeline as refusals only and did not follow the cascade
inside the refusal.

`doc_tools/utils/sustainment_header_trust.py`:

- **`mfr_from_document(index)` (`:482`)** is a genuine text-layer extractor
  returning `(value, source)`, both the verbatim printed form. Its safety is
  **uniqueness, not shape**: candidates are grouped by `_name_key` and it
  succeeds only when every key is a prefix of the longest, so two unrelated
  names is a **refusal**, not a guess. It re-verifies its own answer through
  `provenance.resolve_value` so the value cannot be blanked by the next check.
- It is wired as **`_DOCUMENT_WINS = {"mfr": mfr_from_document}` (`:542`)**, with
  `recover_mfr_from_document` (`:260`) as a narrower contraction step ahead of
  it, and it is reached **including when the model returned nothing at all**.
  The reason string is literally *"header.mfr recovered: the header pass
  returned none; written from the document's own 'X'"*.
- That refusal call is **unguarded** by the header exception, so **on a 408 with
  a healthy text layer mfr is already written from the document today.**

So my line *"the trust pipeline fixes precision, never recall"* is **false for
mfr** — `_DOCUMENT_WINS` fixes recall too. It stays true for `doc_id`,
`pub_date` and `revision`. The accurate description of today's mfr: **the model
only nominates, and the text layer adjudicates.** `mfr_from_document`'s own
docstring states the policy — *"a model value the document prints verbatim is
already the document's answer and stands untouched."*

**And the degraded gate the ruling needs is already there:**
`document_wins = None if text_layer_degraded else _DOCUMENT_WINS.get(field)`.
A damaged layer cannot be trusted to SPELL a name — TYC prints `TE Connecvity` —
so on a degraded document the region witness supplies the value instead. A
text-layer-primary mfr arm that ignored this would write the misspelling into
the graph.

**Consequence for item 1:** for mfr there is nothing to build. The ruling is
already implemented, one layer deeper than I looked.

## 3. The measurement that changes the pin condition — nothing scores doc_id

Walking `scripts/pcn_ground_truth.json`: header ground truth exists for
**three** of the ten notices, with **three** fields each.

| notice | mfr | pub_date | doc_level_ltb_date |
|---|---|---|---|
| TYC | `TE Connectivity` | `2024-06-07` (not `2024-06-10`, the print stamp) | `2024-06-06` |
| TI | `Texas Instruments Incorporated` | `2021-03-25` | **`expect_absent`** |
| IDT | `Integrated Device Technology, Inc.` | `2019-10-14` | `2020-01-15` |

**3 x 3 = the 9.** So "headers 7/9" is **9 fields over 3 documents**, not 9
notices — and lane 01's *"your fire 2 scored 5 of 9 headers"* is 5 of 9 fields.
One bad notice costs up to 3.

**There is no `doc_id` expectation and no `revision` expectation anywhere** (a
whole-file scan: zero `doc_id` keys). Two consequences, and they bear directly
on the ruling:

1. **A corpus-gate run cannot validate any doc_id work** — not the text-layer
   arm, not the filename refusal, not the identity triple. A green gate would
   say nothing about it. Unit tests are the only proof it can have, which is how
   I have specified it.
2. **The three-fire pin condition therefore measures mfr / pub_date / ltb on
   three notices.** The single remaining blocker there is **TYC**, and both of
   its failures sit in **fire 3 — the only fire with the vision 408**:

| fire | mfr | pub_date | vision 408 |
|---|---|---|---|
| 1 | exact `TE Connectivity` | exact `2024-06-07` | no |
| 2 | exact `TE Connectivity` | exact `2024-06-07` | no |
| 3 | **absent** | **distractor `2024-06-10`** | **yes, page 2** |

TYC's text layer is degraded, so `_DOCUMENT_WINS` is correctly off and the
region witness is the only arm that reads it right — and that witness is the
voided-page-2 408 the ruling says **stays as is**. So *"pin after the corpus
gate reads green on three fires"* is, as the corpus stands, **gated on a vision
timeout not recurring**, not on the header work. Two of three fires were
already green on TYC. **I have not changed that path and will not without a
ruling.**

## 4. What a three-fire run needs that I cannot do alone tonight

The gate scores **the pinned image, not the working tree**. CI builds on a PR to
`main`, and a build on a PR **pushes no image** (it is gated on `event_name`).
So the real sequence for measuring `da7c1ee` is:

**merge to `main` -> image built and pushed -> pin the chart -> three fires ->
read the verdict.**

That makes "three fires, pin when green" an ordering question rather than a
blocker: the pin has to move **before** the fires can measure the code, and a
pin PR's own gate verdict reads RED on report age in the meantime, which is
normal and not a finding. **Chris is asleep; I have not merged anything.** Say
the word and I will take it in that order.

## 5. Lane 01's window data, and one discrepancy worth naming

Their packet (10-20 00:12Z) gives the fleet window: LLM slow 10-18
05:06-06:56, an engine-a retry loop feeding timed-out calls until ~08:43, no
node pressure, no OOM, no eviction — the slowness was on the GPU host. My
gate's three 10-18 fires ran 07:00-11:25, i.e. **inside and just after** that
window, which attributes the 300 s cuts to the cluster rather than to this
repo's code. They will no longer start a roll between 07:00Z and the gate's
last fire.

**The discrepancy:** they name the five absent from header agreement on 10-18 as
**ADI, Diodes 2683, EOL-36, IDT, TI**; I measured the `ExtractHeader` timeouts
on **PCN24-029 (3/3), IPCN25300X (3/3), TI (2/3), IDT (1/3)**. Only TI and IDT
appear in both. So **absence from the agreement table is not the same event as a
header timeout** for at least three of those notices, and the known instrument
defect is the likelier cause of the other three (the agreement check reads the
fire **logs**, not `corpus_f{n}.json`, and the echo caps at 262 144 B of a
~440 KB log). That instrument fix is still on the list; until it lands, an
ABSENT row means "not visible in the echoed window", not "not measured".

## 6. Where item 1 stands

- **mfr:** nothing to build (section 2). I will add a regression test that pins
  the behaviour the ruling demands — a cut header with a healthy text layer
  writes the document's own mfr — so a later refactor cannot quietly remove it.
- **doc_id:** net-new, specified, and in progress as a `doc_id_from_document`
  extractor built on `mfr_from_document`'s shape — uniqueness as the safety,
  self-verification through `provenance.resolve_value`, a mandatory
  `PCN|PDN|PTN|EOL` code token so a bare number is never a claim, label-echo
  rejection for the measured `PCN #: 2683` trap, and **gated off on
  `text_layer_degraded`** like mfr. It is deliberately **not** registered in
  `HEADER_SOURCED_FIELDS` yet: the model emits no `doc_id_source` at all, so
  registering it would refuse and re-derive every doc_id in the corpus in one
  unmeasured step.

  **My first shape rule for it was wrong, and it was caught before any code
  existed.** Measured against the 11 doc_ids the corpus has actually written
  (`FPCN26191XA`, `IPCN25300X`, `PCN20250409000.1`, `PDN 23_0120`,
  `PTN-DD-026-2023-REV-0`, ...), it failed two ways. It **missed 5 of the 10
  code-bearing forms**, because a word boundary after the code token cannot
  match a glued `PCN20250409000.1` and a hyphen was neither a legal separator
  nor a legal first character — so the real printed `PCN-2683` (Diodes),
  `PCN-36` (EOL-36) and `PCN-24-210412` (TYC) were all invisible to it. Worse,
  case-insensitive matching with a two-character value made **any two-letter
  prose word a notice number**: on TYC line 8 verbatim it wrote **`PCN Date`**
  as the doc_id while the real `PCN-24-210412` printed in the same run did not
  match. Nothing downstream would have caught that — the fragment *is* printed
  on the page, so the sourcing check passes it. It also **silently disarmed the
  uniqueness safety**: a second number that never becomes a candidate cannot
  disagree with the first, so the refusal never fires.

  Both defects are now ruled and the replacement rule is measured 15/15 against
  the same forms — every real doc_id reads, every prose fragment refuses, TYC
  yields only the real number, and the two-key refusal fires on its merits. Two
  things worth carrying out of this: **a fabricated doc_id is strictly worse
  than an absent one** here, because section 3 means nothing would ever score
  it; and the colon is now excluded from the separator set, so the
  `PCN #: 2683` label echo produces *no candidate* rather than one a later
  filter has to catch.
- **pub_date / revision:** out of scope. The current ruling names mfr and doc_id,
  and TYC shows why a text-layer date arm is the riskiest of the set — its
  distractor `2024-06-10` **is** printed on the page, as the portal's print
  stamp, so sourcing cannot separate it from the issue date.

## 7. What I did not measure

- **Which layer imposes the old 300 s.** Still unprobed. The 90 s bound is now
  the lower one, so the question is no longer load-bearing for the fire budget —
  but it also means the 600 s `AbortController` has still never bitten, so
  whether it works at all remains untested.
- **Whether the 90 s bound changes the cut count on a slow endpoint.** It must,
  arithmetically (a 300 s call becomes a 90 s refusal), but no fire has run on
  this code.
- **doc_id behaviour on the real corpus.** Unscored by construction (section 3),
  so I will instrument what the new arm extracts per notice rather than claim it
  from a green gate.
