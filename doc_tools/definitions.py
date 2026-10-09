from dagster import Definitions, load_assets_from_modules, AssetSelection, define_asset_job, EnvVar
from dagster_aws.s3 import S3Resource, s3_pickle_io_manager
from dag_tools import S3SensorComponent
from doc_tools.components.document_parser import DocumentParserComponent
from doc_tools.components.sqlserver_extractor import SqlServerExtractorComponent
from doc_tools.components.oracle_extractor import OracleExtractorComponent
from doc_tools.components.design_parser import DesignParserComponent
from doc_tools.components.datahub_sensor import DataHubSensorComponent
from doc_tools.components.aitool_sensor import AIToolSensorComponent
from doc_tools.assets import semantic_assets, xml_ingestion, ontology_assets, semantic_linker, dds_ingestion, rabbitmq_ingestion, global_semantic_ingestion, aitool_linker, global_aitool_ingestion, iads_ingestion, doors_ingestion
from doc_tools.utils.dagster_resources import Neo4jResource, WeaviateResource, LLMExtractorResource, JenaResource
from doc_tools.partitions import ontology_partitions, design_files_partition, iads_files_partition, xml_files_partition
from doc_tools.utils.content_kind import ingress_user_prefixes
import os
from dag_tools.utils.k8s import resolve_k8s_resource_tags

# 1. Instantiate the Custom Parser Component
document_parser = DocumentParserComponent(
    name="process_document_artifact",
    partition_name="pdf_files",
    config={
        "graph_node_label": "WorkInstruction",
        "graph_child_label": "Page",
        "vector_collection_name": "DocumentChunk",
        "procedure_id_format": r"^\d{4}$",
        "step_id_format": r"^\d+(?:\.\d+)*$",
        "valid_personnel_roles": "QC Inspector, Journeyman, Safety Officer",
        "valid_hazard_classes": "1.1D, 1.3C, Hazmat 3, Biohazard",
        "valid_process_categories": "Transformation, Inspection, Movement, Rework, Critical Safety Hold",
        "bucket": "processing-artifacts"
    }
)
_document_parser_defs = document_parser.build_defs(None)

# 1b. ADR-0041 ingress-user sensor's own parser instance — a SEPARATE
# DocumentParserComponent, not a config toggle on `document_parser`, so it
# gets its OWN partition set (user_pdf_files, not pdf_files — see
# doc_tools/partitions.py) and its own job/asset name
# (process_user_document_artifact). obtained_via="user-drop" makes this
# instance stamp every manifest it produces with the ADR-0041 provenance
# block (doc_tools/utils/ingest_provenance.py) WHEN the sidecar carries
# none of its own (see sidecar_manifest_name below — the sidecar's block
# wins). path_prefix_strip strips the "ingress-user/" transport prefix
# before domain/content_kind derivation so that LOCATION never becomes a
# semantic domain label. Same `config={...}` dict as `document_parser` —
# the vetted and user-drop paths target the same graph/vector labels, only
# their provenance differs.
#
# sidecar_manifest_name="manifest.json" — Lane 1's live sidecar filename
# (measured 2026-10-02 against sandbox MinIO: every object under
# ingress-user/{kind}/{sha256}/ pairs the document with a manifest.json
# sidecar carrying domain_type/content_kind/ingest_id/provenance). Setting
# this makes DocumentParserComponent read THAT sidecar instead of deriving
# domain_type="pdf"/content_kind="<64 hex>" from the key — see
# doc_tools/components/document_parser.py's F2/F3 comment for why a format
# or a hash must never become a semantic label.
user_document_parser = DocumentParserComponent(
    name="process_user_document_artifact",
    partition_name="user_pdf_files",
    obtained_via="user-drop",
    path_prefix_strip="ingress-user/",
    sidecar_manifest_name="manifest.json",
    # Selects build_user_knowledge_graph (not the default
    # build_knowledge_graph) so this job never selects the vetted graph
    # asset, which is pinned to pdf_files_partition — a different
    # partitions_def than this instance's user_pdf_files. See
    # doc_tools.assets.semantic_assets.make_build_knowledge_graph.
    downstream_graph_asset="build_user_knowledge_graph",
    config={
        "graph_node_label": "WorkInstruction",
        "graph_child_label": "Page",
        "vector_collection_name": "DocumentChunk",
        "procedure_id_format": r"^\d{4}$",
        "step_id_format": r"^\d+(?:\.\d+)*$",
        "valid_personnel_roles": "QC Inspector, Journeyman, Safety Officer",
        "valid_hazard_classes": "1.1D, 1.3C, Hazmat 3, Biohazard",
        "valid_process_categories": "Transformation, Inspection, Movement, Rework, Critical Safety Hold",
        "bucket": "processing-artifacts"
    }
)
_user_document_parser_defs = user_document_parser.build_defs(None)

