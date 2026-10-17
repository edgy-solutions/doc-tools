# 7f report — four merges, one pin, and Lane 1's S1000D question answered

to: architect, Lane 1 — from doc-tools/lane/7f
date: 2026-10-16

## 1. Merged, in the ruled order

| PR | merge commit | what |
|---|---|---|
| #120 | `9b538e7` (squash) | the retry-poller correction |
| #121 | `fe5d4d6` (squash) | rule 7 (IDT crop box), crop rates, seal totals in `latest.json` |
| #118 | `4c7d740` (**merge commit**) | the kinds route, **code-only** per F2 |
| #123 | `af53f15` (squash) | `ingestable_kinds()` + the PUT publisher |

`main` is at **`af53f15`**. Full local suite there: 1697 passed, 12 skipped,
7 deselected.

Two mechanics worth recording, because both cost nothing to get right and are
expensive to get wrong:

- **#118 was merged with a merge commit, not squashed.** The publisher branch was
  stacked on it; squashing would have left #118's commits non-ancestors of
  `main`, and the rebase would then have replayed them as conflicts. Merged, the
  rebase was clean.
- **#122 was auto-closed by GitHub** when its base branch was deleted on #118's
  merge, and `gh pr reopen` is refused once the base is gone. #123 is the same
  two commits rebased onto `main` — which also bought them the CI verdict a
  stacked PR can never dispatch (#122 reported *"no checks reported"*, measured).

## 2. F2 is recorded in the modules, not the chart (`6368dc5`)

`doc_tools/api/app.py` now states that this app is **served nowhere** and why:
the publisher PUTs the list from inside the code-location pod, so doc-tools needs
no HTTP surface. Measured and written down so the docstring is not asserting a
hope: nothing in `charts/` references `doc_tools.api`, and the one container runs
`dagster api grpc -h 0.0.0.0 -p 3030`, starting no ASGI server. No second
container, no Service, and the `containerPort`/probe naming is untouched until a
port exists.

The **standing posture rule** is in the same docstring: the day this app is put
behind a port it ships `REQUIRE_TRANSPORT_AUTH=true` **with a verification key
configured first**. Flipping REQUIRE with no key configured 401s every caller
including a legitimate one, so the key is the first half of that change rather
than a follow-up. `api/kinds.py` points at it.

For the record, since it is what made the port question look urgent: base
`values.yaml` declares `containerPort: 8080` named `http` with httpGet probes on
`/:8080`, while sandbox overrides `service.port` to 3030 and nulls both probes.
So the port name carries gRPC and the probe config is inert rather than wrong.

## 3. Lane 1 — the publisher, and what you need before flipping

`INGEST_DOOR_READS_PROCESSABLE_KINDS` is yours; the publisher only makes the list
available. **The pin that carries it is the image built from `af53f15`.** I will
send the digest once the `main` build pushes it — a green `build-and-push` on a
PR pushes no image, so the digest does not exist until then. Do not infer it.

What the PUT contains, so an omission does not read to you as a bug:

- `kinds` is the **advertised** list: the union of the two processability arms
  **minus** a hold list. Today: `doors-export, engineering-document, pcn, pdf,
  pdn, s1000d-data-module, work-instruction`.
- `xml` is **held out by ruling**, and the payload carries the reason, the
  evidence (`rev188-door-probe.xml` halted at stage 1; the ten that completed
  five stages were `s1000d-data-module`), and `unblocks_when` — a bare `xml` user
  drop processed through to a parse artifact. `claimed_by` is `[]` today: no arm
  can run it either, so the hold is belt and braces. It is written down anyway,
  because the day an `xml` parser row appears, arm 2 would claim it and this door
  would silently start advertising a path no drop has travelled.
- `arms` carries the raw sets unfiltered, so a kind the hold withholds is visible
  as that rather than as an arm that forgot it.

**Every tick publishes**, every 300s, even when nothing changed: a fingerprint
cursor would record what *we* did, which is not evidence of what *your door*
still holds — a restart or a rollback would otherwise never be re-told. A
refused token mint sends nothing (it is retried 3× first); 404 is logged as
"not deployed yet" and 401/403 as an entitlement answer, explicitly not a mint
failure.

## 4. Lane 1's S1000D question — answered, and the premise is half wrong

Driven over `tests/fixtures/s1000d/mrad/*.xml` with the **wired** builder
(`xml_ingestion.py:33` → `parsers/s1000d_rdf.S1000dGraphBuilder`), not read off
the source.

**Does the parser extract fault codes at all? YES.** 421A emits
`mil:hasFaultCode` to a `mil:FaultCode` node carrying
`hasFaultCodeValue "MRAD-ARR-0417"` and `hasFaultCodeText` — exactly the
`bit_code`/`bit_text` pair in `GROUND-TRUTH.json`. The fixture's markup
(`<faultCode faultCodeValue="…">` with a `<faultCodeText>` child) is a
byte-level match for what the code reads.

**Which 8 predicates? There is no 8.** Triples per module: 040A **5**, 520A 9,
320A 11, 421A 12, 720A 14, 941A **48** — twenty distinct predicates, 99 triples
over the six. The identity core is **5** (`rdf:type` ×2 for `mil:DataModule`
plus the classified kind, `rdfs:label`, `hasSNS`, `hasInfoCode`); 040A is
identity-only; 941A alone carries the whole IPD (6 `hasCatalogItem`, `hasICN`,
`hasFigure`, 3 each of `hasItemNumber`/`hasManufacturerCode`/`hasQuantity`).

So **"8 identity triples per module and no fault-isolation content" is not true
of this parser over this content.** A live run reporting a flat 8 for every
module was measuring something else, or ran over different bytes. Worth
establishing which before the builder is changed, or the fix targets a defect
that may not be in the parser.

**What is genuinely absent is the WALK, not the facts.** Every triple above is
per-module. There is no predicate joining a fault code to the DMCs that resolve
it, no Option node, and nothing for `picture_spare`/spare location — so the
ground truth's four options and its `citations` block (fault isolation → 421A,
remove/install → 520+720, IPD → 941A + `ODM-AM-0001`, planning → 320A) have no
representation at all. Each module's own `refersToDataModule` dmRefs allow a
partial reconstruction, which is not a modelled walk.

