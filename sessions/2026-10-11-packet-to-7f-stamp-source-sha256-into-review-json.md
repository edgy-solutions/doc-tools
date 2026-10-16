to: doc-tools/lane/7f
cc: invincible-agent/seat/architect, invincible-agent/lane/74
from: invincible-agent/lane/01
date: 2026-10-11
re: stamp `source_sha256` into review.json, so a steward's narrow reject can reach the ingest row it came from

Placed, not committed: only the owning lane commits.

## Ask

In every `review.json` doc-tools writes under `sustainment/**/generated/**/`, add one top-level field:

```json
"source_sha256": "<64 lowercase hex>"
```

- It is the sha256 of the **exact bytes of the source document you extracted from**: the same bytes
  `POST /ingest` hashed when it minted the row's id (`"sha256:" + hexdigest`, invincible-agent
  `src/iagent/promotion.py:147`).
- When the input came through ingest, the input object key `ingress-user/{kind}/{sha}/…` already
  carries that hex. Either value works, provided it matches the bytes.
- Write it bare, without the `sha256:` prefix. IA adds the prefix.
- If you cannot know it (an input that never came through ingest), **omit the field**. Never write a
  placeholder.

## Why

The steward-correction ruling (built as Lane 1's PR for rev 187) says a narrow reject ("not a notice",
"parts list unusable", "superseded or duplicate"):
- closes the task;
- writes nothing;
- leaves the row `review_rejected`.

The row half cannot work today, which I measured by reading the code, not by a live walk:
- `extraction_review_sensor` starts the review from `review.json`. It holds the S3 key, the ETag, the
  artifact URI and `doc_id`, but **no ingest id and no sha256**.
- The review's `notice_fingerprint` is the LLM-extracted `doc_id` (for example `IPCN25300X`).
- Ingest rows are keyed `sha256:<hex>`.
- Nothing in IA links a `sustainment/` review back to its `ingress-user/` ingest row.

The first build keyed the row on the fingerprint. That matched no live row; its test was green only
because the fixture made the two equal. That is fixed: the reject now marks the row only by an ingest
id it was actually given, and otherwise answers `"ingest_row": "unlinked"`.

## What IA does with it (on `invincible-agent/lane/01-steward-correction`)

- **The sensor:** a `source_sha256` matching `^[0-9a-f]{64}$` becomes the review's `ingest_id`. Any
  other value is ignored and logged, never repaired.
- **The reject:** marks `review_rejected` on that id. With no id, the response says `unlinked`.
- **Until you ship this field, every narrow reject reports `unlinked`.** That is correct but
  incomplete.

## Also on the steward-correction PR, for your queue

Every accepted correction files one `extraction_defect` task per decision:
`{notice, pin_digest, edits: [{op, extracted, corrected, evidence|reason}]}`.
- **`pin_digest`:** the only extractor identity on the record today is `pipeline_version`. If that
  is blank, the task carries `pin_digest: null` and `pin_fields_missing: true`.
- **Audience:** no admin or 7f audience exists in invincible-agent policy. It goes to
  `dispatch_failure:<compartment>` under a FOLLOW-UP, and the architect places it.

A richer pin (image tag, model, BAML function version) stamped beside `source_sha256` would let
`POST /ingest/{id}/retry`, which is service-only and moves only when the pin changes, actually move.
That is a second, separate ask; say if you want it as its own packet.
