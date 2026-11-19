# ADR-0102 — every ingestion step is an asset, wired as a declarative component

**Status:** built
**Date:** no ruling date is recorded; standing guidance in `AGENTS.md` · recorded 2026-11-18
**Deciders:** this repo's standing agent guidance (`AGENTS.md` §Workflow Guide 2–3); no individual
decider is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:56-57` (§Workflow Guide 2–3); `doc_tools/definitions.py:473` and `:573-621`
**Related:** [ADR-0100](ADR-0100-doc-tools-is-a-code-location-not-a-service.md),
[ADR-0101](ADR-0101-processable-kinds-are-published-not-served.md),
[ADR-0116](ADR-0116-a-sensor-cannot-declare-a-kind.md),
[ADR-0104](ADR-0104-a-new-domain-is-a-schema-and-a-plugin.md); the component record
[`docs/arch/components/extraction-pipeline.md`](../arch/components/extraction-pipeline.md)

## Context

A new ingestion step can be written two ways. It can be a function called from inside an existing
step — fast to write, invisible to Dagster, with no materialisation record, no partition, no
retry and no way to re-run just that step. Or it can be a Dagster `@asset`, with all of those.

The same fork exists one level up, for the jobs and sensors that *drive* the assets. This repo
used to configure them from a `config.yaml`; a YAML file that names ops, labels and collections
drifts away from the code it configures silently, and the failure surfaces as a sensor that
targets an op which no longer exists.

Both halves were settled in favour of the typed, declarative form, and the legacy `config.yaml`
was removed. Measured at the pin: **there is no `config.yaml` anywhere in the tree.**

## Decision

**Every new step in the ingestion pipeline is a modular Dagster `@asset`; jobs and sensors are
instantiated as Declarative Components in `doc_tools/definitions.py`, which replaced the legacy
`config.yaml`.**

- Assets live in modules under `doc_tools/assets/` and are collected by
  `load_assets_from_modules([...])` over eleven modules (`definitions.py:473`). At the pin those
  modules carry **eighteen `@asset` decorators**.
- Jobs and sensors are **component instantiations**, not hand-rolled definitions: ten
  `S3SensorComponent` instances plus this repo's own `DocumentParserComponent`,
  `DesignParserComponent`, `SqlServerExtractorComponent`, `OracleExtractorComponent` and
  `DataHubSensorComponent`. Each is built with `.build_defs(None)` and its `.assets`, `.jobs`,
  `.sensors` and `.resources` are merged into the single `Definitions` object at `:573`.
- A component **encapsulates `IngestionConfig`** — graph labels, vector collections, prefixes,
  partitions — so the backend logic stays domain-agnostic. §Workflow Guide 3 states the
  corollary: *do not pollute the backend logic with specific client schemas.*
- One `Definitions` object is the code location's whole contract (`:573-621`): the components'
  assets, jobs and sensors concatenated with seven named jobs and three hand-built sensors, and a
  resource map whose every credential is an `EnvVar` reference rather than a value.

## Consequences

- Every step has a materialisation record, a partition where it needs one, and can be re-run
  alone from the launchpad. That is what makes a one-off repair possible without a code change —
  the deactivated AITool sync is kept callable exactly this way
  ([ADR-0105](ADR-0105-the-aitool-binding-plane-travels-as-a-unit.md)).
- Adding a domain is adding a component instance, not a new wiring path. The cost is that
  **`definitions.py` is the single file every new seam touches** — 639 lines at the pin, and the
  one file where two lanes adding a sensor in the same week will conflict.
- A sensor's shape is fixed by the component's contract, not by the sensor's author. One
  consequence is recorded separately: a sensor has one `target_job` and cannot declare a content
  kind, which is why a new drop shape gets a new sensor rather than a widened regex
  ([ADR-0116](ADR-0116-a-sensor-cannot-declare-a-kind.md)).
- Because the components come from `dag_tools`, a change in that package's component contract
  lands here as a `definitions.py` failure at code-location load — the whole location fails, not
  one sensor.
- **A naming drift to be aware of:** `AGENTS.md:57` names `S3ToFileComponent` as one of the two
  example components. It is a real `dag_tools` export, but at the pin **this repo instantiates no
  `S3ToFileComponent`** — the S3 half is `S3SensorComponent` plus a parser component. The rule is
  built; the example in the guidance is stale.

## Alternatives considered

- **Keep `config.yaml`.** Rejected by the guidance that replaced it; the drift mode above is the
  reason given. No measurement of the failure is recorded.
- **Plain Dagster `@job`/`@sensor` definitions instead of components.** Not recorded as
  considered. The shape of the alternative is clear — each seam writes its own sensor, job and
  config — and the cost the components are meant to avoid is that each seam then re-expresses
  labels, collections and partitions in its own way. It is **not** recorded as weighed.
- **A function call instead of an asset for a small step.** Rejected by §Workflow Guide 2 as a
  rule, with no exception carved for size.
