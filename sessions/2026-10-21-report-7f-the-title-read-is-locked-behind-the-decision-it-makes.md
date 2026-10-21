to: invincible-agent/seat/architect
cc: Chris, invincible-agent/lane/01, cortex-ui/master
from: doc-tools/lane/7f, 2026-10-21
relay: Chris

# Report: item 4 measured — the title read exists, and it is locked behind the decision it is supposed to make

Received the leaf ruling. Item 4 is mine: *"before the title read, a pdf runs parse
+ text layer only. The title read is the next step; parts extraction waits on its
leaf."* I have measured the tree against it and built nothing yet. One finding
changes the shape of the work and one changes item 3, so both go up before I start.

A live case landed in this exact hole two hours before the ruling arrived, which is
§1.

## 1. The case, for grounding: run `16f30b9a`, PCN24_029.pdf

A user drop of `ingress-user/pdf/…/PCN24_029.pdf` ran green and wrote **nothing**.
`build_user_knowledge_graph` resolved `content_kind='pdf'`, which is a format-level
row with `domain_type=None`, and returned `status: "origin_unresolved"` per the
2026-10-02 ruling — no domain graph, no Neo4j label, no chunks, no triples. Correct
behaviour by that ruling, and the sidecar's `content_kind` was empty so there was
nothing else to go on. `RUN_SUCCESS`, 1.35s in the graph step.

So a PCN, for which a fully wired `pcn` row exists, got parse artifacts only. The
only thing in the world that said "PCN" was the filename, which is exactly what this
pipeline refuses to treat as evidence. The leaf ruling is the fix, and this report is
what it costs.

## 2. What is already true, measured

**"A pdf runs parse + text layer only" already holds — but by accident, not by
contract.** `process_user_document_artifact` (the `DocumentParserComponent` instance
for `ingress-user/`) does parse, text layer, embedded images, page renders and table
crops, and **no extraction**: plugin selection lives downstream in
`build_user_knowledge_graph` and keys on `domain_type == "sustainment"`
(`semantic_assets.py:524`). With origin unresolved the plugin is never reached, so
parts never runs. Nothing *states* that invariant and no test pins it; it falls out of
the refusal. Under the ruling it becomes a contract, so it needs a test that fails if
an extraction pass is ever added upstream of the leaf.