# 2. Instantiate Sensors (decoupled from assets)
pdf_sensor = S3SensorComponent(
    bucket="processing-artifacts",
    prefix="manufacturing/inbound/",
    partition_name="pdf_files",
    target_job=f"{document_parser.name}_job",
    target_op=document_parser.name,
    filter_patterns=["archive/", "metadata.json", "generated/"],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_pdf_sensor_defs = pdf_sensor.build_defs(None)

sustainment_sensor = S3SensorComponent(
    name="sustainment_sensor",
    bucket="processing-artifacts",
    prefix="sustainment/inbound/",
    partition_name="pdf_files",
    target_job=f"{document_parser.name}_job",
    target_op=document_parser.name,
    filter_patterns=["archive/", "metadata.json", "generated/"],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_sustainment_sensor_defs = sustainment_sensor.build_defs(None)

# ADR-0041 — watches the ingress-user inbox, dynamically registers each new
# object into the user_pdf_files partition set, and targets the SEPARATE
# user_document_parser job (never document_parser's job) — same filter
# patterns and s3_resource block as sustainment_sensor, matched exactly,
# PLUS an s3_filter regex gate (D1/D2 fix, below).
#
# The four objects live under this prefix today (measured 2026-10-02):
#   ingress-user/pdf/736499f2eebb7dece392ad285e1a5b03e49e50a88a069cb0cc820b91dc4149d9/manifest.json       -> rejected (sidecar, not \.pdf$)
#   ingress-user/pdf/736499f2eebb7dece392ad285e1a5b03e49e50a88a069cb0cc820b91dc4149d9/roll11-capture.pdf  -> MATCHES
#   ingress-user/pdf/fa231498f527921fc547cb97009a7d98fb45927bdaf7237028ea1cb60305e9bb/PCN23-002.pdf       -> MATCHES
#   ingress-user/pdf/fa231498f527921fc547cb97009a7d98fb45927bdaf7237028ea1cb60305e9bb/manifest.json       -> rejected (sidecar, not \.pdf$)
#
# s3_filter is the GATE: apply_filter() (dag_tools/resources/s3.py) runs
# re.match against it, so a key must be exactly
# ingress-user/pdf/<64-hex-sha256>/<name>.pdf to fire a run at all — this
# also rejects ingress-user/cad/<64hex>/part.step (D2: a CAD drop must never
# reach the PDF parser). filter_patterns' own "manifest.json" entry
# (ADDED here, D1 fix) is the independent BELT: a substring match on the
# sidecar's own name, stated by a second mechanism in case the regex is
# ever loosened. Before this change, filter_patterns excluded
# "metadata.json" (the vetted/legacy sidecar name) but not Lane 1's
# "manifest.json" — so every upload registered TWO partitions and one fed
# the sidecar JSON straight to the PDF parser as if it were a document.
ingress_user_sensor = S3SensorComponent(
    name="ingress_user_sensor",
    bucket="processing-artifacts",
    prefix="ingress-user/",
    partition_name="user_pdf_files",
    target_job=f"{user_document_parser.name}_job",
    target_op=user_document_parser.name,
    # Generated from the `pdf` kind-registry row (content_kind.ingress_user_prefixes),
    # byte-identical to the literal this replaced; sealed by tests/test_ingress_prefix_registry.py.
    s3_filter=ingress_user_prefixes()["pdf"],
    filter_patterns=["archive/", "metadata.json", "generated/", "manifest.json"],
    # THE USER-DROP SENSOR STARTS ITSELF. dag_tools' S3SensorComponent defaults
    # `default_status` to "STOPPED", so on a fresh install (or any instance with
    # no stored status for this sensor) a user drop into `ingress-user/` sat in
    # MinIO until a human opened the Dagster UI and flipped it on. That is the
    # one sensor a user's own upload depends on, so the default is wrong for it
    # specifically; the other sensors here are deliberately left STOPPED.
    #
    # NOT RETROACTIVE, and this is the part that misleads: `default_status` is
    # consulted only when the instance has NO stored status for the sensor. A
    # sensor a human has ever explicitly started or stopped keeps that stored
    # state across deploys, so this flag cannot restart one that was turned off
    # on purpose — check the UI rather than inferring from this line.
    default_status="RUNNING",
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_ingress_user_sensor_defs = ingress_user_sensor.build_defs(None)

# The XML sibling of ingress_user_sensor: a user-dropped XML under
# ingress-user/xml/<sha256>/<name>.xml. Upstream already mints these (the seam
# accepts the `xml` kind); the drops sit unprocessed in MinIO because this repo
# had no sensor for them (the PDF sensor's regex rejects .xml) and the XML
# router could not resolve a parser for an `ingress-user/` key.
#
# A SEPARATE SENSOR, NOT A WIDENED REGEX: a sensor has ONE target_job. Loosening
# the PDF sensor's regex to accept .xml would route XML into the PDF parser --
# the exact D2 defect that sensor's comment was written to prevent. The pattern
# is generated from the `xml` kind-registry row. filter_patterns stay identical:
# the manifest.json belt matters here too.
#
# default_status="RUNNING" for the same reason as the PDF seam: a user's own
# upload depends on it. Not retroactive (a stored status wins) -- check the UI.
ingress_user_xml_sensor = S3SensorComponent(
    name="ingress_user_xml_sensor",
    bucket="processing-artifacts",
    prefix="ingress-user/xml/",
    partition_name="xml_files",
    target_job="xml_graph_sync_job",
    target_op="extract_rdf_from_xml",
    s3_filter=ingress_user_prefixes()["xml"],
    filter_patterns=["archive/", "metadata.json", "generated/", "manifest.json"],
    default_status="RUNNING",
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_ingress_user_xml_sensor_defs = ingress_user_xml_sensor.build_defs(None)

ontology_sensor = S3SensorComponent(
    name="ontology_sensor",
    bucket=os.getenv("ONTOLOGY_BUCKET", "ontologies"),
    prefix="",
    partition_name="ontology_files",
    target_job="ingest_ontology_job",
    target_op="ingest_ontology_to_jena",
    # ingest_ontology_job's selection includes BOTH ops, and both require
    # the same S3FileConfig (file_url). Without listing the second op
    # here the sensor-triggered run fails config validation with
    # "Missing required config entry sync_jena_ontologies_to_neo4j at
    # path root:ops". prime_databases.py's --trigger-ingest provides
    # both ops' config explicitly via GraphQL; this aligns the sensor
    # path with that. See dag-tools S3SensorComponent additional_target_ops.
    additional_target_ops=["sync_jena_ontologies_to_neo4j"],
    filter_patterns=[],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_ontology_sensor_defs = ontology_sensor.build_defs(None)

design_sensor = S3SensorComponent(
    name="design_sensor",
    bucket=os.getenv("DESIGN_BUCKET", "design-artifacts"),
    prefix="",
    partition_name="design_files",
    target_job="parse_design_metadata_job",
    target_op="parse_design_metadata",
    filter_patterns=[],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_design_sensor_defs = design_sensor.build_defs(None)

# 2026-06-29 — IADS bundle sensor. Watches the `iads/` prefix at ANY
# depth so the architect can organize bundles by project/program
# (e.g. `iads/army/aviation/helmet.iads`, `iads/airforce/c130/...`).
# The S3SensorComponent's prefix-listing walks all sub-paths; cursor
# tracking is by S3 key so re-uploads of the same bundle don't
# retrigger. Each new `.iads` file launches `iads_ingest_job` which
# unpacks the bundle to `40051/...` paths that the xml_sensor below
# then picks up for per-WP ingest.
iads_sensor = S3SensorComponent(
    name="iads_sensor",
    bucket="processing-artifacts",
    prefix="iads/",
    partition_name="iads_files",
    target_job="iads_ingest_job",
    target_op="extract_iads_bundle",
    # Skip the unpacked-output dirs the IADS extractor creates so the
    # sensor doesn't loop on its own outputs. The `40051/` prefix is
    # outside our `iads/` watch so this filter is defensive only.
    filter_patterns=["/generated/"],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_iads_sensor_defs = iads_sensor.build_defs(None)

# 2026-06-29 — XML per-WP sensor. Watches the `40051/` prefix at ANY
# depth so files produced by `extract_iads_bundle` (and any manually
# uploaded XMLs under that prefix) trigger `xml_graph_sync_job`. The
# `extract_rdf_from_xml` asset's `XmlIngestConfig` now accepts
# `file_url`, matching the S3SensorComponent's config contract; the
# four downstream assets in the job (upload_to_jena, init_neo4j_n10s,
# sync_jena_to_neo4j, index_xml_chunks_to_weaviate) receive their
# inputs from `extract_rdf_from_xml`'s dict output and don't need
# their own per-op config. The `generated/` filter excludes the
# images/text the bundle extractor uploads alongside the WP XMLs.
#
# We currently scope to `40051/` because that's the only XML doc-type
# the IADS extractor produces. As S1000D / DITA / IADS-direct WPs land,
# expand prefix or add sibling sensors per doc-type. The
# `extract_rdf_from_xml` router dispatches by first path segment so
# adding `s1000d/` etc. is a one-line widening here.
xml_sensor = S3SensorComponent(
    name="xml_sensor",
    bucket="processing-artifacts",
    prefix="40051/",
    partition_name="xml_files",
    target_job="xml_graph_sync_job",
    target_op="extract_rdf_from_xml",
    filter_patterns=["/generated/"],
    s3_filter=r".*\.xml$",
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_xml_sensor_defs = xml_sensor.build_defs(None)

# DOORS flat-CSV export route. New sensor, deliberately NO default_status: it
# stays stopped until an operator turns it on.
doors_sensor = S3SensorComponent(
    name="doors_sensor",
    bucket="processing-artifacts",
    prefix="doors/",
    partition_name="doors_files",
    target_job="doors_ingest_job",
    target_op="ingest_doors_export",
    s3_filter=r".*\.csv$",
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_doors_sensor_defs = doors_sensor.build_defs(None)

design_parser = DesignParserComponent(
    name="parse_design_metadata"
)
_design_parser_defs = design_parser.build_defs(None)

datahub_sensor = DataHubSensorComponent(
    name="datahub_approval_sensor",
    datahub_gms_url=os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080/api/graphql"),
    datahub_token=os.getenv("DATAHUB_TOKEN", "")
)
_datahub_sensor_defs = datahub_sensor.build_defs(None)

# AITool binding plane — RETIRED 2026-06-13 per ADR-0006 §Addendum.
#
# Gateway v0.2 (agent_fleet/mesh_registrar) is now sole writer of AITool
# predicate edges into Neo4j + Weaviate. The sensor's role was to poll
# DataHub for mesh_is_registration=true MCPs and materialize them; v0.2
# does that synchronously in the request path with bounded forward-retry
# + saga compensation, eliminating the sync-gap window the sensor's
# run-key dedup + allowlist drift bug classes lived in.
#
# Why DEACTIVATED, not deleted:
#   - The component, asset (sync_aitool_predicate_to_neo4j), and helper
#     functions in doc_tools/assets/aitool_linker.py stay in the
#     codebase so a one-off manual re-sync of a specific tool_urn is
#     still possible via Dagster's launchpad (the asset takes a
#     tool_urn config and is idempotent). It just isn't triggered by
#     a sensor anymore.
#   - Rollback is a one-line revert: re-add the sensor block to
#     Definitions() below if v0.2 needs to be turned off in an
#     emergency. Until that happens, AITool MCPs in DataHub are
#     audit-trail records, not materialization triggers.
#   - The Dataset sync sensor (datahub_sensor) is UNCHANGED — it
#     operates on glossary terms / Dataset HAS_DATA edges, which v0.2
#     explicitly does not touch (ADR-0006 §Addendum §Scope guardrails).
#
# A short-window race during cutover is the only failure mode this
# transition introduces — see ADR-0006 §Addendum §Cutover. The mitigation
# in that section is: the conjunctive-read invariant makes any
# half-written state unrouted, so even if the sensor fires once during
# the rollout window with allowlist-drift'd properties, the resulting
# edge is unrouted until v0.2 re-registers it cleanly.
#
# aitool_sensor = AIToolSensorComponent(
#     name="aitool_registration_sensor",
#     datahub_gms_url=os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080/api/graphql"),
#     datahub_token=os.getenv("DATAHUB_TOKEN", "")
# )
# _aitool_sensor_defs = aitool_sensor.build_defs(None)

# 3. Assets & Jobs
all_assets = load_assets_from_modules([semantic_assets, xml_ingestion, ontology_assets, semantic_linker, dds_ingestion, rabbitmq_ingestion, global_semantic_ingestion, aitool_linker, global_aitool_ingestion, iads_ingestion, doors_ingestion])

sqlserver_extractor = SqlServerExtractorComponent(
    name="extract_sqlserver_metadata",
    domain="DATA_ENGINEERING",
    host=os.getenv("SQLSERVER_HOST", "localhost"),
    port=int(os.getenv("SQLSERVER_PORT", "1433")),
    database=os.getenv("SQLSERVER_DATABASE", "master"),
    username=os.getenv("SQLSERVER_USERNAME", "sa"),
    password=os.getenv("SQLSERVER_PASSWORD", "password"),
    driver=os.getenv("SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server"),
    trust_server_certificate=os.getenv("SQLSERVER_TRUST_CERT", "true").lower() == "true"
)
_sqlserver_extractor_defs = sqlserver_extractor.build_defs(None)

oracle_extractor = OracleExtractorComponent(
    name="extract_oracle_metadata",
    domain="DATA_ENGINEERING",
    host=os.getenv("ORACLE_HOST", "localhost"),
    port=int(os.getenv("ORACLE_PORT", "1521")),
    service_name=os.getenv("ORACLE_SERVICE_NAME", "ORCL"),
    username=os.getenv("ORACLE_USERNAME", "system"),
    password=os.getenv("ORACLE_PASSWORD", "password")
)
_oracle_extractor_defs = oracle_extractor.build_defs(None)

# 3. Dynamic K8s Resource Management
# Resolve tags using different prefixes for resource control
xml_k8s_tags = resolve_k8s_resource_tags(prefix="XML_INGEST", default_cpu="2000m", default_mem="6Gi")
ontology_k8s_tags = resolve_k8s_resource_tags(prefix="ONTOLOGY_INGEST", default_cpu="1000m", default_mem="2Gi")
design_k8s_tags = resolve_k8s_resource_tags(prefix="DESIGN_PARSER", default_cpu="1000m", default_mem="2Gi")

doors_ingest_job = define_asset_job(name="doors_ingest_job", selection=["ingest_doors_export"])

xml_graph_sync_job = define_asset_job(
    name="xml_graph_sync_job",
    # `index_xml_chunks_to_weaviate` added 2026-06-28 to close the
    # corpus-ingest gap: prior selection only wrote Jena+Neo4j, leaving
    # Engine W's Weaviate `DocumentChunk` collection unpopulated from
    # XML pubs. The asset consumes `extract_rdf_from_xml`'s `chunks`
    # output (in-memory, per the "Zero disk I/O" rule) and writes one
    # row per searchable unit to DocumentChunk.
    selection=[
        "extract_rdf_from_xml",
        "upload_to_jena",
        "init_neo4j_n10s",
        "sync_jena_to_neo4j",
        "index_xml_chunks_to_weaviate",
    ],
    tags=xml_k8s_tags
)

ingest_ontology_job = define_asset_job(
    name="ingest_ontology_job",
    # Option 3 fix (2026-06-12): include sync_jena_ontologies_to_neo4j so
    # TTL ingests propagate to Neo4j's OntologyClass graph in the same
    # job. Without this, the Session-1 DAG-wiring break stays open and
    # canonical classes never reach the runtime graph the resolver reads.
    selection=["ingest_ontology_to_jena", "sync_jena_ontologies_to_neo4j"],
    tags=ontology_k8s_tags
)

# RULING 3 (2026-09-19) — the per-domain, per-manifest-entry ingest sentinel.
#
# A SEPARATE JOB, not an addition to `ingest_ontology_job` above, and the reason
# is structural rather than tidiness: that job is PARTITIONED (one run per TTL)
# and `weaviate_ontology_readiness` deliberately is not. A per-partition
# readiness check cannot see the entry whose partition NEVER RAN, which is the
# blind spot the ruling exists to close — so the sentinel has to stand outside
# the partition set and enumerate what should have run. Run it AFTER the
# partitioned ingest fans in.
ontology_readiness_job = define_asset_job(
    name="ontology_readiness_job",
    selection=["weaviate_ontology_readiness"],
    tags=ontology_k8s_tags,
)

design_metadata_job = define_asset_job(
    name="parse_design_metadata_job",
    selection=["parse_design_metadata"],
    tags=design_k8s_tags
)

# 2026-06-29 — IADS bundle ingest. Unpacks a `.iads` container into S3:
# each WP XML lands under `40051/<project>/<program>/<bundle>/<wp>.xml`
# and each graphic (CGM converted via Inkscape, other formats as-is) lands
# under the parser's predicted `<wp>/generated/<wp>/images/` path. The
# downstream xml_sensor then triggers `xml_graph_sync_job` per WP XML.
iads_k8s_tags = resolve_k8s_resource_tags(prefix="IADS_INGEST", default_cpu="1500m", default_mem="4Gi")
iads_ingest_job = define_asset_job(
    name="iads_ingest_job",
    selection=["extract_iads_bundle"],
    tags=iads_k8s_tags,
)

s3_io_manager = s3_pickle_io_manager.configured({
    "s3_bucket": os.getenv("DAGSTER_STORAGE_BUCKET", "processing-artifacts"),
    "s3_prefix": "dagster-artifacts"
})

defs = Definitions(
    # AITool sensor RETIRED 2026-06-13 per ADR-0006 §Addendum — the
    # gateway v0.2 saga is now sole writer of AITool predicate edges.
    # The aitool_linker module (with sync_aitool_predicate_to_neo4j)
    # is loaded via all_assets so the asset is still callable for
    # one-off manual syncs through the Dagster launchpad. The SENSOR
    # is what's gone — no automatic polling of DataHub for mlModel MCPs.
    assets=list(_document_parser_defs.assets) + list(_user_document_parser_defs.assets) + list(_sqlserver_extractor_defs.assets) + list(_oracle_extractor_defs.assets) + list(_design_parser_defs.assets) + list(_datahub_sensor_defs.assets) + all_assets,
    jobs=list(_document_parser_defs.jobs) + list(_user_document_parser_defs.jobs) + list(_datahub_sensor_defs.jobs) + [xml_graph_sync_job, ingest_ontology_job, ontology_readiness_job, design_metadata_job, iads_ingest_job, doors_ingest_job],
    sensors=list(_pdf_sensor_defs.sensors) + list(_sustainment_sensor_defs.sensors) + list(_ingress_user_sensor_defs.sensors) + list(_ingress_user_xml_sensor_defs.sensors) + list(_ontology_sensor_defs.sensors) + list(_design_sensor_defs.sensors) + list(_datahub_sensor_defs.sensors) + list(_iads_sensor_defs.sensors) + list(_xml_sensor_defs.sensors) + list(_doors_sensor_defs.sensors),
    resources={
        "io_manager": s3_io_manager,
        "s3": S3Resource(
            endpoint_url=EnvVar("S3_ENDPOINT_URL"),
            aws_access_key_id=EnvVar("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=EnvVar("AWS_SECRET_ACCESS_KEY"),
        ),
        "neo4j": Neo4jResource(
            uri=EnvVar("NEO4J_URI"),
            username=EnvVar("NEO4J_USERNAME"),
            password=EnvVar("NEO4J_PASSWORD")
        ),
        "weaviate": WeaviateResource(
            http_host=EnvVar("WEAVIATE_HTTP_HOST"),
            grpc_host=EnvVar("WEAVIATE_GRPC_HOST")
        ),
        "llm": LLMExtractorResource(
            langfuse_public_key=EnvVar("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=EnvVar("LANGFUSE_SECRET_KEY"),
            langfuse_host=EnvVar("LANGFUSE_HOST")
        ),
        "jena": JenaResource(
            url=EnvVar("JENA_URL"),
            dataset=EnvVar("JENA_DS"),
            username=EnvVar("JENA_USERNAME"),
            password=EnvVar("JENA_PASSWORD")
        ),
        **_pdf_sensor_defs.resources,
        **_sustainment_sensor_defs.resources,
        **_ingress_user_sensor_defs.resources,
        **_ingress_user_xml_sensor_defs.resources,
        **_ontology_sensor_defs.resources,
        **_design_sensor_defs.resources,
        **_iads_sensor_defs.resources,
        **_xml_sensor_defs.resources,
        **_doors_sensor_defs.resources,
    },
)

del _document_parser_defs
del _user_document_parser_defs
del _pdf_sensor_defs
del _sustainment_sensor_defs
del _ingress_user_sensor_defs
del _ingress_user_xml_sensor_defs
del _ontology_sensor_defs
del _design_sensor_defs
del _design_parser_defs
del _datahub_sensor_defs
del _iads_sensor_defs
del _xml_sensor_defs
del _doors_sensor_defs
# del _aitool_sensor_defs  # RETIRED 2026-06-13 — gateway v0.2 is sole writer; see ADR-0006 §Addendum
del _sqlserver_extractor_defs
del _oracle_extractor_defs
