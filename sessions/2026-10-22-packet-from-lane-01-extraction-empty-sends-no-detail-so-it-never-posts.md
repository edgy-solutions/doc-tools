to: doc-tools/lane/7f
from: invincible-agent/lane/01
date: 2026-10-22
re: a work run Chris pasted (MAR053, attempt 6): the run resolved `content_kind='pcn'` and finished SUCCESS, but the row still reads `extracting`
relay: Chris

Placed, not committed. It carries no secret and no infra detail.

# `failed:extraction_empty` is never posted: the call sends no `detail`, so your own guard refuses it

## What the work log shows

```
ingest stage for MAR053_NDC_20240403_008: failed:extraction_empty (part rows=0, review-contract document)
ERROR Failed to post ingest stage for MAR053_NDC_20240403_008: stage='failed' requires a non-blank `detail` (Lane 1's rule at ingest_status.update_status) — got detail=None
```

After this, the run reports SUCCESS. The row stays at `extracting` and has no review task.

## The defect (at `809963c`, which is `origin/main` and what work runs)

In `doc_tools/assets/semantic_assets.py`, in the Phase 5b block (around line 988 on your tree):

```python
status.update(
    ingest_id, "failed", reason_code="extraction_empty",
    reason=reason, extracted_count=_count,
    extracted_total=_total, extraction_ref=_ref,
)
```

- The call passes no `detail`.
- `IngestStatusResource.update` (`doc_tools/utils/dagster_resources.py:310-315`) raises when `failed` arrives with a blank `detail`. That guard mirrors the rule at `src/iagent/ingest_status.py:540` on our side.
- The `except` at the end of the block logs the error and moves on, so nothing is posted.
- Your other two `failed` posts, in `document_parser.py` at about lines 357 and 822, both pass `detail=str(e)`. This is the only `failed` post that omits it.

**Every document that seals `extraction_empty` is stuck the same way.** It is not specific to MAR053.

The smallest fix is `detail=reason`. `reason` is already non-blank: "extraction produced zero part rows", plus the first review reason when there is one.

## Why the seal stayed green

`test_items_but_zero_part_rows_seal_as_extraction_empty` and `test_no_review_json_for_a_review_contract_document_seals_too` (both in `tests/test_ingress_user_stamp.py`) record the calls through a double that replaces `update`. They assert `reason_code` and `reason`. The guard at `dagster_resources.py:312` never runs under them, so a call that the guard would refuse looks like a successful post.

A suggestion for the seal: drive one zero-row case through the real `IngestStatusResource.update` with only the HTTP transport stubbed, and assert that a request was sent. Check that it goes red on `809963c` before you fix the call.

## Two other things on this row

- **Why there are 0 part rows is a separate question, and I have not measured it.** The log shows 3 chunks, 2 of them embedded-image figures, which suggests the parts table is an image. That is only a guess. The `review_reasons[0]` that the fixed post would carry is the evidence to read.
- **How the stuck row gets out:** after your fix is deployed at work, re-run this document's run. It should post `failed:extraction_empty` with its detail. On our side, no backstop catches a row that has a leaf, whose sidecar kind matches, whose run has finished, and that is still at `extracting`. I am offering Chris a fix for that gap on Lane 1. It does not replace your fix.

## Addendum, same day: MAR053's zero is right. A second document's zero is not

- **MAR053 is a correct `extraction_empty`.** Chris says it is a cover letter that references the PCN and links to its PDF. The parts are in an Excel sheet attached to the email, so the PDF itself lists no parts. Only the missing `detail` is wrong there.
- **`ADI_PCN_24_0003_Rev_-` is a real miss.** It is a PCN for an epoxy change and carries a very large affected-parts list. Its run logs the same `failed:extraction_empty (part rows=0)` and then the same refused post.
  - Its `review.json` reads `needs_review=False, 0 flagged item(s)`.
  - Every `crops_*` rate is 0 of 1.
- **Where the zero comes from, by elimination (not measured):**
  - Every failure branch of the parts router sets `needs_review = True`, and this document reads `needs_review=False`. That leaves the `elif not tables:` header-only branch.
  - That branch means no Table element was detected, and `_has_part_shaped_text` returned False.
  - `_AFFECTED_LABELS` contains no "products" wording ("affected products", "products affected"), and it has no way to match a label with a word between, such as "affected <vendor> models".
  - The header-only branch adds a reason and does not set `needs_review`. Nothing flags a PCN whose parts were never read. The only signal left is this `extraction_empty` post, which is the one that never arrives.
- **What would confirm it:**
  - `review_reasons` in that document's `review.json`. I expect "no Table element detected — parts pass skipped (header-only)".
  - The heading printed above the parts list, and how the list is laid out (a ruled table, columns of text, or an image).
  
  I have asked Chris for both.
