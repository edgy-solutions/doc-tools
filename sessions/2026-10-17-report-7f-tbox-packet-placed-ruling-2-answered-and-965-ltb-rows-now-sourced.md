# Report — doc-tools/lane/7f, 2026-10-17 (second half of the overnight)

For the architect, cc Lane 1 and cortex. Covers the work after the evidence
measurement reported in
`2026-10-17-report-7f-evidence-coverage-measured-7017-items-and-the-ltb-date-miss-is-structural.md`.

## Headline

- **#131 merged** (`2a1c9fa`) — procedure order is an `rdf:List` with URI cells.
  `tests` green on the exact head commit, read from the rollup.
- **Ruling 3 discharged** — the 25 undeclared `mil:` terms are a placed packet,
  sealed three ways; the emitted-vs-declared gap closes to **zero**.
- **Ruling 2 follow-up answered by measurement** — the S1000D builder emits
  **no** non-module-subject triples at all. No code change.
- **#132 open** — the 965 unsourced `parts[].ltb_date` rows were *inherited*
  doc-level dates, and they are now sourced to the sentence that states them.
  Row-level evidence coverage goes from 5903/7017 to **6868/7017**.
- **The corpus gate is still not armed.** Two rulings owed. Arming it publishes
  a red authority report, and a red authority report freezes every merge here.

## 1. Procedure order — merged, and it caught a trap first

`rdf:List`, because `mil:stepIndex` is absent from the deployed vocabulary in
**subject, predicate and object** position. The list cells are deterministic
URIs (`mil:proclist-{doc}-{proc}-{pos}`), not blank nodes, and that was not a
style choice.

The instance-graph write serializes the whole builder graph to N-Triples and
ships it as SPARQL `INSERT DATA`. **`INSERT DATA` mints a fresh blank node per
execution.** An rdflib `Collection` — the obvious way to write a list — would
therefore have appended a complete duplicate list on every re-ingest and
silently voided the set-idempotency that write's own comment claims. The
ordered Day 2 idempotency proof would have failed, and it would have looked
like a pipeline defect: in-process `Graph.add` with a `BNode` is perfectly
idempotent, so no parser unit test would show it. The breakage exists only
across the SPARQL round trip. Sealed two ways in `tests/test_parsers_rdf.py`:
no term in the structure is a `BNode`, and a second parse of the same bytes
grows the graph by **zero** triples.

**Consequence you need to plan for:** the six MRAD fixtures went **99 → 146**
triples (520A +21, 720A +26; the other four emit no procedure). So
`mrad.ttl` in invincible-agent — a zero-drift snapshot of this parser at 99 —
**must be regenerated**, and the ordered "expect 112 in `MAINTENANCE_INSTANCES`"
belongs to the pin *before* #131. It must be re-derived against whatever pin is
deployed when Lane 1's retries land, not assumed.

## 2. I got the TBox evidence wrong once, and the correction is in the tree

My first pass reported "no `mil:` term is declared in the vocabulary graph at
all". **That was wrong.** The `ASK` scanned **predicate** position, and a TBox
declares its terms as **subjects** (`mil:hasPart a owl:ObjectProperty`), using
`rdf:type`/`rdfs:label`/`rdfs:domain` as its predicates. A predicate-position
scan over a pure TBox returns zero **by construction, whatever it declares**.

This is the same trap I had warned Lane 1 about two paragraphs earlier in the
same packet — reading 511 `rdf:first` triples as precedent for ordering when
they are OWL class expressions. True-sounding evidence from a query that cannot
see the thing it was asked about. Corrected in six places (commit `dd1ad9a`,
the code comment, the test docstring, the PR body, the memory, and the Lane 1
packet).

The truth: **17 `mil:` subjects, 69 triples** in deployed
`<http://internal/MAINTENANCE>` — 16 terms plus the ontology header, exactly
`setup/ontologies/mil_extension.ttl`, correctly stamped `domain=MAINTENANCE`.
**The decision did not move**: `mil:stepIndex` is genuinely absent in all three
positions, so `rdf:List` stands on corrected evidence.

## 3. Ruling 3 — the packet, and why it is not a new file

> "Day 2, you declare every `mil:` term the builder emits in a `mil.ttl` TBox
> loaded by `ontology_assets` into MAINTENANCE."

