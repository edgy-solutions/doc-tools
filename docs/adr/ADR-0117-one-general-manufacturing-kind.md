# ADR-0117 — one general manufacturing kind, not a kind per step class

**Status:** accepted + built
**Date:** 2026-06-18 (architect's ruling) · recorded 2026-11-18
**Deciders:** the architect
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/plugins/manufacturing.py:375-377` and `:410-418` — a code comment, which
was the **only** written statement of this ruling before this record. Built at `:424` (the Jena
insert's single class) and `:62-63` (the plugin's default target ontology class)
**Related:** [ADR-0104](ADR-0104-a-new-domain-is-a-schema-and-a-plugin.md),
[ADR-0145](ADR-0145-domain-labels-go-on-nodes-only.md),
[ADR-0153](ADR-0153-one-uniform-contract-for-legacy-extractors.md)

## Context

A work instruction describes very different work: sensors, electronics, munitions, mechanical
assemblies. The obvious modelling move is a kind per step class — a sensor-assembly kind, a
munitions kind — so that a query can ask for one class of work without filtering, and so that the
ontology says what sort of step it is.

The cost of that move is paid in two places at once. Each sub-kind needs a row in the
kind-selection mapping table with a registered `target_ontology_class` and a BAML extractor
behind it ([ADR-0104](ADR-0104-a-new-domain-is-a-schema-and-a-plugin.md)), and each needs its own
class in the `mfg` extension ontology; and the substrate's symmetric (subject, predicate) routing
then has to be taught every one of them, or a verb typed against the general class stops reaching
the specific ones. Sub-kinds minted before any routing asks for them produce an ontology with
several classes whose only difference is a word in the source document, and a mapping table whose
rows cannot be told apart by anything the pipeline reads.

## Decision

**A single general manufacturing kind today, not separate kinds per step class.**

- The general kind is `mfg:WorkInstruction`, in the canonical `mfg` namespace. Every extracted
  step is inserted as that class, and the plugin's SPARQL declares no other.
- **Sensors, electronics, munitions and mechanical assemblies are what is *described*, not
  separate kinds.** The distinction lives in the step's content and in the overlay fields, not in
  its type.
- Sub-kinds become **rows in the kind-selection mapping table only when routing pressure
  justifies them** — deferred to Wave-3, not refused for ever. The ruling names the trigger
  (routing pressure) rather than a date.
- The `:ManufacturingStep` Neo4j label stays for backward compatibility, because existing
  `MATCH` queries filter on it; the canonical content-kind edge is what makes a step reachable
  through the substrate class chain.
- The plugin's `_DEFAULT_TARGET_ONTOLOGY_CLASS_URI` is the general class, and that default is
  *consistent*, not a silent default in the HALT-rule sense: the dispatcher overrides it with
  `kind_entry.target_ontology_class` from the content-kind resolver, which halts on
  unclassifiable input ([ADR-0116](ADR-0116-a-sensor-cannot-declare-a-kind.md)).

## Consequences

- A query for "munitions work instructions" cannot be expressed as a class; it is a filter over
  content or overlay fields. That is the accepted cost, and the overlay is where the variety
  actually lives — typed relationship nodes for hazards, certifications, standards, parts and
  tooling, which are data rather than code
  ([ADR-0174](ADR-0174-an-overlay-field-is-data-not-code.md)).
- One class means one extractor contract and one substrate routing entry, so adding a new sort of
  manufacturing document costs an overlay field set rather than an ontology change plus a mapping
  row plus a routing rule.
- The deferral is open-ended by design. "Routing pressure" is not measured anywhere, so the
  decision to mint a sub-kind will be a judgement call rather than a threshold — and this record
  is where the next person learns that the general kind was a ruling and not an accident.
- The two labels — the legacy `:ManufacturingStep` and the canonical class — both exist, so a
  reader can find manufacturing content two ways and has to know that one is compatibility
  surface.
- The class this plugin writes is declared in an ontology **this repo does not hold**. The
  comment points at `setup/ontologies/mfg_extension.ttl`; measured at the pin there is no
  `setup/` path and no `.ttl` file among the 663 tracked files. The path resolves in the
  platform repo, which is where substrate priming lives
  ([ADR-0103](ADR-0103-substrate-priming-is-the-platforms.md)) — and the comment cites it
  **unqualified**, so a reader checking that `mfg:WorkInstruction` is declared has to know to
  look in another repo. The seam is in [FOREIGN.md](FOREIGN.md); the unqualified citation is in
  [DEBT.md](DEBT.md).

## Alternatives considered

- **A kind per step class** (sensors, electronics, munitions, mechanical assemblies). Rejected by
  the ruling of 2026-06-18, and deferred rather than closed: the comment names the condition
  under which the rows get written.
- **Keep the pre-canonical placeholder namespace** that the direct-load shape used. Rejected
  separately, in the same comment: it was the pre-canonical direct-load shape, and the legacy
  classes left behind in the gateway's state document are described there as residue.
- **Drop the `:ManufacturingStep` label now that the canonical edge exists.** Rejected in the
  comment: existing `MATCH` queries filter on it, so removing it is a change to live queries, not
  a tidy-up.
