# Report — 7f: evidence coverage is measured, and the one real miss is structural

Measured, not estimated: **88 deployed `review.json` artifacts, 7017 review
items**, read inside the sandbox pod (`doc-tools-5f69db5b94-cf5qm`, imageID
`...@sha256:2bf85719d2ca...`, one distinct value). S3 credentials were never
materialized locally. Scripts: `scratchpad/measure_evidence_coverage.py`,
`scratchpad/measure_ltb_evidence.py`.

## The headline: a bbox already exists for most rows, and "has a bbox" is the wrong test

Every review item already carries `page_number`, `bboxes`, `page_dims`,
`match_method`, `match_confidence` — built in
`doc_tools/utils/sustainment_merge.py:152-163`. So `evidence_ref` is not absent
from this pipeline; it is **present, unnamed, and of two very different
qualities**. Three states, because presence is not sufficiency:

| state | n | what it is | meets the steward test? |
|---|---|---|---|
| `cell` | **4269** | `match_method=text_layer_cell` — the exact table cell | **yes** |
| `region` | **1634** | `resolve_value`'s *enclosing* region | **no** — see below |
| `none` | **1114** | no bbox, `page_number` null | no |

**The 1634 `region` rows are the trap.** The code's own comment at
`sustainment_merge.py:197-201` says `resolve_value` "resolves to the enclosing
TABLE region (every part on a page sharing one huge box)". A gate that asks only
"is there a bbox?" passes all 1634. A steward handed one of those outlines sees
a box around the whole table and has to scroll by hand to find the row — the
exact thing the review standard forbids. **So the binding test is not
`evidence_ref is not null`; it is `evidence_ref is row-level`.**

## The 1114 misses decompose cleanly, and only one is a defect

| kind | n | cause | fixable? |
|---|---|---|---|
| `parts[].ltb_date` | **965** | `source_absent` in **965 of 965** | yes — a defect |
| `header.summary` | 74 | `region="derived"`, LLM-paraphrased, no source exists | **no, by design** |
| `header.categories` | 74 | same — derived | **no, by design** |
| `header.mfr` | 1 | `not_found` on PCN-24-210412 (TYC) | known: damaged text layer |

So 148 of the 1114 can **never** carry a bbox in principle: a derived summary is
not a quotation of the document, so there is nothing to outline. The single
`header.mfr` miss is the TYC notice whose text layer drops `ti` everywhere — an
already-recorded defect, not a new one.

**That leaves `parts[].ltb_date` as the entire real miss: 965 rows, 87% of all
misses.**

## Why the LTB date cannot produce a bbox — measured to the mechanism

Not a flaky match. `ltb_date_source` is **absent in 965 of 965** items, so
`provenance.resolve_value` is handed the *ISO-normalized value* (`2024-06-06`),
which the document never prints verbatim. `not_found` is therefore guaranteed by
construction, 100%, and would stay 100% however good the matcher got.

Three emission paths, and **they disagree** — which is why this looks random and
is not:

1. **Tier 1, pure text layer** (`sustainment.py:616-617`) sets
   `"ltb_date": None` and `"ltb_date_source": None` *explicitly*, commented
   "per-row dates are not a column in this shape". It emits no per-row date at
   all, so it contributes **no** miss — `build_review_items` skips a falsy
   `ltb_date`.
2. **Grid forwarding** (`sustainment.py:735-745`) already does the right thing:
   it knows `roles.ltb_date_col` and sets `"ltb_date": ltb, "ltb_date_source":
   ltb` — the verbatim cell. **A proven in-repo pattern for the fix already
   exists on this path.**
3. **The pure-vision parts pass** returns a `PartImpact` whose `ltb_date_source`
   is permitted null by `baml_src/sustainment.baml:36` — and is null every time.

So the 965 belong to path 3. CORRECTION to my own first read: I initially wrote
that "`ltb_date` has no text-layer cell path"; that is wrong as stated — path 2
has one, and the defect is specifically that path 3 supplies a value with no
source while paths 1 and 2 do not.

**A merged row can be half-evidenced.** TYC (PCN-24-210412) shows 38 `cell` and
40 `none` across 81 items: the MPNs carry exact cell bboxes from the text layer
while their per-row LTB dates, supplied by vision, carry nothing. A steward can
confirm the part and cannot confirm its date, on the same row.

Note `parts[].ltb_date` also has no dedicated cell-bbox field, unlike
`text_layer_bbox` and `text_layer_replacement_bbox`. Even path 2's verbatim
source only reaches `region` quality, never `cell`.

## RULING NEEDED before the gate can be armed

