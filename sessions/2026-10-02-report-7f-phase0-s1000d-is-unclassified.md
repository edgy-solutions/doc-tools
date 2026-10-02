# Phase 0 — measured: the S1000D path emits no content kinds at all

**Measured 2026-10-02 on `main` @ `a4b8a91`.** Instrument:
`scratchpad/phase0_measure.py`, which loads
`doc_tools/parsers/s1000d_rdf.py` **by file path** (so
`doc_tools/__init__.py`'s `from .definitions import defs` never runs and no
Dagster import happens) and drives `S1000dGraphBuilder.parse_data_module`
over all six mock modules at `C:\tmp\overnight-1002\M6\`. Run with
`.venv\Scripts\python.exe` from PowerShell (rdflib 7.6.0, lxml present).

This is the **real ingest-path builder** — the one
`doc_tools/assets/xml_ingestion.py:11,131` wires for `'s1000d'` — not
`s1000d_ingest.extract_facts`, which no asset imports.

---

## 1. The headline: zero classified kinds. Confirmed, and total.

| module (info code) | triples | `rdf:type` objects emitted |
|---|---|---|
| 040A | 4 | `mil:DataModule` |
| 320A | 4 | `mil:DataModule` |
| 421A | 4 | `mil:DataModule` |
| 520A | 6 | `mil:DataModule`, `mil:Tool` |
| 720A | 8 | `mil:DataModule`, `mil:Tool`, `mil:Part` |
| 941A | 8 | `mil:DataModule`, `mil:Figure` |

Aggregate `rdf:type` objects across all six: `mil:DataModule` ×6,
`mil:Tool` ×2, `mil:Part` ×1, `mil:Figure` ×1.

**Classified data-module kinds emitted — Descriptive / Procedure /
FaultIsolation / IPD: NONE.**

So the earlier "5 of 6 correct, 1 generic" result measured
`s1000d_ingest.extract_facts`, which is off the ingest path. On the live path
the fault-isolation module, the two procedures and the IPD are
indistinguishable from the descriptive module. The 320 (maintenance-planning)
info code is not an outlier — it is the one case where the unused parser and
the used one happen to agree.

The authoring agent's `infoCode="320"` choice is not a fault and must not be
changed: 3xx is the only unmapped family in the mock, so it is the only input
that exercises `mil_info_code_map.py`'s silent fallthrough.

## 2. Every DMC URI differs from the authored DMC — six for six

| authored (filename) | builder emits |
|---|---|
| `ODMRAD-A-34-10-01-00A-040A-A` | `ODMRAD-A-34-1-0-01-040-A-A` |
| `ODMRAD-A-34-10-01-00A-320A-A` | `ODMRAD-A-34-1-0-01-320-A-A` |
| `ODMRAD-A-34-10-01-00A-421A-A` | `ODMRAD-A-34-1-0-01-421-A-A` |
| `ODMRAD-A-34-10-01-00A-520A-A` | `ODMRAD-A-34-1-0-01-520-A-A` |
| `ODMRAD-A-34-10-01-00A-720A-A` | `ODMRAD-A-34-1-0-01-720-A-A` |
| `ODMRAD-A-34-10-01-00A-941A-A` | `ODMRAD-A-34-1-0-01-941-A-A` |

Two independent defects compose here, and the measurement separates them:

1. **`disassyCode` is dropped entirely.** The authored `00A` segment
   (disassyCode `00` + variant `A`) is absent from every emitted URI.
   `s1000d_rdf.py:67-69` reads only the short names `disasCode` /
   `disasCodeVariant`; these S1000D 4.x modules spell them `disassyCode` /
   `disassyCodeVariant`, the attribute lookup returns empty, and the inline
   join's `if p` filter silently drops the position. This is the bug the
   authoring agent found, now measured rather than read.
2. **The shape is wrong independently of (1).** `10` becomes `1-0` —
   `subSystemCode` and `subSubSystemCode` are emitted as separate hyphen
   groups where `assemble_canonical_dmc` concatenates them, and the same
   applies to `info`+`ivar`. So even with the attribute fallback added, the
   inline join at `s1000d_rdf.py:45-66` still cannot produce the authored
   DMC. Fixing (1) alone changes every URI and *still* leaves the two parsers
   disagreeing — the worst of the three available states.

**Consequence for the architect's 2(c) condition:** since no emitted URI
currently matches its authored DMC, every existing S1000D `dmc-` URI in the
live graph is already wrong. The migration question is therefore not "is the
new shape worth the churn" but "how many wrong URIs exist." The live count is
still owed (§5).

## 3. Shared subjects — the collision is real and already instantiated

- **`mil:part-ODM-SE-0001` is coined by two of the six modules** (520A and
  720A) and merges into one node. Across the six, the combined graph holds 33
  triples against 34 summed per-document — one triple collapsed by exactly
  this merge.
- **`mil:fig-fig_0`** is the worst case available: the mock's `<figure>`
  carries no `id`, so `s1000d_rdf.py:106` falls back to `f"fig_{idx}"` and
  coins a document-independent subject named after a loop index. **Any**
  second publication with an unlabelled figure collides on this exact URI.
- Full subject inventory: `part-` = `ODM-AM-0001`, `ODM-SE-0001`; `fig-` =
  `fig_0`.

This confirms the defect is not about the mock. Two real publications naming
the same part number merge today, and `fig_0` collides between any two
documents — a customer's second manual hits it.

Related, measured: tools and spares share the `part-{pn}` prefix
(`s1000d_rdf.py:82` and `:91`), so one part number appearing in both
`reqSupportEquip` and `reqSpares` yields a single subject typed both
`mil:Tool` and `mil:Part`. Not instantiated in these six — `ODM-SE-0001` is a
tool in both documents that name it — but the prefix collision is live.

## 4. The fault walk: the data is in the source and none of it reaches the graph

Predicates the builder emits, over all six: `rdf:type` ×9, `rdfs:label` ×7,
`mil:hasInfoCode` ×6, `mil:hasSNS` ×6, `mil:requiresTool` ×2,
`mil:hasFigure` ×1, `mil:hasPart` ×1, `mil:hasURL` ×1. **Total 33 triples.**

What the source carries and the builder discards:

- **A fault code.** `421A` has `<faultCode faultCodeValue="AM-BIT-017">` plus
  `faultCodeText`, `isolationProcStep`, `test`/`answer`. No `FaultCode` node
  is emitted and no predicate references the value.
- **Five content cross-references** (`dmRef` → `dmRefIdent` → `dmCode`,
  excluding each module's one `brexDmRef`): 320→520, 320→720, 421→520,
  421→720, 720→941. Zero cross-reference edges are emitted.
- **Three parts-list items.** `941A` has a `catalogSeqNumberGroup` with
  `catalogSeqNumber item="0001"/"0002"/"0003"`. Only one `mil:hasPart` edge
  exists in the whole corpus, from 720A.

The walk the OpenDDIL dry run needs — fault code → fault-isolation module →
procedure → IPD → parts — is **fully present in the source and fully absent
from the graph**: `AM-BIT-017` (421A) → 720A → 941A → three catalogue items.
Every hop exists as a `dmRef` the builder does not read. This is §2.6 of the
plan, and the measurement confirms it is a feature gap, not a parser bug.

## 5. The live `dmc-` count is ZERO — 2(c) is free

The architect's condition for ruling 2(c) free was the live count. Measured
2026-10-02 against sandbox Jena (`iagent-fuseki-0`, `ns/sandbox`), read-only
SPARQL over `/ds/sparql`, no writes of any kind:

| query | result |
|---|---|
| distinct `mil:dmc-*` subjects, all named graphs | **0** |
| distinct `mil:dmc-*` subjects, default graph | **0** |
| named graphs holding any `dmc-` subject | **none** |
| distinct subjects typed with any `mil:*` class | **0** |
| `part-`/`fig-` subjects shared across >1 graph | **none** |

**There is no migration to run.** The shape change in 2(c) is free, and this
is the cheapest moment it will ever be — the next real publication makes it
expensive.

The zero is not a misdirected query. The same endpoint in the same session
returns **18,756 triples across 11 named graphs** (`SUSTAINMENT` 10,887,
`MAINTENANCE` 4,959, `SUSTAINMENT_INSTANCES` 1,904, `MESH` 345, …) and 16,782
in the default graph. 17 distinct `mil#` subjects exist, but they are
**vocabulary** — the `owl:Class` declarations from `mil_extension.ttl` — not
instances; the top `rdf:type` objects corpus-wide are `owl:Class` (1,523),
`owl:Restriction` (707) and `s3kl:*`. Nothing is typed as a `mil:*` class.

**A second finding falls out of this, material to Phase 3/4.** There are **no
`urn:doc:*` named graphs at all**. The XML job's `upload_to_jena` writes per
document to `urn:doc:{s3_key}` (`semantic_assets.py:605`), so the absence
means the XML ingest path has never landed a triple in sandbox Jena. The
40051 demo fixture is not there either. So the S1000D route is not merely
unclassified — it is **unproven end-to-end in sandbox**, and Phase 3/4 should
be planned as a first run, not a repeat. (The PCN/PDN path is unaffected: it
writes instances to `SUSTAINMENT_INSTANCES`, which holds 1,904 triples.)

Phase 0 itself wrote nothing anywhere: no upload, no credentials read, no
graph mutation. The cluster contact was five read-only SPARQL SELECTs.

## 6. Note on an earlier figure

A first pass at the cross-reference inventory reported 11 `dmRef` elements.
That was `grep '<dmRef'`, which also matches `<dmRefIdent`. The correct
figures are 11 `dmRef`/`dmRefIdent` lines, 6 `brexDmRef` boilerplate refs,
and **5 content cross-references** as listed in §4.
