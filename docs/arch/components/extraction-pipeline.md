# The extraction pipeline (CO-EXTRACT)

The extraction pipeline is what doc-tools is for: a document lands in object storage, and
the pipeline turns it into a parse artifact, a graph, a vector index and a review record a
person can act on. It is a Dagster code location — the deployed pod serves assets, jobs and
sensors over gRPC and runs nothing on its own clock.

Two things about it are easy to assume and wrong, so they are findings below rather than
asides: **nothing in this repo is scheduled**, and **what a kind *is* is not this repo's to
declare** — doc-tools declares only what it runs.

**This record describes; it proposes nothing.** Statuses are those of [the README](../README.md),
and line numbers are valid only at the pin listed there. The record shape is provisional.
Nothing in this record was run: it is read from the code, the chart and the test names.

## Findings

1. **Work enters by sensor, never by schedule.** `doc_tools/definitions.py` defines no
   `ScheduleDefinition` and passes no `schedules=` to `Definitions`. The `sensors=` list at
   `:582` is **ten** S3 sensors, one DataHub poller, two retry sensors and one publisher.
   The ten are `dag_tools.S3SensorComponent` instances (`definitions.py:3`, constructed at
   `:89`, `:106`, `:128`, `:170`, `:274`, `:294`, `:320`, `:346`, `:383`, `:404`) — dag-tools'
   `CO-S3-SENSOR` classes, not sensor code of ours. The eleventh, `datahub_sensor`, is this
   repo's own `DataHubSensorComponent` and watches no prefix at all: it polls a DataHub
   GraphQL endpoint for recently tagged entities. Every document ingest therefore begins with
   an object appearing under a watched prefix, or with the gateway offering a retry. `built`
2. **A sensor is per prefix, and the prefix is where the kind comes from.** Each
   `S3SensorComponent` watches one prefix and targets one job: `manufacturing/inbound/`,
   `sustainment/inbound/`, `training/course/`, `ingress-user/`, `ingress-user/xml/`, `iads/`,
   `doors/`, one numeric programme prefix, and two that watch the bucket root (the numeric
   prefix is left unquoted here: a bare five-digit prefix has the shape of a programme
   identifier, and these records name none). The ingress patterns are generated
   from the kind registry rather than written as literals, which is pinned by a test that
   compares the generated pattern with the shipped one. A sensor cannot declare a content
   kind: the path derives it. `built`
3. **Most sensors ship stopped, and the chart cannot tell you which are running.** Only the
   two user-drop sensors carry `default_status="RUNNING"`; the DOORS sensor deliberately
   declares none. The comment that sets this says the part that misleads: `default_status` is
   consulted **only** when the Dagster instance has no stored status for that sensor, so a
   sensor a human has ever started or stopped keeps the stored value and the code's default
   is dead text. What is actually running is therefore `not established` from this repo.
   `built` (the defaults); `not established` (the live state)
4. **The cursor is a watermark and the run key is content-addressed.** `S3SensorComponent`
   is the platform's, installed from `dag_tools`, not vendored here: its cursor is the last
   key of a `LastModified`-sorted listing, and its run key is `{ETag}-{object_key}`. Two
   consequences are load-bearing and neither is this repo's code: re-uploading identical
   bytes mints the same run key and launches nothing, and a run key consumed by a *failed*
   run stays consumed. `built` (in the platform package, read at its installed copy)
5. **The retry path is a separate sensor because dedup is per sensor name.** The retry
   sensor polls the gateway's retries route every 300 s, defaults to RUNNING, and mints
   `{ingest_id}-a{attempt}` — attempt-scoped, so a second retry of the same ingest is not
   swallowed. It holds no S3 cursor. A second instance targets the XML job. `built`
6. **One sensor launches no runs at all.** The processable-kinds publisher exists for its
   side effect: it publishes the kind list every tick, deliberately, and its cursor is a
   record rather than a gate — so a consumer that missed a publication gets the next one 300 s
   later instead of waiting for the list to change. Both properties are pinned by name.
   `built`
7. **The parse step is one asset, dynamically partitioned, and it returns the manifest.**
   `DocumentParserComponent` builds `process_document_artifact` (partition `pdf_files`) and
   `process_user_document_artifact` (partition `user_pdf_files`) over a
   `DynamicPartitionsDefinition` with `AutomationCondition.on_missing()`. The asset's output
   is the manifest dict. `built`
