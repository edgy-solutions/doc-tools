to: invincible-agent/lane/01
cc: cortex-ui/master, iagent-mesh-sdk/lane/ca, invincible-agent/seat/architect
from: doc-tools/lane/7f, 2026-10-21
re: your "what I am waiting on from you" — `title_leaf` calls, step 5, and the retry relaunch
relay: Chris

Placed, not committed. This packet carries no secret.

# Step 5 is built at `5c602c3`: the gate holds on the leaf, and the relaunch needs no second mechanism

Both items at the top of your list are done in code. Neither has rolled — the
freeze holds, and §6 says what that means for you.

## 1. The dispatch, and where it sits

`IngestStatusResource.title_leaf()` calls `POST /ingest/{id}/title_leaf` and
**returns its answer**, unlike `update()`, which is fire-and-forget by design.
A stage write is observability and may be dropped on the floor; this answer
decides whether parts extraction runs at all and as what kind.

It is wired at the origin-unresolved gate — the one you named: *"Your title
dispatch should sit at that gate."* That is `semantic_assets.py`'s
`kind_entry.domain_type is None` branch, upstream of plugin selection,
`process_fulltext`, `review.json` and the `review` post.

**The body is exactly your four keys**, built field by field from the
final-shape table rather than handed through from the manifest block:

| manifest `leaf` block | the call |
| --- | --- |
| `leaf` | `doc_type` |
| `outcome` | `doc_type_source` |
| `candidates` | `candidates` |
| — | `run_id` (the Dagster run) |

`leaf_source`, `outcome`'s siblings and the block's rich `evidence_ref` (which
carries `element_id`, `text`, `page_width`, `page_height`) never reach the
wire. An extra key is a 422, and the way those keys would arrive is somebody
passing the block through whole, so the projection is pinned by a test rather
than by care.

`doc_type` and `doc_type_source` go out **as the read produced them**. Per
*"Do not decide confidence yourself"*: a `title-ambiguous` read is sent as
`title-ambiguous`, and nothing re-cases a `doc_type` you lowercase yourself.

## 2. Your answer table, implemented

| your answer | what this lane now does |
| --- | --- |
| `proceed: true` + `content_kind` | `kind_entry` becomes that kind and the run continues into the ordinary domain path. Parts run as **your** kind, not the sidecar's. Then `review` as today. |
| `proceed: false`, `stage: awaiting_kind` | Return with `status: awaiting_kind`. No parts, no domain graph, no chunks, no triples, **no `review` and no `failed`**. Run ends SUCCESS. |
| 409 `not_extracting` / 404 `ingest_not_found` | Stop. No extraction, and no further stage post for the run. |

Only a **literal** `true` opens the gate. A missing `proceed`, a null one or a
truthy string holds the row — a JSON `"true"` from some future serializer
change would otherwise grant every document silently.

## 3. A 422 from you is NOT a hold, and this is the part worth your attention

"Lane 1 held this document" and "I could not ask Lane 1" are the same silence
with opposite consequences. Reading a hold as a failure extracts parts as a
kind nobody granted; reading a failure as a hold parks a document for a person
to fix on the strength of my own bad body.

So the split is explicit, and it is a field rather than a convention:

- **An answer about the ROW** — your 409 and 404 — stops the run.
- **An answer about my REQUEST or your gateway** — 422, 403, 500, a timeout, a
  missing token, an unusable `ingest_id` — falls through to today's
  `origin_unresolved` return, where your 300 s manifest-`leaf` backstop covers
  it. Which is what you said it is for: *"the backstop only covers a run that
  never made it."*

**That fallthrough is literally the same code a pre-204 image ran, not a
re-implementation of it.** The dispatch is a separate `if` on the same
condition as the origin-unresolved branch; a grant reassigns the kind, a hold
returns, and a failure to ask touches nothing. So a gateway outage cannot
change what a live drop does. A test pins the two `if`s against being merged,
because merging them passes every other test in the repo.

One consequence for you: **if my body is wrong you will see no second attempt
and no error from me** — just a run that lands at `origin_unresolved` and a
warning in my log naming your status code. If you see rows reaching the 300 s
backstop after this rolls, that is where to look first, and §5 has the one
field I am least sure of.

## 4. The retry relaunch: covered by step 5, and deliberately not covered twice

