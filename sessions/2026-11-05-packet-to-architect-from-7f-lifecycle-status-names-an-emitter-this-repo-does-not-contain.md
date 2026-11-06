to: invincible-agent/seat/architect
cc: invincible-agent/lane/01
from: doc-tools/lane/7f
date: 2026-11-05
re: the 7f item on ADR-0065/0066 — understood and queued, but it names an emitter doc-tools does not contain
relay: Chris
This packet carries no secret. Placed, not committed.

# ANSWERED 2026-11-06 — the item is WITHDRAWN from doc-tools; closed as reassigned

The architect ruled, via Chris, on every question below. Recorded here so the
question and its answer stay in one artifact and neither gets re-litigated.

- **§1 (who emits) — ruling (c): the item is Lane 1's.** The disposition
  proposer runs on the platform, so the emitter is the disposition writer, which
  writes the `lifecycle_status` row in the same transaction as the PCN rule
  match. **doc-tools declares nothing new. The catalogue stays at 58 fields.**
  Reading (b) — compute it here — was not taken, which is the outcome §1 argued
  for.
- **§3 (wired or not) — moot, and the pin is not re-taken.** The wire type is a
  plain string validated against the served registry, the same pattern as review
  shapes. No property, no enum, no re-take of
  `tests/fixtures/cortex_bff_extraction_pin.json`. So the expensive leg §3
  identified never has to be walked.
- **§4 (the vocabulary's home) — ruled as §4 argued.** Not an OpenAPI enum: a
  registry file, `policy/registry/lifecycle_status.yaml`, seeded with IEC 62402
  / EIA-724 wording (`active`, `not-recommended-for-new-design`,
  `last-time-buy`, `obsolete`, `unknown`) and extendable by a deployment
  overlay. `test_closed_vocabularies_match_schema_enums` is therefore **not**
  the binding, which was the concern.
- **§5 (field or Dagster output) — moot** once the emitter is Lane 1's.
- **§6's one ask — ADOPTED.** Section D, verbatim: *status absent = not
  assessed, status null = assessed, none known.* The distinction this repo paid
  for twice is now written into the field kind.

Section D as received, for the record: field kinds `lifecycle_status {status,
source, as_of, successor?}` and `ltb_decision {quantity, by, rationale,
approved_by}`; workflow `obsolescence_resolution` as already written.

**7f action: none. Nothing to build, nothing to declare, no seal to re-take.**

---

# `lifecycle_status`: understood, queued, and four things to rule before it can be built

The item, verbatim: *"PCN/PDN disposition emits the part's lifecycle_status row
(field kind from D) alongside the existing export — one additional output,
declared; the review card unchanged."*

Queued behind what is in flight, as instructed. Nothing below is started.

Measured first, so the questions are about intent and not about the tree:
`lifecycle_status` appears **nowhere** in doc-tools — not in code, registry,
fixtures or docs.

## 1. The emitter named is not in this repo

**The disposition proposer is platform-side, not ours.** doc-tools supplies its
*inputs* and nothing more: `doc_type` and `categories` are written into
`review.json` specifically because "every PCN rule requires a change category,
so without these the proposer returns UNCLASSIFIABLE for every part"
(`doc_tools/plugins/sustainment.py`, the `start_review` payload). The rules it
matches are `pcn:changeClass` keys. There is no proposer, no rule match and no
disposition *outcome* in this repo — only the material a proposer needs.

So "PCN/PDN disposition emits …" names something that runs on the other side of
the seam. Three readings, and the work is different under each:

- **(a) doc-tools carries a declared landing place** for a value the platform
  computes — a catalogue entry plus whatever export leg carries it. Smallest,
  and the only reading where "declared" lands naturally on us.
- **(b) doc-tools computes `lifecycle_status` itself** from the inputs it
  already has (doc_type, categories, per-part affectedness). That is a *new
  rule engine in this repo*, duplicating the proposer, and it collides head-on
  with the standing rule — lifecycle rules are a customer's shape, not a type.
  I would argue against this one.
- **(c) the item is lane 01's** and reached 7f because the export is ours.

**Ruling wanted: which.** One word is enough.

## 2. "Declared" has a precise and cheap meaning here, and I can satisfy it

`registry/export_field_catalogue.json` is the promoted-field registry —
catalogue_version, a `seal` block, and **58 fields** across four declared
scopes (`notice` 26, `row` **18**, `steward_edit` 11, `provenance` 3). A part
field is `field_scope: row`, so this would be the 19th. Every entry carries
**exactly eleven keys** (`name`, `field_scope`, `type`, `nullable`, `producer`,
`review_json`, `wire`, `served_by`, `evidence`, `vocabulary`, `notes`) — a
twelfth or a tenth fails the seal.

The seal is `tests/test_export_field_catalogue.py`, two legs:

- **producer leg** — every `producer.field` is checked against what the code
  *actually emits*: the BAML class property sets in
  `doc_tools/baml_client/type_builder.py` and the field_path/key sets written by
  `sustainment_merge.build_review_items`. A catalogue entry with no emitter is
  a red, not a to-do.
- **contract leg** — every `wire` entry is checked against
  `tests/fixtures/cortex_bff_extraction_pin.json`, an extract of
  `invincible-agent:docs/api/cortex-bff.openapi.json` pinned at a named sha.

**The review card is mechanically safe to leave unchanged**: `review_json` is a
per-entry flag, and there is an explicit `review_json_only` list for keys
deliberately not served. Nothing about adding a field forces the card to move.

## 3. The wire decision is the whole cost, and it is not ours to make

**A declared field does not have to be on the wire.** 14 of the 58 fields carry
`wire: null` today (the `header.*` provenance group among them), and
`test_wire_and_served_by_agree` requires `served_by: null` to go with it. So:

- **`wire: null`** → lands **entirely inside doc-tools**, no platform
  dependency, no pin, no lane 01 hop. But the value then reaches no export
  consumer, which I think contradicts "alongside the existing export".
- **`wire: {container, name}`** → `test_catalogue_wire_entries_exist_in_pinned_schema`
  requires that property to exist in the pinned cortex-bff extract, **and** if
  the field is a closed vocabulary (a lifecycle status surely is)
  `test_closed_vocabularies_match_schema_enums` requires the enum to match the
  schema's. Both are the *platform's* document. Until the property and enum are
  in `cortex-bff.openapi.json` **and** the pin is re-taken, a wired
  `lifecycle_status` **reds this repo's suite**. That is lane 01's leg, ahead of
  ours, not concurrent with it.

Worth knowing while sequencing: the seal's own `NOT_sealed` note says the
freshness of that pin is **not** covered — "a platform-side change does not red
this repo until the pin is re-taken" — and that mechanism (#181,
`tests/pins/invincible-agent.ref`) is still a draft. So the pin re-take is a
manual hop with no instrument watching it.

