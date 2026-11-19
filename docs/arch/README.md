# Architecture records for doc-tools

These records **describe doc-tools as it is**. They do not propose. Where a record names
something that is not built, it gives that thing a status of `accepted` or `proposed` and
says so. Nothing unbuilt is called built.

They are this repo's half of the mesh architecture portal. The mesh-wide records — the
gateway, the broker, the mesh data client, the alignment to the outside references, and
the roadmap — are in [dag-tools `docs/arch/`](https://github.com/edgy-solutions/dag-tools/tree/lane/arch-components-2/docs/arch),
and are cited from here rather than restated.

## The shape is provisional

The records are written for [arch-kit](https://github.com/edgy-solutions/arch-kit), pinned
at tag `v0.1.0` (`e0b9b3c40520440a09a4e0e6050ea5017de05848`). arch-kit v0.1.0 declares a
project (`arch-kit.yaml`), views, and a `decisions/` directory with its registers; it has
no record type for a *component* or a *flow*. Until the kit or OpenDDIL lane 02's loader
declares one, these files follow **the shape the dag-tools arch lane is using** at
`a246e0693194bfbe7b1bc66962781273d480fa74`: a title with an id, findings first, each
finding carrying a status, then gaps, then what the code does not establish, then a
Sources table. When lane 02's shapes arrive these records are converted to them.

No `arch-kit.yaml` is declared in this repo yet, so no kit tool runs over these records.
That is [not established](NOT-ESTABLISHED.md) rather than decided: whether doc-tools
declares its own project or is read as a source by one project in another repo is lane
02's call, and the loader it is building reads this tree read-only at a pinned sha.

## Status vocabulary

Every claim carries exactly one status. The vocabulary is the dag-tools arch lane's, so
that one word means one thing across the four repos; it is repeated here rather than
linked because a record is read on its own.

| Status | Means | Evidence it needs |
|---|---|---|
| `measured` | A recorded run against a running system showed it. | The record of the run. Having a test that could measure it is not enough. |
| `built` | Code at the pinned commit does it. | A file and line. A test that pins it, when one exists; when none does, the row says so. |
| `accepted` | A decision record or a ruling accepts it, and no code does it yet. | The decision record or the ruling, with its date. |
| `proposed` | It is written down as intent, but not accepted or built. | Where it is written. |

A gap is something a consumer or a reference expects and doc-tools does not provide. Its
status is the status of whatever partial thing exists. A gap with nothing built is written
`not built`.

Two statuses on one row (`accepted + built`) mean the ruling and the code are both in
hand and agree. Where they disagree, the row says so and the status is the code's.

## Pins

All evidence is read at these commits. **A line number is valid only at its pin.**

| Source | Pin | Read status |
|---|---|---|
| doc-tools | `5eb72e5cefaa4e3b414f4fc3b9f7c0bde4c98bed` | this repo, read directly |
| arch-kit | `v0.1.0` = `e0b9b3c40520440a09a4e0e6050ea5017de05848` | the record form, read directly |
| dag-tools (arch records) | `a246e0693194bfbe7b1bc66962781273d480fa74` | the shape and the status vocabulary, read directly |
| invincible-agent | not read here | this repo's platform peer. Facts about the deployment overlay, the substrate priming and the ADR namespace it owns are named as *that* repo's and left `not established` here rather than read from a local checkout — a local checkout is not the deployed contract. |

Statuses for anything deployed are read from `charts/` and from code, **never from a
cluster**: nothing in these records put load on any environment.

## Citing a decision record

`ADR-0001` means three different things in this fleet — doc-tools' memory-bounded PDF
ingestion, invincible-agent's `mem0-llm-decouple`, and dag-tools' `mesh-publishing-protocol`
— and at this pin 75 tracked files in this repo cite an `ADR-00NN` number (51 of them
outside `sessions/`), spanning 20 distinct numbers, while `docs/adr/` holds exactly one
file. These records therefore **name the owning repo**:

| Citation | Means |
|---|---|
| `ADR-0001` | a record in this repo's `docs/adr/` |
| `iagent:ADR-0041` | a record in invincible-agent's `docs/adr/` (66 records and an index) |
| `dag:ADR-0001` | a record in dag-tools' `docs/adr/` |

A bare number is this repo's. Two numbers cited in this tree resolve in no repo on this
workstation (`ADR-0059`, `ADR-0066`); they are in [the not-established list](NOT-ESTABLISHED.md),
not silently repaired.

## What these records never carry

No site, customer or host is named. No document value, no filename from a private set, and
no credential — not even a credential's presence, except as `len=N sha256:XXXXXXXX`. An
environment variable that carries a credential is named, never valued. Rates, counts,
digests and file paths may be shown.

## Records

These records arrive as a stack of pull requests, bottom-up. A row marked *next* is named
here because the records that exist cite it; the file is not in the tree yet, and the link
will not resolve until its PR lands.

| Record | Kind | State |
|---|---|---|
| [components/extraction-pipeline.md](components/extraction-pipeline.md) | component (CO-EXTRACT) | in this commit |
| [components/ontologies-and-alignment.md](components/ontologies-and-alignment.md) | component (CO-ONTOLOGY) | in this commit |
| [components/corpus-gate.md](components/corpus-gate.md) | component (CO-CORPUS-GATE) | in this commit |
| [NOT-ESTABLISHED.md](NOT-ESTABLISHED.md) | this repo's half of the merged not-established list | in this commit |
| [flows/document-to-review-record.md](flows/document-to-review-record.md) | flow (FL-REVIEW), a document arriving to a review record | in this commit |
| `decisions/` | decision records, from the 2026-11-16 census | next |
