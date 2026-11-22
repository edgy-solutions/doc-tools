# ADR-0121 — a null `domain_type` is not a defect

**Status:** built
**Date:** 2026-10-02 (ruled) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/components/document_parser.py:227-257` — a code comment, which was
the **only** written statement of this ruling before this record; the refusal it replaces
is at `:258-276`. Pinned by `tests/test_ingest_id_and_domain_ruling.py` part B
(`test_b1`–`test_b6`) and `tests/test_provenance_invariant.py`.
**Related:** [ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md),
[ADR-0113](ADR-0113-the-kind-wins-over-the-manifest.md),
[ADR-0120](ADR-0120-ingest-id-is-one-canonical-spelling.md) (the same ruling's other half),
[ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md)

## Context

The sidecar a user drop arrives with carries a `domain_type`. The parser used to **halt**
when it was absent: no domain, no ingest.

That halt was unsatisfiable from the door. Lane 1's gateway hardcodes `domain_type` on
`POST /ingest` and accepts no domain parameter at all, so a drop arriving through the
sanctioned route could not supply one even in principle. The halt therefore fired on
correct behaviour, and the only way past it was for somebody to default a domain — which
is this lane inventing a semantic claim about unvetted content, the exact hazard the rest
of the 2026-10-02 ruling exists to prevent.

The ruling settled where the value actually comes from: *"domain_type comes from the
registered content kind's declared domain, never a run tag"* — and, this record adds,
never a door parameter either. The door declares the **kind**. The registered row declares
the domain, or declares that the kind has none.

Four of the nine `KIND_MAPPING` rows declare a domain. The other five are **format-level**
kinds — `pdf`, `engineering-document`, `doors-export` among them — which declare none *by
design*. Under the old halt a correctly-registered format-level drop was indistinguishable
from a malformed one.

## Decision

**A null `domain_type` in Lane 1's sidecar is expected, not a defect. The refusal moves
from "no domain" to "no registered kind".**

- A drop declaring a kind that has a `KIND_MAPPING` row is **admissible with a null
  domain**. The write path reads the domain off the row; for a format-level kind it
  returns "origin unresolved" and writes nothing anywhere, which is the correct outcome
  and not an error.
- A drop declaring **no** kind, or an unregistered one, still halts — and still halts *in
  the parser*, where the sidecar key is in hand to name, rather than two hundred lines
  downstream where it is out of reach. The blocker is now the one thing the door actually
  controls: the picker's confirmed kind. The refusal text names the registered kinds and
  the two ways to fix it (send `content_kind` on the door's optional form field, or add a
  `KIND_MAPPING` row, which is reserved to the architect).
- The resolved domain is **deliberately not copied onto the manifest**. The row is read
  again downstream, where the origin-unresolved short-circuit lives; copying it here would
  create a second authority for one value, and for a format-level kind there is no value
  to copy.
- The adjacent guards are **kept**: a `domain_type` of `pdf` or `cad` is a file *format*
  and is refused as a semantic label, and a `content_kind` that is a 64-hex hash is refused
  as a kind. A null domain being legal does not make a wrong one legal.
- The third old blocker is gone outright. `DOMAINS_THAT_PERSIST_PROVENANCE` was deleted by
  the same ruling — *"provenance persists for every domain; it's an invariant of the write
  path, not an opt-in"* — so a resolved domain no longer has to earn its way into a set.

## Consequences

- A format-level drop now completes its parse and writes its artifacts, and the fact that
  nothing reached a domain graph is reported as `origin_unresolved` rather than as a halt.
  A reader must know that those two look different on purpose.
- The halt that remains is **actionable by the door**, which the old one was not.
- Deleting a guard is the easy half and the dangerous half: the guard existed because
  unvetted content reaching Neo4j with no mark on it is indistinguishable from vetted
  content. The replacement safety is that provenance is now stamped unconditionally, which
  is why `tests/test_provenance_invariant.py` is mostly about the **supply** — that the
  write path stamps — and only one of its tests is about the absence.
- The admissible-with-null case logs explicitly, naming the kind, the row's declared
  domain and whether the row is format-level. That log line is the only place a reader sees
  which of the two admissible shapes a drop took.
- `test_b5_the_run_tag_read_is_gone_from_the_source` pins the negative half: the run-tag
  read the ruling forbade is absent from the source, not merely unused.

## Alternatives considered

- **Default the domain when the sidecar omits it.** Rejected in the refusal text itself:
  *"a wrong one writes unvetted content into a vetted domain's graph."* This is the whole
  reason the guard is a refusal and not a fallback.
- **Have the gateway accept a domain parameter.** Not taken, and not this lane's to take.
  It would also contradict the ruling's own sentence: the domain comes from the registered
  kind, so a door-supplied domain is a second authority for a value the registry owns. See
  [ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md) for how a disputed
  registry value travels instead.
- **Copy the row's domain onto the manifest at the parser.** Rejected in the comment at
  the site: two authorities for one value, and nothing to copy for a format-level kind.
- **Keep the halt and add format-level kinds to an exemption list.** Not recorded as
  considered. Its shape would have been a second list beside `KIND_MAPPING` with the same
  ownership question, which the "read the domain off the row" ruling removes rather than
  relocates — but that argument is this record's, not a recorded deliberation.