The carrier **already exists**, in invincible-agent, already primed into
MAINTENANCE. A second file declaring the same namespace from a second place
would be worse than extending it, so the 25 declarations extend
`mil_extension.ttl`. doc-tools does not commit in that tree, so it is placed:

`invincible-agent/sessions/2026-10-17-packet-to-lane-01-twentyfive-undeclared-mil-terms-for-mil-extension-ttl.md`

Sealed before placing, from this repo's venv, against your file plus the block
concatenated:

```
merged parses OK, triples: 182
mil: subjects now: 42          (your 17 + these 25)
COLLISIONS with existing: none
every term: one rdf:type, one rdfs:label, one skos:definition, zero rdfs:comment

emitted 41 terms = 16 classes + 25 properties
UNDECLARED CLASSES   : (none)
UNDECLARED PROPERTIES: (none)
DECLARED BUT NEVER EMITTED: MIL          (the ontology header — correct)
```

Three things worth your attention:

- **Domain and range are measured, not inferred from the property names.** Read
  off the graph the parser actually produces. **Three properties get no
  `rdfs:domain`** because their emitted subject classes are genuinely disjoint:
  `mil:hasCatalogItem` (DataModule **and** Figure), `mil:hasPartNumber`
  (CatalogItem, Part **and** Tool — and `mil:Tool` is deliberately not a
  `mil:Part`), and `mil:hasPart`. Omitting is in-file precedent: you already do
  it for `hasSNS` and `hasInfoCode`. A single domain there would be a false
  statement.
- **Flagged, not changed:** the already-declared `mil:hasPart` carries
  `rdfs:domain iof:InformationContentEntity`, and we also emit it from a
  `mil:CatalogItem` subject, which is not declared an ICE. Either
  `mil:CatalogItem` becomes an ICE subclass or that domain wants relaxing. It
  is your triple.
- `rdfs:comment` appears nowhere — **it is the embedding** in that file, and a
  class declaring both it and `skos:definition` yields two rows with the
  Weaviate upsert keeping whichever lands last. Build notes are `#` comments,
  which are not triples.

One honest limit: the 41 is a **static scan** for `self.MIL.<term>` plus the
content kinds built from `mil_info_code_map`. A term assembled at runtime from
a variable would not appear in it. We know of none; the info-code map is the
one dynamic case and the scan covers it explicitly.

## 4. Ruling 2 follow-up — answered, and the answer is "nothing"

> "The only thing that stays `urn:doc:`-only is what isn't about the module
> subject — the raw-document/blob triples, if any."

Census over the six MRAD fixtures plus the hotspot fixture
(`scratchpad/subject_census.py`):

```
198 triples, 44 distinct subjects
SUBJECT namespace census:
    198  http://edgy-solutions.com/ontology/mil#
blank-node subjects: 0
urn:doc subjects   : 0
```

**Every subject is in the `mil:` namespace. There are no `urn:doc:` subjects
and no blank nodes.** So there is nothing that should stay `urn:doc:`-only, the
whole-graph write with no subject filter is exactly right under ruling 2, and
**no code change is needed**. Corroboration worth noting: the only URIRefs that
appear as objects but never as subjects are the 12 class IRIs used as
`rdf:type` objects, plus `rdf:nil` — precisely the TBox terms the ruling-3
packet declares. And zero blank nodes confirms the URI-cell choice holds in the
**emitted** graph, not just in the parser's own tests.

(The measurement also re-printed the `3xx` fallthrough warning: info code `320`
has no `mil:` content kind, so a maintenance-planning module classifies as the
bare `mil:DataModule` root and is indistinguishable downstream. Still yours to
rule on; deliberately not in the TBox packet.)

## 5. Item 4 — the 965 were inherited, and they are now sourced (#132)

The measurement said 965 of the 1114 no-bbox items were `parts[].ltb_date` with
`source_absent` 965/965. The cause is **not** extraction.

Most notices state the last-time-buy date **once, in prose**, and no row prints
it. `reconcile_ltb` backfills every such row from the document-level date: it
writes the ISO value into `ltb_date` and leaves `ltb_date_source` at `None`.
`build_review_items` then fell back to `ltb_date_source or ltb_date` — i.e. it
searched the positioned OCR index for the **ISO string itself**, a form the
document does not print. `not_found` was guaranteed by construction.

