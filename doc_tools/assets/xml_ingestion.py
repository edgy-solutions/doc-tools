import os
import boto3
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from dagster import asset, AssetExecutionContext, Config, MaterializeResult
from dagster_aws.s3 import S3Resource

from doc_tools.parsers.s1000d_rdf import S1000dGraphBuilder
from doc_tools.parsers.dita_rdf import DitaGraphBuilder
from doc_tools.parsers.iads_rdf import IadsGraphBuilder
from doc_tools.parsers.mil_std_40051_rdf import MilStd40051GraphBuilder
from doc_tools.partitions import xml_files_partition
from doc_tools.utils.dagster_resources import WeaviateResource
from doc_tools.utils.xml_chunks import extract_chunks_from_graph

# XML military pubs (S1000D / IADS / DITA / 40051) are all maintenance
# content. The Neo4j post-sync labeling in semantic_assets applies the
# `:MAINTENANCE` label after n10s import for the same reason; this asset
# tags Weaviate chunks identically so Engine W's domain-scoped hybrid
# search finds them.
_XML_INGEST_DOMAIN = "MAINTENANCE"


def _is_missing_key(exc: Exception) -> bool:
    """True when `exc` is S3's "that key is not there", matched by ERROR CODE.

    Deliberately NOT `except s3_client.exceptions.NoSuchKey:`. That form resolves
    the exception class off the client at match time, which has two costs. It
    cannot be paired with a defensive fallback clause — a TypeError raised while
    MATCHING an except clause propagates out of the whole `try`, so a later
    `except Exception` in the same statement is never consulted. And it misses the
    404-shaped ClientError boto3 raises in place of NoSuchKey when the caller
    lacks `s3:ListBucket` on the bucket. Code-based matching covers both.
    """
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
        return code in ("NoSuchKey", "404")
    return type(exc).__name__ == "NoSuchKey"


class XmlIngestConfig(Config):
    """Two-shape config for `extract_rdf_from_xml`:

    1. ``{s3_bucket, s3_key}`` — the original manual-launchpad shape.
       Kept for backward compatibility with any GraphQL launchRun
       callers that already use this form.
    2. ``{file_url: "s3://bucket/key"}`` — the S3SensorComponent shape
       used by the new ``xml_sensor`` (added 2026-06-29). The sensor
       passes file_url; the asset parses it into bucket+key. The other
       sensor-triggered jobs in doc-tools (document_parser,
       ingest_ontology) already use this convention.

    Exactly one of the two shapes must be provided. Use the module-
    level ``resolve_xml_config()`` to normalize to (bucket, key).
    Empty-string-as-unset is the form Dagster's Pythonic-config schema
    inference accepts (``Optional[str] = None`` trips schema inference
    with ``Unable to resolve config type`` for the partitioned-asset
    path). Matches the existing ``IngestionConfig`` shape in
    ``doc_tools/config.py``.
    """

    s3_bucket: str = ""
    s3_key: str = ""
    file_url: str = ""


def resolve_xml_config(config: XmlIngestConfig) -> tuple[str, str]:
    """Normalize the two-shape XmlIngestConfig to (bucket, key)."""
    if config.s3_bucket and config.s3_key:
        return config.s3_bucket, config.s3_key
    if config.file_url:
        parsed = urlparse(config.file_url)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
            raise ValueError(
                f"file_url must be an s3:// URI with bucket+key; "
                f"got {config.file_url!r}"
            )
        return parsed.netloc, parsed.path.lstrip("/")
    raise ValueError(
        "XmlIngestConfig requires either (s3_bucket+s3_key) or file_url. "
        "Got neither."
    )

