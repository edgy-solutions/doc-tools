# ADR-0104 — a new domain is a BAML schema and a plugin, never raw litellm

**Status:** accepted + built
**Date:** no ruling date is recorded; standing guidance in `AGENTS.md` · recorded 2026-11-18
**Deciders:** this repo's standing agent guidance (`AGENTS.md` §Extension Patterns); no individual
decider is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:71-81` (§Extension Patterns, "Adding a New Domain");
`doc_tools/plugins/base.py:24` (`AugmentationPlugin`); the dispatcher at
`doc_tools/assets/semantic_assets.py:931-969`
**Related:** [ADR-0102](ADR-0102-assets-and-declarative-components.md),
[ADR-0173](ADR-0173-the-baml-prompt-layout-is-fixed.md),
[ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md),
[ADR-0174](ADR-0174-an-overlay-field-is-data-not-code.md); the component record
[`docs/arch/components/extraction-pipeline.md`](../arch/components/extraction-pipeline.md)

## Context

The cheapest way to add an extraction for a new domain is to call a model from inside the asset
that needs it: a few lines of litellm or langchain, a prompt string in the same file, and a dict
parsed out of the response. It works the first time.

What it costs is paid later, and in several places at once. The response has no schema, so a
field that stops arriving is discovered by a `KeyError` downstream rather than at the boundary.
The prompt is in Python, so it cannot be reviewed as prompt text, drift-checked, or served from
anywhere else ([ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md)). The
persistence is written inline, so the graph shape for the new domain is defined in the asset
rather than next to the other domains'. And each new domain repeats all of it slightly
differently, so there is no single place to fix a class of defect.

## Decision

**A new domain is five steps, in order, and none of them is a model call in an asset.**

1. Define the parsing schema in `baml_src/{domain}.baml`.
2. Follow the fixed BAML prompt layout — role/task, `### DOCUMENT TEXT ###`,
   `### INSTRUCTIONS ###`, `### OUTPUT FORMAT ###` — to mitigate recency bias
   ([ADR-0173](ADR-0173-the-baml-prompt-layout-is-fixed.md)).
3. Run `baml-cli generate`, which writes the compiled models into `doc_tools/baml_client`.
4. Create `doc_tools/plugins/{domain}.py` extending `AugmentationPlugin`.
5. Register it in the dispatcher switch inside `doc_tools/assets/semantic_assets.py`.

**And the prohibition that goes with them: no raw litellm or langchain logic in the assets.**

Built, at the pin:

- Seven `baml_src/*.baml` schemas and a committed `doc_tools/baml_client/` — generated code is in
  the tree, so the image needs no generate step.
- `AugmentationPlugin` (`plugins/base.py:24`) is an `ABC` whose contract is the four points a
  domain has to implement: `augment`, `to_graph_queries`, `process_fulltext`, and the prompt
  accessors. Every domain plugin subclasses it — `CompliancePlugin`, `DocumentPlugin`,
  `MaintenancePlugin`, `ManufacturingPlugin`, `SustainmentPlugin`, `TrainingPlugin`,
  `PlaybookPlugin`.
- The dispatcher is one switch (`semantic_assets.py:931-969`), and its `else` branch is
  `TrainingPlugin` — not a neutral default. `document` and `playbook` are therefore dispatched
  **explicitly**, and the comment at `:965` says why.
- **Measured absence:** no module under `doc_tools/` imports `litellm` or `langchain`. The only
  occurrence of either name in the package is a gateway hostname inside an error message
  (`doc_tools/utils/embed.py:51`).

## Consequences

- A field that the model stops returning is a schema failure at the boundary, not a `KeyError`
  three assets later. The boundary is a real boundary, not free: what the schema declares
  required is what the schema will refuse.
- The prompt is text in a file, which is what makes the file path production and the drift check
  possible ([ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md),
  [ADR-0172](ADR-0172-the-drift-check-reads-the-runtimes-own-var.md)).
- Step 3 is a **generated-code commit**: `baml_client` is in the tree, so a schema edit that is
  not followed by `baml-cli generate` ships a client that does not match its schema, and nothing
  in the image regenerates it.
- The `else`-is-`TrainingPlugin` dispatcher means **forgetting step 5 is not a crash**. A new
  domain whose registration is missing runs the training plugin and produces a plausible,
  wrong-shaped result. That is the cost of a switch with a non-neutral default, and it is why the
  two latest kinds are wired explicitly.
- `langchain` is still a **declared dependency** (`pyproject.toml:21`) that nothing imports. It is
  dead weight in the image rather than a violation, but it means the prohibition cannot be
  enforced by the absence of the package.

## Alternatives considered

- **Call the model directly from the asset** (raw litellm/langchain). Rejected by the first line
  of §Extension Patterns. No measurement is recorded; the grounds are the four costs above.
- **A plugin registry keyed by domain, instead of a switch.** Not recorded as considered. The
  obvious shape — a mapping from `domain_type` to plugin class, with a missing key raising —
  would remove the silent-default cost above. It is **not** recorded as weighed, and the switch
  is what is built.
- **Pydantic models and a hand-written client instead of BAML.** Not recorded as considered.
  BAML is a pinned dependency (`baml-py==0.222.0`) and the layout rule in step 2 is written
  against its prompt rendering.
