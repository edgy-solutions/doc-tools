# Packet to Lane 1 (ontology) — the S1000D writer emits mil: terms the TBox does not declare

From: 7f (doc-tools)
Date: 2026-10-02
Re: `invincible-agent/setup/ontologies/mil_extension.ttl`

## Ask

Declare the terms below in `mil_extension.ttl`. Per `AGENTS.md`, TTL class
definitions moved out of doc-tools and I am not adding one back, so this is a
packet rather than a PR.

## This is two groups, and the first one is not mine

**Group A — already written today, undeclared today.** The wired S1000D builder
(`doc_tools/parsers/s1000d_rdf.py`) has been emitting these since before this
week's work. Verified by `grep -c` against `mil_extension.ttl`: **0 occurrences
each**, and no other TTL in `setup/ontologies/` declares them either.

| term | kind | written at |
|---|---|---|
| `mil:Figure` | class | every `<figure>` in every S1000D module |
| `mil:hasFigure` | DataModule -> Figure | same |
| `mil:hasPartNumber` | datatype, on Tool / Part | the cross-document join key |
| `mil:hasURL` | datatype, on Figure | the resolved image URL |

I am flagging these so the group B additions are not mistaken for the cause.
`mil:hasPartNumber` is the one I would prioritise: the builder scopes part and
tool subjects per document specifically so cross-document identity is recovered
by joining on THAT literal, which makes it load-bearing rather than decorative.

**Group B — new, from S1000D week 2 (2(e)).** Fault-code nodes, cross-module
reference edges, IPD catalog items and planning intervals.

| term | kind | domain -> range | carries |
|---|---|---|---|
| `mil:FaultCode` | class | — | a BIT / fault code as printed |
| `mil:hasFaultCode` | object | DataModule -> FaultCode | |
| `mil:hasFaultCodeValue` | datatype | FaultCode -> string | the cross-document join key, same role as `hasPartNumber` |
| `mil:hasFaultCodeText` | datatype | FaultCode -> string | the printed fault text |
| `mil:refersToDataModule` | object | DataModule -> DataModule | an S1000D `dmRef` cross-reference |
| `mil:PlanningInterval` | class | — | a scheduled maintenance interval |
| `mil:hasPlanningInterval` | object | DataModule -> PlanningInterval | |
| `mil:hasIntervalValue` | datatype | PlanningInterval -> string | e.g. `180` |
| `mil:hasIntervalUnit` | datatype | PlanningInterval -> string | e.g. `days` |
| `mil:CatalogItem` | class | — | one IPD `catalogSeqNumber` line |
| `mil:hasCatalogItem` | object | DataModule / Figure -> CatalogItem | emitted from BOTH |
| `mil:hasItemNumber` | datatype | CatalogItem -> string | e.g. `0001` |
| `mil:hasQuantity` | datatype | CatalogItem -> integer | `xsd:integer` when the source text parses |
| `mil:hasManufacturerCode` | datatype | CatalogItem -> string | e.g. `ODM` |

`mil:CatalogItem` also carries `mil:hasPartNumber` and `mil:hasPart` (to the
existing `mil:Part` node), both already in the vocabulary or in group A.

## Group C — 3xx has no content kind, and that is now load-bearing

Surfaced while probing this week's seal, not by reading code. The classifier
logs it itself, once per module parsed:

> S1000D info code '320' falls in family 3xx, which has no `mil:*` content kind
> (maintenance-planning / scheduled-maintenance). Classifying as the root
> `mil:DataModule` — the data module will be indistinguishable from every other
> unclassified DM downstream. Adding a kind is a TBox change in
> `invincible-agent/setup/ontologies` and goes through the architect.

That message is `#53`'s fallthrough logging working exactly as designed, and it
is the only 3xx family in the MRAD fixture set. The other five modules (040,
421, 520, 720, 941) all classify.

### The ask, sourced from the issue in use (added 2026-10-02)

The issue in use is **S1000D Issue 4.2**, uniformly across all six modules —
every one declares
`xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-2/xml_schema_flat/<name>.xsd"`.
This matters because `mil_info_code_map.py`'s own docstring carries the
standing caution *"Confirm the info-code ranges against the actual S1000D issue
in use. The families are standardized but boundaries shift issue-to-issue"* —
so here is that confirmation, read off the data rather than from memory.

Each module's declared schema and authored `infoName`:

| info code | schema declared | `infoName` | currently classifies as |
|---|---|---|---|
| 040 | `descript.xsd` | Description | `mil:DescriptiveDataModule` |
| **320** | **`schedul.xsd`** | **Maintenance Planning Data** | **the bare root** |
| 421 | `fault.xsd` | Fault Isolation | `mil:FaultIsolationDataModule` |
| 520 | `proced.xsd` | Remove Procedure | `mil:ProcedureDataModule` |
| 720 | `proced.xsd` | Install Procedure | `mil:ProcedureDataModule` |
| 941 | `ipd.xsd` | Illustrated Parts Data | `mil:IllustratedPartsDataModule` |