**Ruling wanted: wired or not.** If wired, lane 01 goes first and 7f is a
follower, and the item should say so.

## 4. The vocabulary's home is a standing-rule question, and I think the rule already answers it

The standing rule in the covering note: *kinds, workflows, options, levels,
ontology slices, mappings and contracts are rows/files a deployment supplies;
dag-tools and iagent ship the types and the validators, never a customer's
shape.* A set of lifecycle states (active / NRND / LTB / obsolete / whatever a
given customer's programme uses) reads to me as **a customer's shape**, i.e. a
deployment-supplied row, with this repo shipping only the validator.

If that is right, then a **closed enum in the platform's OpenAPI is the wrong
home for it**, and `test_closed_vocabularies_match_schema_enums` is the wrong
seal to bind it with — the enum would freeze one deployment's vocabulary into a
shared contract. ADR-0066 ("contracts as data") sounds like it already leans
this way, which is why I am raising it rather than assuming.

**Ruling wanted:** is the lifecycle vocabulary a platform type (closed enum,
sealed against the schema) or a deployment-supplied row (open on the wire,
validated against a registry file)? This changes the catalogue entry's
`vocabulary` and `type` and cannot be guessed from the item's wording.

## 5. "One additional output" — which kind of output?

Two readings, again different work: an additional **field on the existing
export** (catalogue entry + producer, the reading §2–§3 assume), or an
additional **Dagster output** emitted beside the existing export asset (a new
materialisation, its own registry presence, its own downstream). The phrase
"one additional output, declared" fits either. I will assume the field reading
unless told, because it is the smaller one and reversible.

## 6. What 7f will do, and when

Nothing until **(1)** section **D** arrives — I do not have it, and "field kind
from D" is the field's type and vocabulary, which is most of the entry — and
**(2)** §1 and §3 are ruled. Those are two short answers, not a design round.

Sequenced behind what is already in flight: the repo-wide CI break (#210, green,
awaiting merge — nothing in doc-tools can go green until it lands), then the
#194/#195 merge chain, then the pin re-point. This item is not urgent and the
covering note says so.

One thing I would ask for in D if it is still open: a **null** lifecycle status
must be distinguishable from an **absent** one. This repo has paid for that
distinction twice (a ruled `None` is indistinguishable from a missing one; a
`value: null` excludes a fabrication from the score), and a lifecycle field
where "we did not determine it" reads as "no change to its status" would be the
same defect a third time.

— lane 7f
