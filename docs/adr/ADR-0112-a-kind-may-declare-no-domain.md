# ADR-0112 — a kind may declare no domain, and origin is resolved by evidence

**Status:** built
**Date:** 2026-10-02 (architect ruling) · recorded 2026-11-18
**Deciders:** the architect
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `registry/content_kind_domains.json:2`, generated from
`scripts/generate_kind_registrations.py:116-127` (the `null` clause at `:122`);
`tests/test_kind_registry.py:232`; the ruling quoted at
`doc_tools/utils/content_kind.py:18-35`; the write path's short-circuit at
`doc_tools/assets/semantic_assets.py:703-755`
**Related:** [ADR-0113](ADR-0113-the-kind-wins-over-the-manifest.md) (the companion ruling of the
same day), [ADR-0121](ADR-0121-a-null-domain-type-is-not-a-defect.md),
[ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md)

## Context

Some registered kinds name a *format*, not a subject: `pdf`, `engineering-document`,
`doors-export`, `cad`, `dxf`. A PDF is not a sustainment document or a training document; it is a
PDF. But every write in this pipeline is domain-scoped — the Neo4j label, the
`<http://internal/{DOMAIN}_INSTANCES>` graph name, and the plugin that extracts are all selected
by `domain_type`.

So a format-level kind arriving with no domain has to go somewhere, and the code's old answer was
a hardcoded `"Training"` default in the `domain_type` chain. That writes an unvetted drop into a
vetted domain's graph on no evidence at all: the only thing the pipeline knew about the document
was its file format, and it used that to choose whose data it joins. A domain's consumers then
read it as that domain's content.

The alternative failure is as bad in the other direction. Making the absence an error halts the
drop, which reads as a defect in the drop and puts every user-dropped PDF back on the floor —
when nothing is wrong: the kind resolved, and what it says is *"I have no domain."*

## Decision

**A kind may declare no domain. `domain` is `str | None`, `None` is a positive assertion, and
origin is resolved by evidence, not by kind.**

- `ContentKindEntry.domain_type` is `Optional[str]`. The ruling's own rows:
  `pcn`, `pdn` → sustainment; `s1000d-data-module` → maintenance; `engineering-document`,
  `doors-export`, `pdf` → none.
- **What such a drop actually produces**, measured at the pin: an early return, before any
  resource client is fetched, carrying `status: "origin_unresolved"` with the `doc_id`, the
  content kind, the node label and the collection name — and **nothing written**. No domain
  graph, no Neo4j parent node (the MERGE needs a domain label), no Weaviate chunks (the
  collection is shared), no plugin (plugin selection *is* by domain), no triples. The parse
  artifacts the upstream asset already wrote under the dropper's own prefix are the whole of what
  exists, which is what *"visible to the dropper only"* means.
- The stage is **"origin unresolved"** — not a staging domain, and there is deliberately **no
  `INGRESS` domain class** to park it in.
- The manifest's `declared_domain` is **not** a fallback here, even when it carries one
  ([ADR-0113](ADR-0113-the-kind-wins-over-the-manifest.md)): on this path it is derived from an S3
  prefix or a sidecar that hardcodes null, and neither is evidence of origin.
- Resolving origin needs the document-identity pass (document number, revision, CAGE code,
  contract/program identifiers) and a match against a system of record — neither of which is a
  domain this asset may pick.
- The declared domain rides **beside** the registry rows in
  `registry/content_kind_domains.json`, because the SDK registration model is `extra="forbid"`
  and a `domain:` key in a YAML row would raise and stop the whole registry directory loading.
  That file's `_comment` is the one place the `null` convention is written for a reader of the
  data.

## Consequences

- A format-level drop is **inert, not failed**. Nothing downstream sees it, and no status in the
  graph says it was refused — the run's output metadata is the only place it appears. A reader
  looking for the document in a domain graph finds nothing and has to know this record to know
  why.
- A real resolution path is owed: until the identity pass and the system-of-record match land,
  every such drop stays in that state. The ruling accepts that, because the alternative is a
  wrong domain rather than a slow one.
- `None` must be read as a value, never as a missing field. A null `domain_type` is not a defect
  ([ADR-0121](ADR-0121-a-null-domain-type-is-not-a-defect.md)), and a row that *should* have a
  domain and does not writes nothing in exactly the same silence — which is why a new domain-
  bearing kind declares its `domain_type` in the same change as its plugin branch.
- The sidecar JSON is generated, so the convention cannot drift from the rows: both come from one
  pass over `KIND_MAPPING`.

## Alternatives considered

- **Default a domain-less kind to `Training`** — the behaviour that was there. Rejected by the
  ruling: it writes unvetted content into a vetted domain's graph on the evidence of a file
  extension.
- **Make a domain-less kind a hard error.** Rejected in the short-circuit's own comment: nothing
  is wrong, the kind resolved, and a halt would read as a defect in the drop and put every user
  drop back on the floor.
- **Add an `INGRESS` domain and stage the drop there.** Explicitly rejected by the ruling — the
  stage is *"origin unresolved"*, not a staging domain, and no `INGRESS` domain class exists.
- **Carry `domain: null` in the registry rows themselves** rather than in a sidecar. Not
  available at the pin: the model is `extra="forbid"` with no `domain` field, so the key raises.
  The row migration that retires the sidecar is recorded as travelling *with* the SDK pin bump,
  not before it (`tests/test_kind_registry.py:241-245`).