The schema location is a **reliable discriminator in this corpus**: for the
five codes that do classify, the declared schema agrees with the kind the
first-digit table assigns, in all five cases. That is what licenses using it
for the sixth.

**Ask:** a content kind for the 320 module, `rdfs:subClassOf mil:DataModule`,
named from one of the two sourced candidates:

- **`mil:ScheduledMaintenanceDataModule`** — from the declared schema
  `schedul.xsd`, i.e. what the authoring tool says this module *is*.
- **`mil:MaintenancePlanningDataModule`** — from the authored
  `<infoName>Maintenance Planning Data</infoName>`, i.e. what the author says
  it is.

I lean to the **schema** name, because the schema is the structural contract
the parser reads while `infoName` is free text an author can write anything
into. Either is defensible and the name remains yours. Plus the matching entry
in `doc_tools/parsers/mil_info_code_map.py` once the class exists.

**One caution that is the real content of this ask.** `INFO_CODE_RANGES` keys
on the **first digit**, so adding a row for `"3"` assigns the kind to the
*whole* 3xx family. My evidence covers **info code 320 only** — one module.
The `UNMAPPED_FAMILIES` gloss that calls 3xx *"maintenance-planning /
scheduled-maintenance"* is now **sourced for 320** by `schedul.xsd`, and still
**unsourced for the family**: nothing in this repo contains the Issue 4.2
info-code table, so I cannot show that every 3xx code shares that meaning, and
in S1000D the 3xx band is broader than scheduled maintenance alone. So either:

1. give 3xx the kind at **sub-code granularity** (320, or the codes actually
   evidenced), leaving the rest of the family counted as fallthrough; or
2. confirm the family boundary against the Issue 4.2 info-code table and map
   the whole first digit.

Option 1 is what the evidence supports today. Option 2 needs a document I do
not have — if you have the 4.2 info-code list, that single table settles it
and also lets the `1xx` / `6xx` / `8xx` glosses in `UNMAPPED_FAMILIES` be
sourced the same way, since all four are currently unsourced prose.


**Why it matters more than it did last week:** the planning interval is the one
2(e) output that is NOT forward-reachable from a fault code (the 320 module
names the fault only in prose, so it coins no fault-code node). It is reached by
asking which module *refers to* the procedure the fault isolation cites — and
with 320 typed as the bare root, that query cannot be narrowed by kind. The walk
seal therefore asserts the reverse hop WITHOUT a kind constraint, which is
weaker than the forward hops, which do constrain on
`mil:ProcedureDataModule` and `mil:IllustratedPartsDataModule`. Give 3xx a kind
and that assertion can be tightened.

This is not blocking either. It is the one of the three groups I would
prioritise, because it is the only one where the missing term measurably weakens
an assertion that exists today.

## What is and is not broken while these are undeclared

**Not broken:** a direct SPARQL query on the predicate. The builder's own
comment records that Jena serves these graphs **without reasoning**, which is
why it emits both `mil:DataModule` and the specific content kind rather than
relying on `rdfs:subClassOf`. On that same basis an undeclared predicate still
matches a query that names it, and the week-2 walk seal
(`tests/test_s1000d_walk_seal.py`) passes against the in-memory graph without
any TBox present at all.

**Broken:** anything that routes by the class hierarchy rather than by naming
the predicate. A consumer asking for subclasses of a concept, or a resolver
picking a provider by class, cannot see a class that is not declared. I have
not measured a specific consumer failing on this — I am reporting the shape of
the gap, not a failure.

So: not urgent, and not a blocker for 2(e) landing. It should not stay open
indefinitely, because the longer the writer emits undeclared terms the more the
TBox stops being a description of what is in the graph.

## One judgement for you, not for me

`mil:refersToDataModule` is deliberately **untyped on its target**. The
referring module asserts only the edge; the referenced module types itself when
it is ingested. That means a `dmRef` to a module absent from the corpus leaves a
URI with an edge and no type — a dangling reference, which I think is the honest
representation (the reference genuinely exists in the document). If you would
rather it were typed `mil:DataModule` on sight, say so and I will change the
writer; I did not want to fabricate a node for a module nobody has ingested.

## Context

The S1000D parser situation is worth knowing if you touch this: there are TWO
S1000D parsers in doc-tools and the WIRED one is `s1000d_rdf.py`
(`doc_tools/assets/xml_ingestion.py:11,131`). `s1000d_ingest.py` is imported by
no asset. Any earlier S1000D result you may have been shown measured the
unwired one.
