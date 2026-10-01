# `notice_identity` — the Level-2 dedupe contract

**For the ingress-user lane (7f), which owns the sensor.** doc-tools owns the key;
you own the decision. This is the seam between them, written so you can code
against it without reading `doc_tools/utils/notice_identity.py` — though that
module's docstring is the authority if the two ever disagree.

Module: [`doc_tools/utils/notice_identity.py`](../doc_tools/utils/notice_identity.py).
Tests that pin it: [`tests/test_notice_identity.py`](../tests/test_notice_identity.py).

---

## 1. Why there is a key at all

Two arrivals of the same notice must not both ingest, and a newer revision must
supersede an older one rather than sit beside it. Neither question can be answered
from what a sensor sees: an S3 object gives you a filename, an ETag and a timestamp,
and none of those tell you that `Diodes_PCN_2683_Rev1_EOL.pdf` and
`Diodes_PCN_2683_FULLGREEN.pdf` are the same document (they are — byte-identical, see
§5.4), or that a re-uploaded file is a revision rather than a duplicate.

The identity has to come from the **header** — `(mfr, doc_id, revision)` as printed in
the document. That is extracted during ingest, so doc-tools computes the key at the
header pass and hands it to you on the artifacts below. You never re-run extraction to
dedupe.

## 2. Where to get it — three artifacts, no extraction needed

All three are written by an ordinary ingest. Same value in each; pick by what your
sensor already reads.

| Artifact | Path | Where the identity is |
|---|---|---|
| `review.json` | `{base_dir}/review.json` | `notice_identity` (top level) and `stats.notice_identity` |
| `extraction.json` | `{base_dir}/extraction.json` | `augmentations[0].stats.notice_identity` |
| corpus-run JSON | `scripts/pcn_corpus_run.py` output | `{filename}.stats.notice_identity`, plus `written_header` and `content_hash` |

`base_dir` is `os.path.dirname(manifest["text_location"])`.

The payload is exactly what `build_identity` returns:

```json
{
  "key": "diodes\u001fpcn 2683\u001f1",
  "mfr": "Diodes Incorporated",
  "doc_id": "PCN 2683",
  "revision": "1",
  "normalized_mfr": "diodes",
  "normalized_doc_id": "pcn 2683",
  "normalized_revision": "1",
  "complete": true,
  "note": null
}
```

`key` is the normalized triple joined on `SEPARATOR` (`\x1f`, ASCII Unit Separator) —
it *is* the human-readable triple, deliberately, so there is no digest to keep in sync
with it. It is deterministic across processes: it depends only on the three inputs and
fixed module data, never on Python's salted `hash()`.

**`key` can be `null`.** When it is, `complete` is `false` and `note` says which
component was missing. Treat that as "identity not assertable", never as a key of
`""` — see §5.1.

## 3. The API, if you would rather compute than read

```python
from doc_tools.utils import notice_identity as ni

ni.build_identity(mfr, doc_id, revision) -> dict   # the §2 payload; never raises
ni.notice_key(mfr, doc_id, revision)     -> str    # the raw key; keys anything, even ""
ni.parse_notice_key(key)  -> (mfr_c, doc_id_c, revision_c)
ni.classify_pair(a, b)    -> {"relation": str, "reason": str}
ni.normalize_component(v) -> str   # mfr, doc_id — dot is typesetting noise, stripped
ni.normalize_revision(v)  -> str   # revision — dot is structural, kept (see §6.5)
ni.SEPARATOR              == "\x1f"
```

Use `build_identity`, not `notice_key`. `notice_key` will cheerfully build a key out of
empty strings; `build_identity` is the one that decides a header is too incomplete to
key at all, and that decision is the whole point (§5.1).

## 4. `content_hash` is yours to compute

`classify_pair` takes two records shaped like:

```python
{"key": str | None, "content_hash": str, "revision": str | None,
 "doc_id": ..., "mfr": ...}
```

