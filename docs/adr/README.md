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

That is the whole list. Everything else this repo's architecture rests on is either another
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
