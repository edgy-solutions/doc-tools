# The user-drop halt is the door's optional picker, not a parser defect

Report, lane 7f, 2026-10-12. Raised by a pasted traceback:
`ValueError: ADR-0041 guard: sidecar 'ingress-user/pdf/734d9c94.../manifest.json'
carries no domain_type (got None) AND no registered content_kind (got None)` from
`process_user_document_artifact`, `document_parser.py:253`.

## Verdict

**The halt is correct. Nothing in `document_parser.py` is broken, and no
`KIND_MAPPING` row is missing.** The drop arrived with no confirmed content kind,
and the guard refused to guess a domain for it, which is exactly its declared job.
The defect is upstream: **the door accepted an upload without a kind.**

**It is not my cycle.** `process_user_document_artifact` is the user-drop path, not
the corpus gate. `pcn-gate-8725e04` was ACTIVE with 0 restarts throughout, before
and after. The drop was made by `alice@example.com` at 2026-10-12T20:32:29Z.

## What was measured

`734d9c94db9bc63b7d0c513aa0ea5232113ad6f94f6fa60fec9a4d2244516afe` is
**EOL-36_BYV34-400,-BYV34-500.pdf**, 163821 bytes — byte-identical to the corpus
document of the same hash, measured this afternoon. The drop is a re-submission of
a notice the corpus already carries.

The sidecar does **not** omit the fields. It writes them as nulls:

    content_kind   None
    domain_type    None
    media_kind     'pdf'          <-- the FORMAT, and the only kind-ish value present
    ingest_id      'sha256:734d9c94...'
    provenance     present (as_of, authoritative_source, ingest_id, ingest_run,
                            ingested_at, obtained_via, standing)

Across all twelve drops under `ingress-user/pdf/`, read inside the pod:

| state | count | content_kind | domain_type | media_kind |
|---|---|---|---|---|
| succeeded | 7 | `'pcn'` | `'sustainment'` | `'pdf'` |
| **halted** | **5** | `None` | `None` | `'pdf'` |

The five halted drops, all from `alice@example.com`, spanning twelve days:

    736499f2eebb  roll11-capture.pdf                 2026-10-01T15:53:38
    fa231498f527  PCN23-002.pdf                      2026-10-02T03:13:54
    0096a523a94d  PCN23-002.pdf                      2026-10-04T04:27:08
    c75116ec47bf  PCN24-060.pdf                      2026-10-11T02:42:04
    734d9c94db9b  EOL-36_BYV34-400,-BYV34-500.pdf    2026-10-12T20:32:29

**This is a standing backlog, not tonight's one-off.** Four of the five are
PCN-class notices that would have resolved to `pcn`/`sustainment` had the picker
been used — the same values the seven successful drops carry. Every field except
`content_kind`/`domain_type` is identical between a halted drop and a working one,
including the full provenance block. The single discriminator is the picker.

## Three fixes that look available and are not

**1. Fall back to the path segment.** The key is
`ingress-user/pdf/<sha256>/<name>.pdf`, the segment IS literally `pdf`, `pdf` IS a
registered kind, and the variable is even named `content_kind_from_path`. All of
that is misleading. **Measured, not assumed:**

    _derive_from_path(raw key,      None) -> None
    _derive_from_path(stripped key, None) -> None
    resolve_content_kind({content_kind: None, ...}, key) -> RAISES
        UnclassifiableContentKindError

`_derive_from_path` returns `None` on its **first** guard, `if not s3_key or
domain_type is None`. Path derivation per ADR-0021 means "the segment AFTER the
`domain_type` segment", so it needs a domain to anchor on. A user drop has no
domain by design — "since 2026-10-02 the null domain is expected" — so
**path-derivation is structurally unavailable to every user drop that will ever
exist.** The name `content_kind_from_path` at `document_parser.py:204` is a
misnomer: that branch reads `sidecar.get("content_kind")`, there is no path
involved, and there cannot be. (The genuine path form is the other branch, `:317`.)

I formed the hypothesis that ADR-0021's `resolve_content_kind` would admit this
drop and the ADR-0041 guard was a stricter reimplementation that had drifted from
it. **Testing it disproved it** — both halt, for the same reason. The two rules
agree.

**2. Read `media_kind`.** It is `'pdf'` on all twelve drops. But `media_kind`
appears **nowhere in this repo's Python** — the door writes it and nothing here
consults it. And wiring it in would not help: `_lookup('pdf')` returns
`kind='pdf', domain_type=None`, a format-level row. The drop would parse and then
write nothing semantically — `semantic_assets.py` returns "origin unresolved". The
document would look ingested and contribute nothing to any graph. **That is worse
than the halt**: a silent no-op success is the tolerated-degraded-path shape that
nobody ever goes back and fixes. The four format-level kinds that behave this way
are `pdf`, `xml`, `doors-export`, `engineering-document`.

**3. Add a `KIND_MAPPING` row.** Not applicable — `pdf` already has one — and the
guard's own message reserves that table to the architect.

## Recommendation, not applied

**Make the kind mandatory at the door.** Reject the upload with a 400 naming the
registered kinds, so the person who chose the file is told at the moment they can
still fix it. Today a kindless upload returns success and dies ~250 lines into a
Dagster op, where the only artifact is a stack trace and the uploader has gone.
A 400 at the door is the same refusal, moved to where it is actionable.

The guard message's own first suggestion — "have the door send one of those as
`content_kind`" — is this, and it is the door's change to make, in the door's repo.
Not mine to commit: only the owning lane commits in its own tree.

**What I did not do, deliberately:** did not edit the ADR-0041 guard (an authority
file, and the surrounding ruling block argues the strict rule on purpose), did not
touch `KIND_MAPPING` (reserved to the architect), did not wire `media_kind`, and
did not re-drive the five blocked drops.

## Recovering the five

Setting `content_kind` in each sidecar and re-triggering is the obvious move and
has a known trap: **a re-upload cannot retrigger an ingest.** The run key is
ETag+key and a sensor cursor sits in front of it, so a re-drop of identical bytes
is silently absorbed — no run, no error. Patching the sidecar in place does not
change the document's ETag either. Recovering these five needs a deliberate
re-trigger path, and it should be done once, for all five, rather than per drop.

## Open question for the architect

A kindless user drop currently halts hard. The alternative is to admit it as the
format-level kind, parse it, and write nothing semantic. I recommend the halt —
and recommend moving it to the door — but which of the two is correct is the
architect's call, because the ADR-0041 comment block argues the strict position
explicitly: "the blocker now being the one thing the door controls: the picker's
confirmed kind. Defaulting a domain here would still be this lane inventing a
semantic claim about a user drop."

## Evidence

All S3 reads ran **inside** the doc-tools pod via `kubectl exec -i ... -- python
-I -`; no credentials were materialized locally and no YAML was dumped. Path
derivation and table lookups were run through this repo's venv
(`.venv/Scripts/python.exe -I`), never a bare interpreter.
