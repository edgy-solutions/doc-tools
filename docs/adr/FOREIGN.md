# FOREIGN.md — the decisions this repo depends on and does not own

**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`

doc-tools cannot be understood alone, and before this register the repo never said so in one
place. Every row below is a decision, a schema or a gate that **lives in another repo or
another lane**, and that this repo's behaviour depends on. The point of the list is not
completeness of the other repos' records — it is that a newcomer can tell, for any question,
**which half is not theirs**.

Two rules apply to every row:

- **We do not edit another lane's half.** A disagreement goes as a packet to the owning lane
  ([ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md)), never as an edit.
- **A local checkout of another repo is not that repo's deployed contract**
  ([ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md)). Where a row cites
  another repo, it cites it as that repo's; the value at its pin is read with
  `git show origin/master:<path>` in that repo, by its owner, not inferred from a sibling
  working tree.

## Records and schemas owned elsewhere

| What | Owner | We depend on it for | Status of our half |
|---|---|---|---|
| `iagent:ADR-0041` — the provenance block and `ingest_id`'s canonical spelling | invincible-agent | the one spelling we emit, checked where the block is built | built — [ADR-0120](ADR-0120-ingest-id-is-one-canonical-spelling.md) |
| `iagent:ADR-0004` — contracts/registrations as data | invincible-agent | the auto-approve rule for code-controlled tool registrations | built — [ADR-0152](ADR-0152-no-hitl-for-code-controlled-registrations.md) |
| The **kind registry** — five of the six fields of every content kind | invincible-agent deployment overlay | what a kind *is*; we own only what it *runs* | accepted + built — [ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md) |
| The **read-side graph union** in `execute_sparql` | invincible-agent | half of the write-isolation invariant: our one-graph-per-document write is only safe if the read side unions | our half built — [ADR-0142](ADR-0142-the-read-side-union-lives-in-one-place.md) |
| **Substrate priming** — graph constraints, vector schemas, TBox TTLs | invincible-agent chart (`primeSubstrate` Job) | every class and constraint our writes assume. Editing a `mil:*` class means editing a TTL **in another repo** | accepted — [ADR-0103](ADR-0103-substrate-priming-is-the-platforms.md), [ADR-0148](ADR-0148-one-mil-namespace-across-parsers.md) |
| The **document-kind door** | Lane 1 | `document` becoming routable end to end: the door must offer it as a kind candidate | blocked — [ADR-0231](ADR-0231-the-document-kind-seam.md) |
| The **batch column map's two header fields** | Lane 1 (ruled 2026-10-31) | which two fields Lane 1 serves. **Which two is unresolved** | accepted, unresolved — [ADR-0230](ADR-0230-the-batch-column-map-seam.md) |
| The **training workbench's read side** | lane wb | the consumer of the contract whose write side is here; contract is at version 5, DRAFT | accepted + built, drifted — [ADR-0234](ADR-0234-the-training-workbench-seam.md) |
| The **Level-2 dedupe decision** | the ingress-user lane | we own the key, they own the decision taken on it | built — [ADR-0132](ADR-0132-notice-identity-is-the-key-not-the-decision.md) |
| The **mesh-wide architecture records** — the gateway, the broker, the mesh data client, the two alignment records and the roadmap | dag-tools arch lane | the ids this repo cites rather than restating the records: `CO-` and `FL-` for components and flows, `AL-DCRA` and `AL-DMRA` with the element they name | cited, never mirrored — [the arch README](../arch/README.md) |
| **The architect's rulings**, relayed by Chris as packets | the architect | the top authority over every record in this directory | — |

## What this register deliberately does not do

- **It does not mirror another repo's record text.** A mirrored copy goes stale silently and
  then two repos disagree with no way to tell which is current. A row here names the owner and
  what we use it for; the record itself is read in its own repo.
- **It does not index the architect's packets.** There is no index of them in this repo, which
  is itself a gap — the packets arrive via Chris and land in `sessions/`, which is placed, never
  committed ([ADR-0209](ADR-0209-session-files-are-placed-never-committed.md)). Tracked in
  [FOLLOW-UPS.md](FOLLOW-UPS.md).
- **It does not resolve the ADR-number debt.** Eighteen `ADR-00NN` numbers cited bare in this
  tree mean invincible-agent's records; qualifying them is a separate mechanical change, and
  two numbers resolve in no repo at all. Both are in [DEBT.md](DEBT.md).
