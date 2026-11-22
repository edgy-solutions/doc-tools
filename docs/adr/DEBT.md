# DEBT.md — where the written record and the tree disagree

**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`

A decision record is only useful if it is honest about the places where it is **not** the truth.
This register holds three kinds of row:

1. a **ruling and the code disagree** — the record's status is the code's, and the row is here;
2. a **self-declared status line has gone stale** — the document says one thing, the tree does
   another;
3. a **citation resolves nowhere** — named rather than silently repaired.

Nothing here is repaired by guessing. A row is closed by a ruling, a measurement, or a commit —
not by editing the claim until it reads better.

## 1. A ruling the code does not implement

| # | Ruling | What the code does at the pin | Record |
|---|---|---|---|
| D-1 | A failure reason that reaches a person is a code and a bounded message; raw prompts and raw model output stay in telemetry (ruled 2026-11-18) | Satisfied at the six `sustainment.py` sites. **Not** satisfied at the ingest-row door: `semantic_assets.py`'s `_augment_failure_detail` still composes an exception's own text into the row's detail, and a test pins that echo | [the flow record](../arch/flows/document-to-review-record.md) finding 20; owed as F-5 in [FOLLOW-UPS.md](FOLLOW-UPS.md) |
| D-2 | *Withdrawn on measurement, 2026-11-18.* This row claimed `ALIAS_OF` is not pruned where `TEACHES` is. It **is**: `doc_tools/plugins/training.py:559-570` prunes this course's stale aliases, after the MERGEs, in its own transaction, exactly as `:501-522` does for `TEACHES`. The row is kept as a withdrawal rather than deleted, because the same false claim had reached an architecture record and a register, and a reader who saw it there should find out here that it was wrong | [ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md) |
| D-9 | The BAML extractors order their output to counter recency bias | The ordering instruction appears in the prompt text; **none of the nine extractor functions** implements it in code. The ruling lives entirely in prose the model is asked to follow | [ADR-0107](ADR-0107-no-fetch-mode-and-the-scorer-never-normalises.md) |
| D-10 | A prompt is a file and the file path is production ([ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md)) | `doc_tools/passes/compliance.py:66-78` returns a **mock rule** when the prompt file is absent, so a run with no prompt reports success with nothing extracted instead of failing | [ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md) |
| D-11 | Config names the case; code implements the mechanism — all four of its tests | **Two of the four fail at the pin, and the architect queued both rather than retrofitting.** Test (4): the registered-kind list is derived from the in-code `KIND_MAPPING` table (`doc_tools/utils/ingest_failure.py:146-151`). Test (2): a new domain still needs a new `elif`. Declined explicitly, so this is queued work and not drift | [ADR-0177](ADR-0177-config-names-the-case.md) |
| D-12 | Dynamic Cypher is bounded to one interpolated name, `config.graph_node_label` | Counted at the pin: **8** interpolation sites use that name and **50** use `{self.domain_label}`, which `doc_tools/plugins/base.py:174-180` derives as `domain_type.upper().replace(" ", "_").replace("-", "_")` — a case-and-separator normaliser, **not** an allow-list. The written rule describes 8 of 58 sites. Not a document-driven injection path: `domain_type` comes from run config, not from a document. But the protection on the other 50 is "an operator typed it" plus two `replace` calls, which is not what the rule says | [ADR-0212](ADR-0212-dynamic-cypher-is-bounded-to-one-name.md) |
| D-13 | A gate fire takes the roll lock before it runs | `scripts/pcn_gate_prefire.py` never takes it: zero matches for the lock's own words in that script. The lock is a ConfigMap and the fire does not reach for it | [ADR-0187](ADR-0187-a-hand-fire-takes-the-roll-lock.md) |
| D-14 | `arrives_as` is the platform's field; this lane does not fill it (ruled 2026-10-30) | The platform SDK's v0.9.11 changelog instructs integrators — this lane among them — to populate it. The ruling and another repo's release note give opposite instructions, and **this row does not resolve that**: it goes to lane 01 as a packet ([ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md)) | [ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md), [FOREIGN.md](FOREIGN.md) |
| D-15 | The rulings behind [ADR-0208](ADR-0208-only-the-owning-lane-commits.md) and [ADR-0209](ADR-0209-session-files-are-placed-never-committed.md) | Both are in force and governed every commit in this stack, and **neither had any written statement anywhere in the tree** before these records — they were carried in packets and in habit. That is the census's finding in its purest form: these records are the first time the tree states them | — |

## 2. A status line that has gone stale

| # | Document | What it declares | What the tree shows at the pin |
|---|---|---|---|
| D-3 | `docs/contracts/playbook-kind.md:3` | **"Status: SPEC ONLY. Nothing here is built."**, measured at `main@5c113ce` | The hold on `playbook` was lifted (ruled 2026-11-07): `doc_tools/utils/md_chunks.py` exists and implements the chunking, and `tests/test_processable_kinds_publisher.py:104-116` is named `test_playbook_is_advertised_and_is_held_by_nothing`. The contract's own status line is the stalest statement in `docs/contracts/` — [ADR-0232](ADR-0232-the-playbook-kind-seam.md) |
| D-4 | `docs/contracts/batch-column-map.md:38` | `contract_version: 2` — "the contract and a validator, as of 2026-10-30" | The catalogue's own note describes the superseding at version **1**, and `training-workbench.md` is at version **5** with `contract_version` named only in a change rule. **There is no single place that lists which contract is at which version** — [ADR-0230](ADR-0230-the-batch-column-map-seam.md) |
| D-5 | `docs/contracts/scrub-ledger.md:4`, `:298` | The package "contains the ledger model and nothing else"; §9 declares "**No scrubber.** No tokeniser, no allowlist file, no PDF rewriting" | Stale at the pin, and in the governance-relevant direction. `doc_tools/scrub/` holds `scrubber.py`, `allowlist.py`, `element_text.py` and `draw.py` beside `ledger.py`, and `registry/scrub_allowlist.yaml` exists. Meanwhile the authority has **not** moved: rulings 1–4 of the 2026-10-22 design are unlanded and `RECOMMENDED_POLICY` still carries "RECOMMENDATION, NOT A RULING". So the code was built past a contract that still disclaims it — [ADR-0233](ADR-0233-the-scrub-ledger-seam.md), [ADR-0224](ADR-0224-the-scrub-ledger-is-a-recommendation.md) |
| D-16 | `AGENTS.md:90` | `check_drift.py` fails the merge | **No workflow invokes it.** Zero matches for the script across `.github/`. It is a seal on paper, and F-4 cited it as a precedent until this was measured |
| D-17 | `AGENTS.md:39` | the module is "in no deployed image" | The container build is `COPY . /app`, so it ships. Corroborated independently by `build-container.yml:131-133` calling the build context's `.dockerignore` "EMPTY" when the generated one runs to roughly eighty lines |
| D-18 | `AGENTS.md:24`, `:27` | names `pdn_parts_diagnostic.py` as the diagnostic to run | **The file does not exist** at the pin. A newcomer following the instruction gets nothing |
| D-19 | `AGENTS.md:57` | names `S3ToFileComponent` | Not the component in the tree. The name was not updated when the component changed |
| D-20 | `AGENTS.md:124` | the linker "auto-tags at ≥0.85" | The threshold is **cosmetic**: `doc_tools/assets/semantic_linker.py:158-172` calls the same `propose_datahub_term` on both sides of it, and the branches differ only in log level and which counter increments (`stats["tagged"]` vs `stats["human_review"]`). Nothing is tagged differently |
| D-21 | `AGENTS.md:128-130` | the Neo4j wipe is a root-URI `DETACH DELETE` | The code deletes at **every subject**, not the root URI. The documented procedure and the implemented one differ in blast radius, which is the worst class of doc rot to leave in a runbook |
| D-22 | `AGENTS.md:185-188` | describes the AITool registration sensor as live | It is **commented out** at `doc_tools/definitions.py:463-471`. Found twice independently in this sweep |
| D-23 | `doc_tools/parsers/s1000d_rdf.py:243` | a comment pointing at the join it guards | The code it describes moved to `:263-271`. Comment rot, not a behaviour defect |
| D-24 | `doc_tools/utils/leaf_read.py:157-158` | "The coordinate space of every `bbox` this module emits: unstructured's LAYOUT pixels" | Contradicted **eleven lines below itself** by the 2026-10-21 ruling at `:167-177` ("Crop coordinates: page fractions… So there is NO space key here any more"). The first sentence is the stale half |
| D-25 | `docs/notice-identity-contract.md:3` | "For the ingress-user lane (7f), which owns the sensor" | `7f` is **this** lane's code everywhere else in the fleet. Either the lane code or the ownership claim is wrong, and which one is not this lane's to decide — it goes to the seam's owner as a packet |
| D-26 | `tests/test_corpus_gate_guard.py:46-56` | `pre_roll` "has never been FIRED at a cluster… Existing is not the same as working" | The premise was overturned: `pre_roll` has since been fired. The docstring still argues the superseded case to a reader deciding whether to trust the guard |
| D-27 | `.github/workflows/build-container.yml:128-130` | this lane's reports "are committed there" | False since 2026-11-12 ([ADR-0209](ADR-0209-session-files-are-placed-never-committed.md)). A workflow comment asserting a committing convention that the governing ruling reversed |
| D-28 | `charts/doc-tools/values.yaml` | a fire takes "roughly 70" minutes | Measured: three fires at roughly forty-nine minutes each. The value is quoted by **count only** here — that file commits literal credentials and is never printed with lines shown |
| D-29 | `doc_tools/plugins/manufacturing.py:410-418` | cites `setup/ontologies/mfg_extension.ttl` unqualified | The path resolves in the **platform** repo, not this one: no `setup/` path and no `.ttl` among the 663 tracked files. A reader checking that `mfg:WorkInstruction` is declared has to know to look in another repo — [ADR-0117](ADR-0117-one-general-manufacturing-kind.md), [FOREIGN.md](FOREIGN.md) |
| D-30 | `doc_tools/parsers/design_parser.py` | keys its output on bare names | The keying is enforced **only by `.get` defaults** at the read sites, and a third key exists that the documented shape does not mention. Nothing fails if a producer changes the shape; a reader silently gets the default |

The general fix for this class is a **checkable** status line — a pin it was measured at, plus a
seal that fails when the tree moves past it. This repo has that pattern **once** in working form
(`expectImage`, read back off the pods) and once on paper only (`check_drift.py`, which no
workflow invokes — D-16). The contracts use neither. Owed as F-4 in
[FOLLOW-UPS.md](FOLLOW-UPS.md).

## 3. Citations that resolve nowhere

| # | Citation | What is known | Where it is cited |
|---|---|---|---|
| D-6 | `ADR-0059` | **It is not an ADR.** The number was carried in the *title* of an architect's packet ("RESTORE TRAINING INGESTION — ADR-0059"), and no `ADR-0059` or `ADR-0060` file exists on any pushed branch of this repo. The citation is live in tracked files and is **not** silently rewritten | `docs/contracts/training-workbench.md:9`, `tests/test_kind_registry.py:63` |
| D-7 | `ADR-0066` | invincible-agent's, still in draft. It has no live citation in this repo's tracked tree; where it is discussed it must be written `iagent:ADR-0066 (in draft)` | `docs/arch/NOT-ESTABLISHED.md` NE-15 |
| D-31 | `ADR-0060` | **Joins `ADR-0059` as resolving nowhere.** Cited at `docs/contracts/training-workbench.md:25` as "consumers read through the mesh… is in draft". No `ADR-0060` file exists on any pushed branch of this repo, and the citation is bare, so a reader cannot tell which repo's draft is meant | `docs/contracts/training-workbench.md:25` |
| D-8 | Eighteen bare `ADR-00NN` numbers | They mean invincible-agent's records and predate the citation convention. 75 tracked files cite 20 distinct numbers in the `0001`–`0066` band. This is why this series starts at `0100` | tree-wide; F-1 and F-11 in [FOLLOW-UPS.md](FOLLOW-UPS.md) |

## 4. The structural debt this directory does not close

**The decision history is half committed.** Measured at the pin: `sessions/` holds **93 tracked
files**, the newest dated 2026-11-09, and **195 untracked ones** — because the ruling that
session files are placed and never committed
([ADR-0209](ADR-0209-session-files-are-placed-never-committed.md)) dates from 2026-11-12 and is
honoured from then on. Everything placed before it is in the tree; nothing placed after it is,
including the 2026-11-16 census these records are written from.

So a clone gets the arguments, the alternatives, the measurements and the packets up to
2026-11-09 and loses every one after it. That is census Gap 3, and it is why each record here
carries its own Context and Alternatives rather than a link to a session file: a link would
resolve for a reader of this working tree and for nobody else.

Closing it means either committing the decision history in some form or accepting that these
records *are* the history from 2026-11-12 onward. That is not this lane's call to make alone,
and it is recorded here rather than decided.
