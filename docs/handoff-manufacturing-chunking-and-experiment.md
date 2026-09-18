# Handoff — Manufacturing: per-operation chunking, mock corpus, efficacy experiment

**Status:** measurement instruments built and validated; segmenter and experiment
runner not yet written.
**Branch:** `mfg-extraction-investigation` (unmerged, pushed).
**Read first:** `docs/manufacturing-extraction-findings.md` — the decision brief.

---

## What the corpus has already settled (do not re-litigate)

Nine real work instructions, extractor v0.5.0, measured — not assumed:

- **The LLM invents nothing.** 155 emitted values (31 standards, 66 parts, 58
  operations), grounding check reports **zero absent**. The `4500`
  "procedure_id pollution" hypothesis that drove weeks of this investigation is
  **dead** — that was a blind structural arm, not a model inventing things. This
  is a **recall** problem, not a fabrication problem.
- **One exception, and it is absolute:** `hazard_class` is fabricated in **3/3**
  cases — the document prints `1.1 -1.3`, the model emits `1.1D`, inventing the
  division letter. Recommend removing the field from the schema or marking it an
  unverified classification in the review UI. It must not be surfaced as an
  extraction.
- **No judgment-field starvation.** Three-state coverage shows `absent: 0`,
  `answered: 100%` on every judgment field of every document. The earlier
  "starvation" reading was an artifact of a two-state metric that conflated
  `False` with unanswered.
- **Recall gaps are enormous:** figures 1384 vs 0, standards 78 missed,
  operations 44 missed. One 238-page document: structural arm found **29**
  operations, the LLM found **4**.
- **Extraction is grossly unstable.** The same PDF across 8 runs produced
  `2, 2, 19, 19, 0, 2, 2, 2` parts. Same input, 0 to 19.

## The ordering that follows from that

1. **Diagnose the instability first.** A 0→19 swing on identical input cannot be
   prompt-engineered away, and any chunking A/B run against it is measuring
   noise. The `crops_empty_lost` guard on branch `fix/sustainment-empty-crops`
   (off `origin/main`) is built for exactly this: it counts crops that succeed
   and return nothing, which were previously invisible. **It is not deployed** —
   the sandbox pod runs the image from `main`. Merge + build before expecting it
   in a run.
2. **Move pattern/geometry fields to code.** Already proven: figures via the
   geometry binder (1384 vs 0), standards/parts via regex, `procedure_id`
   structurally. This removes most of the LLM's job.
3. **Then** per-operation chunking for what remains — judgment only.

## MEASURED 2026-09-17/18 — the instability, quantified (87 runs)

Step 1 of the ordering above is **done, and it confirms the ordering**. Overnight
run: 8 cells (2 fixtures × 2 assemblers × `--fix-figure-desc` on/off), ~11 repeats
each, 87 successful calls, 0 failures, `gpt-oss-128k:120b` on the cluster endpoint.
Driver, analyzer, raw responses and `results.jsonl` in `C:\tmp\mfg-overnight`
(`summarize.py` prints everything below).

**The harness is not stable enough to A/B against. 11 of 12 comparisons are
unreadable** — the effect is smaller than the run-to-run spread of the cells being
compared. Same fixture, same assembler, same prompt, same model, same endpoint:

| cell | metric | gt | min–max | range |
|---|---|---|---|---|
| WI / current / current-desc | figures | 9 | 0–8 | **8** |
| WI / current / current-desc | operations | 5 | 1–5 | **4** |
| WI / structured / FIXED | figures | 9 | 0–8 | **8** |
| WI-HARD / structured / current-desc | figures | 11 | 0–10 | **10** |
| WI-HARD / current / FIXED | steps | 18 | 18–31 | **13** |

`figures` swings the ENTIRE ground-truth range on identical input in three separate
cells. This is the 0→19 swing, reproduced and bounded.

