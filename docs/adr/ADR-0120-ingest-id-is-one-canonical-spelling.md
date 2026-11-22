# ADR-0120 — `ingest_id` is `sha256:<64 hex>`, checked where the block is built

**Status:** built
**Date:** 2026-10-02 (ruled, `iagent:ADR-0041`) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris — with one of the ruling's premises
corrected by this lane, in code and in a test rather than only in prose
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/utils/ingest_id.py:1-54` — a module docstring, which was the **only**
written statement of this ruling before this record; the enforcement sites are
`doc_tools/utils/ingest_provenance.py:48-64` and
`doc_tools/components/document_parser.py:302-319`, with the manifest belt at `:707-710`.
Pinned by `tests/test_ingest_id_and_domain_ruling.py` (part A, `test_a1`–`test_a11`) and
`tests/test_provenance_invariant.py`.
**Related:** [ADR-0121](ADR-0121-a-null-domain-type-is-not-a-defect.md) (the same
2026-10-02 ruling's other half), [ADR-0123](ADR-0123-the-stage-post-is-a-runs-last-act.md)
(the stage post this id addresses), [ADR-0132](ADR-0132-notice-identity-is-the-key-not-the-decision.md)

## Context

`ingest_id` is the join key into Lane 1's ingest store. Before this ruling,
`manifest["ingest_id"]` could hold two different strings for the same document: Lane 1's
sidecar supplies `sha256:<64 lowercase hex>`, and doc-tools' own fallback minted
`hashlib.sha256(...).hexdigest()` — the bare 64 hex, no prefix.

The failure is not cosmetic. Lane 1's promotion store deletes "everything whose block
carries this id" by scoping an edge-identity filter to `key=ingest_id` alone, so two
spellings of one document's id means the cleanup sweep matches one set of triples and
misses the other. Worse, `invincible-agent/src/iagent/promotion.py`'s payload guard
refuses the bare-hex spelling outright: a doc-tools-minted ingest was refused promotion
for a *spelling mismatch*, and that refusal surfaced in another repo, long after the write.

**One premise of the ruling is wrong, and the correction is why this record exists in this
shape.** The ruling calls `sha256:<hex>` "the SDK shape". It is not an SDK contract.
Measured against `iagent-mesh-sdk` at `c670fa0`: `iagent_mesh/provenance.py:158` declares
`ingest_id: Optional[str] = None` with **no validator** — its field validators cover only
`authoritative_source`, `as_of`, `ingested_at`, `ingest_run` and `standing` — and the
literal `sha256:` appears nowhere in the SDK. The authority is Lane 1's `INGEST_ID_RE`
(`promotion.py:65`), which doc-tools cannot import because it is not in the published
`iagent_mesh` package.

So nothing between doc-tools and the manifest would catch a bad spelling. A defective
`ingest_id` rides the SDK's own validation all the way onto the artifact and fails far
away, at Lane 1's promotion guard.

## Decision

**There is one spelling, `sha256:<64 lowercase hex>`, and it is checked at the one place
the provenance block is built — not at the edge.**

- `doc_tools/utils/ingest_id.py` owns the spelling. `mint_ingest_id(data)` is byte-for-byte
  the same derivation as Lane 1's `ingest_id_for`, so an id minted here equals the id Lane
  1 would mint for the same bytes. That equality is the only reason the two can be joined.
- `canonical_ingest_id(value, where=...)` has **three** outcomes, deliberately not two:
  already canonical passes through silently; a bare 64-hex is prefixed and lowercased with
  a **WARNING** (the value is recoverable, but the producer emitting it is itself the
  defect); anything else — uuid, truncated hex, empty, `None` — raises
  `IngestIdShapeError`. A uuid is the ruling's named case: it is not a digest of the
  document's bytes, so there is no conversion to the canonical form, only a substitution,
  and a substituted join key names a row that does not exist.
- The check sits in `build_ingest_provenance` because **that block's `ingest_id` IS the
  join key** the cleanup sweep scopes its filter to. A `None` stays `None`: the SDK
  declares the field optional and the non-user-drop paths legitimately have no id to spell.
  Refusing a `None` belongs at the call site that *knows* one was required — the parser's
  sidecar guard — not in the builder.
- `INGEST_ID_RE` here is a **mirror** of a constant in another repo, which is a named
  exception to this repo's own "import the vocabulary, never mirror it" rule. The rule is
  satisfiable for `INGEST_STAGES`, which is in the SDK; it is not satisfiable for this one.

## Consequences

- A defective spelling fails **here**, naming the producer (`where=` is required for
  exactly that reason), instead of surfacing as a refused promotion in another lane's
  sandbox.
- The SDK will **not** catch drift between the two repos, because the SDK does not know the
  shape. If Lane 1 narrows its regex, this mirror must follow by hand.
  `test_a1_pattern_string_is_pinned_to_lane_1s_regex` pins the pattern *string* so a
  narrowing shows up as a failing diff here rather than as a silent refusal in sandbox.
- A bare hexdigest is accepted rather than rejected, which keeps an otherwise-good ingest
  alive at the cost of a WARNING somebody has to read. The coercion is never silent.
- `IngestIdShapeError` subclasses `ValueError`, so handlers that already catch the parser's
  guards still catch it (`test_a7`).

## Alternatives considered

- **Rely on the SDK's validation.** Not available: measured at `c670fa0` the field is a
  bare `Optional[str]` with no validator, which is the finding that corrected the ruling's
  premise. This is why the check is local rather than inherited.
- **Validate at the edge — the sidecar read — only.** Rejected by the placement argument
  above: the manifest has more than one producer, and the parser already gained a third
  canonicalisation site (`document_parser.py:707-710`) as the belt. The builder is the one
  place every producer passes through.
- **Mint a replacement when the spelling is wrong.** Rejected explicitly in the raise
  text: a minted substitute for a uuid names no row in Lane 1's store, so the join breaks
  silently instead of loudly.
- **Import Lane 1's constant instead of mirroring it.** Not possible at the pin —
  `promotion.py` is not in the published `iagent_mesh` package. The mirror is recorded as a
  known exception rather than presented as compliance.
