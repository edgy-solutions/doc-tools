# Decision records — doc-tools

A decision record says what was decided, why, and what would make us revisit it. A commit
message says what changed. This directory exists because, measured on 2026-11-16, **about
seventy dated rulings in force in this repo had their only written statement in a code comment
or a test docstring** — long, careful comments that explain *why*, and that a refactor moving a
function silently relocates. The comment stays where the reader needs it. The record is for the
reader who does not yet know which file to open.

The records here are the written form of [the 2026-11-16 decision census][census], one record
per row. **Reading one record is not the same as reading the code**: every record cites the file
and line that implements it, at a pin, and the code is the thing that runs.

[census]: ../../sessions/ "placed, never committed — see DEBT.md §Gap 3"

## Statuses

The fleet's status vocabulary, as `docs/arch/README.md` declares it. Each record carries exactly
one on its **Status** line, and it is the strongest claim that is honest:

| Status | Means | What it takes |
|---|---|---|
| `measured` | A recorded measurement against real data or a running system stands behind it, and the measurement is citable. | A run, a report, a file. A test that *could* measure is not enough. |
| `built` | Code at the pin does it, pinned by a test. | A file and a line. |
| `accepted` | Ruled and in force. Implementation absent, partial, or owed by another lane. | Who ruled it and when. |
| `proposed` | Written down; not ruled. | — |

Two statuses on one line (`accepted + built`) mean the ruling and the code are both in hand and
agree. **Where they disagree, the record says so and its status is the code's** — and the row
also appears in [DEBT.md](DEBT.md).

A record whose ruling exists only as a code comment is **`accepted`, not `built`**, unless code
at the pin implements it. That distinction is the census's ⚑ mark and it is the reason this
directory exists; collapsing it would hide exactly what the census found.

Four records — the seam records [ADR-0230](ADR-0230-the-batch-column-map-seam.md),
[ADR-0231](ADR-0231-the-document-kind-seam.md),
[ADR-0232](ADR-0232-the-playbook-kind-seam.md) and
[ADR-0234](ADR-0234-the-training-workbench-seam.md) — **qualify** their status in words
(`built; one half accepted`, `accepted, blocked`, `accepted; partially built`,
`accepted (draft)`). A qualifier never replaces a status word and never softens one: it says
*which half* is in hand, because on a seam the two halves have different owners and a single
word would have to lie about one of them. Only these four carry one, and they are the four whose
subject is the seam itself.

## The pin

Every file-and-line citation in these records is read at
**`2b9e6cbc61178f7086cceade8614dca4d736150a`**. **A line number is valid only at its pin.** A
record that moves gets its pin re-read, or its citation drops to a file and a symbol.

## Citing a record

