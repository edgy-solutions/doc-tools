# ADR-0147 — `mesh:` is the canonical namespace prefix

**Status:** accepted + built
**Date:** 2026-09-12 (ruled) · recorded 2026-11-18
**Deciders:** not named — the ruling's only written statement records that `mesh:` *was ruled*
canonical on that date and names no person
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/utils/runbook_ingest.py:34-60` and
`tests/test_runbook_ingest.py:203-218` — a code comment and a test docstring, which were the
**only** written statement of this ruling before this record. Second enforcement site:
`doc_tools/assets/ontology_assets.py:120-124`
**Related:** [ADR-0143](ADR-0143-the-default-graph-is-invisible.md) (the other way a correct
write becomes unreachable), [ADR-0150](ADR-0150-a-glossary-term-urn-uses-the-short-name.md)
(the other identifier-spelling convention), and
[`docs/arch/components/ontologies-and-alignment.md`](../arch/components/ontologies-and-alignment.md)
§5, which carries the same constant in its table

## Context

Runbook pages carry a compact IRI in their frontmatter (`iri: mesh:resolveInstance`), and
`doc_tools/utils/runbook_ingest.py` expands it before anything is stored. The expansion target
is the served graph the HUD renders, which uses `http://invincible-agent/{domain}#`.

**Nothing in either repo compares the two sides.** This is the decision's whole reason to exist,
and it is not a hypothetical: the repo previously carried **both** that namespace and
`http://internal/mesh#`, and the wrong one reached a seed TTL with **ten citations** on a
namespace nothing else used (`runbook_ingest.py:37-40`).

What a divergence produces is not a crash. An expanded IRI is a syntactically valid absolute
IRI, so the ingest succeeds, the page registers, and the node is written — keyed on a subject
nothing else in the mesh keys on. Every layer accepts it and none matches it. The page is
simply **unreachable**, silently, with no exception, no failed assertion and no red asset. The
refusal messages in the module say it in those words: *"the page would register successfully
and be unreachable"* (`:108-115`).

The second-order property is worse. A wrong value used *consistently* passes every internal
check, because every check is wrong the same way — the comment records exactly this about the
then-undeclared `docs:` prefix (`:52-55`).

## Decision

**`mesh:` expands to `http://invincible-agent/mesh#`. That expansion was ruled canonical on
2026-09-12, and `http://internal/mesh#` is the rejected spelling, named explicitly wherever the
canonical one is pinned.**

- **One table.** `PREFIXES` (`runbook_ingest.py:61-64`) is the only place this repo expands a
  compact IRI on the runbook path, and **nothing else resolves**: an unknown prefix raises
  `RunbookRefused` (`:108-115`) rather than being stored verbatim.
- **A prefix declared with no namespace is refused too** (`:117-126`). Resolving it would mean
  inventing the IRI every existing page is keyed on.
- **The values are copied from the other side's declaration**, not chosen to match — the comment
  cites invincible-agent master `ad00891`, `setup/ontologies/mesh_system.ttl:680` and
  `agent_fleet/utils/mesh_registration.py:646`, and says it read both sides because *a
  write-side table agreeing with itself proves nothing*.
- **The rejected value is pinned negatively.** `tests/test_runbook_ingest.py:214-218` asserts no
  prefix starts with `http://internal/`, because a test that only restates the constant cannot
  tell the canonical value from the wrong one.
- The same constant and the same rejected namespace appear on the ontology path:
  `LABEL_SOURCE_PREDICATE` (`ontology_assets.py:120`) and
  `_REJECTED_LABEL_SOURCE_NAMESPACE` (`:124`).

## Consequences

- A drift **on our side** is red: the test fails. A drift **on their side** is invisible to us,
  and this record does not change that. It makes the constant findable without opening the file
  it happens to live in — which is the only thing a written record can do about a cross-repo
  constant with no shared enforcement.
- Adding a prefix is a code change *and* a declaration on the other side, in that order. The
  module refuses rather than guessing, so an undeclared prefix blocks ingest instead of
  producing pages that look ingested.
- The cost is a hard stop where a lenient path would have carried on. That is the trade taken
  deliberately: a refusal is visible, and an unreachable page is not.

## Alternatives considered

- **Pick a plausible expansion for an undeclared prefix.** Recorded as rejected, in the comment
  and in `test_an_undeclared_prefix_refuses_rather_than_inventing_an_expansion`: every page IRI
  would then have been wrong *together*, consistently, and every check would have passed.
- **Keep both namespaces and accept either.** This was the prior *state*, not a considered
  option; it is what produced the seed TTL with ten dead citations.
- **Shared enforcement** — one generated constant, or a contract test that reads both repos — is
  **not** recorded as considered anywhere. The comment names the gap (`"NO SHARED
  ENFORCEMENT"`) and stops there, so the gap is named here rather than papered over.
