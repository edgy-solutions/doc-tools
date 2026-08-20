# Engine design spike: one extraction engine, doc types as config

**Status:** design spike — code under `spikes/engine/`, runnable offline
(`python spikes/engine/test_engine_spike.py`). Nothing here is wired into
production; the spike exists to pressure-test whether the config shape holds
before any migration is commissioned.

**Context:** dozens of doc-ingestion requests are incoming, and the plugin
audit (2026-08, the "attention disease" screen) showed the existing five
plugins are mostly one pipeline wearing costumes: `MaintenanceStep` is a
16-field clone of `ManufacturingStep`, the figure-binding defect spans three
plugins, the standards-normalize-in-LLM defect spans two, and
`ExtractOutline` asks the model for page numbers the elements already carry.
The question is whether new doc types can become *config over a shared block
library* instead of new plugins.

## The claim being tested

A doc type is a **wiring of small, tested blocks** plus **data**:

- **Blocks are code.** Regex families, gazetteer lookup, the geometry
  figure-binder, structural heading detection, one parameterized
  `llm.extract`, reconcile, tiered fallback, descriptor-driven persistence,
  the review lane. Each is a pure function over an `ExtractionContext`,
  unit-testable in isolation, delegating to the already-tested
  `doc_tools/utils/mfg_extractors.py` rather than forking it.
- **Config is data, never logic.** A doc-type YAML *selects* blocks, wires
  their `needs`, and parameterizes them (patterns, enums, field lists,
  ontology namespaces, persistence descriptors). When a doc type needs
  behavior no block provides, the answer is a new tested block — never a
  config hack. `validate_config` rejects unknown kinds and unknown
  dependencies at load, loudly (the config-lie family's front door).
- **The LLM gets judgment only.** `llm.extract` is parameterized by a thin
  field list; the spike's fake LLM asserts that `instruction_text` and
  `torque_spec` never appear in the schema it is handed. The
  anti-attention-disease posture is structural, not a prompt convention.

The falsifiable version: **porting maintenance must be a delta config, not
code.** `spikes/engine/doctypes/maintenance.yaml` is that file — `extends:
manufacturing`, TM/FM/NSN standards families, one new `torque` regex block
instance, a swapped judgment schema, the `mro#` ontology. If a real
maintenance port ever needs more than a file of that shape, the engine thesis
is wrong and we should know *before* committing to it.

## What the spike contains

```
spikes/engine/
  context.py           ExtractionContext + BlockResult (anomalies = the miss-path)
  blocks.py            the block library (registry, ~12 kinds)
  executor.py          topo-order over `needs`, in-process, halt-on-block-crash
  loader.py            YAML loader with `extends` deep-merge (null deletes a key)
  doctypes/
    manufacturing.yaml the reference wiring (deterministic arm + judgment LLM
                       + reconcile + descriptor persistence + review lane)
    maintenance.yaml   the delta config (the clone thesis, made literal)
  test_engine_spike.py 4 checks, offline (fake LLM), pytest-compatible
```

What the tests prove: (1) the manufacturing wiring runs end-to-end and the
deterministic arm fills standards/parts/figures/hazard/duration while the LLM
fills judgment; (2) the corpus report's diff classes fall out of `reconcile`
by construction — an LLM unit the structural pass didn't find becomes an
`llm_only_unit` anomaly (the 4500 pollution), and double-armed fields score
agree/script_only/llm_only exactly like `scripts/mfg_corpus_report.py`;
(3) maintenance runs with zero new code; (4) config lies halt at load.

## Design decisions and their reasons

**Blocks share one signature.** `block(ctx, params, inputs) -> BlockResult`.
`inputs` carries upstream results by block id; `ctx.services` carries the
impure edges (the LLM callable, S3) *injected*, so every block — including
`llm.extract` — runs in tests without the BAML/Dagster stack. This is the
same import-discipline `mfg_extractors.py` already established.

**Anomalies are first-class.** Every block returns `(data, anomalies)`; the
`sink.review_lane` block collects all of them into the review payload. A miss
is a needs_review row, never a silent null — engine-wide, inherited from the
extractor contract, and consistent with the sustainment plugin's hard-won
"silent partials must never look clean" rules.

**`blocks` is a mapping, not a list.** Block ids are keys so `extends` can
override one block's params without restating the wiring, and so `needs`
edges name stable ids. Lists replace wholesale on merge (a regex family list
is one reviewable unit, not a patch series); an explicit `null` removes an
inherited key.

**Reconcile emits the harness's diff classes.** This is deliberate: the
migration oracle for every port is `mfg_corpus_report.py` generalized from
"LLM vs script" to "current-plugin vs engine" over the real corpus. Making
the engine speak the report's vocabulary (agree/script_only/llm_only,
llm_only units = pollution) means parity measurement needs no adapter.