The order was "a row without `evidence_ref` is a corpus-gate miss from
tonight." **Arming that tonight reds the gate immediately and permanently**:
965 structural misses plus 148 that can never be fixed. A red authority report
freezes every merge in this repo — a known, already-paid-for mechanism. I have
not armed it, and I am not going to without a ruling, because the ruling changes
what the check *is*:

1. **Are derived fields exempt?** `header.summary` and `header.categories` have
   no source substring by construction. Either they are exempt, or the gate is
   red forever on 148 items no code change can reach.
2. **Does `region` count as evidence?** If yes, the gate passes 1634 rows whose
   outline is the whole table, and the review standard's "without scrolling the
   PDF by hand" is not actually enforced. If no (my recommendation), the gate
   must fail those too — which is a much larger body of work than the LTB fix,
   and should be a declared pass of its own rather than a surprise red.

My recommendation: exempt derived, require **row-level** evidence for everything
quoted, land the LTB fix first, re-measure, then arm. That sequence never puts
the repo in a frozen state.

## A naming collision in the review standard, worth catching now

The card specifies a per-row `obtained_via`. In this repo `obtained_via` already
means something else and is load-bearing: ADR-0041 **drop** provenance, how a
document entered the system (`"user-drop"`). `doc_tools/passes/identity.py:49-52`
says so explicitly and warns that "reusing the name would silently merge them".
The per-field key for how a value was obtained is `method` / `label` / `region`.
Lane 1 and cortex should take the card's `obtained_via` as `match_method`, or the
two provenances will be conflated in the payload the steward reads.

## Status of tonight's other items

- **Item 1** (two contradictions to the architect, top of file) — **done**,
  merged as `13e05e2` (#129).
- **Item 2** (read `MAINTENANCE_INSTANCES`, expect 112) — **blocked on Lane 1's
  MRAD retries**, which have not run. Not idling; this report is the next item.
- **Item 3** (`rdf:List`) — the *choice* is settled and reported (`mil:stepIndex`
  is not in the vocabulary; no `mil:` term is). **Emission is not yet written**,
  and Lane 1 has not yet been sent the choice as a packet.
- **Item 4** — measured above. Implementation and the three-fire are gated on the
  ruling, because the fire measures a gate whose definition is in question.
- **Item 5** (#128 verdict from the log) — the #128 run `39001729939` is **still
  in progress** (the ~40-min no-push `build-and-push`), and GitHub refuses job
  logs until the run completes. `corpus-gate` **passed**; `corpus-gate-verdict`
  **failed**, which is the known advisory red. I am waiting on the log rather
  than asserting the signature from memory, as instructed.

## Rulings 1 and 2 — what shipped already complies

Ruling 1 ("mirror the PCN path" wins, the urn:doc-only clause withdrawn) and
Ruling 2 ("the unit is the subject, not the predicate") both ratify what #127
shipped: the module subject's **whole** triple set goes to
`MAINTENANCE_INSTANCES`. No code change is needed. The one thing to confirm
against Ruling 2 is that the builder emits no *non*-module-subject
(raw-document/blob) triples that should have stayed `urn:doc:`-only; that check
is still owed and is cheap once the re-drop lands.

## Day 2 addendum (`mesh:universalReferent`) — already shipped, with one conflict

The doc-tools half is **already on `main`** at commit `7ac6caa`, not pending:

- the SELECT carries `OPTIONAL { ?uri mesh:universalReferent ?universal_referent }`
  (`ontology_assets.py:1894`);
- the MERGE writes it (`:2089`), interpolated from `UNIVERSAL_REFERENT_PROPERTY`
  so both sides use one spelling;
- the constant is asserted identifier-shaped at import (`:157`);
- a **two-sided** readback already verifies flagged *and* unflagged (`:2150-2172`).

The addendum's line references (~957, ~1133) point at the Weaviate class write
and an ontology-path docstring respectively — not this code. And its premise
that the sync "carries only label, definition, domain and stamps" is no longer
true.

**The one real conflict: "false when absent".** The shipped code deliberately
writes `None`, never `False`, and says why at `:1931-1937` — Cypher `SET c.prop
= null` *removes* the property, so writing `False` would "put the property on
~24,000 nodes to say nothing, and would make 'the flag was dropped' and 'the
flag is false' indistinguishable from a read." The addendum's seal ("one without
syncs false") therefore **fails against the current code by design, not by
bug**. Both designs agree on the thing the code's comment cares about (an
explicit `false` and an absent triple must read alike); they differ only on
whether that shared reading is `false` or absent. I have not changed it —
overturning a documented decision with a measured rationale needs your word.
