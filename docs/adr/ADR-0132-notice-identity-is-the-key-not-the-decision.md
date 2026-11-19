# ADR-0132 — `notice_identity` is the dedupe key here and the decision elsewhere

**Status:** accepted + built
**Date:** no single ruling date is recorded; the contract document is the statement, and the
behaviours it freezes were fixed through 2026-09-30 · recorded 2026-11-18
**Deciders:** the two lanes the contract names — doc-tools owns the key, the ingress-user lane
owns the decision. No individual ruler is recorded.
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/notice-identity-contract.md` (the contract, §1-§7);
`doc_tools/utils/notice_identity.py:1-24` — the module docstring, which the contract names as
**the authority if the two disagree**; `notice_key` at `:209`, `build_identity` at `:254`,
`classify_pair` at `:359`; pinned by `tests/test_notice_identity.py` (40 tests)
**Related:** [ADR-0235](ADR-0235-the-notice-identity-seam.md) (the seam record, and whose
docstring wins), [ADR-0120](ADR-0120-ingest-id-is-one-canonical-spelling.md),
[ADR-0116](ADR-0116-a-sensor-cannot-declare-a-kind.md)

## Context

Two arrivals of the same notice must not both ingest, and a newer revision must supersede an
older one rather than sit beside it. **Neither question can be answered from what a sensor
sees.** An S3 object gives a filename, an ETag and a timestamp, and none of those say that two
differently-named files are the same document — the corpus contains exactly that pair, two
filenames over one set of bytes, confirmed by a full enumeration of every PDF in every bucket on
2026-09-30 — or that a re-uploaded file is a revision rather than a duplicate.

The identity has to come from the **header**: `(mfr, doc_id, revision)` as printed in the
document. That is extracted during ingest, which puts it on doc-tools' side of the seam. The
decision — skip, retire, route to a human — belongs to the lane that watches S3.

Left unwritten, the seam collapses one of two ways: doc-tools decides what to do with a
duplicate — a sensor policy made by a library with no view of the bucket — or the sensor
re-derives identity from the filename, which the byte-identical pair disproves.

## Decision

**`notice_identity` is the Level-2 dedupe KEY and the CLASSIFIER, and nothing more. doc-tools
owns the key; the ingress-user lane owns the decision. Where the contract document and
`notice_identity.py`'s docstring disagree, the docstring is the authority.**

- **The key.** `build_identity(mfr, doc_id, revision)` returns the normalized triple joined on
  `SEPARATOR` (`\x1f`). The key **is** the readable triple — there is no digest, deliberately,
  so there is nothing to keep in sync with it and a collision is legible in a log. It never
  calls Python's salted `hash()`, so two pods produce the same key.
- **`key` can be `null`.** Then `complete` is `false` and `note` says which component was
  missing. That is *"identity not assertable"*, never a key of `""`.
- **The classifier, not the action.** `classify_pair(a, b)` is directional — `a` the arrival,
  `b` the incumbent — and returns one of six relations: `identical`, `duplicate_copy`,
  `supersedes`, `superseded_by`, `revision_order_unknown`, `distinct`. The contract tables the
  **sensor action** for each; the module takes none of them. It does not watch S3 and does not
  decide whether to skip an ingest.
- **`identical` is decided on bytes, before the keys are compared**, and the ordering is
  load-bearing rather than tidy: identical bytes cannot stand in a revision relation to
  themselves, however the header pass keyed them. When this check sat inside the `key_a ==
  key_b` branch, the byte-identical pair — same sha256 — came back `supersedes`, one copy
  declared to supersede the other.
- **`revision_order_unknown` is reachable, and the sensor must not guess.** It is returned
  whenever the revisions are not both numeric, not both single-alphabetic, or one side is absent,
  because an absent revision may be a **header miss** rather than a document that prints none —
  and guessing would hide the newer notice behind the older one.
- **Three artifacts carry the identity**, so the sensor never re-runs extraction to dedupe:
  `review.json`, `extraction.json` and the corpus-run JSON. Same value in each.

## Consequences

- The sensor lane can code against §3 without reading the module, which is what the document
  exists for. The **cost of two statements** is that they drift, and the precedence rule is a
  mitigation rather than a cure: the docstring wins, so a reader who finds a difference knows
  which to believe without adjudicating ([ADR-0235](ADR-0235-the-notice-identity-seam.md)).
- **The key is only as stable as the header pass, and it is not stable on every notice.** The
  function is deterministic; its **inputs** are model output. One corpus notice reads `mfr`
  differently across repeated fires on identical bytes, so its key differs too. The release gate
  reports that as `identity_half_unstable` and blocks on it (`scripts/pcn_corpus_gate.py:760`),
  which is why a pin bump is gated on header agreement and not only on parts recall. An unstable
  key can make one document look like two arrivals; the gate keeps an unstable pin from reaching
  the sensor, and guarantees nothing about any single ingest.
- **A key is comparable only against another key from the same doc-tools version.** Normalization
  may gain cases, so a key must not be persisted as a long-lived foreign identifier across an
  upgrade without re-deriving it — persist the raw `(mfr, doc_id, revision)` beside it. §7 names
  what is frozen (signatures, payload keys, the six relations, `SEPARATOR`, bytes-before-keys,
  `key: null` over empty components) and what is not (`reason` strings, normalization details).
- `revision=None` ("the notice shows none") and `revision='-'` ("the notice prints a dash") are
  kept **distinct**, through a private sentinel no real printed string can normalize to.
  Collapsing them would equate *we do not know whether this was ever revisioned* with *this
  notice explicitly prints no revision*. `_compare_revisions` may learn more formats, and that
  can only turn a `revision_order_unknown` into a decided ordering, never flip a decided one.

## Alternatives considered

- **A `hashlib` digest key.** Rejected in the module, with its reason: a digest would need the
  readable triple exposed alongside it to be debuggable at all, since an opaque hex string tells
  a reviewer nothing about why two notices collided. So the readable form *is* the key.
- **Dedupe on filename, or on ETag and timestamp.** Disproved rather than argued: the two
  filenames over one set of bytes is the case `identical` exists for, and it is why the key is
  computed from the header at all.
- **Have `notice_identity` decide the action.** Refused by the ownership split. The module has no
  view of the bucket, and a skip-or-retire policy made in a pure library would be a sensor
  decision taken by the wrong lane.
- **Aggressive manufacturer normalization**, collapsing more spellings. Rejected with the
  tradeoff stated: a false positive on identity is a silent correctness bug, a false negative is
  a missed dedupe someone else still catches.
