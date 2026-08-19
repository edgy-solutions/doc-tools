# Manufacturing WI Extraction — Findings & Decision Brief

**Audience:** a reviewing agent deciding the path forward.
**Status:** investigation + reproduction complete; no production code changed yet.
**Note on sources:** all findings below come from *our own* synthetic fixtures and a
local model. No proprietary document, no third-party/reviewer prompt, and no
proprietary overlay content is reproduced here or in any artifact. Techniques
referenced (concern-decomposed extraction, deterministic pre-extraction) are
general engineering concepts.

---

## 1. The problem

The manufacturing plugin extracts `ManufacturingStep[]` from a work instruction (WI)
via a single BAML call (`ExtractWorkInstructions`) whose per-step schema is ~18 base
fields (`baml_src/manufacturing.baml`) plus runtime-injected proprietary overlay
fields (`MANUFACTURING_OVERLAY_SPEC`). Model: `gpt-oss-128k:120b` (Ollama locally;
vLLM at the work site). The whole document is fed in one call (confirmed — not a
chunking problem).

Reported symptoms:
- `figure_references` comes back **empty for every step** at the work site, even
  though the `[FIGURE: <file>]` markers are present in the text and the prompt asks
  for them.
- Many fields (overlay fields, and even safety fields) come back **empty**.
- Concerns about step under-extraction and procedure mis-numbering.

## 2. What we built (reproduction harness — all synthetic, non-proprietary)

- **Synthetic fixtures** mirroring the *form* of a real route-sheet WI (repeated
  per-page header/footer furniture incl. a document number, page-number-in-footer,
  4-digit operations, prose/bullet steps with no explicit step ids, tables with
  `text_as_html`, inline `[FIGURE:]` markers). Two variants:
  - **clean**: figures adjacent to the step they illustrate.
  - **hard**: figures *stranded* from steps by OCR-fragment callouts + page breaks;
    lopsided operations (one big op, several tiny) — matches real docs.
  - Emitted as unstructured-style element dicts (type, page_number, coordinates,
    image_path, text_as_html) with a ground-truth count file.
- **Harness** (`scripts/repro_manufacturing_extraction.py`, stdlib only): mirrors the
  production request (real committed prompt + a schema mirroring `manufacturing.baml`,
  incl. the exact current `figure_references` description), whole-doc, one call.
  Instruments: steps vs GT, operations vs GT, figure refs (**actual values +
  resolvable-filename count**), and **per-field fill-rate**. Flags: assembly variant
  (`current` vs a structure-preserving `structured`), `--overlay-fields N`,
  `--fix-figure-desc`, `--fixture clean|hard`.

Artifacts (repo, synthetic): `tests/fixtures/manufacturing/make_synthetic_wi.py`,
`make_synthetic_wi_hard.py` (+ generated `.json`/`.groundtruth.json`),
`scripts/repro_manufacturing_extraction.py`.

## 3. Measured findings (gpt-oss-128k:120b, whole doc, temperature 0)

1. **Figures: the failure is figure→step ADJACENCY, not overload/prompt/context.**
   - clean fixture (adjacent): **8/9** resolvable filenames extracted.
   - hard fixture (stranded): **0/11** resolvable — deterministic collapse to empty.
   - Held with the figure instruction present, overlay off, whole doc in context.
   - Conclusion: the model cannot reliably bind a `[FIGURE:]` marker to a step when
     they are separated by fragment text / page breaks. Reproduces the work symptom.

2. **Field starvation under a fat per-step schema.**
   - 18 base fields, no overlay: `is_safety_critical`, `hazard_class`,
     `required_cert`, `estimated_duration_minutes` all **0/21**; `figure_references`
     ~5%. The model fills a ~6-field "spine" (procedure_id, step_id,
     instruction_text, action_verb, process_category, justification) at 100% and
     starves the tail — *including safety fields*.
   - +12 overlay fields (30 total): more fields at 0% — reproduces "most overlay
     fields not filled."

3. **`procedure_id` header-furniture pollution — INTERMITTENT.**
   - In some runs every step is mis-assigned to `4500` (grabbed from a repeated
     document number like `DWG-4500-01` in the page header); in other runs the true
     operation numbers come out correct. Non-deterministic even at temp 0 (MoE).
     **Single-run A/B is unreliable here — needs N-run measurement.**

4. **Output size is driven by verbatim `instruction_text` echo**, not by the model
   "running out of room." A fully-populated answer for ~24 steps × 30 fields was
   ~7,500 tokens. High completion-token counts do not imply truncation.
   Caveat: token accounting differs by backend — Ollama excludes reasoning tokens
   from `completion_tokens`; vLLM may include them (unverified at the work site).

