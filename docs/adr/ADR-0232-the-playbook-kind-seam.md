# ADR-0232 — the `playbook` kind: the contract's status line is stale

**Status:** accepted; partially built
**Date:** 2026-11-07 (ruled: the splitter fix, and the hold lifted in the same ruling) · the
contract's own statements are measured at `main@5c113ce` · recorded 2026-11-18
**Deciders:** Chris, ratifying this lane's one-day hold and lifting it in the same ruling,
conditional on the splitter fix — recorded in a test docstring
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/contracts/playbook-kind.md:3` — the stale status line;
`tests/test_processable_kinds_publisher.py:104-116` — a test docstring, which was the **only**
written statement of the 2026-11-07 ruling before this record; `doc_tools/utils/md_chunks.py:1-20`;
`doc_tools/utils/content_kind.py:499-512` (the row), `:291` (the phantom), `passes/playbook.py:59`
**Related:** [ADR-0115](ADR-0115-the-playbook-hold-is-lifted.md),
[ADR-0231](ADR-0231-the-document-kind-seam.md) (the sibling kind, which *is* door-blocked),
[ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md)

## Context

`docs/contracts/playbook-kind.md` opens with **"Status: SPEC ONLY. Nothing here is built."**,
measured at `main@5c113ce`. That is a good pattern — a status line with a commit behind it, so a
reader can check it — and at the pin it is **false**.

Measured at the pin, in this tree:

- `doc_tools/utils/md_chunks.py` is the markdown chunker the contract calls "the one genuinely
  new component", including the splitter rule ruled on 2026-11-07;
- `doc_tools/passes/playbook.py` defines `playbook_outline`, and the registry row
  `"playbook"` names `passes=("playbook.playbook_outline",)`, so the pass **resolves**;
- `doc_tools/plugins/playbook.py` gives the kind its own branch in the plugin selector;
- `tests/fixtures/playbook/` carries the fixture, its generator and `golden.json`, pinned by
  `tests/test_playbook_kind_golden.py` — §10's "fixture and golden the build owes";
- `tests/test_processable_kinds_publisher.py:104`,
  `test_playbook_is_advertised_and_is_held_by_nothing`, pins **positively** that the door
  advertises the kind and nothing holds it.

So the contract says nothing is built while five components of it are, and its first bold
sentence — the statement a reader most relies on — is the stalest statement in `docs/contracts/`.
The failure is a reader who opens the contract, believes the build is unstarted, and either
rebuilds the chunker or declines to use a kind the door already offers.

The ruling itself is recorded only in a test docstring: the build found that the leaf-only
chunking rule left text under a non-leaf heading, and text before the first heading, in **no
chunk and therefore unretrievable** — in the fixture, the one sentence saying when to use the
runbook at all. `playbook` was held out for one day; the fix landed and the hold was lifted in
the same ruling, because citations move **once**, before any production corpus exists.

## Decision

**The `playbook` contract's status line is stale and this record supersedes it: the kind is built
on this side of the seam, advertised by the door, and outstanding only where another owner is
outstanding.**

- Built here: the row, the pass, the plugin branch, the chunker, the fixture and the golden. The
  pass is **not** listed in the unbuilt-pass register, because a listed pass that resolves is
  itself a test failure.
- Still owed elsewhere: **`mesh:PlaybookArtifact` as a TTL class** — whose parent is the ontology
  owner's choice, not ours, because a markdown file cloned from git is not PDF-shaped — and the
  overlay row mirroring `passes`, with `review_shape`, which the overlay mirrors from doc-tools
  and never the reverse. Until the class exists the output stays in `PHANTOM_OUTPUTS` and **no
  triples are written**.
- **No door grant is needed**, unlike `document`: a playbook arrives by clone, so there is no
  leaf to grant and nothing here is blocked on the door. `ingress_prefix` is `None` for the same
  reason — there is no user-drop seam and nothing to advertise a drop path for.
- `domain_type="playbook"` is required, not cosmetic: a domain-less row writes no graph and no
  chunks, and an unbranched domain would fall through the plugin selector's `else` to the
  training plugin, running course-concept extraction over a runbook and looking like it worked.
- One item is still **to rule**: making the two existing asset configs rows on a registry. The
  recommendation is to land `playbook` on the mechanism as it stands and make that migration its
  own item, rather than re-plumbing two live ingests under cover of a docs feature.

## Consequences

- This row belongs in [DEBT.md](DEBT.md), and is carried there as D-3: a contract whose
  self-declared status contradicts the tree at the pin. The repair is the contract's, not the
  code's — the code is right.
- The lesson generalises past this file. A status line measured at a commit is checkable but not
  *checked*: the repo already has seals that fail when the tree moves (`expectImage` for images,
  the prompt drift check) and the contracts use neither. That is the shape of the fix.
- A retrieved chunk cites repo + path + heading. **It cannot be resolved to a commit:** the
  resolved sha lands in run metadata and on the document node, not on the chunk, so the file at
  that path may since have changed. The remedy — a third property — was deliberately not taken,
  because it widens the shape the packet proposed.
- A re-ingest overwrites chunks that still exist but **leaves a renamed heading's old row
  behind**, because our re-ingest is additive. A doc-scoped delete before the write is the
  remedy, and it is safe here only because every chunk id is prefixed with its `doc_id`.
- **What a reader must not assume from the status line.** Do not read "SPEC ONLY. Nothing here is
  built" as true — nor this record's correction as "therefore deployed". `main@5c113ce` is a
  commit, not a pod: no live fire has exercised the kind, the golden is the only evidence, and the
  graph write is inert until someone else's TTL lands.

## Alternatives considered

- **Keep the hold on `playbook` until a live fire exercised it.** Rejected in the 2026-11-07
  ruling: the condition that mattered was the splitter fix, because its absence made chunks
  unretrievable.
- **Assume `mesh:PDFArtifact` as the parent for the playbook leaf, as the `document` leaf does.**
  Explicitly refused: a cloned markdown file is not PDF-shaped, so the parent is the ontology
  owner's call.
- **Make the two existing asset configs registry rows first**, buying labels, overlay rows and
  secret-by-name. Recommended against, not ruled: it re-plumbs two live ingests.
