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
| NE-14 | Whether doc-tools declares its own arch-kit project or is read as a source by a project in another repo. No `arch-kit.yaml` is declared here, and arch-kit v0.1.0 has no record type for a *component* or a *flow*. This is lane 02's call. **Narrowed 2026-11-19** by the relayed clause "the composed build places each member's records", which says a composition exists and this repo is a member of it — not which of the two shapes above that makes. The shapes packet itself was not read here. | `undecided` | [README](README.md) |
| NE-15 | What `ADR-0059` and `ADR-0066` are. Both are cited in this tree and resolve in no repo on this workstation. They are not silently repaired. | `another repo` | [README](README.md) |
| NE-16 | Which alignment rows of the DoD and NATO references doc-tools answers to. Every "Place in the mesh" row that cites an element is `proposed`: those records do not name doc-tools at their pin, so the alignment is this lane's reading until the arch lane confirms it. The **Plane** rows cite no element at all — the architect ruled on 2026-11-19 that the plane layer is not established. | `another repo` | all three component records |
| NE-17 | What the deployed overlay actually sets, as opposed to what `charts/` declares. A local checkout is not the deployed contract, and these records read no cluster and no sibling working tree. | `cluster` | [README](README.md) |
| NE-18 | Whether a stage POST succeeds in any environment, and what fraction of runs lose it. A transport failure is a WARNING log line and nothing counts it. | `measurement` | [FL-REVIEW §13](flows/document-to-review-record.md) |
| NE-19 | What the reader renders from `review.json`. The wire shape is ruled and served verbatim; the rendering is another lane's code and was not read. | `another repo` | [FL-REVIEW §17](flows/document-to-review-record.md) |
| NE-20 | Which queue a document lands in when it completed the flow and wrote no `review.json`. The stage posts `review` whether or not a review record was written. | `another repo` | [FL-REVIEW §7](flows/document-to-review-record.md) |
| NE-21 | The two `review.json` layouts: this repo writes one shape, a second exists under earlier pins, and which readers still accept which was not established. | `unread` | [FL-REVIEW](flows/document-to-review-record.md) |
| NE-22 | How long the flow takes end to end for any document, which is why no step of FL-REVIEW is `measured`. Same evidence gap as NE-03, restated at the flow. | `measurement` | [FL-REVIEW](flows/document-to-review-record.md) |

## Answered since this list was published

A row that gets answered is **not deleted**: the id was published and another lane may have
cited it. It moves here, with the answer and where the fact now lives.

- **NE-23** — whether `CO-` and `FL-` are a mesh-wide id namespace, and who assigns in it.
  **Ruled 2026-11-19**, relayed through Chris from lane 02's shapes packet: **a repository does
  not prefix its ids with its own name, and the composed build places each member's records.**
  So there is one namespace at compose time, and membership is what the build supplies — not a
  prefix on the id. This repo is already compliant: `CO-EXTRACT`, `CO-ONTOLOGY`,
  `CO-CORPUS-GATE`, `FL-REVIEW`, the `NE-` rows here and the `ADR-01NN` series all carry no
  repo name. Nothing was renamed to satisfy the ruling and nothing needs to be.
  **What was applied is the relay, not the packet.** Lane 02's shapes packet is not in this
  repo's `sessions/` inbox and was not read here, so the two clauses above are quoted from the
  relay and nothing further is inferred from them. The packet has been asked for.
  One case is unclear and has gone to lane 02 rather than been guessed at: an **ADR number is
  not unique across members** — `ADR-0001` exists in this repo and in invincible-agent, and 18
  bare `ADR-00NN` citations in this tree mean invincible-agent's records, which is why
  [the ADR README](../adr/README.md) qualifies a foreign one as `iagent:ADR-0041`. That
  qualifier is a *citation* of another member's record, not a repo prefix on an id of ours, so
  it is read as compatible with the ruling and kept. Whether the composed build wants
  something else is lane 02's to say. See [DEBT.md](../adr/DEBT.md) and
  [FOLLOW-UPS.md](../adr/FOLLOW-UPS.md).

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