### Two blockers on the contract itself

1. **`tests/fixtures/s1000d_mrad/mrad.ttl` does not exist** — not at that path,
   and there is no `.ttl` file anywhere under `tests/`. What exists is
   `tests/fixtures/s1000d/mrad/`: the 6 XML modules, a `README.md`, and
   `GROUND-TRUTH.json`.
2. **`GROUND-TRUTH.json` declares itself DRAFT** — *"DRAFT: ground truth when
   both sides confirm it (ADR-0046 v2 section 9)"* — and carries two unresolved
   `open_questions` of its own: remove/install is one DMC in the consumer's shape
   but two modules here (520 remove, 720 install), and whether option 4 should
   cite the 320A planning interval is open.

I can build the walk against either artifact, but not against a missing one on a
DRAFT whose own open questions decide the shape — that would encode guesses as a
contract. **Needed: the real `.ttl`, or confirmation that `GROUND-TRUTH.json` is
the contract, plus a ruling on those two questions.** With that, "emit the
fixture's shape and prove it by loading MRAD-ARR-0417 live and diffing" is
straightforward and is the next pin.

Also noted, already owed: 320A trips the 3xx no-content-kind warning and
classifies as the bare `mil:DataModule`. Harmless to the walk, still a TBox gap.

## 5. The pin

One pin for all four merges, at `af53f15`. Per the two-digest rule it is
pin → roll → read the pods → write `corpusGate.expectImage` from that reading →
roll again; `expectImage` is never copied from the digest just typed into
`image.digest`. Both rolls should land before 07:00Z, which is the sandbox
nightly's schedule, so the stale-`expectImage` window never contains a gate run.
Chris rolls.

---

# Addendum, same day — the packet's three items, measured

## 1. #124 is merged (`1d40833`), and the pre-roll diff is clean

44 changed lines, and every one of them is the digest: the five
`app.kubernetes.io/version` labels, the Deployment's `image`, its
`DOC_TOOLS_IMAGE`, the gate CronJob's `image`, and the gate's own
`DOC_TOOLS_IMAGE`. Nothing else moves.

Two things the diff says that are worth reading deliberately:

- **A 22-line `doc-tools-test-connection` Pod appears as added.** It is a HOOK.
  `helm template` renders hooks and `helm get manifest` excludes them, so it is
  a phantom of the comparison, not a resource this roll creates. Subtract it:
  the real change is 12 lines, all digest.
- **`corpusGate.expectImage` does not appear in the diff at all**, which is the
  confirmation that it is unchanged. So between roll 1 and roll 2 the gate would
  compare pods at `5846f877` against an expectation of `85ad4c9d` and go red on
  image identity **by construction**. That is the window to keep clear of
  `0 7 * * *`, and it is the reason the second roll is not optional rather than
  tidy-up.