@asset(partitions_def=xml_files_partition)
def extract_rdf_from_xml(context, config: XmlIngestConfig, s3: S3Resource) -> dict:
    """
    Universal XML to RDF extractor. Routes to specific parsers based on the
    S3 directory prefix and processes files entirely in-memory.

    Partitioned by `xml_files_partition` (added 2026-06-29) so the
    new `xml_sensor` (S3SensorComponent) can register a partition
    per WP XML it discovers under the `40051/` prefix and trigger
    `xml_graph_sync_job` per-WP. The downstream four assets
    (`upload_to_jena`, `init_neo4j_n10s`, `sync_jena_to_neo4j`,
    `index_xml_chunks_to_weaviate`) consume this asset's output
    via `deps=["extract_rdf_from_xml"]` — Dagster runs them per
    partition automatically, no separate partition_def needed
    on them. Manual launchpad runs still work — operator picks
    a partition key from the dynamic partition UI.
    """
    s3_client = s3.get_client()

    s3_bucket, s3_key = resolve_xml_config(config)
    context.log.info(f"Fetching XML from s3://{s3_bucket}/{s3_key} into memory...")

    response = None
    try:
        response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        xml_bytes = response['Body'].read()
    except Exception as e:
        context.log.error(f"Failed to fetch file from S3: {e}")
        raise e
    finally:
        if response:
            try:
                response['Body'].close()
            except Exception:
                pass

    # Routing Logic: Use the root directory name from the s3_key.
    # Path-prefix dispatch supports any depth — `40051/army/aviation/helmet/M0004.xml`
    # still routes to the 40051 parser via the first segment. The architect's
    # 2026-06-29 "support depths" ruling is honored here.
    doc_type = s3_key.split('/')[0].lower()

    PARSERS = {
        's1000d': S1000dGraphBuilder,
        'iads': IadsGraphBuilder,
        'dita': DitaGraphBuilder,
        '40051': MilStd40051GraphBuilder
    }

    if doc_type not in PARSERS:
        context.log.error(f"No parser registered for directory type: {doc_type}")
        raise ValueError(f"Unsupported doc_type: {doc_type}")

    context.log.info(f"Routing to {PARSERS[doc_type].__name__} for doc_type: {doc_type}")

    # Derive doc_id from s3_key (e.g., "s1000d/manual_v2.xml" -> "manual_v2")
    import os
    filename = os.path.basename(s3_key)
    doc_id = os.path.splitext(filename)[0]
    base_dir = os.path.dirname(s3_key) or "unknown"
    base_name = filename.replace('.', '_')
    image_prefix = f"s3://{s3_bucket}/{base_dir}/generated/{base_name}/images/"

    # Fetch the per-bundle graphics manifest (written by
    # `extract_iads_bundle`) if present at the sibling path. The
    # manifest is the single source of truth for figure URLs +
    # rendering_origin; without it the parser falls back to the legacy
    # `<boardno>.png` prediction. Sibling path = same dir as the WP XML,
    # not under generated/. For an IADS-sourced WP at
    # `40051/army/aviation/helmet/M0004.xml`, the manifest sits at
    # `40051/army/aviation/helmet/graphics_manifest.json`.
    import json as _json
    graphics_manifest: Optional[Dict[str, Any]] = None
    if doc_type == "40051":
        manifest_key = f"{base_dir}/graphics_manifest.json"
        try:
            manifest_resp = s3_client.get_object(Bucket=s3_bucket, Key=manifest_key)
            graphics_manifest = _json.loads(manifest_resp['Body'].read())
            try:
                manifest_resp['Body'].close()
            except Exception:
                pass
            context.log.info(
                f"Loaded graphics manifest from s3://{s3_bucket}/{manifest_key} "
                f"with {len(graphics_manifest.get('figures', {}))} figure entries."
            )
        except Exception as e:
            # BEST-EFFORT, NEVER FATAL. The manifest is optional — the parser has
            # a defined behaviour without one — so no failure reading it may kill
            # the ingest. Same ruling as `_fetch_override` in
            # assets/iads_ingestion.py: "don't kill the whole ingest because the
            # operator's override is momentarily unreachable." A plain miss is the
            # expected legacy-path case and logs at info; anything else (corrupt
            # JSON, AccessDenied) is WARNED, so a broken manifest is visible as a
            # broken manifest rather than reading as "this WP has no figures."
            graphics_manifest = None
            if _is_missing_key(e):
                context.log.info(
                    f"No graphics_manifest.json at s3://{s3_bucket}/{manifest_key} — "
                    f'figures resolve to rendering_origin="unresolved" with no '
                    f"mil:hasURL (legacy single-XML ingest path)."
                )
            else:
                context.log.warning(
                    f"graphics_manifest.json at s3://{s3_bucket}/{manifest_key} could "
                    f"not be read ({type(e).__name__}: {e}) — treated as absent, so "
                    f'every figure in this WP resolves to rendering_origin='
                    f'"unresolved". This is a MISCONFIGURATION, not the legacy path: '
                    f"the manifest exists but is unusable."
                )

    builder = PARSERS[doc_type](
        bucket=s3_bucket,
        doc_id=doc_id,
        image_prefix=image_prefix,
        graphics_manifest=graphics_manifest,
    ) if doc_type == "40051" else PARSERS[doc_type](
        bucket=s3_bucket, doc_id=doc_id, image_prefix=image_prefix,
    )

    # Parse the in-memory bytes and capture the root URI
    root_uri = builder.parse_data_module(xml_bytes)

    # Return the serialized RDF string directly for in-memory passing (K8s safe)
    rdf_string = builder.serialize(format="turtle")
    context.log.info(f"RDF serialized to string successfully. Root URI: {root_uri}")

    # Extract text chunks from the same in-memory graph the parser
    # just built. Mirrors the architect's "Zero disk I/O" + "Pass
    # raw Turtle data and root URIs between assets as dictionaries"
    # rules — we don't re-parse the XML or write to disk; we walk
    # the rdflib.Graph the parser already populated.
    #
    # The chunks land in Weaviate's DocumentChunk via the
    # `index_xml_chunks_to_weaviate` asset below. This closes the
    # architectural gap surfaced in the 2026-06-29 corpus-ingest
    # investigation: the prior xml_graph_sync_job pipeline only wrote
    # Jena+Neo4j; Engine W's hybrid search over DocumentChunk had no
    # XML-sourced rows, so every routed query returned 0 sources.
    chunks: List[Dict[str, Any]] = []
    try:
        chunks = extract_chunks_from_graph(
            builder.graph, root_uri, _XML_INGEST_DOMAIN
        )
        context.log.info(
            f"Extracted {len(chunks)} text chunks from {root_uri} "
            f"(domain={_XML_INGEST_DOMAIN}; written by "
            f"index_xml_chunks_to_weaviate downstream)."
        )
    except Exception as e:
        # Per [[feedback-trailing-steps-nonfatal]]: chunk extraction is
        # a secondary output. If it fails, the primary RDF+Neo4j path
        # still proceeds. The downstream asset will see chunks=[] and
        # log accordingly.
        context.log.warning(
            f"extract_chunks_from_graph failed for {root_uri} "
            f"(chunks=[] passed downstream): {e}"
        )

    return {
        "rdf_string": rdf_string,
        "root_uri": root_uri,
        "s3_key": s3_key,
        "chunks": chunks,
    }