`build_identity` supplies everything **except `content_hash`**, and that is not an
oversight to work around — the plugin sees extracted text, not the uploaded object, so
it cannot honestly hash the bytes. The sensor holds the object. You hash it:

```python
record = {**identity_from_artifact, "content_hash": "sha256:" + sha256(body).hexdigest()}
```

Hash the **source object's bytes**, not the extracted `text.json`. Two partitioning runs
over one identical PDF produce different text extractions, so a text hash reports one
document as two. `scripts/pcn_corpus_run.py::source_content_hash` is the reference
implementation, and it reads `manifest["source_key"]` — the key the producer declared,
not one derived by string surgery on `text_location`.

## 5. The six relations, and what to do with each

`classify_pair(a, b)` is directional: `a` is the arrival, `b` the incumbent.

| `relation` | Means | Sensor action |
|---|---|---|
| `identical` | Same `content_hash`. The same bytes. | Drop the arrival. Nothing to ingest. |
| `duplicate_copy` | Same key, different bytes — a re-render, re-scan or corrected typo. | Your call. Same notice, so not a new document; the bytes did change. |
| `supersedes` | Same `(mfr, doc_id)`, and `a` is the newer revision. | Ingest `a`, retire `b`. |
| `superseded_by` | Same `(mfr, doc_id)`, and `a` is the older revision. | Do not let `a` displace `b`. |
| `revision_order_unknown` | Same `(mfr, doc_id)`, revisions differ, order **not decidable**. | **Do not guess.** Route to a human. |
| `distinct` | Different `(mfr, doc_id)`, or either record has no key. | Ingest independently. |

`identical` is checked **before** the keys are compared, and the ordering is
load-bearing rather than tidy. Identical bytes cannot stand in a revision relation to
themselves, however the header pass keyed them. This check used to sit inside the
`key_a == key_b` branch, and a pair whose keys differed only because the header pass
reported the revision inconsistently skipped it and came back `supersedes` — measured on
the real Diodes PCN-2683 pair, same sha256, one copy declared to supersede the other.

`revision_order_unknown` is a real, reachable outcome and not a fallback that never
fires. It is returned whenever the two revisions are not both numeric, not both
single-alphabetic, or one side is absent — because an absent revision may be a header
miss rather than a document that prints none, and guessing would hide the newer notice
behind the older one.

## 6. Four things that will bite you

### 6.1 A refused `mfr` produces no key, and that is deliberate

The key is computed **after** `refuse_unsourced_header_values`. A notice whose `mfr` was
refused (the printed value carried no citation) reaches `build_identity` as falsy and
gets `key: null`, so it is never matched against anything.

That direction is chosen, not accidental. Declining to key costs a **missed duplicate**,
which the next arrival can still be compared against once its header is sourced. Keying
on a refused value costs a **false match**, which silently merges two manufacturers'
notices. The same applies to a document that legitimately prints no manufacturer at all:
both reach the module as a falsy `mfr`, and it does not try to tell them apart.

So: `key: null` means *do not dedupe this one*. It does not mean the ingest failed.

### 6.2 An empty `mfr` is not a key

Do not synthesize a key from the raw `mfr`/`doc_id`/`revision` fields when `key` is
`null`. Every failed-header document would collide under one key with every other.
`classify_pair` already handles a `null` key by returning `distinct`; let it.

### 6.3 The key is only as stable as the header pass, and today it is not stable on every notice

The key is a deterministic function of its inputs. The **inputs** are model output, and
at pin `dd043b6` one corpus notice (`TYC-PCN-24-210412.pdf`) reads `mfr` differently
across repeated fires on identical bytes, so its key differs too. The release gate
(`scripts/pcn_corpus_gate.py`) reports that as `identity_half_unstable` and blocks on it,
which is why a pin bump is gated on header agreement and not only on parts recall.

Practically: an unstable key can make one document look like two arrivals. The gate is
the mechanism that keeps an unstable pin from reaching you; it is not a guarantee about
any single ingest.

### 6.4 The Diodes pair is one document under two filenames

