# Packet to the architect — from doc-tools/lane/7f

Two rulings needed, one paragraph each, at the top as asked. Then the procedure
order answer, which is a measurement rather than a preference.

---

## Ruling 1 — "identity/provenance stays in `urn:doc:` only" vs "mirror the PCN path"

These cannot both be followed literally, because the PCN path *does* write
identity and provenance into its instance graph: at
`doc_tools/plugins/sustainment.py:2003-2053` the document node's `rdf:type` and
**both** PROV terms (`PROV_GENERATED_AT`, `PROV_DERIVED_FROM`) are inside the
`INSERT DATA { GRAPH <…_INSTANCES> { … } }` block. What shipped in #127 takes
the "mirror" half and writes the module's **whole** triple set to
`MAINTENANCE_INSTANCES`. I want to flag that this costs nothing in practice on
this path, and that is a measurement rather than a judgement: **the S1000D
builder emits no PROV term at all**, and the ingest provenance here *is the
graph name* (`urn:doc:<s3_key>`), not a triple — so "identity/provenance stays
in `urn:doc:` only" is, for the XML path as it exists, a constraint on an empty
set. The ruling I need is whether that reading holds, or whether you want the
set split; if split, see Ruling 2, because the two are the same question seen
from opposite ends.

## Ruling 2 — a type-less, label-less subject is not walkable

If `rdf:type` and `rdfs:label` for a DataModule were held back to `urn:doc:`, a
domain-scoped walk would read `mil:hasFaultCode` edges off a subject it can
neither classify nor name — which is the exact condition the second write exists
to end, so the narrow reading of Ruling 1 would re-create the defect at one
remove. The reason this is a ruling and not an implementation detail is that
there are two honest ways out and they are not equivalent: either the whole
triple set goes to `_INSTANCES` (what shipped, one write, no duplication
question), or type and label are *duplicated* into `_INSTANCES` while the rest
of identity stays in `urn:doc:`, which means two writes, a rule about which
terms are "structural" enough to copy, and a new drift surface every time the
parser adds a term. I shipped the first and will switch to the second on your
word, but I do not think the second should be chosen without someone owning that
term list.

---

## Procedure order: **`rdf:List`** — `mil:stepIndex` is not in the vocabulary

You said pick `rdf:List` unless `mil:stepIndex` is already in the vocabulary, and
say which. **It is not.** Measured against the deployed vocabulary graph
`<http://internal/MAINTENANCE>` (4959 triples) in the sandbox pod, not against a
local checkout:

```
ASK mil:stepIndex declared anywhere in the vocab graph   -> False
ASK any mil: namespace term at all in the vocab graph    -> False
```

So: **`rdf:List`.**

Three things about that answer you should have before you rule on anything built
on it.

**`rdf:List` is already in the graph, but not as precedent for ordering.** All
**511** `rdf:first` triples in the vocabulary are OWL axiom plumbing —
`owl:intersectionOf` (139), `owl:unionOf` (84), `owl:propertyChainAxiom` (3),
`owl:members` (2), and `rdf:rest` chaining (283). **Zero** of them order domain
content. I am not offering "the vocabulary already uses `rdf:List`" as support,
because that would be true-sounding and wrong: it uses it for class expressions.

**The step concept exists; the ordering does not.** The vocabulary declares
`iof-maint:ProcedureStep`, and the only predicates touching it are `rdf:type`,
`rdfs:label`, `rdfs:subClassOf` and `skos:definition` — no ordering predicate of
any kind. So this is a genuine gap rather than a choice between two existing
options.

**The larger finding behind the `False`: no `mil:` term is in the vocabulary
graph at all.** Our parser emits `mil:hasFaultCode` and ~19 other `mil:`
predicates, and the vocabulary graph declares **none** of them. So the question
"is `mil:stepIndex` in the vocabulary" has a sharper answer than "no" — the
whole `mil:` TBox is absent from the graph a domain reader would consult. That
bears on the 3xx/320A no-content-kind gap I already owe you, and it means an
`rdf:List`-based ordering will be as undeclared as everything else `mil:` unless
the TBox question is settled separately. I am not folding that into this ruling;
flagging it so `rdf:List` is not later read as having been declared.

---

## Done since the last packet, for context only — no action

All three pins are rolled. The instance-write pin is `f4d6440` /
`sha256:2bf85719`, helm **rev 48** (image) and **rev 49** (gate expectation),
seal 3/3, ~2h50m clear of the 07:00Z nightly. PR #128 lands the values. The
rollout-status finding is in `AGENTS.md` under Safety Guardrails as directed.

**The instance graph is still empty** — the write fires at XML ingest, so the
green seal is a precondition, not a result. After the ten modules are re-dropped
it must read **112** (the distinct union of the ten `urn:doc:` graphs, 20
subjects); **193** means it is accumulating and the idempotency claim is wrong,
**~99** means the repo fixtures rather than the dropped bytes got there.

Full detail, if you want it after ruling:
`sessions/2026-10-17-report-7f-the-instance-write-landed-and-the-ten-drops-are-six.md`
