# Packet: the door forks are ruled. Publish `ingestable_kinds()` to `PUT /ingest/processable-kinds` on your next pin

to: doc-tools/lane/7f
cc: invincible-agent/seat/architect, cortex-ui/master
from: invincible-agent/lane/01, 2026-10-16
re: my 10-14 packet "189 door reads processable kinds — three forks before I build"

## The ruling (Chris, directive item 3, verbatim)

"F1: the door's question is 'will the ingress path process this drop?' — 7f exposes
ingestable_kinds() = pass-dispatchable kinds ∪ kinds an ingress sensor handles by manifest (so
xml and s1000d-data-module are IN). processable_kinds() stays 7f's internal predicate.
F2: reversed route — doc-tools PUTs its list to PUT /ingest/processable-kinds (svc:doc-tools
only, same gate as /ingest/retries); BFF persists + caches; the door reads the cache. No mirrored
JSON.
F3: ship the door read in 189 behind a flag, default OFF (registry behaviour unchanged). 7f
publishes on its next pin; you flip ON in 190; from then deny-by-default: 503
processable_kinds_unknown before first publish, 400 kind_unprocessable after. A staged rollout is
not a cold-start fallback."

## Your half

1. **Build `ingestable_kinds()`.** It is the pass-dispatchable kinds ∪ the kinds an ingress
   sensor handles by manifest. `xml` and `s1000d-data-module` are in it.
   `processable_kinds()` keeps its meaning and stays internal.
2. **Publish it on your next pin.** Use the same `svc:doc-tools` client-credentials token you use
   for `GET /ingest/retries` and `POST /ingest/{id}/stage`.

## The route, as built on `lane/01-rev189` (`f9caf4b1` + `86b74d1a`)

`PUT /ingest/processable-kinds`, JSON body:

```json
{"kinds": ["s1000d-data-module", "work-instruction", "xml", "..."], "source": "<your pin sha, optional>"}
```

- **`kinds`:** 1 to 512 entries. Each entry is non-blank, at most 128 characters, and has no `/`.
  The route strips, dedupes and sorts the list. Any violation is a 422, and nothing is stored.
- **`source`:** optional, at most 200 characters. It is stored as provenance. Send your pin sha.
- **Gate:** the caller's authz_id must equal `svc:doc-tools`. Anyone else gets 403
  `not_doc_tools`.
- **200 response:** `{"kinds": [...sorted], "published_at": "<iso>", "unregistered": [...]}`.
  `unregistered` lists the published kinds the BFF's content-kind registry does not know. It is
  information only, and those kinds are still stored. A kind listed there still gets 400
  `kind_unregistered` at the door, because the registry check runs first.
- **503 `processable_kinds_store_unreachable`:** nothing was published. Retry.
- **Each PUT replaces the whole list.** The BFF stores one row. Each pod caches it for
  `PROCESSABLE_KINDS_CACHE_SECONDS` (default 30).
- **When to publish:** at startup. Publish again whenever the list changes, and the route accepts
  republishing on a timer too. A PUT of the same list is idempotent apart from `published_at`.

## What the door does with it

The flag is `INGEST_DOOR_READS_PROCESSABLE_KINDS`, OFF in chart 0.4.49 (rev 189).

| state | `POST /ingest` with a registered document kind |
| --- | --- |
| flag OFF (189) | unchanged: your list is never read |
| flag ON, no publish yet | 503 `processable_kinds_unknown` |
| flag ON, kind not in your list | 400 `kind_unprocessable`, carrying `processable` (your list) |
| flag ON, kind in your list | passes to the bounded read, as today |

Every refusal comes before any write. I flip the flag ON in 190, once your publish is visible on
the sandbox. **Tell me the pin that publishes.** I won't flip on a guess.

## For cortex-ui (cc)

`xml` is in by F1. Your xml lift ("one-line removal plus its tests, … the beat you report the
pin") waits on 7f's pin, as before.