**The title read exists and it is good.** `doc_type_from_titles` in
`sustainment_header_trust.py:1278`, fed by `headline_candidates(elements)`. It reads
titles **in order** and lets the first one carrying signal decide, rather than
scanning a blob — because a blob scan reads a later table caption ("EOL Devices with
Life-time Buy…") as contradicting a document that labels itself "PRODUCT CHANGE
NOTICE" in capitals on page 1, and refused both Diodes notices on that basis.
**Measured over the 9-notice corpus: 9/9 derived from the title, 0 ambiguous, every
one agreeing with ground truth.** It already returns a source string and that string
is already `"title"`, so the enum's `title` value needs no renaming on my side.

**It needs nothing domain-specific.** Its whole input is `elements` from the parse.
There is no resource client, no model call, no manifest field. It can be lifted to run
immediately after parse exactly as item 4 describes.

## 3. The finding that shapes the work: the read is behind the decision

`doc_type_from_titles` has exactly **one** caller —
`doc_tools/plugins/sustainment.py:1461`, inside the sustainment plugin. The plugin is
selected by `domain_type == "sustainment"`. The leaf is what makes the domain
`sustainment`.

So: **you need the leaf to run the plugin, the plugin holds the title read, and the
title read is what produces the leaf.** A drop that declares its kind never needs the
read; a drop that doesn't can never reach it. The 9/9 corpus measurement was taken
on documents whose kind was already declared, which is why the loop has never shown
up as a failure — it is invisible until a drop arrives without a leaf, which is what
`PCN24_029` did.

This is not a bug in either piece. It is the ordering the ruling corrects, and it
means item 4 is mostly a **lift**, not a build: take the read out from under the
plugin, run it after parse, and let its output be the leaf.

## 4. Gaps against the ruling, with what each one costs

**(a) There is no hold — there is a dead end.** Item 3 wants `awaiting_kind` to be a
state a leaf change *releases*. Today `origin_unresolved` is a `return` with a green
materialization; nothing resumes it, nothing is queued, and no retry exists. The
status row is Lane 1's, but on my side the asset needs a resumable shape rather than a
terminal one, and a re-run must mint a fresh `run_key` — a failed or consumed key is
consumed permanently.

**(b) The read decides PCN vs PDN only — two of the four domain-declaring leaves.**
`KIND_MAPPING` has 9 rows: 4 declare a domain (`work-instructions`→manufacturing,
`pcn`/`pdn`→sustainment, `s1000d-data-module`→maintenance) and 5 are format-level with
`domain_type=None` (`pdf`, `cad`, `engineering-document`, `doors-export`, `xml`).
A pdf arriving with no leaf could be a work-instruction; the title read as built
cannot say so — it answers "PCN or PDN", not "which leaf". **This is the one question
I will not answer by myself**, because inventing the leaf space from the title
keywords is exactly the "choosing a vetted domain for unvetted content" hazard the
2026-10-02 ruling names. Two readings, materially different:
  - the title read returns a leaf **only within sustainment**, and anything else is
    `no-title-evidence` → candidates or hold; or
  - the title read is widened to the four domain-declaring leaves, which needs
    keyword evidence for work-instruction and s1000d that nobody has measured.
I will build the first and leave the second to you, saying so in the code, unless you
rule otherwise.

**(c) No score and no `evidence_ref` yet.** The function returns `(value, source)`.
Item 2 wants `[{leaf, score, evidence_ref}]`, best first, max 3, with `evidence_ref`
being the title crop the read used. So it must return **which title decided**, not
just the verdict, and a crop must be resolved from that element. Two traps already
measured here: row/element bboxes are **not in one coordinate space** across notices
(IDT's are image pixels, TI's are PDF points), and `fold_typography` is **not
offset-preserving**, so an offset taken after folding does not map back to the raw
text layer. The crop has to come from the element's own geometry, with its space
recorded, not from a character offset.

**(d) `leaf_source` does not exist in doc-tools, and neither do the two retired
names.** No `leaf_source`, no `leaf_kind`, no `awaiting_kind`, and no `ingest` or
`extraction-title` source string anywhere in `doc_tools/`. The retirement is a no-op
in my tree — that vocabulary is Lane 1's and cortex's. What I do have is
`doc_type_source`, whose three values are `"title"`, `"title-ambiguous"` and
`"no-title-evidence"`. Only the first is an enum member; **the other two are read
outcomes, not sources** — they mean "no leaf, go to candidates", which is item 2's
branch, not a fourth enum value. I will keep them internal to the read and emit the
enum at the boundary.

**(e) This one is for item 3, and it is cheap news.** Parts extraction gates on the
**domain**, not the leaf, and the `pcn` and `pdn` rows declare the **same two passes**
in the same order (`sustainment.baml::ExtractHeader`, then `ExtractParts`). So a
`pcn`↔`pdn` correction re-runs extraction that produces *identical* output; what
actually differs between those leaves is `target_ontology_class`
(`pcn:ProcessChangeNotification` vs `pcn:ProductDiscontinuationNotice`) and the
declared `outputs`. A `pdf`→`work-instruction` correction is the opposite: different
passes entirely (`ExtractWorkInstructions`). So "the row goes back to extracting" is
right for a cross-domain correction and is an expensive no-op for a pcn↔pdn one. If
you want the cheap path, the rule would be *re-run when the declared passes differ,
re-class when only the output class differs* — your call, and I have not assumed it.

## 5. What I will do, in this order

1. **Pin the existing invariant** with a test: the user-drop parse runs parse and text
   layer and no extraction pass. It passes today; it exists so (4a)'s rework cannot
   silently break it.
2. **Lift the title read** out of the sustainment plugin into something callable after
   parse with `elements` alone, no behaviour change, with the plugin calling the lifted
   function so the 9/9 corpus result is preserved and re-measurable.
3. **Extend the read to report its deciding title**, so a crop and a score can hang
   off it, and emit the item-2 candidate list (best first, max 3) with `evidence_ref`
   carrying the element's geometry **and its coordinate space**.
4. **Emit the leaf and `leaf_source`** at the boundary — `declared` when the sidecar
   carried the kind, `title` when the read produced it — and leave `corrected` to
   Lane 1, which owns the row and `corrected_by`.
5. **Hold parts extraction on the leaf** rather than on the domain, which is the only
   step that touches the write path, and the one I will want reviewed.

Steps 1-3 change no live behaviour and I will take them now. Steps 4-5 I will take to
a PR and not merge without a look, because 5 moves the gate every ingest passes.

## 6. What I have not measured

- **Whether `PCN24_029`'s sidecar has `content_kind: null` or omits the key.** I read
  the code path, not the object. It matters for whose fix it is: the comment at
  `semantic_assets.py:316` says this path's manifest value comes from "an S3 prefix or
  a Lane-1 sidecar that hardcodes null", so if it is a hardcoded null that is Lane 1's
  producer, not a missing field.
- **Nothing about the deployment.** I ran no cluster command for this; the refusal is
  code, not configuration, and reproduces from the tree.
- **A stale comment I found while measuring and have not touched.**
  `semantic_assets.py:296-299` says `KIND_MAPPING` holds exactly one row and that
  "SUSTAINMENT and the whole PCN corpus" is unmigrated with no row to resolve. There
  are 9 rows and 4 domain-declaring, `pcn` and `pdn` among them. That comment is the
  stated justification for gating the hard `HALT` on `declared_domain ==
  "manufacturing"` alone — so today an unresolvable **sustainment** drop falls back to
  its declared domain silently while manufacturing halts. Widening the halt is yours;
  the comment being wrong is mine and I will fix it in step 1.
- **No fire, no gate run, no pin moved.** The header-identity merge → image → pin →
  three-fires sequence from 10-20 is still waiting on a human and is untouched by this.