@asset(deps=["extract_rdf_from_xml"], partitions_def=xml_files_partition)
def index_xml_chunks_to_weaviate(
    context: AssetExecutionContext,
    extract_rdf_from_xml: dict,
    weaviate: WeaviateResource,
) -> MaterializeResult:
    """Write the chunks produced by `extract_rdf_from_xml` into the
    Weaviate `DocumentChunk` collection (the one Engine W's hybrid
    search reads).

    Closes the Weaviate-population leg of `xml_graph_sync_job`. Before
    this asset, the job wrote Jena (full RDF) + Neo4j (n10s import)
    but the Weaviate collection that Engine W queries got nothing
    from XML pubs — only the PDF path (`build_knowledge_graph` in
    semantic_assets) populated it.

    The result: Engine W routed-specialist queries about helmet TM
    content returned 0 sources because no chunks existed. After this
    asset lands, the XML pipeline populates Weaviate alongside
    Jena+Neo4j, mirroring the architect's "all three stores carry
    the document" intent that the docs describe but the asset graph
    didn't implement.

    Per [[failure-mode-pluralism-in-fixes]]: this is the Path 1
    follow-up. Bug A (routing lock) and Bug B (PROV contamination)
    were fixed first; they exposed THIS gap as the next mechanism
    to address. The architect ruled "add the missing XML→DocumentChunk
    asset" 2026-06-29 after I surfaced the architectural mismatch.

    Per [[fixture-must-exercise-paths]]: until a real ingest run
    populates Weaviate via this asset and Engine W returns non-empty
    sources for a routed helmet query, this asset is unproven.
    """
    # Local imports to keep the module-load light and to allow the
    # helpers from semantic_assets (which carry the embed-document
    # + Weaviate-insert pattern build_knowledge_graph already uses) to
    # land WITHOUT cross-asset shadowing risk. See
    # `doc_tools/assets/semantic_assets.py` for the canonical
    # `_ensure_weaviate_collection` + `_index_chunk` definitions.
    from doc_tools.assets.semantic_assets import (
        _ensure_weaviate_collection,
        _index_chunk,
    )

    chunks: list[dict] = list(extract_rdf_from_xml.get("chunks") or [])
    root_uri = extract_rdf_from_xml.get("root_uri", "<unknown>")
    s3_key = extract_rdf_from_xml.get("s3_key", "<unknown>")

    if not chunks:
        # Honest-empty per `[[honest-failure-as-demo-asset]]`. The
        # downstream signal (no chunks for this WP) is more useful than
        # a fabricated placeholder, and operators can distinguish
        # "parser emitted no text Literals on the root" from "Weaviate
        # write failed" by reading this log line.
        context.log.warning(
            f"index_xml_chunks_to_weaviate: 0 chunks for root_uri="
            f"{root_uri} (s3_key={s3_key}). Either the parser didn't "
            f"emit text Literals on the root, or the chunker missed "
            f"this WP's predicate shape. Investigate before assuming "
            f"the pipeline is healthy."
        )
        return MaterializeResult(
            metadata={
                "chunks_written": 0,
                "root_uri": root_uri,
                "s3_key": s3_key,
                "collection": "DocumentChunk",
            }
        )

    weaviate_client = weaviate.get_client()
    try:
        # Idempotent collection-create. In practice the collection
        # already exists from the PDF path's prior runs; this is the
        # safety net for a fresh-cluster prime.
        _ensure_weaviate_collection(weaviate_client, "DocumentChunk")

        # Delete existing chunks for THIS doc_id before re-indexing.
        # Without this, re-ingest accumulates: each run appends a new
        # set of objects for the same doc_id+section, and Weaviate
        # ends up with N copies of each chunk after N re-ingests. The
        # 2026-06-30 chunk-text fix needed three re-ingests to land
        # cleanly because old "See the structural panel" objects
        # remained alongside new "Figure X." objects, with both
        # candidates in BM25/vector retrieval. Delete-then-insert is
        # the idempotent contract — same doc_id at the input always
        # produces the same chunk set at the output, no accretion.
        #
        # Per `[[verification-must-fail]]`: this delete MUST be observable.
        # We log the count deleted so operators can confirm the
        # cleanup actually fired (a silently-failing delete that
        # always reports 0 would be a regression).
        try:
            from weaviate.classes.query import Filter as _W_Filter
            collection = weaviate_client.collections.get("DocumentChunk")
            # delete_many returns a result object; matched count is the
            # observable signal.
            del_result = collection.data.delete_many(
                where=_W_Filter.by_property("doc_id").equal(root_uri),
            )
            deleted_count = getattr(del_result, "matches", None)
            if deleted_count is None:
                # Older client API path — best-effort log
                deleted_count = "?"
            context.log.info(
                f"index_xml_chunks_to_weaviate: pre-deleted "
                f"{deleted_count} existing DocumentChunk rows for "
                f"doc_id={root_uri} (idempotent re-ingest contract)."
            )
        except Exception as del_err:
            # Delete failing should NOT kill the ingest — if delete
            # errors and insert succeeds, we still get the new chunks
            # written, just possibly with stale companions. Logged
            # loudly so observability surfaces the gap.
            context.log.warning(
                f"index_xml_chunks_to_weaviate: pre-delete FAILED for "
                f"doc_id={root_uri} (non-fatal, continuing with insert): "
                f"{del_err}"
            )

        written = 0
        failed = 0
        for chunk in chunks:
            try:
                # _index_chunk embeds via doc_tools.utils.embed.embed_document
                # (LiteLLM nomic-embed-text, `search_document:` prefix) and
                # inserts. On embed-gateway failure it writes the row
                # without a vector — BM25 still works, backfill later.
                _index_chunk(weaviate_client, "DocumentChunk", chunk)
                written += 1
            except Exception as e:
                # Per [[feedback-trailing-steps-nonfatal]]: per-chunk
                # failure must not kill the whole batch. Log loudly,
                # count, continue. Operators can re-run with the same
                # config to retry idempotently (chunks are deterministic
                # in shape; re-running produces dup rows only if
                # Weaviate's auto-id assignment picks new UUIDs — see
                # follow-up to make this fully idempotent via
                # deterministic UUIDs from doc_id+section).
                failed += 1
                context.log.warning(
                    f"index_xml_chunks_to_weaviate: failed to write "
                    f"chunk (section={chunk.get('section','<?>')}, "
                    f"doc_id={chunk.get('doc_id','<?>')}): {e}"
                )

        context.log.info(
            f"index_xml_chunks_to_weaviate: wrote {written}/{len(chunks)} "
            f"chunks to DocumentChunk for {root_uri} (failures: {failed})."
        )
        return MaterializeResult(
            metadata={
                "chunks_written": written,
                "chunks_failed": failed,
                "chunks_total": len(chunks),
                "root_uri": root_uri,
                "s3_key": s3_key,
                "collection": "DocumentChunk",
            }
        )
    finally:
        # Mirror semantic_assets / ontology_assets: close the Weaviate
        # client cleanly. The resource manages connection pooling
        # across the asset run; explicit close at the asset boundary
        # is the established pattern.
        try:
            weaviate_client.close()
        except Exception:
            pass