8. **`hi_res` is conditional, and the document path is what makes it unconditional.**
   `extract_text_and_metadata` defaults to `strategy: "auto"`; it switches to `hi_res` and
   adds `extract_image_block_types=["Image", "Table"]` only when both `extract_images` and an
   output directory are given. The parser always passes them, so on this path the strategy is
   `hi_res` — but the function on its own does not promise it. `built`
9. **Two DPI knobs, two different jobs.** `DOC_PARSER_PDF_IMAGE_DPI` (default 200) is the DPI
   the cropped Table/Image blocks are captured at — the images the sustainment vision pass
   reads. `DOC_PARSER_PAGE_RENDER_DPI` (default 300) is the full-page raster, via pypdfium2.
   The page-render default and the chart's explicit setting of it are each pinned by a test.
   `built`
10. **A failed download does not fail the run: it writes a mock string and continues.** On a
    download exception the parser logs a warning and, if no file arrived, writes the literal
    `mock document content` into the temp path. Everything downstream then succeeds on
    content that is not the document — a whole green graph over a substituted body. This is a
    defect, recorded as a gap below rather than softened here. `built` (the behaviour)
11. **The manifest declares what it knows instead of letting a reader derive it.**
    `source_key` is written because the sustainment text-layer pass must re-open the original
    PDF, and reconstructing that key by string surgery on `text_location` would break the
    first time the layout changed. The same reasoning is written out for the pipeline version,
    which Lane 1 derives from the artifact rather than from a caller's assertion (`ADR-0034`).
    `built`
12. **The pointer is written last, strictly after the versioned object.** The versioned
    `manifest.json` is put first and the mutable pointer after it, so a reader that follows
    the pointer never finds it naming an object that is not there yet. `built`
13. **The ingest id is the sidecar's, else minted from the bytes, and the sidecar's
    provenance wins.** A sidecar manifest supplies `ingest_id` and, when present, its own
    provenance block; otherwise the id is minted from the file bytes and
    `build_ingest_provenance` stamps the block. Both land as top-level manifest keys. Pinned
    by name. `built`
14. **Pass dispatch is registry-driven and invents no default.** `run_passes_for_kind` looks
    the kind up and runs its declared passes in order; an unknown kind raises
    `PassContractError` — *"no default is invented"*. A pass whose dotted name contains `::`
    is a BAML pass and this dispatcher does not call it; a class rather than a callable is
    refused. All three are pinned by name. `built`
15. **The declared pass tuple is not what runs on every path.** Only three call sites invoke
    the dispatcher — the DOORS asset, the document plugin and the playbook plugin. The
    sustainment path runs its own passes, so a kind's `passes` tuple is a declaration that
    only those call sites execute. `built`
16. **Plugin selection is an inline ladder, and its `else` is the Training plugin.** The
    chain in `_build_knowledge_graph_impl` keys on `domain_type`: manufacturing, maintenance,
    compliance (falling back to Training on `ImportError`), sustainment, document, playbook,
    `else` Training. There is no selector function. The comment at the `else` says why it
    matters: an unbranched new domain does not get a generic plugin, it gets the Training one,
    *and it looks like it worked*. The `document` branch exists because of exactly that, and
    is pinned by a test. `built`
17. **The kind registry is one table in code; the yaml rows are generated from it.**
    `KIND_MAPPING` is the source of truth; `registry/content_kinds/*.yaml` carries 14
    generated rows marked do-not-edit, and a sidecar maps each kind to a domain or to null for
    a format-level kind. Three tests pin the sync, the SDK validation and the null-is-not-an-
    empty-string rule. `built`
18. **The platform owns what a kind is; doc-tools owns what it runs.**
    `PLATFORM_OWNED_FIELDS = ("domain", "arrives_as", "review_shape", "label")`. doc-tools
    sets `kind`, `passes` and `outputs` on every row and projects four optional fields only
    where a row declares them; the SDK model is `extra="forbid"`. Ruled 2026-10-24. Two drift
    tests compare the shared kinds' passes and domains against the overlay. `built`