`Diodes_PCN_2683_Rev1_EOL.pdf` and `Diodes_PCN_2683_FULLGREEN.pdf` are byte-identical
(md5 `abe083fe8bab…`, 181899 bytes; confirmed by a full enumeration of every PDF in
every bucket, 2026-09-30). They are the case `identical` exists for, and the case that
proves filename-based dedupe is not enough.

### 6.5 A dotted revision now orders correctly — segment-wise, zero-padded

**Fixed 2026-09-30.** Revision normalization runs through `normalize_revision`, not
`normalize_component`: it keeps the `.` that separates dotted revision segments (a
leading/trailing dot is still stripped as typesetting — `"2."` is revision `2` plus a
sentence period, not a structural dot). `_compare_revisions` then splits a dotted-numeric
revision on `.`, maps each segment to `int`, zero-pads the shorter side to the longer
side's segment count, and compares the resulting tuples segment-wise.

**What it used to do**, for the historical record — `normalize_component` stripped the
dot, so both sides were compared as concatenated integers:

| a | b | OLD reported (wrong) | actually |
|---|---|---|---|
| `2.0` | `1.15` | `superseded_by` | `2.0` is **newer** |
| `3.0` | `2.99` | `superseded_by` | `3.0` is **newer** |
| `1.0` | `1.00` | `superseded_by` | the **same** revision |

That was decided wrongly and silently, which is the one outcome §5's
`revision_order_unknown` exists to avoid.

**The new rule.** Dotted-numeric revisions (every segment all-digits — this subsumes
plain integers, which are just the one-segment case) compare segment-wise with
zero-padding:

| a | b | now reported | why |
|---|---|---|---|
| `2.0` | `1.15` | `supersedes` | `(2, 0) > (1, 15)` |
| `3.0` | `2.99` | `supersedes` | `(3, 0) > (2, 99)` |
| `2.0.1` | `2.0` | `supersedes` | `(2, 0, 1) > (2, 0, 0)` zero-padded |
| `1.0` | `1.00` | `duplicate_copy` | `(1, 0) == (1, 0)` — equivalent spelling |
| `01` | `1` | `duplicate_copy` | `(1,) == (1,)` — leading zero doesn't count |

An equal tuple comparison is a new, explicit `order == 0` branch in `classify_pair` — it
reports `duplicate_copy` ("same notice identity, different bytes"), because two spellings
of the same revision are the same identity, not an ordering. Anything not both
dotted-numeric and not both single-alphabetic (a dotted value with a non-numeric segment,
e.g. `1.A` vs `1.B`; a dotted value against a non-numeric scheme, e.g. `2.0` vs `R5`; a
printed dash; one side absent) still comes back `revision_order_unknown`, exactly as
before — this change only widens what counts as decidable, it never flips a decision.

Consumers that previously had to guard `supersedes`/`superseded_by` against a dotted
revision no longer need to: that guard is removed, and re-adding it would make a caller
refuse valid orderings (`2.0` genuinely supersedes `1.15` now).

**Scope.** The nine corpus notices carry revisions `R5`, `1` and absent — none dotted —
so this change alters no corpus key or relation. See the now-passing (no longer
`xfail`) tests at the foot of
[`tests/test_notice_identity.py`](../tests/test_notice_identity.py).

## 7. What is frozen, and what is not

**Frozen — code against these.** The names and signatures in §3; the §2 payload keys;
the six `relation` values; `SEPARATOR`; the rule that `identical` is decided on bytes
before keys; the rule that an incomplete header yields `key: null` rather than a key
built from empty components.

**Not frozen.** `reason` strings are for humans and logs, not for matching on.
Normalization details (which corporate suffixes are stripped, which punctuation is
dropped) may gain cases — so a key is comparable only against another key from the
**same** doc-tools version. Do not persist a key as a long-lived foreign identifier
across an upgrade without re-deriving it; persist the raw `(mfr, doc_id, revision)`
alongside it if you need to.

`_compare_revisions` may learn to order more revision formats over time. That can only
turn a `revision_order_unknown` into a decided ordering, never flip a decided ordering.
