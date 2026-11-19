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

## Citing a record — a bare number means *this* repo

`ADR-0001` means three different things in this fleet: this repo's memory-bounded PDF ingestion,
invincible-agent's `mem0-llm-decouple`, and dag-tools' `mesh-publishing-protocol`. So a citation
**names the owning repo** unless it is ours:

| Citation | Resolves to |
|---|---|
| `ADR-0100` | a record in this directory |
| `iagent:ADR-0041` | a record in invincible-agent's `docs/adr/` |
| `CO-DAGSTER`, `FL-BIG` | a dag-tools component or flow record, by its stable id |
| `AL-DMRA S4`, `AL-DCRA R1` | a dag-tools alignment record, cited together with the element it names |
| dag-tools `§4p.3` | a dag-tools decision. That lane keys its decisions to census sections, not to ADR numbers, and the repo is named in the citation |
| dag-tools roadmap row 8 | one numbered row of the dag-tools roadmap, which runs 1 to 16 |

dag-tools has **no ADR-numbered series this repo may cite**: the `dag:ADR-NNNN` form that
stood here was ours, not theirs, and is withdrawn. The ids above are stable and were supplied
by that lane at commit `823bf3480fbbfc1f4e41a0766e228507aacf4236`; **paths may move, ids may
not**. A part of dag-tools that is not on their id list has no record yet — ask by packet,
never invent an id.

**An id carries no repo name.** Applied 2026-11-19 on Chris's relay; in lane 02's packet the
rule is one of the **proposed rules of §4, "for lane 03 to confirm"**, so it is applied, not
confirmed. A repository does not prefix its ids with its own name; the composed build renders
each member's records under that member, with the member's name in the anchors; and an existing
prefixed id still matches the pattern. Every id this repo mints is bare — `ADR-0100`,
`CO-EXTRACT`, `FL-REVIEW`, `NE-01` — so nothing was renamed, and by the third clause nothing
would have had to be.

The `iagent:` and `dag-tools` forms in the table above are **citations of another member's
record**, not prefixes on ids of ours: an ADR number is not unique across members (`ADR-0001`
exists in two), so a citation has to say whose it is. **The packet accepts that form.** §4's
evidence line reads "decision ids, `prefix:ADR-NNNN`, or repository paths; must resolve", and
`iagent:ADR-0041` is `prefix:ADR-NNNN`. What is still open, and is with lane 02 rather than
decided here, is whether the prefix must be the member's name as the composition spells it —
this repo writes `iagent:`, and the member is `invincible-agent` — and whether a
section-of-a-guide citation such as `dag-tools §4p.3` is an accepted evidence form at all or
must be rewritten as a repository path with a line range. Both are [F-15](FOLLOW-UPS.md).

Externally-owned records this repo depends on are listed in **[FOREIGN.md](FOREIGN.md)**, with
the owning repo and what we use them for. Two numbers cited in this tree resolve in no repo on
this workstation (`ADR-0059`, `ADR-0066`); they are in [DEBT.md](DEBT.md), named rather than
silently repaired.

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
