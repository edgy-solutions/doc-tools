# ADR-0231 — the `document` kind is declared here and not routable end to end

**Status:** accepted, blocked
**Date:** 2026-10-25 (architect order, overnight item 2) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris; the blocker is Lane 1's to clear
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/contracts/document-kind.md:3-6` — the contract's own status line;
`docs/contracts/document-kind.md:235-249` §9, the four things owed by Lane 1;
`doc_tools/utils/content_kind.py:460-477` (the registry row) and `:285` (the phantom output);
`doc_tools/passes/identity.py`, `doc_tools/passes/document.py:238`
**Related:** [ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md),
[ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md),
[ADR-0116](ADR-0116-a-sensor-cannot-declare-a-kind.md),
[ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md),
[ADR-0232](ADR-0232-the-playbook-kind-seam.md) (the sibling kind that is **not** door-blocked)

## Context

The consumer is ask-the-manual: a question answered with a citation of the form *page N, heading
H*. Every strict choice in the contract is downstream of one sentence — **a citation that moves
between runs on the same bytes is worse than no citation, because it is checkable and wrong** —
which is why both passes are deterministic and LLM-free and nothing on the path samples.

The failure this record exists to prevent is a reader concluding that the kind works. Everything
on our side of the seam is in the tree and green: the registry row, the two passes, the synthetic
six-page procedure fixture and its golden. What is missing is one entry in somebody else's
deployment overlay, and the symptom of its absence is **silence** — a PDF lands, the format-level
`pdf` row resolves no origin, the leaf-grant branch asks Lane 1's door, the door offers no
`document` candidate, and the asset simply never adopts a grant. Nothing fails. Nothing is
logged as refused. The kind looks declared because it *is* declared.

The second trap is where the contract was measured. **Everything below §9 was measured in this
tree on the branch `7f/document-kind`** — not against a running system, and not against the
deployed image. A branch measurement says the code in a checkout behaves this way; it says
nothing about what the pod runs ([ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md)).
At the pin the row and both passes are also on `origin/main`, which moves the measurement no
closer to deployed: the deployed contract is the rolled image, and no live fire has exercised
this row.

## Decision

**`document` is a statement about origin — "this PDF is one of ours" — declared completely in
doc-tools, and it is not routable until Lane 1's door offers it as a kind candidate.**

- The kind declares `domain_type="document"`, deliberately: the leaf-grant branch adopts a grant
  only when the granted kind carries a domain, so **a domain-less `document` row would have been
  refused by the very door meant to route to it**. This does not reopen the 2026-10-02 ruling
  that format-level rows carry no domain — `document` is not a format.
- Its passes are `("identity.document_identity", "document.document_outline")`, in that order and
  both deterministic. No BAML, no sampling.
- **No `ingress_prefix`.** A prefix is a user-drop seam and a seam needs a retry sensor behind
  it; a document arrives through the existing `pdf` seam.
- **Four things are owed by Lane 1 (§9), and only the first is the blocker:** `document` as a
  candidate in `allowed_leaves` with a label; the overlay row mirroring `passes`;
  `review_shape: document`; and `mesh:GeneralDocumentArtifact` as a TTL leaf. Per the standing
  rule the overlay mirrors doc-tools, never the reverse.
- Until the TTL class exists the output stays in `PHANTOM_OUTPUTS` and **no triples are written**.

## Consequences

- The evidence for this kind is the golden and nothing else. The row is not exercised by any live
  fire, because the door does not grant the leaf.
- Known limits are recorded rather than discovered: chunks are page-granular, so a page carrying
  two headings cites the deeper, later one; `.pdf` only, so a `.docx` manual is not ingestable as
  `document`; and `domain_type="document"` creates a new domain, whose hazard is the plugin
  selector's `else` branch being the training plugin.
- Changing a recognizer, the furniture list, the `section_for_page` tie-break or the section-id
  encoding **moves existing citations** and is a contract change, not a refactor: regenerate the
  golden deliberately, say so in the PR, and packet the consumer. A changed fixture sha is a
  contract change too, not a re-pin.
- **What a reader must not assume from the status line.** "Declared in doc-tools, **not yet
  routable end to end**" is not a to-do list for this lane. There is nothing here left to build;
  the status will change when another lane's overlay changes, and no amount of work in this repo
  will move it. Nor does "measured" in the sections below §9 mean measured in production: it
  means measured on a branch, in a checkout, with no fire behind it.

## Alternatives considered

- **Declare `document` with no domain, like `pdf` and `xml`.** Rejected by measurement: the
  leaf-grant branch requires a domain on the granted kind, so the row would be unroutable even
  after the door offered it.
- **Add an `ingress_prefix` so `document` has its own drop path.** Rejected: a prefix implies a
  sensor, sensors are wired for `pdf` and `xml` only, and a sensor cannot declare a kind
  ([ADR-0116](ADR-0116-a-sensor-cannot-declare-a-kind.md)). The grant route already exists.
- **Hand-write the overlay row in Lane 1's tree to unblock ourselves.** Not considered as an
  option here, and it is refused on principle: a disputed or missing registry value goes to lane
  01 as a packet, not an edit ([ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md)).
- **Sub-page chunking, so a page with two headings cites the right one.** Recorded as a separate
  change and not attempted here. No alternative design for it is recorded.
