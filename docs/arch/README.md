# Architecture records for doc-tools

These records **describe doc-tools as it is**. They do not propose. Where a record names
something that is not built, it gives that thing a status of `accepted` or `proposed` and
says so. Nothing unbuilt is called built.

They are this repo's half of the mesh architecture portal. The mesh-wide records — the
gateway, the broker, the mesh data client, the alignment to the outside references, and
the roadmap — belong to dag-tools, and are cited from here by **stable id**, never by path
or branch: `CO-*` for a component, `FL-*` for a flow, `AL-DCRA` and `AL-DMRA` for the two
alignment records, each cited together with the element it names (`AL-DMRA S4`,
`AL-DCRA R1`). That lane supplied the ids at commit
`823bf3480fbbfc1f4e41a0766e228507aacf4236`, the head of a stack of drafts, none merged.
**Ids are stable; paths are not** — which is why no branch URL appears here. A part of
dag-tools carrying no id on that list has no record yet: ask by packet rather than invent
an id.

## The shape: markdown now, converted later

The records are written for [arch-kit](https://github.com/edgy-solutions/arch-kit). **Lane 02's
shapes packet has now been read** — not from this repo's inbox, which still holds no copy, but
from the copy the dag-tools architecture lane was relayed and told this lane about
(`PACKET-2026-11-18-dagtools-shapes.md`, 297 lines, dated 2026-11-18, "from lane 02 to lane 03").
It carries six record shapes, the declaration keys and the split of who builds what. Three of
its facts govern these files:

- **A component record is `proposed`, not built.** The kit pins the packet names are `v0.2.0` =
  `c1940ddfb63e065e3938ddf9529a9ee68cf87dd3` (tagged; decisions-only mode and the alignment
  type) and kit main = `93d8818be841d21c814d41ed9f3f9c67040cd992` (the merge of composition,
  #21, over flows, #23). The **flow** type is on main, its design not ruled; the **component**
  type is a proposal for OpenDDIL lane 03 to build or change, and so is a roadmap record. Those
  three shas are quoted from the packet and **were not read here**: no arch-kit tree was opened
  at any of them.
- **Records stay markdown until lane 03's types are on kit main**, and are converted then,
  keeping their ids. The packet rules this for the dag-tools architecture lane, which like this
  lane writes records and builds no kit code, and says the mesh loader reads the markdown
  records directly until then. So these files are **not** converted now: the order's "then
  convert" waits on a record type that exists.
- **Gaps are not a key in the proposed component shape.** A part's gaps, including a present
  exposure, stay in prose in the member's own markdown record and the loader renders them from
  there. The gap sections here are therefore the right home for them, and every member's
  not-established table is merged into one page — which is what
  [NOT-ESTABLISHED.md](NOT-ESTABLISHED.md) is for.

Until that conversion the files follow **the shape the dag-tools arch lane was using when that
shape was read**, at `a246e0693194bfbe7b1bc66962781273d480fa74`: a title with an id, findings
first, each finding carrying a status, then gaps, then what the code does not establish, then a
Sources table. That lane has moved on since — it supplied this repo with its citation ids at
`823bf3480fbbfc1f4e41a0766e228507aacf4236` — and the shape has not been re-read there.

**A composed project is a member, not a component** (ruled 2026-11-18, per the packet).
"Component" now means one part of one system: what `CO-EXTRACT`, `CO-ONTOLOGY` and
`CO-CORPUS-GATE` are. doc-tools is a *member*, and these records say so.

No `arch-kit.yaml` is declared in this repo, and the packet requires none of a member: it asks
each member lane for its repository, a full 40-character commit, and the path of its
`arch-kit.yaml` *if it has one*, and lane 02 then reads that repository as a read-only checkout
at that commit and commits nothing in it. A project with no portal of its own declares
`portal: none` with `consumes:` and needs nothing else. That a member need not declare a project
to be read is settled; whether this repo should declare `portal: none` anyway is lane 02's call
and stays [not established](NOT-ESTABLISHED.md).

## Status vocabulary

Every claim carries exactly one status. The vocabulary is the dag-tools arch lane's, so
that one word means one thing across the four repos; it is repeated here rather than
linked because a record is read on its own.

| Status | Means | Evidence it needs |
|---|---|---|
| `measured` | A recorded run against a running system showed it. | The record of the run. Having a test that could measure it is not enough. |
| `built` | Code at the pinned commit does it. | **One of four, at a pinned commit**: a file path with lines, a test, a chart template, or a release record. A census key or a decision record **alone does not support `built`** — it supports `accepted` (the architect, 2026-11-19). A test that pins it as well, when one exists; when none does, the row says so. |
| `accepted` | A decision record or a ruling accepts it, and no code does it yet. | The decision record or the ruling, with its date. |
| `proposed` | It is written down as intent, but not accepted or built. | Where it is written. |

A gap is something a consumer or a reference expects and doc-tools does not provide. Its
status is the status of whatever partial thing exists. A gap with nothing built is written
`not built`.

Two statuses on one row (`accepted + built`) mean the ruling and the code are both in
hand and agree. Where they disagree, the row says so and the status is the code's.

Lane 02's shapes packet carries the same four words with the same evidence, and says the mesh
loader **checks each member's own rules**: one status per claim from the four, and a `measured`
claim with a re-readable result or it is reported. Nothing in these records is `measured`, for
exactly the reason that rule names: this repo holds no re-readable run record of a parse, a
flow or a fire ([NE-03](NOT-ESTABLISHED.md), [NE-22](NOT-ESTABLISHED.md)).

**The `built` rule was checked against these records, not just written down.** The architect
ruled it on 2026-11-19 saying nothing needs rewriting now and that records written from here on
should cite the code; this lane measured the existing ones anyway, because a rule nobody checks
is a rule nobody keeps. All **92** `built` claims across the three component records and the flow
record now carry a file path with lines, a test, or a chart template:

| Record | `built` claims | Carrying path-with-lines, a test or a template |
|---|---|---|
| [CO-EXTRACT](components/extraction-pipeline.md) | 22 | 22 |
| [CO-ONTOLOGY](components/ontologies-and-alignment.md) | 16 | 16 |
| [CO-CORPUS-GATE](components/corpus-gate.md) | 19 | 19 |
| [FL-REVIEW](flows/document-to-review-record.md) | 35 | 35 |

Two of the flow's rows did not, when measured: step 1 cited only the component record that holds
the evidence, and step 3 stated the behaviour without naming where it lives. Both now cite the
code — `content_kind.py` with lines and its test, and the installed sensor package with lines —
which is the whole of the correction the rule asked for.

## Pins

All evidence is read at these commits. **A line number is valid only at its pin.**

| Source | Pin | Read status |
|---|---|---|
| doc-tools | `2b9e6cbc61178f7086cceade8614dca4d736150a` | this repo, read directly |
| arch-kit | `v0.1.0` = `e0b9b3c40520440a09a4e0e6050ea5017de05848` | the record form, read directly. **Superseded upstream**: lane 02's packet names `v0.2.0` and a later main, and neither was read here — see [the shape section](#the-shape-markdown-now-converted-later) |
| lane 02's shapes packet | `PACKET-2026-11-18-dagtools-shapes.md`, dated 2026-11-18 | the six record shapes, the declaration keys and the split. Read from the copy relayed to the dag-tools arch lane; it is not in this repo's `sessions/` inbox and carries no commit of its own |
| lane 02's structured-fields packet | `PACKET-2026-11-19-architect-structured-fields.md`, dated 2026-11-19 | §4.1 — the thirteen DCRA capability ids, the rules for the `Capability` column, and the ruling that Appendix 14 is the source of the planes and not a capability; and §1's rule that the portal reads columns **by header name, not position**. Read from the dispatch copy the architect's instruction carried; it is not in this repo's `sessions/` inbox and carries no commit of its own |
| dag-tools (arch records) | `a246e0693194bfbe7b1bc66962781273d480fa74` | the shape and the status vocabulary, read directly |
| dag-tools (the plane list) | `16da96502281c5496b1553e3ed560c2a10e77ed0` | `docs/arch/README.md` "## Planes" and `AL-DCRA`'s "## Data planes (Appendix 14)" rows L1–L4, read directly. **PR #111, unmerged**, relayed by the dag-tools arch lane on 2026-11-19: the sha is the pin, because the branch moves and `main` does not carry it yet |
| dag-tools (headers and namespaces) | `4c6107523acf50bfc1338c4ee46813ff9090f929` | two narrow reads, both in the local checkout: the connections and steps **column names** across its 32 component and 3 flow records (F-21, F-22), and that `mesh#` occurs nowhere in that tree (the Gaps bullet in [CO-ONTOLOGY](components/ontologies-and-alignment.md)). Headers relayed by that lane and verified here, not taken on report |
| invincible-agent | not read here | this repo's platform peer. Facts about the deployment overlay, the substrate priming and the ADR namespace it owns are named as *that* repo's and left `not established` here rather than read from a local checkout — a local checkout is not the deployed contract. |

Statuses for anything deployed are read from `charts/` and from code, **never from a
cluster**: nothing in these records put load on any environment.

## Citing a decision record

`ADR-0001` means three different things in this fleet — doc-tools' memory-bounded PDF
ingestion, invincible-agent's `mem0-llm-decouple`, and dag-tools' `mesh-publishing-protocol`
— and at this pin 75 tracked files in this repo cite an `ADR-00NN` number (51 of them
outside `sessions/`), spanning 20 distinct numbers, of which 18 mean another
repo. When that was measured `docs/adr/` held one file; it now holds [this
series](../adr/README.md), numbered from `0100` for exactly that reason. These records
**name the owning repo**:

| Citation | Means |
|---|---|
| `ADR-0001` | a record in this repo's `docs/adr/` |
| `iagent:ADR-0041` | a record in invincible-agent's `docs/adr/` (66 records and an index) |
| `CO-DAGSTER`, `FL-BIG` | a dag-tools component or flow record, by its stable id |
| `AL-DMRA S4`, `AL-DCRA R1` | a dag-tools alignment record, cited together with the element it names |
| `dcra:A9` | one of the NATO DCRA's thirteen capabilities, by the id lane 02 declares once in the mesh composition; `A`*n* is that document's appendix *n* |
| dag-tools `§4p.3` | a dag-tools decision; that lane keys its decisions to census sections |
| dag-tools roadmap row 8 | one numbered row of the dag-tools roadmap, which runs 1 to 16 |

A bare number is this repo's. Two numbers cited in this tree resolve in no repo on this
workstation (`ADR-0059`, `ADR-0066`); they are in [the not-established list](NOT-ESTABLISHED.md),
not silently repaired.

**An id carries no repo name.** Chris relayed this on 2026-11-19 as settled and this lane
follows it. In lane 02's packet itself the rule is one of the **proposed rules of §4, "for lane
03 to confirm"** — so the status word on it is `proposed`, not ruled, and it is applied here
because the relay said to, not because the packet says it is final. The rule: a repository does
not prefix its ids with its own name; the composed build renders each member's records under
that member, **with the member's name in the anchors**, so two members may each have a
`CO-BROKER`; and **an existing prefixed id still matches the pattern and needs no change**.
`CO-EXTRACT`, `CO-ONTOLOGY`, `CO-CORPUS-GATE`, `FL-REVIEW` and the `NE-` rows are all bare, so
nothing was renamed and nothing would have needed renaming either way. The qualified forms in
the table above are citations of another member's record, not prefixes on ours; §4 of the same
packet lists `prefix:ADR-NNNN` as an accepted evidence form, which is that qualifier. See
[NE-23](NOT-ESTABLISHED.md).

## What these records never carry

No site, customer or host is named. No document value, no filename from a private set, and
no credential — not even a credential's presence, except as `len=N sha256:XXXXXXXX`. An
environment variable that carries a credential is named, never valued. Rates, counts,
digests and file paths may be shown.

**The term check is a pattern check, not only a word list** (the architect's instruction of
2026-11-19, given to another lane after lane 02 found a host name in one of its records; adopted
here before this repo's records go anywhere). Three classes are grepped over `docs/arch/` and
`docs/adr/` before a push:

| Class | Pattern | Result, 2026-11-19 |
|---|---|---|
| IPv4 literal | `\b([0-9]{1,3}\.){3}[0-9]{1,3}\b` | 0 |
| internal suffix | `\.(svc\|local\|internal\|corp\|cluster\|lan\|intranet)\b` | 0 |
| domain-shaped token | a label, a dot, then a public suffix | 4 in the records, all explained below — and 6 once this note quotes two of them, which is the usual fate of a check that documents itself |

Of the four domain-shaped hits, two are not hosts at all: `github.com/edgy-solutions/arch-kit`
is the kit's public repository, and `app.kubernetes.io/name=doc-tools` is a label key. The other
two are **one ontology namespace IRI**, cited twice in `ADR-0148` because the code declares it
(`AGENTS.md:110`) and an ADR that omitted it would be wrong. It is domain-shaped, it names no
deployed host, and nothing in this repo resolves it. Whether a preview must redact a namespace
IRI anyway is the architect's call and has been asked — it is not redacted unilaterally, because
removing it would make the record false rather than safe.

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
| [../adr/README.md](../adr/README.md) | 94 decision records, from the 2026-11-16 census, plus three registers | in this commit |