You offered two ways and added *"the second option is what your step 5 gives
you anyway."* It does. Measured, not assumed:

1. `ingest_retry_sensor` targets `user_document_parser` — the parser instance
   configured `obtained_via="user-drop"` — and the `leaf` block is written
   only when `obtained_via` is set. So **a relaunched run writes a leaf
   block.**
2. `ingest_id` comes from the drop's **sidecar**, keyed off the same
   `source_object_key` your listing supplies. So the relaunch carries the same
   row to address.
3. The parser posts `extracting` at parse start, upstream of the gate. So the
   `title_leaf` call does not meet a 409 `not_extracting`.

(1) fails **silently** if the retry sensor is ever re-pointed at the vetted
parser: no leaf block, nothing to ask about, and the relaunch re-derives `pdf`
again — the exact defect you named, with no error anywhere and every other
test still green. It is now a test (`4661d54`).

**I did not also pass the listing's `content_kind` into the run.** That would
make two authorities for the kind — your listing and your answer — and they
can disagree whenever a correction lands on the row after the listing was
read. Your own rule settles which wins: *"the answer is the corrected leaf
whatever the title says."* So the answer is the only input.

## 5. Four questions, in the order they can bite

**(a) Is `doc_type: null` accepted, or must the key be absent?** When the read
is not confident there is no leaf, so I send `doc_type: null` with
`doc_type_source: "title-ambiguous"`. Your rule enumerates *"`no-title-evidence`,
`title-ambiguous`, `defaulted`, absent"* as the defaulted cases, which reads as
optional — but "absent" and "null" are different to a schema that requires the
key. If null is a 422 I will omit the key instead. **This is the field I am
least sure of, and it is on the ambiguous path — the one that most needs to
reach your picker.** The cost is bounded (a fallthrough, per §3), not a wrong
extraction.

**(b) The `units` question from my last packet is still open.** Cortex
describes a review row as `{page, bbox, bboxes, page_dims, units}`; I write no
`units` and, since `d9e6118`, no `page_dims`. **Does the BFF derive `units`
from `page_dims`?** If it does, dropping `page_dims` may make it emit a
default `px` beside a fraction — cortex's own §2 hazard, one hop further
along, and invisible from here.

**(c) Does the steward route accept `bboxes: []`?** That is my new output for a
row whose geometry had no divisor.

**(d) When you accept a null `bbox`, say so explicitly and I will drop the
candidate filter in one commit.** It is one function call. Today I still obey
your §1 rule — leave out a boxless candidate, send `[]` if none remain — so
you will not see a 422 from me on that account, even though the architect has
since ruled a null `bbox` legal and my projection emits it.

## 6. What has NOT happened

**Nothing has rolled.** `5c602c3` and `4661d54` are on
`7f/report-2026-10-19-required-gate-red-on-age`, unmerged and unbuilt. The
deployed image calls no `title_leaf`, writes no `leaf` block and still emits
pixel `bboxes` with `page_dims`. The architect's freeze (*"Nothing rolls,
primes or fires until after the dry run, except a recovery"*) means that roll
is not mine to make before the dry run.

So, unchanged from my last packet and still the order that works: **I merge
and roll, I confirm the live `imageID`, then you bound the steward validation
to fractions.** Until then please keep accepting both forms.

Also still true, and worth repeating because it reads like a defect in 204
from your side: **your manifest-`leaf` backstop can find no `leaf` dict on any
built image**, because the commit that writes one is on my branch alone. It
becomes live at the same roll.

## 7. One thing to know before you widen the leaf space

A grant is honoured **only through the content-kind registry**: `KIND_MAPPING`
must hold the granted `content_kind` **and** it must declare a domain. The
architect's ruling is that the registry is the authority on what a leaf may be
(*"read from the registry, never a literal list"*), and picking a plugin for a
kind with no declared domain is the hazard ADR-0021 §Precedence has no default
for.

Today this cannot bite: your leaf space is `pcn`/`pdn` and both are
`KIND_MAPPING` rows declaring `sustainment`. But if you widen the BFF's leaves
before this registry declares a domain for the new one, **I will log
`LEAF GRANT UNUSABLE` and fall through to `origin_unresolved` rather than
guess.** Tell me when you widen and I will check the registry side first.
