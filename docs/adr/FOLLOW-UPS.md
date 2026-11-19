# FOLLOW-UPS.md — what is owed

**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`

What a decision record commits us to and has not yet got. A row leaves this register when the
thing is done, not when it is scheduled. Rows are grouped by **who is owed from**, because the
most common waste in this repo is a lane working on another lane's half.

Where a row is owed from another lane, the ask goes as a packet
([ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md)) and this lane continues with
the next item meanwhile. Nothing here blocks.

## Owed by this lane

| # | What | Why it is owed | Where |
|---|---|---|---|
| F-1 | A mechanical PR qualifying every bare `ADR-00NN` citation in this tree as `iagent:` | 75 tracked files cite 20 distinct numbers; 18 of the 20 mean invincible-agent's records. The convention now exists ([README](README.md)); the tree predates it | this directory's §"Citing a record" |
| F-2 | An index of the architect's packets | They are the top authority over these records and arrive via Chris into `sessions/`, which has been placed-not-committed since 2026-11-12 — so a clone gets the rulings and, for anything after 2026-11-09, none of their text | [ADR-0209](ADR-0209-session-files-are-placed-never-committed.md), [FOREIGN.md](FOREIGN.md) |
| F-3 | A record of how a change reaches production, end to end | Census Gap 4: nothing in the repo explains the path from a merge to a rolled pin. The pieces are recorded ([ADR-0200](ADR-0200-a-stacked-pr-runs-no-ci-gate.md)–[ADR-0204](ADR-0204-show-the-values-diff-before-a-roll.md)); the *sequence* is not | census Gap 4 |
| F-4 | A freshness seal on each contract's self-declared status line — and on an architecture record's claims | Census Gap 7, widened twice: three contract status lines have gone stale (D-3, D-4, D-5), and on 2026-11-18 four claims in [ontologies-and-alignment.md](../arch/components/ontologies-and-alignment.md) were found contradicting the code **two commits after that record shipped**, one of them inverting a safety property. Writing a record is not the same as keeping it true. This repo has the pattern once in working form (`expectImage`, read back off the pods) and once on paper only (`check_drift.py`, which no workflow invokes — D-16); the contracts use neither | [DEBT.md](DEBT.md), [ADR-0172](ADR-0172-the-drift-check-reads-the-runtimes-own-var.md) |
| F-5 | The third leak door: the ingest-row failure detail in `semantic_assets.py` | The 2026-11-18 ruling — a failure reason a person reads is a code and a bounded message — is satisfied at six sites in `sustainment.py` and **not** at `_augment_failure_detail`. `accepted`, not built | [the flow record](../arch/flows/document-to-review-record.md) |
| F-6 | Convert these records to lane 02's shape when it arrives | They are written in the arch lane's current shape by instruction; the kit's format is owed from OpenDDIL's lane 02. **The packet exists:** a ruling relayed 2026-11-19 cites "lane 02's shapes packet", and it is not in this repo's inbox — asked for as F-15 | census §"What I did not do" |

## Owed by another lane

| # | What | From whom | What is blocked |
|---|---|---|---|
| F-7 | Which **two** header fields Lane 1 serves | Lane 1 (ruled 2026-10-31, values unresolved) | the batch column map seam cannot be called settled — [ADR-0230](ADR-0230-the-batch-column-map-seam.md) |
| F-8 | The door offering `document` as a kind candidate | Lane 1 | `document` is declared here and not routable end to end — [ADR-0231](ADR-0231-the-document-kind-seam.md) |
| F-9 | Rulings 1–4 of the scrub-ledger design (2026-10-22) | the architect | the tokeniser and the allowlist. The safe answers are recorded **as safe, not as ruled** — [ADR-0224](ADR-0224-the-scrub-ledger-is-a-recommendation.md) |
| F-10 | A yes/no on the `concept_parse` failure detail | lane tr (packet placed 2026-11-18) | whether the training path keeps an exception echo that carries a rendered prompt |
| F-11 | Eighteen `ADR-00NN` numbers, made resolvable | invincible-agent | F-1 can qualify the citations; it cannot make another repo's records exist. Renumbering them was never ours | [DEBT.md](DEBT.md) |
| F-12 | Reconciliation of the training-workbench contract with what the workbench consumes | lane wb and lane tr jointly | the contract is at version 5, DRAFT, and has drifted — [ADR-0234](ADR-0234-the-training-workbench-seam.md) |
| F-15 | Lane 02's **shapes packet** itself, and a ruling on the cross-member ADR number | lane 02 (asked 2026-11-19) | the packet is not in this repo's `sessions/` inbox, so the id ruling was applied from Chris's relay of two clauses, not from the packet. The unclear case: ids carry no repo name, yet an ADR number is not unique across members (`ADR-0001` exists in two, and 18 bare `ADR-00NN` cites here mean invincible-agent's). This repo reads `iagent:ADR-0041` as a *citation* of another member, not a prefix on an id of ours, and keeps it — [NE-23](../arch/NOT-ESTABLISHED.md) |

## Owed by a measurement not yet taken

| # | What | What would release it |
|---|---|---|
| F-13 | `xml` in `ingestable_kinds()` | a user-drop sensor actually processing a bare xml drop. The hold is a named-measurement hold, not arm math — [ADR-0114](ADR-0114-xml-is-held-out-until-a-drop-proves-it.md) |
| F-14 | Whether an `ALIAS_OF` keyed to its **first-asserting course** is the wanted behaviour | a ruling from the contract's owner, not a measurement. *Restated 2026-11-18:* the accumulation this row used to claim does not exist — both edge kinds are pruned ([D-2](DEBT.md), withdrawn). What is unruled is the keying: `r.course_id` is set `ON CREATE`, so a second course asserting the same pair can neither re-key the edge nor keep it when the first course drops it — [ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md) |

**Not in this register:** anything whose status is simply `accepted` with implementation owed and
no date — that is the record's own Status line, and duplicating it here would make this file the
index instead of [README.md](README.md). A row appears here only when something concrete is
owed by a named party.
