# Report — 7f: the ownership ruling landed, three PRs merged, and the values travel as a packet

**Date:** 2026-10-30
**Lane:** 7f (`doc-tools`)
**Ruling acted on:** architect, 2026-10-30 — *"ownership stands as ruled 10-24:
the platform registry declares kind/domain/arrives_as/review_shape/label (Lane 1
fills them from your packet); doc-tools declares passes. Your decline + test
stay. #192, #191, #181 merge."*

---

## 1. The merges, read from state

Per the standing rule that a status claim is read from git/GitHub in the same
message as the claim, not from a packet:

| PR | what | merge commit | confirmed |
|---|---|---|---|
| **#181** | the overlay drift seal reads a PINNED sha, not a working tree | `f332c63` | `MERGED 14:49:51Z`, present in `origin/main` |
| **#191** | `customer_mpn` as its own row field and column | `1a25fd3` | `MERGED 14:50:05Z`, present in `origin/main` |
| **#192** | v0.9.11 pin + kinds adoption | **not yet** | see §3 |

No `--admin`, no force. Squash merges, matching this repo's history. **No path
appears in two of the three PRs** — measured before merging, which is why the
order was free and no rebase was needed.

## 2. What the ruling falsified in #192's own prose, and the fix

The ruling closes a collision that #192 described as live in three places. Left
as written, the merged tree would have carried a statement the architect had
already overturned. Corrected in `6061adf`:

* `doc_tools/utils/kind_registrations.py` — the projection docstring said *"NOTE
  THE COLLISION, because it is not resolved by either side."* It now records the
  ruling, that iagent-mesh's 2026-10-21 changelog line is **superseded**, and
  that what this lane owes is a **packet to Lane 1**, not a row here.
* `tests/test_kind_registry.py` — the arm's docstring said that if a ruling
  landed on this side, *"this arm is the one to delete."* The ruling went the
  other way, so the arm is **permanent**; deleting it would re-open the second
  source of truth both the 10-24 and 10-30 rulings close.
* `doc_tools/utils/content_kind.py` — the `review_shape` decline now names the
  10-30 affirmation beside the 10-24 split it already rested on.

Prose only: no projected field, row payload or assertion changed.
`tests/test_kind_registry.py` — **22 passed**.

## 3. #192 is not merged yet, and why

`6061adf` restarted `build-and-push` (started 14:53Z; the previous runs took
38–45 minutes). Seven of eight checks are green at this head;
`corpus-gate`/`corpus-gate-verdict` skip as they do on every non-`charts/` PR.
The build at the *previous* head `7ef11e4` was green, and `6061adf` changes only
docstrings — but a predicted verdict is not a read one, so the merge waits for
the run. **Note:** pushing did not cancel the in-flight `edebdad` run; two
builds ran concurrently for the same branch.

## 4. The packet — what the ruling actually asks of this lane

*"Lane 1 fills them from your packet."* So the values exist, and they travel:
`sessions/2026-10-30-packet-to-lane-01-from-7f-the-four-platform-owned-kind-fields-row-by-row.md`.
All thirteen registered kinds, with `domain` / `arrives_as` / `review_shape` /
`label` and a basis for each. Its substance, in brief:

* **`domain` is our sidecar verbatim** (`registry/content_kind_domains.json`) —
  in the packet to be compared against, not re-keyed.
* **`arrives_as` is named for nine rows and refused for four.** `cad`,
  `doors-export`, `engineering-document` have **no arrival format measured
  anywhere in the tree** — no suffixes, no prefix, only prose — and a guessed
  value here is a wrong leaf offered to a user. `dxf` and `step-ap242` are
  marked as proposals rather than measurements.
* **`review_shape`: `notice` for `pcn`/`pdn`, `document` for
  `work-instruction` and `document`, refused elsewhere** — `s1000d-data-module`
  emits an RDF graph that neither card fits, `course` has no card, and a
  format-level row runs no passes and posts no review.
* **`label` is proposals only**, flagged as such: it is UI copy served on the
  wire and this lane holds no authority over the wording.
* **The seal's exposure, measured:** our cross-repo seal compares the kind set,
  `passes`, `outputs` and `domain`-against-the-sidecar. It does **not** compare
  `arrives_as`, `review_shape` or `label`, so Lane 1 can fill those three
  without reding our suite. `domain` has a trip-wire, and an explicit
  `domain: null` is a different row from an omitted one.

The packet also carries the measured `parent_link_field` answer for
`s1000d-data-module` (a parent link there is a new directed edge in the graph
builder, not a field name we withheld) and four traps, including that `course`
declares three suffixes of which only `.pptx` has ever fired.

## 5. The audit's two findings are queued, not retrofitted

The architect, same day: *"both findings are queue items after the batch chain:
runtime reads the registry once the platform serves it; the domain if/elif
ladder becomes passes keyed by domain under ADR-0059. Not a retrofit now."*

That confirms the audit's own call (measure, report, do not refactor) and gives
each finding a shape it did not have when I wrote it:

* **test (4)** — the runtime reads `KIND_MAPPING`, and nothing under
  `doc_tools/` reads `registry/content_kinds/` at all. The fix **waits on the
  platform serving the registry**; it is not a local re-plumbing to start now.
* **test (2)** — the `domain_type` `if/elif` ladder becomes **passes keyed by
  domain under ADR-0059**, which is a different design from the row-per-domain I
  had sketched in §4 of the audit. Noted so the sketch is not mistaken for the
  plan.

Neither is open work. Recorded in memory so a future session does not start one.

## 6. Still owed by this lane

* **`branch`/`refresh` on `ContentKindEntry`** — ADR-0063 §1's remaining
  answer. No event kind can be registered from our table until the dataclass
  carries both; every row today is a `branch="document"` row and takes that
  default honestly.
* **#192's merge**, on its build.
* Carried, unchanged: the gate written-arm vs `mfr_agreement` contradiction
  needs a ruling; #167's Neo4j migration dry run as a pod Job; the packet to
  lane tr to re-ingest `_p132`/`_p102` and re-golden.