5. **A structure-preserving assembly** (inject `===== PAGE n =====` markers, tag
   element types, collapse repeated header/footer furniture instead of inlining it)
   cut input tokens ~30% and was faster; it fixed `procedure_id` in one run but that
   did **not** replicate (see #3) — promising but unproven.

## 4. Root-cause synthesis

- **Task shape is the core issue.** One fat per-step object entangling ~18–30 fields
  (mostly null on any given step) forces the model to satisfice: fill a spine, drop
  the tail. Verbatim `instruction_text` echo inflates output. Figure→step binding is
  a *relationship* task the model can't do when markers are stranded.
- **Most fields are pattern/lookup/geometry, not judgment.** Candidates for
  deterministic (code) extraction, with rationale:
  - standards / MP docs — **regex + normalization** (the prompt literally specifies
    the normalization regex; asking a 120B to do it is wasteful and lower-recall)
  - internal part numbers — **regex**
  - `figure_references` — **geometry / reading-order binding** (page_number +
    coordinates already on every element)
  - `procedure_id` — **structural** (which operation section the step falls under)
  - `estimated_duration_minutes`, `hazard_class` — **regex / small lexicon**
  - `material_and_hardware_slang` — **gazetteer**
  - Genuine-LLM (keep): `is_value_added`, `is_safety_critical`, `process_category`,
    step segmentation, and disambiguating genuinely-ambiguous relationships.

## 5. Recommended direction (hybrid, decomposed)

Mirrors the *sustainment* plugin's proven pattern (deterministic tier → bounded LLM
tier → reconcile in code → review lane). The **generic artifact is the pipeline
shape** — deterministic tier → concern-decomposed thin LLM passes → join in code →
reconcile → review lane — instantiated by any plugin. The **per-domain parts** (which
fields are pattern vs judgment, which gazetteer, which geometry rule) are plugin
*data*, exactly like the sustainment disposition rules. Field-level genericity ("one
extractor for all domains") is the wrong abstraction; two plugins sharing a spine
with domain-specific config is the right one.

1. **Deterministic layer** fills the pattern/geometry fields (standards, part numbers,
   figure→step binding, procedure_id, durations, hazard, slang). High recall,
   verifiable, free. **Add these back deterministically when missing from LLM output.**
2. **Decompose the LLM ask by CONCERN into thin, content-only passes** rather than one
   fat per-step object — each keyed by operation number; **join in code**. Thin rows
   remove the sparse-schema starvation; one concern per pass gives high recall.
3. **Chunk by STRUCTURE (per operation) + a shared context header — required for the
   large-doc tail, not optional.** Most WIs fit whole-doc at `LLM_NUM_CTX=128k`, but
   the char-chunker still fires above `max_chars = (128000-4000)*3 ≈ 372k chars`
   (~100+ pages): a 122-page WI splits into 2 char-boundary chunks with ~37k overlap
   (confirmed in production — "two prompts"). That split is doubly bad: (a) the
   boundary lands mid-operation and the **tail chunk loses all front-matter** (parts
   list, general notes, operation structure), and (b) it reserves only 4000 tokens for
   output while verbatim-echo output ≈ input, so each chunk can hit the window ceiling
   and truncate. Structural chunking + shared context header fixes both; dropping the
   `instruction_text` echo (§4) relaxes the output-budget half.
   NOTE: the deterministic layer (§5.1) runs over the WHOLE element list *before* any
   LLM split, so standards/parts/figures keep full recall on large docs regardless of
   how the LLM text is chunked — a free robustness win.
4. **Enumerate-then-enrich** for the genuine judgment fields: small schema per
   call → reliable fill.
5. **Reconcile deterministic + LLM in code; conflicts and gaps → review lane**
   (`needs_review`), never silent null. This is what answers the "can a regex reflect
   the corpus?" worry: a miss is not lost data, it is a `needs_review` row. That
   converts trust into a *measured per-field number with a fallback lane*
   (honest-degradation applied to extraction).

### Two design riders (from this project's scars)

- **Global-context extraction is a new silent-failure surface.** If the deterministic
  pass mis-reads the document number or revision, every chunk inherits the error
  confidently (definition-clobber shape). So the global header the assembler builds is
  an **extracted artifact with its own fill-report in the review lane**, not invisible
  plumbing.
- **Chunking creates a join, and the join key is `procedure_id` — the flakiest field.**
  This is an argument *for* structural chunking: per-operation chunking makes
  `procedure_id` **positional** (the chunk boundary asserts the operation) instead of
  extracted, which kills the `4500` pollution *by construction* rather than measuring
  it. Predicted side-benefit: in the structural arms, `4500` pollution → 0. The N-run
  test should confirm this. (SPO instinct: don't ask the model for what the document's
  structure already asserts.)

## 6. Operating constraint — the corpus is NOT agent-accessible

The reviewing/implementing agent can build the **instrument** but cannot see the
**population** (the real WIs). Same shape as the work cluster: the user is the only
bridge. Design consequences:

- **Fixtures are the hypothesis, the corpus run is the read.** Guard against
  *fixture-fit dressed as corpus-fit* — the clean/hard split already moved figures
  8/9 → 0/11, i.e. **fixture shape dominates the score**; whoever writes the fixture
  decides it. Synthetic 11/11 is necessary, never sufficient.
- **Build a corpus runner that separates instrument from population.** Input: a
  directory of real documents. Output: a report **reviewable without the documents** —
  per-field fill-rate, recall against spot-expectations where they exist, and an
  **anomaly/disagreement file**: every place the deterministic layer produced nothing,
  produced something the LLM contradicted, or hit a pattern near-miss
  (matched-but-malformed, marker-with-no-resolvable-target). Report shows counts,
  field names, and **pattern-shaped examples with values elided/redacted** so the
  agent consumes results without ever seeing inputs. Stamp each run (extractor
  version, corpus slice, doc count, timestamp).
- **The anomaly file is the product of the first run, not the recall number.** First
  corpus recall is whatever it is; the anomalies tell the agent how the real corpus
  differs from the fixtures. Each anomaly class becomes either a new fixture variant
  (the corpus teaches the fixture set) or a real extractor fix. Two or three loops and
  the fixtures converge toward the corpus without the corpus leaving the user's side.
- **Cheap expectations.** For ~5 real docs the user spot-annotates only the *contested*
  fields (figure count, operation numbers) — not full ground truth. Five docs with
  figure-count expectations validate the geometry binder against reality in ~10 min.
- **Acceptance criterion shifts** from "11/11 on the hard fixture" to
  **"N% on the corpus, with every miss in the review lane rather than silent."** A
  pattern that misses 10% with 100% of misses flagged is shippable; one that misses
  2% silently is not.

## 7. Experiment matrix (same fixtures, N-run discipline)

A clean 2×2 — assembly/scope × schema shape — plus the deterministic-layer check:

| arm | scope | schema | tests |
|---|---|---|---|
| **Current** | whole doc | fat per-step | baseline (already measured) |
| **Decomposed** | whole doc | thin concern-passes | the brief's main bet |
| **Structural** | per-procedure chunk + deterministic global header | fat | scope-narrowing isolated |
| **Both** | per-procedure | thin | likely winner if 2 & 3 each help |

- Answers the open question "how much gain is decomposition alone (2 vs 1) vs
  scope-narrowing alone (3 vs 1)"; if 4 ≈ 2, decomposition did all the work.
- **Structural arms predict `procedure_id` pollution → 0 by construction** (rider #2);
  the N-run procedure_id measurement confirms or falsifies it.
- Run **N≈5×** per arm — the `procedure_id` effect is stochastic; single runs mislead.

**Deterministic-layer measurement (gate for shipping §9-B):** add regex
standards/part-number extractors + a geometry figure-binder to the harness; confirm
standards ~100% and figures **11/11** on the hard fixture *as the synthetic gate*, then
the corpus runner (with elided report) as the real gate.

All of the above runs locally against `gpt-oss-128k:120b` on synthetic fixtures + the
user-run corpus pass — no production change, no proprietary data in agent hands.

## 8. Open questions for the decision

- How much of the gain is decomposition (arm 2) vs scope-narrowing (arm 3)? (Matrix.)
- Is structural `procedure_id` derivation reliable across WI templates? (Structural
  arm + N-run; also depends on how cleanly operation headings segment real docs.)
- Which overlay fields are pattern vs judgment? (Depends on the proprietary overlay
  spec — needs the field list to classify; user-side.)
- vLLM reasoning-token accounting at the work site — does it inflate output / eat the
  answer budget? (Quick check on the serving config; user-side.)

## 9. Decision

**B then A**, with riders:

- **Large-doc chunking is an ACTIVE defect (corrected).** `LLM_NUM_CTX=128k` is
  confirmed set, so most docs run whole — but the char-chunker still splits docs above
  ~372k chars (~100+ pages) at an arbitrary char boundary, dropping front-matter from
  the tail chunk and under-reserving output (4000 tokens vs output≈input). The
  122-page doc that submits "two prompts" is this. Structural chunking + shared header
  (§5.3) is therefore required for the large-doc tail, and is the natural test case for
  experiment arms 3/4 (§7) — needs a large synthetic fixture that crosses the 372k
  threshold so the split actually triggers.
- **B — ship the two cheapest, highest-confidence wins first:** (i) deterministic
  standards/part-number/figure extraction added back post-LLM; (ii) structure-
  preserving assembly + furniture collapse. Gate on the deterministic-layer synthetic
  numbers **and** a corpus run whose anomaly file is reviewed.
- **A — then prototype the full hybrid** (deterministic layer + concern-decomposed
  passes + reconcile/review), gated by the §7 matrix (N-run) quantifying the payoff.
- Do **not** treat the four experiments as a formality — especially the N-run
  `procedure_id` measurement, because §3.5 is honest that the assembler fix did not
  replicate; shipping an unproven single-run win is the "stable at n=3" lesson with a
  paper trail.

## 10. Artifacts & housekeeping

- Synthetic, verified clean of proprietary tokens: `make_synthetic_wi.py`,
  `make_synthetic_wi_hard.py` (+ generated json), `scripts/repro_manufacturing_extraction.py`.
- **Recommendation:** commit this brief to `docs/` in `doc-tools` (it is a decision
  document another agent consumes, verified proprietary-clean) and land the fixtures +
  harness in-tree with the corpus runner — instruments belong in source control with
  their stamp axes. (Transient `_repro_response_*.json` outputs should be gitignored.)