**The one effect that survives its noise floor:** WI-HARD / `current` assembler,
`--fix-figure-desc` moves figures 0 → 8.27 mean against a noise floor of 3. That is
a real fix for the case where the baseline was a hard zero. Everywhere else the
figure-description change is indistinguishable from noise — including on the clean
fixture, where it *looked* like 0→8 on a single run.

### CORRECTION — most of the "instability" is one identifiable bug

The spread table above is accurate, but reading it as generic run-to-run noise is
wrong. Broken down by failure mode:

**The operation-id collapse is a page-furniture capture, not noise.** In 30% of
clean-fixture runs the model returned a single operation, `4500`. That is not
fabricated: the page header is `DWG-4500-01`, repeated on all 15 pages, and
`procedure_id`'s format is `^\d{4}$`, which `4500` satisfies. The real operation
numbers (`0010 0050 0100 0150 0200`) appear ONCE, in a table. The model takes the
token that matches the format and appears 16 times over the one that appears once.

**But repetition count does NOT explain when it fires, and removing the header is
the wrong fix.** Capture rate per cell, same document, same headers throughout:

| fixture | assembler | figure-desc | captured |
|---|---|---|---|
| WI | structured | current | **1/11** |
| WI | structured | FIXED | **9/11** |
| WI | current | current | 8/11 |
| WI | current | FIXED | 4/11 |
| WI-HARD | any | any | 0–2/11 |

Identical document content, identical page furniture: changing only the
`figure_references` description in the schema moves the capture rate from 1/11 to
9/11. The header is what gets *captured*, but what *triggers* the capture is prompt
and schema configuration. Deleting page furniture would be treating a symptom, and
the furniture is there deliberately — it gives the model context it otherwise
lacks. (`assemble_structured` also already emits `===== PAGE n =====` dividers, so
page position is carried independently of the header either way.)

The real conclusion is narrower and points at the existing plan: **`procedure_id`
should not be an LLM output at all.** Item 2 of the ordering — move pattern fields
to code — dissolves this defect as a side effect, because the operation numbers
live in a table and can be read structurally. That also makes item 3 safe: a
segmenter that derives operation boundaries IN CODE is immune to this capture,
whereas one that asked the model where operations begin would inherit it exactly.
That circularity is the reason the code-first ordering is load-bearing rather than
merely tidy.

**Exclude those runs and operation extraction is perfectly stable — range 0 in
every one of the 8 cells.** So operations are not unstable; they have one specific,
diagnosable, fixable defect. Candidate fixes, cheapest first: drop Header/Footer
elements before assembly rather than relabelling them; or source `procedure_id`
structurally from the operation table (already item 2 of the ordering above).

**Figures and step segmentation are genuinely variable**, and survive that
exclusion: `WI/structured/current-desc` still swings figures 0–8 and steps 25–30
across 10 clean runs.

**There is one fully stable configuration.** `WI / current assembler /
--fix-figure-desc`, excluding the capture runs (n=7): operations 5/5, steps 24/24,
figures 8/8 — range 0 on all three. A stable cell exists, which matters: it means
the variance is a property of particular configurations, not of the model per se.

### Two findings that are not about instability

1. **Three schema fields are never populated in ANY of the 87 runs, in any cell:**
   `estimated_duration_minutes`, `required_cert`, and — in 7 of 8 cells —
   `hazard_class`. `is_safety_critical` starves in 3 of 8 cells and never exceeds 7
   of ~25 steps elsewhere. Note this is a DIFFERENT failure from the real corpus,
   where `hazard_class` was recorded as fabricated 3/3: on the mock the model
   simply never emits it. Either way that field is not working.
2. **Operations are unstable on the CLEAN fixture and rock-solid on the HARD one** —
   the inverse of what difficulty predicts. WI-HARD holds 4/4 with range 0 in three
   of four cells; the clean WI swings 1–5 (range 4) in all four, with a mean as low
   as 2.09 against a ground truth of 5. Whatever destabilizes `procedure_id`
   grouping is a property of the clean fixture, not of document difficulty. **This
   is the concrete lead for step 1** — it is reproducible, cheap to re-run, and
   isolated to one fixture.

