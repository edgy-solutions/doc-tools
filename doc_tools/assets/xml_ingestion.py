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
from doc_tools.utils.dagster_resources import WeaviateResource
from doc_tools.utils.xml_chunks import extract_chunks_from_graph

# XML military pubs (S1000D / IADS / DITA / 40051) are all maintenance
# content. The Neo4j post-sync labeling in semantic_assets applies the
# `:MAINTENANCE` label after n10s import for the same reason; this asset
# tags Weaviate chunks identically so Engine W's domain-scoped hybrid
# search finds them.
_XML_INGEST_DOMAIN = "MAINTENANCE"


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

    Exactly one of the two shapes must be provided. If both are set,
    s3_bucket+s3_key wins (they're explicit; file_url is a convenience).
    """

    s3_bucket: Optional[str] = None
    s3_key: Optional[str] = None
    file_url: Optional[str] = None

    def resolve(self) -> tuple[str, str]:
        """Return (bucket, key) after honoring the two-shape contract.

        Raises ValueError on invalid config so Dagster surfaces a clear
        failure instead of None-dereferencing downstream.
        """
        if self.s3_bucket and self.s3_key:
            return self.s3_bucket, self.s3_key
        if self.file_url:
            parsed = urlparse(self.file_url)
            if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
                raise ValueError(
                    f"file_url must be an s3:// URI with bucket+key; "
                    f"got {self.file_url!r}"
                )
            return parsed.netloc, parsed.path.lstrip("/")
        raise ValueError(
            "XmlIngestConfig requires either (s3_bucket+s3_key) or file_url. "
            "Got neither."
        )

@asset
def extract_rdf_from_xml(context, config: XmlIngestConfig, s3: S3Resource) -> dict:
    """
    Universal XML to RDF extractor. Routes to specific parsers based on the
    S3 directory prefix and processes files entirely in-memory.
    """
    s3_client = s3.get_client()

    s3_bucket, s3_key = config.resolve()
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

    builder = PARSERS[doc_type](bucket=s3_bucket, doc_id=doc_id, image_prefix=image_prefix)

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


@asset(deps=["extract_rdf_from_xml"])
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