A bare number is this repo's own. A number from another repo **names that repo**, in the
ruled long form -- `invincible-agent ADR-0041`, never the short `iagent:ADR-0041`. The
convention, the 2026-11-16 ruling behind it, and the index of every external record this
tree cites are in **[ADRs in doc-tools](#adrs-in-doc-tools--the-citation-convention-and-the-index-of-what-we-cite)**
below.

The short-prefix table that stood here is **withdrawn**: it was written before that ruling
and contradicted it, so this merge took `main`'s side. Externally-owned records this repo
depends on are also listed in [FOREIGN.md](FOREIGN.md), and the two numbers that resolve in
no repo on this workstation are named in [DEBT.md](DEBT.md) rather than silently repaired.

## Why this series starts at 0100

Measured at the pin: **75 tracked files in this repo cite an `ADR-00NN` number**, spanning 20
distinct numbers in the `0001`–`0066` band, and **eighteen of those twenty mean
invincible-agent's records** — cited bare, from before the convention above existed. Numbering
this series `0002`, `0003`, … would therefore mint a doc-tools `ADR-0004` while `AGENTS.md`
§AITool Binding Plane says `ADR-0004` meaning `iagent:ADR-0004`, and the collision would be
invisible to a reader and to any tool.

So **this series begins at `ADR-0100`**, and the `0002`–`0099` band is left empty on purpose.
Nothing new can be confused with a citation already in the tree. Qualifying the existing bare
citations is a separate, mechanical change with its own PR — tracked in
[FOLLOW-UPS.md](FOLLOW-UPS.md) — and renumbering another repo's records was never ours to do.

`ADR-0001` (June 2026, `Draft / Proposed`) predates the `ADR-NNNN-slug.md` filename shape the
rest of the fleet uses and was renamed to match it; its content is untouched.

## The registers

| Register | What it holds |
|---|---|
| [DEBT.md](DEBT.md) | where a ruling and the code disagree, where a status line has gone stale, and the citations that resolve nowhere |
| [FOLLOW-UPS.md](FOLLOW-UPS.md) | what is owed — by this lane, by another lane, or by a measurement that has not been taken |
| [FOREIGN.md](FOREIGN.md) | every externally-owned decision record this repo depends on, with its owner |

The architecture records that cite these are in [`docs/arch/`](../arch/README.md): three
component records, one flow record, and this repo's half of the not-established list.

## Index

### Scope and shape of the repo

| Record | Status |
|---|---|
| [ADR-0100 — doc-tools is a Dagster code location, not a service](ADR-0100-doc-tools-is-a-code-location-not-a-service.md) | accepted + built |
| [ADR-0101 — processable kinds are published by PUT from inside the pod](ADR-0101-processable-kinds-are-published-not-served.md) | built |
| [ADR-0102 — every ingestion step is an asset, wired as a declarative component](ADR-0102-assets-and-declarative-components.md) | built |
| [ADR-0103 — substrate priming lives in the platform chart, not here](ADR-0103-substrate-priming-is-the-platforms.md) | built |
| [ADR-0104 — a new domain is a BAML schema and a plugin, never raw litellm](ADR-0104-a-new-domain-is-a-schema-and-a-plugin.md) | accepted + built |
| [ADR-0105 — the AITool binding plane travels as a unit if the repo splits](ADR-0105-the-aitool-binding-plane-travels-as-a-unit.md) | accepted |
| [ADR-0106 — `doc_tools/batch/` is an operator CLI, not the pipeline](ADR-0106-batch-is-an-operator-cli-not-the-pipeline.md) | built |
| [ADR-0107 — no fetch mode, and the scorer never normalises](ADR-0107-no-fetch-mode-and-the-scorer-never-normalises.md) | accepted + built |
| [ADR-0108 — dependencies through `uv add`, never pip](ADR-0108-dependencies-through-uv-never-pip.md) | accepted |

### Kinds, domains and ownership

| Record | Status |
|---|---|
| [ADR-0110 — the platform owns what a kind is; doc-tools owns what it runs](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md) | accepted + built |
| [ADR-0111 — a disputed registry value goes to lane 01 as a packet, not an edit](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md) | accepted |
| [ADR-0112 — a kind may declare no domain, and origin is resolved by evidence](ADR-0112-a-kind-may-declare-no-domain.md) | built |
| [ADR-0113 — where the manifest and the kind disagree on domain, the kind wins](ADR-0113-the-kind-wins-over-the-manifest.md) | built |
| [ADR-0114 — `xml` is held out of the door until a drop proves the path](ADR-0114-xml-is-held-out-until-a-drop-proves-it.md) | accepted + measured |
| [ADR-0115 — the hold on `playbook` is lifted](ADR-0115-the-playbook-hold-is-lifted.md) | accepted + built |
| [ADR-0116 — a sensor cannot declare a content kind; the drop path carries it](ADR-0116-a-sensor-cannot-declare-a-kind.md) | accepted + built |
| [ADR-0117 — one general manufacturing kind, not a kind per step class](ADR-0117-one-general-manufacturing-kind.md) | accepted + built |

### Provenance, identity and precedence

| Record | Status |
|---|---|
| [ADR-0120 — `ingest_id` is `sha256:<64 hex>`, checked where the block is built](ADR-0120-ingest-id-is-one-canonical-spelling.md) | built |
| [ADR-0121 — a null `domain_type` is not a defect](ADR-0121-a-null-domain-type-is-not-a-defect.md) | built |
| [ADR-0122 — `extracted_count` and `extracted_total` are two fields, not a fraction](ADR-0122-extracted-count-is-not-a-fraction.md) | built |
| [ADR-0123 — the stage post is a run's last act, and stages never move backwards](ADR-0123-the-stage-post-is-a-runs-last-act.md) | built |
| [ADR-0124 — header identity precedence: the text layer has primacy](ADR-0124-header-identity-precedence.md) | built + measured |
| [ADR-0125 — before the title read, a pdf runs parse and text layer only](ADR-0125-a-pdf-runs-parse-only-before-the-title-read.md) | built |
| [ADR-0126 — the leaf-read output shape, and who owns the leaf-source mapping](ADR-0126-the-leaf-read-output-shape.md) | built |
| [ADR-0127 — a title signal has an order, not a score](ADR-0127-a-title-signal-has-an-order-not-a-score.md) | built |
| [ADR-0128 — `evidence_ref` is served as is, and nothing else is served](ADR-0128-evidence-ref-is-served-as-is.md) | accepted + built |
| [ADR-0129 — a customer part number column is never an affected part](ADR-0129-a-customer-part-number-is-never-an-affected-part.md) | built + measured |
| [ADR-0130 — a null row value is excluded from scoring, and says nothing about the document](ADR-0130-a-null-row-value-is-excluded-from-scoring.md) | measured |
| [ADR-0131 — the wire half validates a steward's row edits against the server's batch](ADR-0131-row-edits-are-validated-against-the-servers-batch.md) | built |
| [ADR-0132 — `notice_identity` is the dedupe key here and the decision elsewhere](ADR-0132-notice-identity-is-the-key-not-the-decision.md) | accepted + built |

### Graph write conventions

| Record | Status |
|---|---|
| [ADR-0140 — a document is isolated in its own named graph, replaced whole](ADR-0140-one-named-graph-per-document-replaced-whole.md) | built |
| [ADR-0141 — producers with different reproducibility must not share a graph](ADR-0141-reproducibility-decides-the-graph.md) | built + measured |
| [ADR-0142 — the read side scopes to the union, in one place](ADR-0142-the-read-side-union-lives-in-one-place.md) | built |
| [ADR-0143 — RDF in Jena's default graph is invisible to the mesh](ADR-0143-the-default-graph-is-invisible.md) | built + measured |
| [ADR-0144 — the vocabulary path appends; only the instance path replaces](ADR-0144-the-vocabulary-path-appends.md) | built |
| [ADR-0145 — domain labels go on nodes, never on relationships](ADR-0145-domain-labels-go-on-nodes-only.md) | accepted + built |
| [ADR-0146 — the instance-graph supersede key is the slug](ADR-0146-the-supersede-key-is-the-slug.md) | built |
| [ADR-0147 — `mesh:` is the canonical namespace prefix](ADR-0147-mesh-is-the-canonical-prefix.md) | accepted + built |
| [ADR-0148 — one `MIL` namespace across every standard parser](ADR-0148-one-mil-namespace-across-parsers.md) | built |
| [ADR-0149 — a parser returns serialized RDF, never a file path](ADR-0149-a-parser-returns-rdf-not-a-path.md) | built |
| [ADR-0150 — a glossary-term URN uses the short name; the ontology URI is a property](ADR-0150-a-glossary-term-urn-uses-the-short-name.md) | built |
| [ADR-0151 — semantic tags are late-bound by polling DataHub, through HITL](ADR-0151-semantic-tags-are-late-bound-through-hitl.md) | built |
| [ADR-0152 — no HITL for code-controlled tool registrations](ADR-0152-no-hitl-for-code-controlled-registrations.md) | built |
| [ADR-0153 — every legacy extractor emits one uniform contract](ADR-0153-one-uniform-contract-for-legacy-extractors.md) | built |

### Training and concepts

| Record | Status |
|---|---|
| [ADR-0160 — a `Concept` is keyed on a hash, because Neo4j carries no uniqueness on name](ADR-0160-a-concept-is-keyed-on-a-hash.md) | built |
| [ADR-0161 — stale `TEACHES` edges are replaced, in one write](ADR-0161-teaches-edges-are-replaced-in-one-write.md) | built |
| [ADR-0162 — a concept no slide teaches gets neither a proposal nor a canonical](ADR-0162-a-concept-no-slide-teaches-is-not-aligned.md) | built |
| [ADR-0163 — alignment direction, and where a canonical concept is created](ADR-0163-alignment-direction-and-who-creates-a-canonical.md) | accepted + built |
| [ADR-0164 — concepts are extracted one call per section group](ADR-0164-one-concept-call-per-section-group.md) | built |
| [ADR-0165 — the concepts pass implements the contract's rules, not its own](ADR-0165-the-contract-decides-the-concepts-rules.md) | accepted |

### Prompts and extraction configuration

| Record | Status |
|---|---|
| [ADR-0170 — prompts are files in the repo, and the file path is production](ADR-0170-prompts-are-files-and-the-file-path-is-production.md) | built |
| [ADR-0171 — production must not depend on the live Langfuse path](ADR-0171-production-does-not-depend-on-langfuse.md) | accepted + built |
| [ADR-0172 — the drift check reads the same env var the runtime serves](ADR-0172-the-drift-check-reads-the-runtimes-own-var.md) | built |
| [ADR-0173 — the BAML prompt layout is fixed](ADR-0173-the-baml-prompt-layout-is-fixed.md) | accepted |
| [ADR-0174 — a manufacturing overlay field is data, not code](ADR-0174-an-overlay-field-is-data-not-code.md) | built |
| [ADR-0175 — proprietary prompt text goes through `PROMPT_SOURCE`, not the repo](ADR-0175-proprietary-prompt-text-is-not-committed.md) | accepted |
| [ADR-0176 — tables are converted to Markdown grids for the global pass](ADR-0176-tables-become-markdown-grids.md) | built |
| [ADR-0177 — config names the case; code implements the mechanism](ADR-0177-config-names-the-case.md) | accepted |

### The corpus gate

| Record | Status |
|---|---|
| [ADR-0180 — raw verdicts are advisory and never the verdict](ADR-0180-raw-verdicts-are-advisory.md) | built |
| [ADR-0181 — a declaration must be keyed to the field under test](ADR-0181-a-declaration-is-keyed-to-its-field.md) | built |
| [ADR-0182 — the written arm compares canonical forms, not strings](ADR-0182-the-written-arm-compares-canonical-forms.md) | built + measured |
| [ADR-0183 — DECLINED is the third bucket, and the strict verdict grants nothing](ADR-0183-declined-is-the-third-bucket.md) | built + measured |
| [ADR-0184 — a red line says which fires declared](ADR-0184-a-red-line-says-which-fires-declared.md) | built |
| [ADR-0185 — `pre_roll`'s `checked: False` is by design](ADR-0185-pre-roll-checked-false-is-by-design.md) | accepted |
| [ADR-0186 — the gate clock is off, and a fire is a deliberate act](ADR-0186-the-gate-clock-is-off.md) | accepted + measured |
| [ADR-0187 — a hand fire takes the roll lock, not a new lock](ADR-0187-a-hand-fire-takes-the-roll-lock.md) | accepted + built |
| [ADR-0188 — the corpus denominator is a rate over ten notices, not a count](ADR-0188-the-denominator-is-a-rate-not-a-count.md) | measured |
| [ADR-0189 — the published report is the authority; a fire log is raw](ADR-0189-the-published-report-is-the-authority.md) | measured |
| [ADR-0190 — ground truth for the TI second table: devices only](ADR-0190-ground-truth-ti-page-two-is-devices-only.md) | measured |

### CI, rolls and releases

| Record | Status |
|---|---|
| [ADR-0200 — a stacked PR runs no CI gate](ADR-0200-a-stacked-pr-runs-no-ci-gate.md) | measured |
| [ADR-0201 — the build-skip allowlist is deliberately not widened](ADR-0201-the-build-skip-allowlist-is-not-widened.md) | accepted |
| [ADR-0202 — `expectImage` is read back off the settled pods](ADR-0202-expect-image-is-read-off-the-pods.md) | measured |
| [ADR-0203 — the `expectImage` patch is part of the roll](ADR-0203-the-expect-image-patch-is-part-of-the-roll.md) | accepted + built |
| [ADR-0204 — show the values diff before a roll, through the sanctioned path](ADR-0204-show-the-values-diff-before-a-roll.md) | accepted + built |
| [ADR-0205 — print a length and a hash prefix, never a secret value](ADR-0205-a-length-and-a-hash-prefix-never-a-value.md) | accepted + built |
| [ADR-0206 — Python through this repo's venv, and the suite from PowerShell](ADR-0206-the-venv-and-powershell-rule.md) | measured |
| [ADR-0207 — CI's interpreter is pinned to 3.12](ADR-0207-cis-interpreter-is-pinned.md) | built + measured |
| [ADR-0208 — only the owning lane commits in this repo](ADR-0208-only-the-owning-lane-commits.md) | accepted |
| [ADR-0209 — session files are placed, never committed](ADR-0209-session-files-are-placed-never-committed.md) | accepted |
| [ADR-0210 — worktrees live outside the scratchpad](ADR-0210-worktrees-live-outside-the-scratchpad.md) | accepted |
| [ADR-0211 — the Dockerfile is generated inside the workflow](ADR-0211-the-dockerfile-is-generated-in-the-workflow.md) | built |
| [ADR-0212 — dynamic Cypher is bounded to one interpolated name](ADR-0212-dynamic-cypher-is-bounded-to-one-name.md) | accepted |

### Retractions and standing cautions

Records that say what **not** to believe. A retraction is a decision, and an unwritten one gets
re-cited.

| Record | Status |
|---|---|
| [ADR-0220 — the "136 of 402" PDN figure is retracted](ADR-0220-the-136-of-402-figure-is-retracted.md) | measured |
| [ADR-0221 — the PDN diagnostic grades a stored artifact, not an extractor change](ADR-0221-the-diagnostic-grades-a-stored-artifact.md) | measured |
| [ADR-0222 — the 2026-09-21 validation is the authority for `table_text_layer`](ADR-0222-the-corpus-validation-is-the-authority.md) | measured |
| [ADR-0223 — the mesh-slots request document records the correction, not the request](ADR-0223-the-mesh-slots-document-records-the-correction.md) | measured |
| [ADR-0224 — the scrub ledger is a recommendation, not a ruling](ADR-0224-the-scrub-ledger-is-a-recommendation.md) | proposed |
| [ADR-0225 — a local checkout is not the deployed contract](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md) | measured |

### The seams — one record per contract, as each declares itself

| Record | Status |
|---|---|
| [ADR-0230 — the batch column map, and the two header fields lane 1 serves](ADR-0230-the-batch-column-map-seam.md) | built; one half accepted |
| [ADR-0231 — the `document` kind is declared here and not routable end to end](ADR-0231-the-document-kind-seam.md) | accepted, blocked |
| [ADR-0232 — the `playbook` kind: the contract's status line is stale](ADR-0232-the-playbook-kind-seam.md) | accepted; partially built |
| [ADR-0233 — the scrub ledger seam is a contract with no scrubber](ADR-0233-the-scrub-ledger-seam.md) | proposed |
| [ADR-0234 — the training workbench contract, and which side owns which write](ADR-0234-the-training-workbench-seam.md) | accepted (draft) |
| [ADR-0235 — the notice-identity seam, and whose docstring wins](ADR-0235-the-notice-identity-seam.md) | accepted + built |

### Before this series

| Record | Status |
|---|---|
| [ADR-0001 — memory-bounded `hi_res` PDF ingestion](ADR-0001-memory-bounded-hi-res-pdf-ingestion.md) | Draft / Proposed, June 2026 — predates the status vocabulary above |

---

<!--
The part below arrived on `main` in 816eba9 ("a cross-repo ADR citation names its repo"),
which created this same path independently of the 0100 series. The merge of 2026-11-21 hit
it as an add/add conflict and resolved it by keeping BOTH parts: this directory's own README
first, then the citation convention and the index of what we cite. Nothing was dropped
except the superseded short-prefix table, named above.
-->

# ADRs in doc-tools — the citation convention, and the index of what we cite

**Ruled 2026-11-16:** *"Every ADR citation in doc-tools names its repo (for example
invincible-agent ADR-0038)."* **Clarified the same day, by the architect, for all lanes:**
*"an ADR number cited from another repo names that repo. Inside a repo, a bare number means
that repo's own ADR and needs no change. Do not rewrite a repo's internal citations."*

## The convention

**A number from another repo names that repo:** write **`<repo> ADR-00NN`**. Never the old
short spelling `iagent ADR-00NN`.

```
    invincible-agent ADR-0041      dag-tools ADR-0001      <- qualified, always
    ADR-0001                       <- means THIS repo: doc-tools ADR-0001
```

**A bare number is doc-tools' own**, and stays bare. We have exactly one record (below), so
in practice a bare citation here is either `ADR-0001` or a mistake.

The qualified form applies everywhere a cross-repo citation is read — prose, comments,
docstrings, contracts, chart comments, log messages and test names alike. Applied across
this tree on 2026-11-16: **210 citations in 50 files, every one of them to another repo's
record**. Two scopes were deliberately left alone: `sessions/`, because a dated report is a
record of what was said at the time and rewriting one would falsify it; and doc-tools' own
`ADR-0001`, which the clarification above confirms needs no qualifier inside this repo.

**Why it is not pedantry.** `ADR-0001` names **three different decisions**:

| Citation | Decision |
|---|---|
| `doc-tools ADR-0001` | Memory-bounded `hi_res` PDF ingestion ([here](0001-memory-bounded-hi-res-pdf-ingestion.md)) |
| `invincible-agent ADR-0001` | `mem0` / LLM decouple |
| `dag-tools ADR-0001` | The mesh publishing protocol |

Three repos number independently from 0001. Inside this repo the bare form resolves by the
rule above, but **across repos it is ambiguous** — and that is the usual case here:
doc-tools holds **one** ADR of its own and cites **seventeen** that belong to
invincible-agent, so a citation picked at random is almost certainly not ours.

## doc-tools' own records

| Record | Status |
|---|---|
| [`doc-tools ADR-0001`](0001-memory-bounded-hi-res-pdf-ingestion.md) — memory-bounded `hi_res` PDF ingestion | Draft / Proposed, 2026-06-10 |

That is the whole list **of the `0001` series**; the `0100` series indexed above holds the
rest, and the two are one directory. Everything else this repo's architecture rests on is
either another
repo's ADR (below), a dated ruling recorded in code, a contract under
[`../contracts/`](../contracts/), or an agent convention in
[`AGENTS.md`](../../AGENTS.md) / [`CLAUDE.md`](../../CLAUDE.md).

## invincible-agent records this repo cites

Resolved file by file against `invincible-agent/docs/adr/` on 2026-11-16. The count is
citations in this tree, `sessions/` excluded.

| Citation | Subject | Cites | Anchored in |
|---|---|---|---|
| `invincible-agent ADR-0004` | Predicate-graph routing | 3 | `AGENTS.md` §AITool Binding Plane |
| `invincible-agent ADR-0006` | Verb registry location | 17 | `doc_tools/assets/aitool_linker.py` |
| `invincible-agent ADR-0008` | Routing fallback policy | 2 | `doc_tools/assets/aitool_linker.py` |
| `invincible-agent ADR-0009` | Sunset classification axes | 9 | `doc_tools/assets/aitool_linker.py` |
| `invincible-agent ADR-0017` | Presentation as predicate | 1 | `doc_tools/assets/aitool_linker.py` |
| `invincible-agent ADR-0018` | Symmetric SPO routing | 1 | `doc_tools/plugins/manufacturing.py` |
| `invincible-agent ADR-0019` | Ontology routing substrate | 8 | `doc_tools/assets/aitool_linker.py` |
| `invincible-agent ADR-0021` | Deterministic content-kind selection at ingest | 40 | `doc_tools/utils/content_kind.py` |
| `invincible-agent ADR-0034` | Trust lifecycle / admission policy | 11 | `doc_tools/utils/provenance_stamp.py` |
| `invincible-agent ADR-0035` | Two planes: process and data, with embedded provenance | 1 | `doc_tools/plugins/sustainment.py` |
| `invincible-agent ADR-0037` | Ratified-docs corpus, help-surface grounding | 2 | `doc_tools/utils/runbook_ingest.py` |
| `invincible-agent ADR-0038` | Telemetry as provenance projection (Langfuse standard) | 10 | `doc_tools/config/telemetry-mapping.yaml` |
| `invincible-agent ADR-0041` | User-contributed documents: ingest on arrival, provenance-gated truth | 93 | `doc_tools/utils/ingest_id.py`, `doc_tools/components/document_parser.py` |
| `invincible-agent ADR-0046` | LangGraph graphs as registered mesh verbs | 1 | `tests/fixtures/s1000d/mrad/GROUND-TRUTH.json` |
| `invincible-agent ADR-0060` | Consumers read through the mesh, never the stores | 3 | `docs/contracts/training-workbench.md` |
| `invincible-agent ADR-0063` | Field kinds, from OpenDDIL | 8 | `doc_tools/utils/content_kind.py` |

`invincible-agent ADR-0041` and `invincible-agent ADR-0021` carry two thirds of all
citations between them: they are the two external records a newcomer must read before
touching the ingest path.

## The two numbers that do not resolve

### `ADR-0059` — UNRESOLVED. It is not an ADR.

The number was carried in the **title of the architect's "RESTORE TRAINING INGESTION"
packet of 2026-10-23**, and no `ADR-0059` file exists in any repo. This is measured, not
assumed: invincible-agent's own
`docs/adr/ADR-0060-consumers-read-through-the-mesh-never-the-stores.md` §Numbering records

> *"No ADR-0059 or ADR-0060 file exists on any pushed branch at `a31b61cb`, checked with
> `git log --remotes --all -- 'docs/adr/ADR-0059*' 'docs/adr/ADR-006*'`. […] 0059 is claimed
> in prose by the training 'restore training ingestion' packet."*

— and 0060 was claimed the same way by a contract, then **taken by a different decision**,
which is precisely the hazard. Corrected 2026-11-16: the citations in
[`../contracts/training-workbench.md`](../contracts/training-workbench.md) and
`tests/test_kind_registry.py` now name **the dated packet** and mark the number unresolved.
**Do not cite `ADR-0059`.** If the architect files it, add the row above and re-point both
sites.

### `invincible-agent ADR-0066` — being drafted.

Owned by invincible-agent and **still in draft**, so no file resolves yet. There is no live
citation of it in this tree — the only mention is
`sessions/2026-11-05-packet-to-architect-from-7f-lifecycle-status-names-an-emitter-this-repo-does-not-contain.md`,
which is a dated report and stays as written. Any new citation must read
**`invincible-agent ADR-0066 (in draft)`** so a reader is not sent after a file that is not
there yet.

### Also cited only in `sessions/`

`invincible-agent ADR-0065` (obsolescence is a process; PCN/PDN notices are its intake) is
cited in dated reports but nowhere in the live tree. It resolves; it simply has no live
citation to qualify.

## Keeping it true

- `invincible-agent/docs/adr/` held **64 ADR files** on 2026-11-16, numbered 0001–0067, with
  **0058, 0059 and 0066 absent** (0058 exists on `lane/74-adr-0058-draft` only).
- A citation is a cross-repo dependency. **A local checkout is not the deployed contract** —
  resolve a number with `git show origin/master:docs/adr/…` in the owning repo, not from
  whatever is in a sibling working tree.
- Mesh-wide decisions that span tools are recorded in `dag-tools` and cited from here, so
  expect `dag-tools ADR-00NN` rows to appear in this table over time.

## Five citations deliberately still unqualified

`charts/doc-tools/values.yaml` and `charts/doc-tools/values-sandbox.yaml` carry five
cross-repo citations in **comments** that this pass left as bare numbers: ADR-0021,
ADR-0034 (twice), ADR-0038 and ADR-0041 — all invincible-agent's.

They are held back, not missed. `corpus-gate-verdict` is
`if: needs.changes.outputs.charts == 'true'`, so **editing a comment in a chart file arms
the gate guard** against the committed `docs/corpus-gate/latest.json`. Measured on
[#226](https://github.com/edgy-solutions/doc-tools/pull/226) on 2026-11-16: the qualified
comments made the job run and fail in 13s on the standing TYC `mfr` blocker — a verdict
that PR neither introduced nor could fix. Qualifying a comment is not worth an exempted
gate or a red check on a docs change.

**Qualify them in the next PR that touches `charts/` for a real reason** — a pin bump,
which carries a report of its own. Then this section goes away.