**Dagster granularity.** The block DAG is in-process; Dagster stays at the
coarse asset boundary that exists today (parse → knowledge-graph). A block
config may set `isolation: true` to be promoted to its own asset when it
genuinely earns a pod (a vision pass wanting its own GPU box, heavy OCR). The
spike records the flag and runs in-process; pod-per-regex is explicitly
rejected — that overhead buys nothing.

**Persistence is descriptor data.** `sink.graph_map` promotes
`manufacturing_overlay.py`'s idea — a field declares both its extraction and
its persistence — to engine level. The spike's renderer is simplified;
production reuses the tested overlay renderers (`render_step_attrs`,
`render_related_blocks`, `render_sparql_lines`) behind the same descriptors,
and the proprietary-overlay secret-load composes at the same merge point it
does today.

## Where each existing plugin lands

| plugin | engine expression | residue |
|---|---|---|
| manufacturing | the reference config (this spike) | none expected |
| maintenance | delta config over manufacturing | none expected |
| compliance | small config: per-section `llm.extract` (already thin, one concern) + graph_map | must ALSO delete the DAFMAN-DEFAULT/ERROR-FALLBACK fabrication-on-error (bad-data-on-error, separate defect) |
| training | outline becomes `structural.outline` (headings + `page_number` from element metadata — the LLM should never have been asked for page numbers) + per-chunk `llm.extract` for concepts + figure binder | `execute_pass2_rollup` (Cypher cross-linking) stays a post-graph hook; either a `sink.rollup` block kind holding Cypher templates as data, or the one bespoke residue |
| sustainment | the shape FITS (`control.tiered` models text-layer→vision exactly; anomalies model its review lane) but it is the LAST port, not the third | provenance bbox resolution, the vision truncation-detection collar, and trace telemetry are three block kinds that don't exist yet; port only after 2–3 easy types prove the axis |

## Risks (unchanged from the discussion, now with anchors)

1. **One engine = one blast radius.** A bug in `reconcile.units` breaks every
   doc type. Non-negotiable mitigation: per-block unit tests plus a golden
   test per doc-type config (`test_manufacturing_graph_golden.py` is the
   precedent), and the corpus harness as the cutover gate.
2. **Persistence mapping is the actual hard part.** The ontology targets
   (mfg#, mro#, iof#, pcn#) and their instance-graph scoping rules (see
   sustainment's `_INSTANCES` graph invariant) concentrate the real
   complexity. Budget ~60% of migration effort here, not in extraction.
3. **Config schema must emerge, not be designed.** This spike's schema is a
   hypothesis. Freeze it only after manufacturing, maintenance, and ONE
   genuinely new incoming doc type have been expressed in it.
4. **Shape outliers stay bespoke until the library covers them.** Training's
   rollup and sustainment's provenance/vision tiers are absorbed last or not
   at all; a two-plugin residue is an acceptable end state.

## Recommended path (unchanged)

1. Land the deterministic hybrid for manufacturing (in flight — awaiting the
   first corpus report).
2. Generalize `mfg_extractors` → `wi_extractors` with per-domain config
   (maintenance families are already sketched in `maintenance.yaml`).
3. Port manufacturing onto the engine; prove parity on the corpus via the
   generalized report.
4. Port maintenance as the delta config; if it is not config-only, stop and
   re-evaluate.
5. Take one brand-new incoming request through the engine; let its friction
   define the next blocks.
6. Old plugins keep running until each type reaches measured parity. Never
   big-bang.

## Follow-ups (backlog, not spike scope)

- **`doc_tools/__init__.py` eager-imports Dagster.** It runs
  `from .definitions import defs` at package init, so importing *any* pure util
  (`from doc_tools.utils import mfg_extractors`) transitively drags in Dagster.
  Three separate consumers — `scripts/mfg_corpus_report.py`,
  `scripts/mfg_deterministic_gate.py`, and now `spikes/engine/blocks.py` — have
  each independently invented the same `importlib`-by-path workaround. Three
  workarounds for one eager import is the signal: make `defs` lazy (or move the
  pure utils off the eager path) and all three workarounds collapse into a plain
  `from doc_tools.utils import ...`. One-line backlog item; do it when the engine
  work touches these imports anyway, not before.