### What this does NOT say

Still the mock corpus, so still segmenter/harness logic only — it cannot say the
LLM is better or worse at the real task. But the instability it measures is the
harness's own, and that transfers: an A/B on the real corpus faces at least this
much noise.

## THE FIXTURES DO NOT MATCH THE REAL LAYOUT (2026-09-18, from the SME)

The real documents are: **a title page carrying one big procedure number, then that
procedure's step pages, then the next procedure's title page**, and so on.

The synthetic fixtures are not shaped like that. Operation boundaries are inline
`Title` elements sitting mid-page among narrative and images:

```
clean fixture:  p6  [Title] Operation 0010 - Kitting Instructions
                p8  [Title] Operation 0050 - Bracket Sub-Assembly
                p11 [Title] Operation 0100 - Final Integration
```

No dedicated title page exists anywhere in either fixture, and the clean fixture
additionally opens with a summary TABLE of all five operations that the real
documents may not have at all.

**Consequence: the mock corpus cannot validate a title-page segmenter, because it
contains no title pages.** The limit recorded above ("validates segmenter logic
only") is therefore too generous as it stands — it validates a segmenter for a
layout that is not the production one. Anything built against these fixtures and
keyed on page structure is being confirmed by a document shape that does not occur.

**DONE (`308f365`):** `make_synthetic_wi_reallayout.py` +
`synthetic_work_instruction_reallayout.json`. Added alongside the old fixtures, not
replacing them — the overnight measurements and the 8/9-vs-0/11 figure result are
pinned to those. 109 pages, 18 operations, 1550 elements, headings as
`UncategorizedText` at 0.58/page, 46% UncategorizedText overall, `REVISION: ####`
in every footer. `--verify` prints its shape against the corpus numbers.

It is verified to DISCRIMINATE between segmenter designs, which is the only reason
to keep a fixture like this — cross-references to other operations sit on the
heading-less pages, so:

```
naive page-text regex        73/109 pages correct
standalone OPERATION elem   109/109 pages correct
```

Ground truth carries `page_to_operation`, which the old fixtures cannot score at
all. **Caveat that does not go away:** this validates segmenter LOGIC against
measured SHAPE. It is still invented content, so it cannot say anything about
extraction quality.

### What the REAL corpus actually looks like (from `mfg_corpus_report2.json`)

Read out of `per_doc[].parse` — no cluster access needed, the report already carries
it:

| doc | pages | elements | structural ops | `OPERATION ####` | bare `####` | Title |
|---|---|---|---|---|---|---|
| doc_0000 | 108 | 1823 | 18 | 94 | 12 | 74 |
| doc_0001 | 106 | 1604 | 25 | 74 | 16 | 109 |
| doc_0002 | 238 | 4295 | 27 | 70 | 12 | 317 |
| doc_0003 | 280 | 5410 | 19 | 100 | 0 | 307 |
| doc_0004 | 3 | 29 | 0 | 0 | 0 | 5 |
| doc_0005 | 24 | 320 | 6 | 0 | 5 | 10 |

Four things follow, and each one invalidates something currently assumed:

1. **Scale.** Real documents are 100–280 pages with 18–27 operations. The fixtures
   are 15 and 9 pages with 5 and 4. A chunking decision tuned on a 15-page fixture
   is being tuned two orders of magnitude away from the target.
2. **Operation headings arrive as `UncategorizedText`, not `Title`.** The shape
   `OPERATION ####` appears 70–100 times per document under `UncategorizedText`;
   the fixtures encode operation boundaries as `Title` elements. **A segmenter
   keyed on `Title` finds nothing in production.** This is the single most
   important mismatch.
3. **The heading repeats — but NOT on every page, and the gap is large.** Measured
   `OPERATION ####` per page: doc_0000 **0.87**, doc_0001 **0.70**, doc_0002
   **0.29**, doc_0003 **0.36**, doc_0005 **0.00** (six operations, not one
   OPERATION line). So in half the corpus barely a third of pages declare their
   operation, and one document marks them some other way entirely.

   **A segmenter must CARRY FORWARD across silent pages** — it cannot ask each page
   which operation it belongs to, and it must not require a heading to start a run.
   doc_0005 additionally shows the heading cannot be the ONLY accepted marker; it
   has 5 bare `####` and no OPERATION lines. This is the thing
   `page_operation_sequence` needs to report per document, not as a single
   corpus-wide yes/no.
4. **The `4500` capture has a real analogue.** doc_0000's footer is
   `REVISION: #### (...)` on all 106 pages — a 4-digit token in page furniture,
   repeated document-wide, competing with the real operation numbers. The mock's
   failure mode is not a fixture artifact; it mirrors something production has.

Also note doc_0000 carries TWO operation notations at once: `OPERATION ####` in
body text and `OP ##` (two digits) inside `Title` elements. And doc_0003 has 100
`OPERATION ####` with ZERO bare `####`, so a standalone big-number title page is
not universal across the corpus — the SME-described layout is real but is not the
only one, and a segmenter must not assume it.

**Instrument hygiene:** both `mfg_corpus_report*.json` on disk are indented with
NON-BREAKING SPACES and do not parse with `json.load` (2643 and 5609 NBSPs;
`eval_draft.json` from July is clean). They were almost certainly captured by
pasting terminal output rather than written by the script. Next week's run should
be redirected to a file directly, or the analysis cannot be automated.

### The boundary signal must be the HEADING, not "an operation number on the page"

Already present in the hard fixture, page 3:

```
[Title]         Operation 0050 - Bracket Sub-Assembly
[NarrativeText] ... Check the Bracket for dents, cuts and scratches
                (see Op 0200 for inspection criteria) ...
```

Two operation numbers on one page, one of which is a CROSS-REFERENCE in running
text. A segmenter that regexes operation numbers out of page text assigns that page
to 0050 and 0200 both. A segmenter keyed on the title page — or failing that, on
the `Title` element specifically — is immune, because a cross-reference never
appears alone on a sparse page.

With the real layout the contiguity assumption behind `page_operation_sequence`
stops being an assumption: title page N to title page N+1 *defines* the run, so
every step page in between belongs to N by position. `procedure_id` is then
assigned structurally and is never an LLM output — which is exactly what removes
the `4500` capture documented above, without touching page furniture.

## Per-operation chunking: what is built, what is missing

**Built and validated:**
- `mfg_extractors.extract_operations_detailed()` — operations with element type
  and which pattern matched (provenance, so an over-matching rule names itself).
- `mfg_extractors.extract_operation_occurrences()` — **every** occurrence with
  page and element index. This is what spans need; the `_detailed` variant
  dedupes by id and is useless for segmentation.
- `mfg_corpus_report.page_operation_sequence()` — measures whether chunking is
  supportable at all: `contiguous`, `runs_out_of_order`, `front_burst_pages`,
  `coverage`, and `supported` as the conjunction.

**Not built:** `segment_operations()` — the thing that turns occurrences into
spans.

### The two traps it must survive (both observed in real documents)

1. **The ids repeat, heavily.** `OPERATION ####` appears 94/136/99 times per
   document because it is printed in the page footer of every page in that
   operation. Treating each match as a boundary yields 136 "sections" for 29
   operations. **The repetition is a gift**: it says which *page* belongs to
   which operation. The robust formulation is therefore *assign each page to an
   operation, then a section = a maximal run of consecutive pages*, not "find
   section starts".
2. **Route sheets list every operation up front.** WI documents open with a route
   sheet naming all operations, so naive first-occurrence logic puts every
   boundary on page 1. Currently protected only by luck — route sheets are
   `Table` elements and `title_types` excludes `Table`. Make that explicit.

**Fallback required:** one document has **no `OPERATION` in its footers at all**
(only `REVISION:`); its 18 operations came entirely from `UncategorizedText`.
Page-run assignment cannot work there — an element-position fallback is needed.

### Before building it, run the measurement

`page_operation_sequence` ships in the report now. On the next corpus run, read
`per_doc[].page_operation_sequence.supported`. If contiguity does not hold, or
`front_burst_pages > 0` across the corpus, the page-run design is wrong and
should be reconsidered rather than forced.

## The mock corpus — what it is and is NOT for

**It is for testing the segmenter's code**: does it collapse 136 repeated footer
matches into 29 sections, survive a route-sheet burst, fall back when footers
carry no operation, produce non-overlapping spans that cover the document. That
is deterministic; **no LLM involved**.

**It cannot test whether the LLM improves.** Fixture shape dominates the result —
measured: the clean synthetic fixture gave figures 8/9 and the hard one gave 0/11,
same model, same prompt, and the same author wrote both fixtures. If you invent
the step text and the model extracts it well, you have proven your prose is easy
to parse. **Do not let a mock decide an efficacy question.**

Build it from the real structural parameters, which are known and redaction-safe
(from the corpus reports): element histograms (`UncategorizedText` 833/658/1400/
2377, `Footer` 212/215/773/732), page counts (108/106/238/280/24/3), operation
counts (18/25/29/19/6/0), repetition rates (`OPERATION ####` ×94/136/99/16), and
the fact that one document has zero footer operations.

## The efficacy experiment (`mfg_experiment_runner.py`, not yet written)

The user's constraint: **test the model against the corpus without the agent
seeing the corpus.** The resolution is that *the measurement travels, the corpus
does not*.

**Scoring baseline — content-free.** Do not treat the script as truth (it missed
19 standards the LLM found). Use the **union of values either arm found that the
document corroborates** (grounding proves both arms real). Each arm then scores
as "recovered X of N reference values" — a fraction, never a value.

**Arms** (the 2×2 from the brief): `whole_fat` (today's baseline), `whole_thin`,
`perop_fat`, `perop_thin`.

**N runs per arm is non-negotiable** given 0→19 on identical input. It also pays a
bonus: if `whole` swings across runs and `perop` does not, the experiment
*measures the instability for free*.

**Division of labour:**
| what | where |
|---|---|
| debug arm assembly, chunking, parsing, token accounting | locally, same model (`gpt-oss-128k:120b` on the LAN), synthetic fixtures |
| the actual efficacy A/B | operator's side, real corpus, same model/context |
| reading the result | agent, from a redacted report |

Local model access is for **de-risking mechanics**, not measuring efficacy.

**Cost:** the operator has confirmed local compute is free and can run overnight,
so the full grid (9 docs × 4 arms × 5 runs ≈ 180 calls) is acceptable. Still make
`--docs/--arms/--runs` configurable and default to something smaller for the first
proving run.

## Free wins available now, no code required

`llm_only` is 18 standards + 55 parts, and their shapes are site-specific families
the committed config does not know:
- standards: `AAA-AAA-AAA-###` (7), `AA-#####` (4), `AAAAAA-####A`, `AAAAAAA-AAA##`
- parts: `###-###-###`, `#######-#`, `###J##`, `PA#####`, `SK#####`, `SD##-#####`

Add them to a copy of `examples/mfg_extractors.sample.yaml` and point
`MANUFACTURING_EXTRACTORS_SPEC` at it — each converts an `llm_only` miss into an
`agree`. The sample currently documents only a `standards` section; a
`part_numbers` section with these shapes should be added.

## Instrument hygiene — a real risk for the next session

Three fixes have now been made in one of the two report scripts and not carried to
the other (path-depth assumption, redaction defaults, document-name leakage).
`mfg_corpus_report.py` and `pdn_parts_diagnostic.py` have drifted into parallel
implementations of the same contract: artifact discovery, redaction, local-map,
stamping, source grouping. **Factor the shared discipline into one module both
import** before either grows further, so a fix lands once.