An inherited date is not unlocatable. The sentence that states it **does**
resolve, as `header.doc_level_ltb_date` already demonstrates. So:

| change | why |
|---|---|
| `reconcile_ltb` records `ltb_date_inherited` | after the backfill the two cases are otherwise identical: same ISO value, same null source |
| inherited rows borrow the header bbox, `match_method: "inherited_doc_level"` | a borrowed bbox must never read as a cell the row owns |
| borrowed **only if the header date resolved** | an unlocated header date lends nothing; the row reports `not_found` rather than looking sourced with an empty box |
| a row with its own date resolves on its **source only** | an MPN's value *is* its printed form, so searching for it is sound; a bare ISO date can match an unrelated occurrence — a "document issued" stamp — and outline the wrong thing. A confident wrong crop is worse for a steward than an honest miss. A test pins that exact trap. |

**Deliberately not done:** `needs_review` is untouched. These rows still carry
`needs_review=False`. Flagging them changes which notices are refused outright
(the Qorvo shape: a doc-level reason with no per-part flag refused a clean
notice), and that is the owed ruling. This PR fixes the **evidence**, which is
what was ordered.

Row-level evidence coverage: **5903 → 6868 of 7017**. Left unsourced: **149,
and none of them are rows** — 74 `header.summary` + 74 `header.categories`
(derived from the whole document; there is no crop, and inventing one would be
worse) + 1 `header.mfr` (the notice whose text layer drops `ti`).

## 6. Two rulings owed before the gate is armed

1. **Are derived fields exempt?** `header.summary` and `header.categories` have
   no crop by nature. 148 of the remaining 149 are these.
2. **Does a `region`-quality bbox count as evidence?** This is the one that
   matters, and it is not visible from the ordered test as written:

| `match_method` | n | what the outline actually is | row-level? |
|---|---|---|---|
| `text_layer_cell` | 4269 | the exact cell | **yes** |
| `region_preferred` / `unique` | 1634 | the **enclosing table box** | **no** |
| none (pre-#132) | 1114 | no bbox | no |

"A row without `evidence_ref` is a miss" passes all 1634, whose outline is the
whole table — every row on the page sharing one box. That does not meet
"confirm mpn + value against the outlined crop". **There are three evidence
states, not two**, and a non-null test cannot tell the good one from the
mediocre one.

Recommendation unchanged: exempt derived, require **row-level**, re-measure
against a deployed pin, then arm. We have not armed it, because arming tonight
publishes a red authority report and that freezes every merge in this repo.

## 7. Still blocked, and what it is waiting on

- **Item 2** (`MAINTENANCE_INSTANCES`, expect 112, five triples per module) —
  Lane 1's MRAD retries. The 112 must be re-derived, not assumed: #131 changed
  the triple count, and the deployed bytes differ from the fixtures (ten drops
  are six modules; two pairs disagree, 720A 19 vs 14).
- **Day 2 idempotency proof** — same blocker, plus it needs a pin carrying #131.
- **Day 2 `mesh:universalReferent`** — already shipped at `7ac6caa`. The
  addendum's "false when absent" seal fails **by design**: Cypher
  `SET c.prop = null` *removes* the property, so writing `False` would put it on
  ~24,000 nodes to say nothing and make "dropped" and "false"
  indistinguishable. Not changed without a ruling.
- **Day 2 cad survey** — not started (survey only, no code, as ordered).

## Artifacts

| what | where |
|---|---|
| procedure `rdf:List` | **merged** `2a1c9fa` (#131) |
| inherited LTB evidence | **#132** open, `b632928` |
| TBox packet (25 terms) | placed, invincible-agent `sessions/...twentyfive-undeclared-mil-terms...md` |
| LTB contract packet | placed, invincible-agent `sessions/...an-inherited-ltb-row-jumps-to-a-different-page.md` |
| subject census (ruling 2) | `scratchpad/subject_census.py` |
| TBox seals | `scratchpad/seal_ttl.py`, `scratchpad/tbox_gap_merged.py` |
| measured domain/range | `scratchpad/measure_domain_range.py` |

Full local suite after #132: **1746 passed, 17 skipped, 7 deselected** (the 7
are the `corpus_gate` guard tests, deselected by default — a known trap, and
the reason a green local run is not a green gate).
