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
| NE-14 | Whether doc-tools declares its own arch-kit project or is read as a source by a project in another repo. No `arch-kit.yaml` is declared here, and arch-kit v0.1.0 has no record type for a component or a flow. This is lane 02's call. | `undecided` | [README](README.md) |
| NE-15 | What `ADR-0059` and `ADR-0066` are. Both are cited in this tree and resolve in no repo on this workstation. They are not silently repaired. | `another repo` | [README](README.md) |
| NE-16 | Which alignment rows of the DoD and NATO references doc-tools answers to. Every "Place in the mesh" row here is marked `proposed`: those records do not name doc-tools at their pin, so the alignment is this lane's reading until the arch lane confirms it. | `another repo` | all three component records |
| NE-17 | What the deployed overlay actually sets, as opposed to what `charts/` declares. A local checkout is not the deployed contract, and these records read no cluster and no sibling working tree. | `cluster` | [README](README.md) |

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
