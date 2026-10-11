to: doc-tools/lane/7f, invincible-agent/lane/74
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-10
re: a steward reject for "extraction error" lands TERMINAL; POST /ingest/{id}/retry cannot reach it, and nothing re-extracts on a new pin

> **SUPERSEDED the same night by the steward-correction ruling. Do not build the asks below.**
> - The steward CORRECTS rows in the review resolve: `obtained_via=steward-corrected`,
>   `corrected_by`, `extracted_value` and an evidence pointer, written to the graph with that
>   provenance.
> - Every correction files an `extraction_defect` record {notice, pin digest, extracted,
>   corrected, evidence} to the admin/7f queue.
> - A narrow reject (wrong document / not a notice / duplicate) closes the task, writes nothing,
>   and leaves the row `review_rejected`.
> - `/ingest/{id}/retry` stays, driven ONLY by a pin change, never by the UI.
> - Lane 1 builds this as a PR for 187. The MEASURED section below still stands as the "before".

Placed, not committed: only the owning lane commits. Copies of this packet are in both repos' `sessions/`.

## Chris's order

> steward rejecting a review with reason "extraction error" must route the drop to POST
> /ingest/{id}/retry once a new pin lands, not to terminal. Confirm the retry path does that, or
> packet 7f/74.

**It does not.** I measured this by reading the code on master `1fdf27e6`; I did not walk it live.
Each step below breaks the chain on its own.

## Measured (`src/iagent/gateway.py` @ 1fdf27e6)

1. **Every reject is written `rejected`, which is terminal** (~3563-3575, the document_promotion
   act).
   - `_stage = PROMOTED if decision == PROMOTED else REJECTED`.
   - `_detail = req.comment`, so the reason is free text and only ever stored as the row's detail.
   - Nothing reads the reason. "extraction error" and "wrong document" land in the same state.
2. **The request has no structured reason.** `HumanTaskActRequest` (~646) carries `decision`,
   `comment`, `overrides` and `on_behalf_of`. There is nothing to branch on except parsing prose.
3. **Retry refuses a rejected row** (`@app.post("/ingest/{ingest_id}/retry")`, ~9979; `_terminal_stages`
   at ~10016).
   - PROMOTED, REJECTED, FAILED, DUPLICATE, CASE_OPENED and AWAITING_ORIGIN all return **409 `terminal`**.
   - EVENT returns 409 `resend_the_event`. RECEIVED and EXTRACTING return 409 `in_pipeline`.
   - Only `review` does anything, and what it does is re-file the promotion task
     (`_file_or_find_document_promotion_task`). **Retry never re-extracts.**
4. **doc-tools cannot move it either** (`POST /ingest/{ingest_id}/stage`, ~10245-10272). REJECTED is
   in its `_terminal_stages`, so any move off it returns 409 `backwards_move`.
5. **Nothing ties a new extraction pin to a stranded drop.**
   - `src/iagent/defs/extraction_review_sensor.py:820-828` says a CONTENT refusal is fixed by
     re-extracting: a new ETag gives a new key, which composes afresh. That covers new *content*.
   - A new extractor *pin* with unchanged content moves no ETag. The only key-wide lever is the
     manual `REVIEW_REQUEST_KEY_EPOCH`, and it re-drives refusals in the review sensor, not
     `rejected` ingest rows.

So today an "extraction error" reject is a dead end. Re-uploading the artifact is the only way out,
and it creates a new ingest_id.

## The asks (proposed split; the architect decides the shape)

- **74 (the ingest route and stage machine):**
  - Add a structured reject reason to the document_promotion act, for example
    `reason: extraction_error | wrong_document | …`. Keep the comment, which is still required.
  - Under `extraction_error`, write a NON-terminal parked stage (for example
    `awaiting_reextraction`) instead of `rejected`, with the comment as its detail.
  - Let `/ingest/{id}/retry` accept that stage: send it back to `extracting`, or hand it to
    doc-tools to re-run, rather than returning 409 `terminal`.
  - Every new stage has four homes: `ingest_status.STAGES`, both `_terminal_stages` tuples, the
    stage route's `_forward_order`, and the gating manifest. Census them, don't edit one.
- **7f (extraction and the pin):**
  - When a new extractor pin lands, find the rows parked under `extraction_error`, re-extract them,
    and POST `/stage` → `review` (or call retry). The pin version must be part of what
    distinguishes a re-extraction, since the ETag will not move.
  - Say whether the pin-to-redrive trigger belongs in doc-tools (the ingress sensor) or in IA (a
    sensor on the parked stage). That decides who owns the seal.
- **The seal both halves need:** a reject with reason `extraction_error` must NOT be terminal, and
  a reject with any other reason MUST stay terminal (the control). Then, after a pin change, the
  same ingest_id must reach `review` again.

## What I did not do

- I changed no code: this is a design change across two repos and the stage machine.
- I did not check doc-tools' side beyond the IA routes it calls.
- I did not walk a reject live on 185.
