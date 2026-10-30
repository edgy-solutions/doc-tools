# Report — 7f: the "no hard-coded case" rule, audited against this tree

**Date:** 2026-10-30
**Lane:** 7f (`doc-tools`)
**Rule audited:** architect's standing rule of 2026-10-30 — *nothing in an API,
wire type, route, engine or UI hard-codes a workflow, document kind, domain,
group, program, recipient, or customer's shape. Code implements the mechanism;
config names the case.*
**Occasion:** PR **#192** was open and green when the rule arrived. The rule says
*tests before you open a PR*, so #192 was audited first, then the tree.

---

## 1. Verdict on #192: it passes, and the rule corroborates its central decision

| test | #192 |
|---|---|
| (1) generic nouns in a new wire type | **n/a / pass** — no new wire type. The fields are the SDK's own (`kind`, `passes`, `outputs`); the domain term is the row's *value*. |
| (2) reachable by adding a row, not a branch | **pass** — `registrations()` iterates the table; no `if kind == …` anywhere in the new code. Measured: the only kind-literal in `kind_registrations.py` or `generate_kind_registrations.py` is docstring prose. |
| (3) a deployment can add its own case in an overlay | **pass, and unchanged by #192** — that is exactly what the platform overlay does, and #192 deliberately does **not** author the overlay's fields. |
| (4) the registry your code reads is the one the server **serves**, not a copy | **#192 is neutral; the tree FAILS this one. See §2.** |

**The rule independently corroborates #192's main decision.** Its list of what
belongs in config names *"a declaration served on the wire (options,
consequences, labels, review shapes)"* — `label` and `review_shape` by name. So
the two fields #192 declines are, by this rule, **wire declarations the server
serves**, not values this repo hard-codes into mirrored rows. That is a second,
independent argument for the decline recorded in
`doc_tools/utils/kind_registrations.py`, arrived at from a different direction
than the 2026-10-24 ownership ruling.

It also **tilts the live collision**. The SDK changelog (2026-10-21) tells 7f to
fill `arrives_as` into `KIND_MAPPING`'s rows; the ownership ruling (2026-10-24)
gives it to the platform; this rule (2026-10-30) says a declaration of that sort
is served, not hard-coded. **Two of the three now point the same way, and the
dissenting one is the oldest.** The ruling is still owed — this lane does not
settle it by reading a third document — but the weight has moved.

## 2. Where this tree fails test (4), measured

**The runtime kind list is a Python dict, not a served declaration and not even
the rows.**

* `doc_tools/utils/ingest_failure.py:140-148` — `_registered_kinds()` derives the
  registered kinds from `KIND_MAPPING` directly: *"derived live from
  KIND_MAPPING (sorted, deduped by `.kind`) — never scraped from a message."*
  That docstring was written to defend against a *worse* source (scraping an
  error message), and it does; but the source it chose is still code.
* **Nothing under `doc_tools/` loads `registry/content_kinds/` at all.** Measured
  by grep for `ROWS_DIR` / `load_content_kind_registrations` / `content_kinds`:
  every hit outside prose is in `scripts/` or `tests/`.

So the published rows are a **copy that nothing reads at runtime** — they exist
to be compared by the cross-repo seal and to be the SDK-validated projection
(which is what #192 made real). The case is named in `KIND_MAPPING`, in code.

This is a pre-existing condition, not something #192 introduced, and #192
narrows rather than widens it: the rows are now built *through* the SDK model,
so the copy can no longer drift into a shape the SDK would refuse.

## 3. Where this tree fails test (2), measured

A domain is reachable only by adding a **branch**, in more than one place:

* `doc_tools/assets/semantic_assets.py` — an `if/elif` ladder on `domain_type`
  over `manufacturing` (883), `maintenance` (894), `compliance` (897),
  `sustainment` (904), `document` (906), with further `domain_type ==
  "sustainment"` tests at 948 and 1225 and `declared_domain == "manufacturing"`
  at 556. A new domain needs a new `elif`.
* The plugin selector's `else` is the **training** plugin, not a default — a
  known trap already in memory — so a new domain silently lands on training
  until someone adds its branch.
* `doc_tools/components/document_parser.py:409,503` — `if domain ==
  "training"`.
* `doc_tools/assets/xml_ingestion.py:247,290` — `if doc_type == "40051"`, a
  standard number hard-coded in the dispatch.

Honest exclusions, so this list is not padded: the `kind == "int" | "bool" |
"list" | "object_list"` tests in `plugins/manufacturing_overlay.py`, `kind ==
"date"` in `witness_regions.py`, `kind == "table_cell"` in `scrub/ledger.py` and
`tool_kind == "Presentation"` in `aitool_linker.py` are **field/value type**
switches, not domain or customer shapes. The rule does not reach them.

## 4. What I did and did not do about §2 and §3

**Did:** audited, measured, and recorded. #192 is unchanged by this audit except
for this report, because it already passes.

**Did not:** refactor the `domain_type` ladders or move the kind source of truth
off `KIND_MAPPING`. Both are real work with real blast radius — the ladder feeds
the write path where *a domain-less row writes nothing*, and moving the source
of truth touches the picker, the seal, and the overlay contract at once. The
rule is forward-looking (*"tests before you open a PR"*); retrofitting it to
these two sites is its own packet, and it needs the ownership ruling first,
since §2's fix is "read what the server serves" and the server currently serves
none of it.

**Recommended order, if that packet is wanted:**
1. The ruling on the four fields (§1) — it decides whether the served
   declaration is the source of truth, which decides §2's shape.
2. §2: make the runtime read the rows (or the served registry), leaving
   `KIND_MAPPING` as the *generator's* input only.
3. §3: replace the `domain_type` ladder with a registry row per domain, and make
   the plugin selector's `else` a refusal rather than the training plugin.

None of that is started.
