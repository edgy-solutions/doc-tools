# What this repo does not establish

This is doc-tools' half of the merged list the two-day order asks for. Every row is something
a reader of these records will reasonably expect to be settled and that **the code, the charts
and the tests at [the pin](README.md) do not settle**. A row is here instead of being guessed
at, and no row is a to-do: it is a statement about the evidence.

Each row has an id so another lane can cite it without quoting it. `NE-` is doc-tools'
prefix. The **Kind** column says what would settle it:

- `cluster` — only a running system can answer it, and these records read no cluster.
- `measurement` — a run nobody has made, or has not recorded.
- `another repo` — the fact belongs to a tree this record did not read.
- `undecided` — nobody has ruled; the code is silent because no decision exists.
- `unread` — in this tree, readable, and not yet read at this pin.

| Id | What is not established | Kind | Where it bites |
|---|---|---|---|
| NE-01 | Which Dagster sensors are RUNNING in any deployed instance. A stored status overrides `default_status`, and the instance config is not in git. | `cluster` | [CO-EXTRACT §3](components/extraction-pipeline.md) |
| NE-02 | Whether anything answers the HTTP liveness and readiness probes. The container serves gRPC on 3030; the probes and `containerPort` are HTTP `/` on 8080, and no HTTP server on 8080 was found in the chart. Whether `doc_tools.definitions` starts the API app in-process was not traced. | `unread` | [CO-EXTRACT §21](components/extraction-pipeline.md) |
| NE-03 | What a parse costs — wall clock, memory, or pages per minute at either DPI. No such measurement exists in this repo, so nothing about parse cost is `measured`. | `measurement` | [CO-EXTRACT](components/extraction-pipeline.md) |
| NE-04 | The DataHub approval sensor's poll interval (Dagster's default, because none is set), and whether any test pins that sensor at all. | `unread` | [CO-EXTRACT](components/extraction-pipeline.md) |
| NE-05 | Whether the `default_status="RUNNING"` on the two user-drop sensors is pinned by a test. None found by name; the test that exists covers the S3 filter. | `unread` | [CO-EXTRACT §3](components/extraction-pipeline.md) |
| NE-06 | Which ontologies are actually loaded in any environment, and whether the manifest the readiness asset enumerates matches what priming uploaded. | `cluster` | [CO-ONTOLOGY §12](components/ontologies-and-alignment.md) |
| NE-07 | Whether the Neo4j mirror covers the same class set as the Weaviate mirror. The asset's docstring and its dependency were read; its body was not. | `unread` | [CO-ONTOLOGY §2](components/ontologies-and-alignment.md) |
| NE-08 | Whether `init_neo4j_n10s` is still on any path. The sync asset's docstring says rdflib extraction, not n10s. | `unread` | [CO-ONTOLOGY](components/ontologies-and-alignment.md) |
| NE-09 | The full property list of the `OntologyClass` collection, and whether a deployed pool's list matches the create path's — a property added to the create path is inert on an already-created collection. | `cluster` | [CO-ONTOLOGY](components/ontologies-and-alignment.md) |
| NE-10 | Whether any `mil:*` term is present in a deployed vocabulary graph. The namespace is declared in `AGENTS.md:110`; what is loaded is a cluster fact. | `cluster` | [CO-ONTOLOGY](components/ontologies-and-alignment.md) |
| NE-11 | Whether a `sandbox/roll-lock` ConfigMap exists in any namespace. It appears in no script, template or chart at this pin — only in `docs/pcn-pre-roll-fire-design.md` as an operator convention. | `cluster` | [CO-CORPUS-GATE](components/corpus-gate.md) |
| NE-12 | What the authoritative duration of a corpus fire is. Code carries three figures ("~70 minutes", "2.5 hours", "~22 minutes ×3") against a measured 2h22m–2h34m in the design document, and none is marked authoritative. | `undecided` | [CO-CORPUS-GATE](components/corpus-gate.md) |
| NE-13 | Whether `tests/test_gate_publish.py` and `tests/test_gate_prefire.py` pin specific rules of the publisher and the pre-fire helper or only their shapes. Both files exist; their test names were not read into these records. | `unread` | [CO-CORPUS-GATE](components/corpus-gate.md) |
| NE-15 | What `ADR-0059` and `ADR-0066` are. Both are cited in this tree and resolve in no repo on this workstation. They are not silently repaired. | `another repo` | [README](README.md) |
| NE-16 | Which alignment rows of the DoD and NATO references doc-tools answers to. Every "Place in the mesh" row that cites an element is `proposed`: those records do not name doc-tools at their pin, so the alignment is this lane's reading until the arch lane confirms it. The **Plane** rows cite no element, and the plane *list* is no longer the gap: the architect ruled on 2026-11-19 that the mesh's four planes are `infrastructure`, `operational-data`, `data-management` and `analytical-data`, from the NATO document's Appendix 14, and that the dag-tools arch lane publishes the list with the alignment records and then assigns each component a plane. What is not established is the *assignment*: the plane written on each of these three rows is this lane's reading at `proposed`, checked against the plane's published *definition* rather than its name, and the dag-tools arch lane's own assignment is the one that settles it. The *list* is published and pinned — dag-tools `16da96502281c5496b1553e3ed560c2a10e77ed0`, PR #111, unmerged, relayed by that lane on 2026-11-19 — and these three rows now cite L2 and L3 of its `AL-DCRA`, so what is open is narrower again: whether that record names doc-tools at all. That lane confirmed on 2026-11-19 that its records place dag-tools components only, that none of them names doc-tools, and that whether L2 or L3 covers a member which is a Dagster code location *inside* `CO-DAGSTER` is the architect's call and not its own (see F-22). The unsettled thing is therefore membership, not the plane: no reading of the four definitions can promote these rows past `proposed` while no published record places this repo at all. The **Capability** ids added the same day are weaker still: they are mapped from the appendix *titles* printed in lane 02's structured-fields packet §4.1, and DCRA v2 (AC/322-D(2025)0056) was not read here, so no cell is confirmed against an appendix's contents. | `another repo` | all three component records |
| NE-17 | What the deployed overlay actually sets, as opposed to what `charts/` declares. A local checkout is not the deployed contract, and these records read no cluster and no sibling working tree. | `cluster` | [README](README.md) |
| NE-18 | Whether a stage POST succeeds in any environment, and what fraction of runs lose it. A transport failure is a WARNING log line and nothing counts it. | `measurement` | [FL-REVIEW §13](flows/document-to-review-record.md) |
| NE-19 | What the reader renders from `review.json`. The wire shape is ruled and served verbatim; the rendering is another lane's code and was not read. | `another repo` | [FL-REVIEW §17](flows/document-to-review-record.md) |
| NE-20 | Which queue a document lands in when it completed the flow and wrote no `review.json`. The stage posts `review` whether or not a review record was written. | `another repo` | [FL-REVIEW §7](flows/document-to-review-record.md) |
| NE-21 | The two `review.json` layouts: this repo writes one shape, a second exists under earlier pins, and which readers still accept which was not established. | `unread` | [FL-REVIEW](flows/document-to-review-record.md) |
| NE-22 | How long the flow takes end to end for any document, which is why no step of FL-REVIEW is `measured`. Same evidence gap as NE-03, restated at the flow. | `measurement` | [FL-REVIEW](flows/document-to-review-record.md) |
| NE-25 | What `serves` carries for these three parts when the records are converted. The proposed component shape (lane 02's packet §4) makes **all ten keys required** and leaves open whether `serves` names alignment element ids; nothing in this tree answers that, and every element id these records cite is `proposed` (NE-16), so a required `serves` would be filled from a reading rather than a record. **The `plane` half of this row is answered**: the architect named the four planes on 2026-11-19 (see NE-16), and each component record's **Plane** row now carries one at `proposed`, so conversion has a value to put in the required key — it is the assignment, not the key, that is still this lane's reading. | `undecided` | all three component records, at conversion |
| NE-26 | What a vocabulary re-ingest **removes**. The drop path is in another repo; this tree shows only what a re-ingest adds, and no part of that path was read at this pin. Recorded 2026-11-19, when the architect's ruling made `built` elsewhere unwritable: a claim needs evidence at a pinned commit, and a gap with none is a row here and not a status. | `another repo` | [CO-ONTOLOGY gaps](components/ontologies-and-alignment.md) |

## Answered since this list was published

A row that gets answered is **not deleted**: the id was published and another lane may have
cited it. It moves here, with the answer and where the fact now lives.

- **NE-14** — whether doc-tools declares its own arch-kit project or is read as a source by a
  project in another repo. **Answered 2026-11-19 from lane 02's shapes packet**, read at the
  copy relayed to the dag-tools arch lane. A member needs **no** `arch-kit.yaml`: §8 asks each
  member lane only for its repository, a full 40-character commit, and the path of its
  `arch-kit.yaml` *at that commit if it has one*, and lane 02 then reads the repository as a
  read-only checkout at that commit and commits nothing in it. So doc-tools is read as a source
  by a composing portal in another repo, which is the second of the two shapes this row asked
  between. One smaller thing is **not** settled and is not reopened as a row because nobody is
  blocked on it: §7 gives `portal: none` with `consumes:` as the declaration for a project with
  no portal of its own, and whether this repo should declare that much is lane 02's call.
  The other half of this row is also now wrong in the reader's favour: arch-kit **does** have a
  flow record type, on kit main (#23), its design not ruled; the *component* type is the thing
  that is proposed, for lane 03 to build. See [the shape section](README.md).

- **NE-23** — whether `CO-` and `FL-` are a mesh-wide id namespace, and who assigns in it.
  **Answered 2026-11-19**, and the answer's own status matters. Chris relayed it as settled and
  this lane follows it; the packet was then read at the copy relayed to the dag-tools arch
  lane, and in the packet the rule is one of the **proposed rules of §4, "for lane 03 to
  confirm"**. So: applied, `proposed`, not confirmed. The rule is that **a repository does not
  prefix its ids with its own name**, that the composed build renders each member's records
  under that member **with the member's name in the anchors** — so two members may each have a
  `CO-BROKER` — and that **an existing prefixed id still matches the pattern and needs no
  change**. There is one namespace at compose time, membership is what the build supplies, and
  a prefix is neither required nor forbidden.
  This repo is already compliant: `CO-EXTRACT`, `CO-ONTOLOGY`, `CO-CORPUS-GATE`, `FL-REVIEW`,
  the `NE-` rows here and the `ADR-01NN` series all carry no repo name. Nothing was renamed, and
  by the third clause nothing would have had to be.
  The one case this lane sent to lane 02 rather than guess is **answered by the same §4**: an
  ADR number is not unique across members — `ADR-0001` exists in this repo and in
  invincible-agent, and 18 bare `ADR-00NN` citations in this tree mean invincible-agent's
  records — and §4's evidence line accepts "decision ids, `prefix:ADR-NNNN`, or repository
  paths; must resolve". `iagent:ADR-0041` is that form. It is a *citation* of another member's
  record, not a repo prefix on an id of ours, and [the ADR README](../adr/README.md) keeps it.
  Two things are still open and are with lane 02, not guessed at here: whether the accepted
  prefix is the member's name as the composition spells it (this repo writes `iagent:`, and the
  member is `invincible-agent`), and whether a section-of-a-guide citation such as
  `dag-tools §4p.3` — the form the dag-tools arch lane keys its decisions to, and the form used
  in these records — is an accepted evidence form or must become a repository path with a line
  range. The second is the dag-tools arch lane's question, raised through this lane because it
  has no address for lane 02. See [FOLLOW-UPS.md](../adr/FOLLOW-UPS.md) F-15.

- **NE-24** — whether dag-tools' `CO-DAGSTER` and `CO-S3-SENSOR` denote the same orchestrator
  and the same sensors this repo runs. **Answered 2026-11-19 by packet, and the doc-tools half
  measured here.** `CO-DAGSTER` is the orchestrator as the charts wire it — the
  invincible-agent chart deploys the webserver, daemon and instance and runs an image as a
  code location — so doc-tools is a code location *inside* it, which
  [CO-EXTRACT](components/extraction-pipeline.md) now says. `CO-S3-SENSOR` is the dag-tools
  sensor **package**, the component classes rather than any instance; whether this repo's
  sensors are built from them was ours to read, and they are: ten of the eleven prefix
  sensors are `dag_tools.S3SensorComponent` instances (`doc_tools/definitions.py:3`). The
  eleventh is this repo's own DataHub poller and watches no prefix. Both links are now in the
  records. Correcting this also corrected a claim of ours: [CO-EXTRACT §1](components/extraction-pipeline.md) had said *eleven*
  S3 sensors.

## What is *not* on this list

Two things that look like gaps are decisions, and they are recorded in the component records
rather than here: the corpus gate's clock is off **by ruling**, not by omission; and `xml` is
held out of the published kind list **by ruling**, with the measurement that would lift it
written into the hold entry. Neither is an unknown.

Nothing on this list is a credential, a document value, a private filename or a site
identifier, and resolving a row must not put one into a record. Rows NE-01, NE-06, NE-09,
NE-10, NE-11 and NE-17 are answerable only against a running environment: answering them is
an operator's action under this repo's safety rules, and the answer enters a record as a
count, a rate or a digest.
