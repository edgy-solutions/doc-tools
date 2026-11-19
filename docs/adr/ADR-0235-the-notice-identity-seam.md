# ADR-0235 — the notice-identity seam, and whose docstring wins

**Status:** accepted + built
**Date:** no ruling date is recorded for the seam itself; the ordering fix it carries is dated
2026-09-30 · recorded 2026-11-18
**Deciders:** a property of the code, written down by this lane — the judgment calls are recorded
in the module docstring, and one of them was reversed by measurement
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/notice-identity-contract.md:3-9` — the status line, which names the authority;
`doc_tools/utils/notice_identity.py:1-92` — the module docstring that **is** the authority, verified
present at the pin; `tests/test_notice_identity.py` (40 tests); `sustainment.py:2188` and `:2537`
**Related:** [ADR-0132](ADR-0132-notice-identity-is-the-key-not-the-decision.md),
[ADR-0124](ADR-0124-header-identity-precedence.md),
[the document-to-review-record flow](../arch/flows/document-to-review-record.md)

## Context

Two arrivals of the same notice must not both ingest, and a newer revision must supersede an older
one rather than sit beside it. Neither question is answerable from what a sensor sees: a filename,
an ETag and a timestamp cannot say that two differently named objects are the same document — they
can be byte-identical — or that a re-upload is a revision rather than a duplicate. Identity comes
from the **header**, as printed in the document, and that is available only during extraction.

So the seam is unavoidable: one side computes an identity it cannot act on, the other acts on an
identity it cannot compute. Left implicit, the failure is a sensor lane re-running extraction to
dedupe, or — worse — inventing a revision order: a backwards direction hides the **newer** notice
behind the older one, which is strictly worse than declining to answer.

The second failure is documentary: a seam written for another lane is a second description of
behaviour that lives in code, and the two drift. This one says in its opening lines which copy wins.

## Decision

**doc-tools owns the key and the classifier; the sensor lane owns the decision. Where the
contract document and the module disagree, the module's docstring is the authority.**

- `doc_tools/utils/notice_identity.py` is a pure library — no object-store client, no Dagster, no
  network, no BAML import. It reads the three header fields the notice header already carries and
  produces a deterministic, human-readable dedupe key plus a classifier over two already-keyed
  records.
- **The module decides nothing about ingest.** It does not skip, flag, retire or watch for
  arrivals; the classifier returns one of six relations and the sensor lane chooses the action
  ([ADR-0132](ADR-0132-notice-identity-is-the-key-not-the-decision.md)).
- The key is computed once, at the header pass, and handed over on three artifacts an ordinary
  ingest already writes. **Nobody re-runs extraction to dedupe.**
- **Bytes outrank the key.** An equal content hash is checked before the keys are compared at all,
  so identical bytes can never be placed in a revision relation to themselves. That ordering is
  load-bearing, not tidy: the check used to sit inside the same-key branch, so a pair whose keys
  differed only because the header pass reported the revision inconsistently skipped it and came
  back as a supersession — measured on a real pair with one sha256 and two declared revisions.
- **The module never invents a total order.** Revision ordering is decided only where it is
  genuinely unambiguous: both sides dotted-numeric, compared segment-wise with the shorter tuple
  zero-padded, or both sides a single alphabetic character. Everything else returns
  `revision_order_unknown`, which is a reachable outcome and not a fallback that never fires.
- The frozen surface is explicit (§7): names and signatures, the payload keys, the six relation
  values, the separator, bytes-before-keys, and the rule that an incomplete header yields a null
  key rather than one built from empty components. Reason strings and normalisation are **not**.

## Consequences

- Nothing on this seam is blocked on anyone. Both halves are in hand: the contract states the
  obligation and the module implements it, pinned by 40 tests — which is why the status carries
  both `accepted` and `built`. The remaining work is a consumer's choice of action, not an owed
  deliverable.
- **A key is comparable only against another key from the same doc-tools version.** Normalisation
  may gain cases, so a key persisted as a long-lived foreign identifier must be re-derived across
  an upgrade; persist the raw triple alongside it.
- The key is only as stable as the header pass, which is not stable on every notice. That is why
  one rule was retired: one-side-absent revisions were once treated as decidable, reasoning that a
  vendor leaves a first release unmarked and stamps only later reprints. Real fires reversed it — a
  revision reported, then none, then the same revision again over three fires of the same bytes —
  so an absent revision carries no information until the extractor reports it reproducibly. **The
  reversal is recorded in the module, not dropped: the original reasoning still sounds right.**
- The conservative choices cost recall on purpose. Corporate-suffix stripping is a short list of
  full suffix words, stripped only as the last token and only if something remains, so some
  equivalent spellings fail to collapse — a missed dedupe a human or an exact content-hash match
  still catches, rather than two manufacturers collapsing into one key, a silent correctness bug.
- An absent revision and a printed dash stay **distinct**, because collapsing them would equate
  "we do not know whether this was ever revisioned" with "this notice prints no revision".
- The key is the readable normalised triple, not a digest, so a collision is debuggable from a
  log. It never uses Python's salted `hash()`, which would differ per pod.
- **What a reader must not assume from the status line.** "doc-tools owns the key; you own the
  decision" does not make the key a decision, a dedupe, or a guarantee of correctness: a key can be
  null, two notices can key alike if the header pass misreads one, and `revision_order_unknown`
  means *the module declines*, not that the documents are unrelated. And since the docstring is the
  authority, a reader who checks only this contract, or only this record, is reading a copy.

## Alternatives considered

- **A `hashlib` digest as the key.** Rejected in the module: a digest would need the readable triple
  exposed alongside it to be debuggable anyway — an opaque hex string says nothing about why two
  notices collided — so the readable form *is* the key, with nothing extra to keep in sync.
- **Let the sensor dedupe on filename, ETag or timestamp.** Rejected by the problem statement:
  none of the three can tell a re-render from a revision, and two differently named objects can be
  byte-identical.
- **Decide the order when one side's revision is absent.** Tried, then retired by measurement, as
  above. This is the one rule in the module that measurement reversed.
- **Put the decision in doc-tools, since it computes the key.** Rejected: the action is the
  sensor's — drop, ingest, retire, hold for review — and the module deliberately holds no policy
  so that a change of policy is not a change of library.
