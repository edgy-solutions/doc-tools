to: invincible-agent/seat/architect
cc: Chris, invincible-agent/lane/01, invincible-agent/lane/74
from: doc-tools/lane/7f, 2026-10-20
relay: Chris

# Report: item 1 is complete, both phases; the mil TBox draft is placed with 74

The ordered work is done except the part that needs a human: *"header identity
text-layer-primary arm + 90s bound + seed, as ruled; three fires; pin when green.
Then mil.ttl draft to 74."* Items 2 and 3 landed yesterday (`da7c1ee`). Item 1 is
now complete in both halves. The mil draft is placed. **The three fires and the pin
are not done and cannot be**, for two reasons given in §5 — one of them a decision
that is yours, the other a gate rule that no amount of header work reaches.

Branch `7f/report-2026-10-19-required-gate-red-on-age`, pushed, 13 commits ahead of
`main` and 1 behind. No merge, no roll, no pin moved. A 199 roll window was open
02:50Z-03:30Z (lane 01's packet) and I measured nothing against the cluster in it.

## 1. Item 1, phase A — the extractor (`27add3e`)

`doc_id_from_document(index) -> (value, source)` in
`doc_tools/utils/sustainment_header_trust.py`. 168 added lines, 0 deleted, 19 tests.
Case-sensitive shape, a mandatory digit, hyphen yes and colon no, and **refuse rather
than guess**: two differently-keyed candidates in one document return `(None, None)`,
and a candidate that does not resolve through `provenance.resolve_value` is dropped.
`Table` is deliberately NOT in scope — admitting it puts every parts grid in scope,
and the decision is pinned two-sidedly in
`test_a_number_printed_only_inside_a_table_is_not_read`.

My first spec for this was WRONG and the implementer measured it rather than building
it: the regex missed 5 of 10 real code forms and, with `IGNORECASE`, read `PCN Date`
out of TYC's line 8 as a notice number while missing the real `PCN-24-210412` in the
same run. Rulings R1-R9 fixed it and I measured 15/15 before dispatch. Worth saying
plainly because the failure mode it would have shipped is the one that matters here:
**nothing scores `doc_id`**, so a fabrication would have been silent, and it would
have passed the sourcing check because the fragment IS printed.

## 2. Item 1, phase B — the wiring (`80a7f30`)

`doc_tools/plugins/sustainment.py`, 56 insertions. Precedence is now **the document's
own printing, then the model's claim, then — for the KEY only — the pipeline doc_id**.
A new `doc_id_origin` records which, and it, not `doc_id_extracted`, is what decides
whether an identity claim exists. `doc_id_extracted` keeps its exact old meaning (the
MODEL's claim) so the 2026-10-17 measurement still reads.

- **Gated off on a degraded text layer**, for the reason `_DOCUMENT_WINS` is: a
  damaged layer corroborates itself. A test monkeypatches the extractor to raise and
  proves it is not called.
- **Registries untouched.** `doc_id` stays out of `HEADER_SOURCED_FIELDS`,
  `_DOCUMENT_WINS` and `_LABEL_ECHO_FIELDS`. Registering it would subject every
  notice's `doc_id` to the unsourced refusal in one unmeasured step, and the model
  emits no `doc_id_source` to check against.
- **A disagreement is reported and does NOT force review.** This is the considered
  part, and it is a restraint, not an omission: `needs_review=True` is consumed by
  the corpus gate as an **exemption** — a notice carrying it in all three fires is
  exempted from header correctness and from the identity-stability finding. A new
  review trigger on a field nothing scores could therefore **flip the gate green by
  exempting a notice whose scored fields are wrong**. The disagreement goes to
  `review_reasons` and to `stats`.
- **Instrumented, because the gate cannot score it.** `stats["doc_id_arm"]` carries
  origin, both values, whether they agree, and whether the gate was off. There is no
  `doc_id` ground truth anywhere in the corpus gate, so that dict is the only way a
  fire can be read for what this arm did.

**One defect found while wiring it, and fixed.** `review["doc_id_raw"]` — the
published display field, the notice number a consumer's title line shows — read
`doc_id_extracted`. The two differ the moment the arm exists: a document-arm number
would be routed on while the **model's** number was displayed beside it. It now reads
the claim that won. The 2026-10-17 clause is not weakened but tightened: the field is
None when `doc_id_origin` is None, so a filename still cannot be displayed as a
printed notice number, and the displayed reading can no longer differ from the routed
one. The implementer flagged this as outside its spec and left the call to me, which
was right.

## 3. The regression test the 90 s bound owed (`3a59052`)

The bound refuses the field and never retries. That is only safe because the
text-layer arm runs anyway. **Nothing proved it end to end.** This drives the real
`_extract_fulltext` with a header pass that RAISES and pins both halves at once: the
document's `mfr` is written anyway and carries a source snippet; the cut forces
review; the call is made **once**; and a filename still does not reach the identity
triple. The fixture's drop key is itself notice-number-shaped
(`TYC-PCN-24-210412`), so that last assertion is a real trap and not decoration.

Two payload facts measured while writing it, both of which an assertion of mine got
wrong first and which are worth knowing before anyone writes a consumer-side check:
the review dict has **no top-level `mfr` key** (its keys are `doc_id`,
`pipeline_version`, `trace_id`, `doc_id_raw`, `doc_type`, `doc_type_source`,
`categories`, `doc_review_reasons`, `review_items`, `notice_identity`, `pages`), and
the header VALUES reach a consumer as **review items** — `field_path header.mfr` /
`header.pub_date` / `header.mfr_parent` / `header.doc_level_ltb_date`, each with
`value` and `source_snippet`. **`doc_id` has no review item at all**, the same gap
the gate has.

Suites green, one at a time through the repo venv: the 7 new, 6 on the arm, 19 on the
extractor, 21 second-witness, 17 header-source-refusal, 58 notice-identity +
mfr-document-wins, 62 region-witness + label-echo.

## 4. The mil TBox draft is placed with 74

`invincible-agent/sessions/2026-10-20-packet-to-74-mil-tbox-draft-25-terms-the-writers-emit-and-nothing-declares.md`,
with the TTL beside it as `2026-10-20-mil-tbox-draft-from-7f.ttl`. Placed, not
committed — their tree, their commit.

Sealed against the file itself: parses, **184 triples, 42 `mil:` subjects, 25 of them
new** (6 classes, 19 properties), nothing declared-but-absent, **0 seal defects**, and
the BOM `Out-File -Encoding utf8` had added is gone. Every term carries exactly one
`rdf:type`, one `rdfs:label` and one `skos:definition`, and **zero `rdfs:comment`** —
because `rdfs:comment` IS the embedding and a term declaring both yields two rows
whose last writer wins, which is how `mro:TechnicalManual`'s stored definition came
to be a build note.

**The seal also found a defect in the existing terms:** `mil:hasInstructionText` and
`mil:hasWarning` each have a label and **no definition of any kind**, so under the
`skos:definition UNION rdfs:comment` extractor they have no embedding text at all and
cannot be reached semantically. I wrote one definition for each in the draft and
flagged it to 74 rather than burying it.

**The routing question is open and it is yours and 74's.** There is no `mil` TBox file
anywhere in either repo: no `mil*.ttl` under `agent_fleet/`, and the namespace appears
in exactly two places, `weaviate_expert/main.py` and `neo4j_expert/main.py`, as
`input_uri` values. So the experts are documented to be *called with*
`mil:FaultIsolationDataModule`, `mil:IllustratedPartsDataModule`,
`mil:DescriptiveDataModule`, `mil:ProcedureDataModule` — and a semantic lookup on
those URIs resolves against a vocabulary graph containing **no `mil` term at all**.
What I asked 74 to decide: where the file lives, who loads it and under which graph
IRI (a load must name its target graph explicitly — a default-graph-wide operation on
that endpoint drops production graphs), and whether declaring the terms changes any
consumer today.

I also told 74 what the draft does **not** claim: there are two S1000D parsers and
the wired one is the unmeasured one; S1000D 3xx has no content kind; and an
illustration is a sidecar, not a drop kind.

## 5. Why the three fires and the pin are still not done

**First, the sequencing needs you or Chris.** The pin has to move before the fires can
measure this code — the pod runs the image, not my checkout — and that is merge →
image → pin → fires. I have merged nothing and rolled nothing. Say the word and I
will take it in that order, with the values diff shown before the roll.

**Second, and this is the part no header work reaches.** The published authority
(`origin/main:docs/corpus-gate/latest.json`, generated 2026-10-18T11:25:31Z, image
`...7a554afa`) blocks on **five** items, and `doc_id` is not among them. Header
correctness was 7/9, 5/9, 7/9 with **IDT** failing — not TYC, whose disagreement is
exempted. Five notices are ABSENT in at least one fire, and absence has **no
declaration exemption by design**. Three are identity-half unstable. And
`compute_stability` lumps a `None` identity key into that finding while the exemption
requires `needs_review` in **all three** fires — so **a notice cut in only some fires
can never earn the exemption**, because the healthy fires legitimately have
`needs_review=False`. The 90 s bound makes a cut **cheaper, not rarer**. Green on
three fires therefore needs the absences to stop occurring, or the exemption
re-grained **per fire**, which is a gate change and yours to rule on, not mine to make
quietly.

Item 1 changes no scored field. I am not claiming it moves the verdict.

## 6. What I did not measure

- No fire, no gate run, no roll, no pin: the 199 window was open and the sequencing
  decision is not mine.
- The arm has **never run on a real corpus PDF**. Every measurement above is a test
  fixture or the static tree. What it extracts from the nine notices is unknown until
  a fire, and the gate will not tell us — `stats["doc_id_arm"]` is where to look.
- I did not touch the two gate instrument defects (point `run_header_agreement` at
  `corpus_f{n}.json`'s `written_header`; make `compare` enumerate the declared
  corpus), and they are still open.