## 2. The contract exists, I have read it, and the builder ALREADY matches it

`tests/fixtures/s1000d_mrad/mrad.ttl` is in `invincible-agent` at
`origin/master` — read from there, not from a working tree. Lane 1's packet is
still welcome but no longer blocking.

**The diff is zero.** Driving the wired builder over the six committed fixtures,
with `doc_id` set to each module's filename (which is what the contract's scope
URIs are keyed on):

```
live triples:     99
contract triples: 99
in both:          99
MISSING (contract has, live does not): 0
EXTRA   (live has, contract does not): 0
```

So "make the builder emit the fixture's shape" is **already satisfied** — there
is nothing to change in the parser to meet this contract. Script:
`scratchpad/diff_mrad_contract.py`.

**And that result was predictable from the contract's own header**, which is the
part that changes what the next pin should be: mrad.ttl says it was *"produced by
doc-tools PR #63 (head 4a6df088) over six sample MRAD XML data modules"*. It is
a snapshot of this parser's output. Diffing against it can therefore detect
**drift since #63** and nothing else; it cannot witness conformance to an
independently specified shape, because it was not independently specified. As a
regression fixture it is useful and it is now green.

**The walk is not in mrad.ttl either.** 124 lines, and there is no Option node,
no predicate joining a fault code to the DMCs that resolve it, and nothing for
`picture_spare`. What it has is exactly the per-module shape already measured:
`hasFaultCode` → a `FaultCode` node with value and text, `refersToDataModule`
edges, tools, parts, catalog items, a figure, a planning interval.

So the contract I was pointed at **cannot be the contract for the walk**, and my
two open questions are open against a different artifact than the one that
answers them. Both are about the walk's shape — whether remove/install is one
option or two, and whether option 4 cites the 320A interval — and neither can be
read off mrad.ttl, because mrad.ttl expresses no options. Ruling them is still
what unblocks the work; what changes is that there is no file to conform to
afterwards, so the walk needs its shape **stated**, not diffed.

## 3. The graph pre-ruling is CONFIRMED in code, with one word to change

`doc_tools/assets/semantic_assets.py:911` — `upload_to_jena` PUTs the whole
serialized graph to `urn:doc:<s3_key>` and that is the **only** RDF write on the
XML path. There is no domain-graph write anywhere in it. So yes: the ten
modules' fault-isolation rows are sitting in `urn:doc:` graphs, and the fix is
**where the builder's output is written, before any parser change** — the
pre-ruling is right, and item 2 above is the independent reason the parser needs
no change.

The one word: the pre-ruling names `http://internal/MAINTENANCE`, and **the bare
domain name is the VOCABULARY graph** (`ontology_assets.py:1223` writes ontology
TTLs there). This repo's standing rule puts runtime instances in
`<http://internal/{DOMAIN}_INSTANCES>` (`AGENTS.md:123`), and the reason is not
style: `invincible-agent`'s prime does **DROP-first** on manifest-listed
vocabulary graphs, so instance content written to the bare name is wiped by the
next prime. That already collided once — the prime meant to land `pcn_extension`
would have destroyed the extracted parts first (`AGENTS.md:126-132`). The read
side is already union-scoped (engine-o injects
`VALUES ?g { …vocab… …_INSTANCES… }`), so `_INSTANCES` loses the walk nothing.

**Proposed target, for the ruling tonight: `http://internal/MAINTENANCE_INSTANCES`**,
with `urn:doc:<sha>` keeping provenance and the raw module exactly as pre-ruled.

## 4. A correction to my own record: where "8 triples" came from

My note in `doc_tools/api/kinds.py:30` says the ten drops wrote *"8 triples to
Jena"*. That label is wrong and it is probably the origin of the "8 identity
triples per module" premise. `upload_to_jena` logs **no triple count** — only
the graph URI. The single triple count anywhere in this pipeline is Neo4j's
`triplesLoaded`, returned by `n10s.rdf.import.fetch`
(`semantic_assets.py:1058-1068`).

So the 8 is a **Neo4j-stage** number, after n10s mapping, not a count of what the
parser emitted or of what Jena received. What the parser emits over these bytes
is 5 / 9 / 11 / 12 / 14 / 48, which matches the contract triple-for-triple. The
two numbers were never in conflict; they were two different instruments at two
different stages, and I labelled one of them with the other's name.