19. **What the pipeline advertises is a union of two arms minus an explicit hold list.**
    `ingestable_kinds()` is the python-pass arm plus the ingress-user XML arm, minus
    `HELD_OUT`. The arms can disagree, and the union sides with the one that actually ran the
    kind; the hold survives an arm claiming it. `HELD_OUT` holds `xml` alone, with its reason,
    its evidence and the condition that lifts it written in the entry: *a user-drop sensor
    processing a bare `xml` drop end to end*. `playbook` was held and lifted the same day and
    the entry is kept as a comment, because the failure mode is the reusable part — a pass
    becoming real is enough to change what this door advertises, and nothing fails when it
    does. `built`
20. **The registry fingerprint covers kinds and passes, and nothing else.** It is a sha256
    over the sorted `(kind, passes)` rows, first 16 hex, carrying nothing from the
    environment — so two code locations can be compared without diffing lists. A change to any
    other field of a row, including a renamed mapping key, leaves the fingerprint identical.
    `built`
21. **The deployed pod is a code-location server, and nothing else.** The chart runs
    `dagster api grpc -p 3030 -m doc_tools.definitions` with `replicaCount: 1`, ingress and
    autoscaling disabled and the manufacturing overlay off. By default the chart deploys one
    Deployment, one Service and a ServiceAccount: the corpus gate's CronJob is `enabled:
    false`. The image pin is guarded — a bare tag is refused, a digest renders. `built`

## Settings and defaults

| Setting | Default | Where | What it does |
|---|---|---|---|
| `DOC_PARSER_PDF_IMAGE_DPI` | `200` | `document_parser.py:442` | DPI of the cropped Table/Image blocks the vision pass reads |
| `DOC_PARSER_PAGE_RENDER_DPI` | `300` | `document_parser.py:535` | DPI of the full-page rasters |
| `_MINIMUM_INTERVAL_S` (retry) | `300` | `ingest_retry_sensor.py:104` | gateway retry poll interval |
| publisher interval | `300` | `processable_kinds_publisher.py:50` | matches the retry sensor, by design |
| `default_status` (user-drop) | `RUNNING` | `definitions.py:193`, `:283` | only consulted when the instance has no stored status |
| `default_status` (others) | STOPPED / unset | `definitions.py:181-190`, `:402` | deliberate; the DOORS sensor declares none at all |
| `replicaCount` | `1` | `charts/doc-tools/values.yaml:2` | one code-location server |
| `resources` | `{}` | `values.yaml:74` | no request and no limit |
| `service.port` | `8080` | `values.yaml:67-69` | also the `containerPort` (`templates/deployment.yaml:70`) |
| `ingress.enabled` / `autoscaling.enabled` / `manufacturingOverlay.enabled` | `false` | `values.yaml:71`, `:277`, `:265` | off by default |

## Gaps

- **A failed download substitutes a mock body and the run goes green.** `document_parser.py:397-402`.
  Nothing downstream can tell a mock body from a short document, and no check compares the
  written content against the object's size or ETag. `built` (the substitution); the check is
  `not built`.
- **No page cap and no memory bound anywhere on the parse path.** No `max_pages`, no page
  limit and no rlimit in `document_parser.py` or `extraction.py`; only the two DPI knobs
  bound the work, and the chart sets `resources: {}`. A single large document is bounded by
  nothing but the node. `not built`.
- **The fingerprint cannot see a field rename.** It covers `(kind, passes)` only, so a
  renamed mapping key or a changed `domain`, `arrives_as` or `review_shape` compares equal
  across two code locations. `built` (the fingerprint); the wider comparison is `not built`.
- **`xml` is advertised by one arm and held by the hold list.** The hold is the only thing
  keeping a kind no arm can run out of the published list, and its lifting condition is a
  measurement nobody has made. `accepted` (the hold, ruled 2026-10-16); the measurement is
  `not built`.
- **The declared `passes` tuple and what executes diverge on the sustainment path.** A reader
  of a registry row cannot tell which of its passes actually run. `built` (both), and the
  divergence is undocumented outside this record.

## Not established from code

- **Which sensors are RUNNING in any deployed instance.** Stored status overrides
  `default_status`, and the Dagster instance config is not in git. Reading a cluster is out of
  scope for these records.
- **Whether anything answers the HTTP probes.** The container command starts a gRPC server on
  3030, while the liveness and readiness probes and the `containerPort` are HTTP `/` on 8080.
  No HTTP server on 8080 was found in the chart, and whether `doc_tools.definitions` starts
  the API app in-process was not traced. If nothing answers, the probes are either failing or
  not evaluated, and which of those it is cannot be read from this repo.
- **The DataHub approval sensor's poll interval**, which is Dagster's default because none is
  set, and whether any test pins that sensor at all: none was found by name.
- **Whether the `default_status="RUNNING"` on the two user-drop sensors is pinned by a test.**
  None was found by name; the test that exists covers the S3 filter.
- **What the parse step costs** — wall clock, memory, or pages per minute at either DPI. No
  such measurement exists in this repo, so no claim here is `measured`.
- Which alignment rows of the outside references this component answers to. The rows
  suggested below are this lane's reading, not the arch lane's. The **plane** is not among
  them: the architect ruled on 2026-11-19 that planes are not established. `proposed`

## Place in the mesh

| Aspect | What the code and chart show | Suggested alignment row |
|---|---|---|
| Purpose | turn a document into a parse artifact, a graph, an index and a review record, addressed by a minted ingest id | `AL-DMRA S4` — data and metadata profiles with lineage and pedigree `proposed` |
| Identity | the ingest id is the sidecar's or minted from the bytes, and is the doc id; the run key is the object's ETag | `AL-DMRA S1` — unique identification `proposed` |
| How the mesh reaches it | it is a Dagster code location over gRPC, running inside the orchestrator dag-tools records as `CO-DAGSTER`; the mesh does not call the pipeline, it drops an object or offers a retry | `AL-DMRA S7` — data exchange `proposed` |
| What it emits | a versioned manifest plus a pointer written after it, a graph write, a vector index, a review record | — |
| Security role | none of its own. It holds credentials for the stores it writes and makes no access decision | `AL-DCRA R1` is *not* here — the enforcement point is the gateway's `proposed` |
| Plane | we would read it as an operational data plane — it produces the data the rest of the mesh reads. That reading is ours and nothing confirms it | `not established` — the `AL-DCRA` plane layer is not settled (architect, 2026-11-19), so no `L`*n* is cited here |

## Sources

All paths are in this repo at the pin in [the README](../README.md), except where a row says
otherwise.

| Claim | Source | Decision | Evidence | Status |
|---|---|---|---|---|
| One `Definitions`; eleven S3 sensors, two retry sensors, one publisher; no schedules | `doc_tools/definitions.py:573`, `:581-582` | — | no `ScheduleDefinition` in the module | `built` |
| Sensor prefixes and their target jobs | `definitions.py:89`, `:106`, `:128`, `:170`, `:274`, `:294`, `:320`, `:346`, `:383`, `:404` | — | — | `built` |
| Ingress patterns are generated from the registry | `doc_tools/utils/content_kind.py:836`, `:850` | — | `tests/test_ingress_prefix_registry.py::test_generated_pdf_pattern_equals_the_shipped_literal`, `::test_xml_pattern_is_generated` | `built` |
| `default_status` is consulted only with no stored status; two sensors RUNNING; DOORS declares none | `definitions.py:181-190`, `:193`, `:283`, `:402` | — | — | `built` |
| Cursor is a `LastModified` watermark; run key is `{ETag}-{key}` | `dag_tools/components/s3_sensor/sensor_component.py:86`, `:112-116`, `:140`; `utils.py:36-38` — **installed package, not this repo** | platform's | — | `built` (read at the installed copy) |
| Retry sensor: 300 s, RUNNING, attempt-scoped key, no S3 cursor | `doc_tools/components/ingest_retry_sensor.py:22-40`, `:104`, `:229`, `:372`; `definitions.py:223`, `:241` | — | `tests/test_ingest_retry_sensor.py::test_the_run_key_is_attempt_scoped_so_a_second_retry_is_not_swallowed` | `built` |
| The publisher launches no runs and publishes every tick; the cursor is a record | `doc_tools/components/processable_kinds_publisher.py:12`, `:50`, `:143`, `:146`, `:165` | — | `tests/test_processable_kinds_publisher.py::test_the_sensor_launches_no_runs`, `::test_every_tick_publishes_even_when_nothing_changed` | `built` |
| The parse asset: dynamic partitions, `on_missing`, returns the manifest | `doc_tools/components/document_parser.py:104`, `:107-109`, `:824` | — | — | `built` |
| `hi_res` and the image block types are conditional on an output dir | `doc_tools/utils/extraction.py:69-87`; called with both at `document_parser.py:436-442` | — | — | `built` |
| The two DPI knobs and their defaults | `document_parser.py:442`, `:533-535`; `extraction.py:107`, `:152` | — | `tests/test_witness_page_render_dpi.py::test_page_render_default_is_300`, `::test_chart_sets_the_page_render_dpi_explicitly` | `built` |
| A failed download writes `mock document content` and continues | `document_parser.py:397-402` | — | — | `built` |
| The manifest's keys, and `source_key` declared rather than derived | `document_parser.py:605-620` | `ADR-0034` (pipeline version from the artifact) | — | `built` |
| The pointer is written strictly after the versioned put | `document_parser.py:754-756`, `:768-784` | — | — | `built` |
| Ingest id from the sidecar else minted; sidecar provenance wins | `document_parser.py:197-215`, `:663-664`, `:683`, `:687`, `:707-709` | — | `tests/test_ingress_user_stamp.py::test_f2_sidecar_provenance_wins_and_ingest_id_is_carried`; `tests/test_ingest_id_and_domain_ruling.py::test_a10_a_none_ingest_id_stays_none_in_the_block` | `built` |
| Dispatch invents no default; a BAML pass is not called here; a class is refused | `doc_tools/passes/dispatch.py:158`, `:193`, `:199-201` | — | `tests/test_passes_dispatch.py::test_unresolvable_and_unknown_kind_raise`, `::test_baml_pass_is_skipped_without_resolution`, `::test_a_class_is_refused` | `built` |
| Only three call sites run the dispatcher | `doc_tools/assets/doors_ingestion.py:89`; `doc_tools/plugins/document.py:107-111`; `doc_tools/plugins/playbook.py:60-63` | — | — | `built` |
| The plugin ladder and its Training `else` | `doc_tools/assets/semantic_assets.py:932`, `:943`, `:946`, `:953`, `:955`, `:957-963`, `:964`, `:968-969` | architect's ruling, recorded at `:959` | `tests/test_document_kind_golden.py::test_the_document_domain_gets_its_own_plugin_branch` | `built` |
| `KIND_MAPPING` is the source of truth; 14 generated rows; the domain sidecar | `doc_tools/utils/content_kind.py:87`, `:734`; `registry/content_kinds/`; `registry/content_kind_domains.json` | — | `tests/test_kind_registry.py::test_the_generated_rows_are_in_sync_with_the_table`, `::test_the_rows_load_and_validate_through_the_sdk`, `::test_the_domain_sidecar_covers_every_registered_kind`, `::test_a_format_level_kind_declares_none_and_that_is_not_an_empty_string` | `built` |
| Field ownership: platform owns four fields; `extra="forbid"`; optional projection | `doc_tools/utils/kind_registrations.py:11-30`, `:116`, `:119` | ruled 2026-10-24 | `tests/test_overlay_kind_drift.py::test_the_shared_kinds_declare_the_same_passes`, `::test_the_shared_kinds_declare_the_same_domain` | `built` |
| `ingestable_kinds()` = two arms minus `HELD_OUT`; `xml` held with its lifting condition | `doc_tools/api/kinds.py:70-71`, `:90-118`, `:131-139`, `:142-157`; `content_kind.py:927` | ruled 2026-10-16 (`xml`); held and lifted 2026-11-07 (`playbook`) | `tests/test_kinds_route.py::test_kinds_is_the_union_of_the_arms_MINUS_the_hold_list`, `::test_the_arms_disagree_on_s1000d_and_the_union_sides_with_the_one_that_RAN_it`; `tests/test_processable_kinds_publisher.py::test_the_hold_survives_an_arm_claiming_the_kind`, `::test_playbook_is_advertised_and_is_held_by_nothing`; `tests/test_ingress_prefix_registry.py::test_processable_kinds_is_a_strict_subset_of_registered` | `built` |
| The fingerprint is `(kind, passes)` only, 16 hex, environment-free | `doc_tools/api/kinds.py:122-128` | — | — | `built` |
| The pod is the code-location gRPC server; defaults; the image pin guard | `charts/doc-tools/values.yaml:2`, `:49-50`, `:67-69`, `:71`, `:74`, `:265`, `:277`, `:284`; `templates/deployment.yaml:70`, `:106-109` | — | `tests/test_chart_image_pin_guard.py::test_a_bare_tag_is_REFUSED`, `::test_a_DIGEST_renders_and_needs_no_acknowledgement`, `::test_the_COMMITTED_sandbox_values_still_render` | `built` |
