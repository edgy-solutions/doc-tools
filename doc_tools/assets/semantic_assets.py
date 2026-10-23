import os
import re
import json
import httpx
import urllib.parse
import collections
from typing import Any, Dict
from dagster import asset, AssetExecutionContext, AssetIn, MaterializeResult, AutomationCondition
from neo4j import GraphDatabase
from doc_tools.config import IngestionConfig
from dagster_aws.s3 import S3Resource
from doc_tools.partitions import pdf_files_partition, user_pdf_files_partition, xml_files_partition
from doc_tools.utils.dagster_resources import Neo4jResource, WeaviateResource, LLMExtractorResource, JenaResource
from doc_tools.plugins import BaseSection, DocumentNode
from doc_tools.plugins.training import TrainingPlugin
from doc_tools.plugins.manufacturing import ManufacturingPlugin
from doc_tools.plugins.sustainment import SustainmentPlugin
from doc_tools.utils.ingest_rates import render_rates, summarize_rates
from doc_tools.utils.provenance_stamp import (
    PROVENANCE_FIELDS, provenance_params, provenance_set_fragment,
)
import weaviate.classes as wvc
from weaviate.util import generate_uuid5


class ProvenanceStampFailedError(RuntimeError):
    """The provenance stamp could not be written, so nothing else may be.

    REPLACES ``ProvenanceNotPersistableError`` and the
    ``DOMAINS_THAT_PERSIST_PROVENANCE`` frozenset it guarded. ARCHITECT RULING
    2026-10-02: *"provenance persists for every domain; it is an invariant of
    the write path, not an opt-in."* The old design asked the resolved domain
    whether its plugin happened to persist the block and halted the ingest if
    not — correct given that only SustainmentPlugin did, but it made the
    invariant a per-domain property. It is now a property of the write itself:
    the parent-document MERGE carries the stamp for every domain (see
    doc_tools/utils/provenance_stamp.py).

    What remains refusable is a FAILED stamp. The parent-node write is
    otherwise best-effort (it logs and continues), and leaving it best-effort
    for a provenance-bearing document would reintroduce exactly the harm the
    deleted check prevented: unvetted content in Neo4j, indistinguishable from
    vetted content, because the one write that would have said so errored into
    a log line. So for a manifest carrying provenance, and only then, that
    write is load-bearing and its failure raises.
    """


class DomainTypeNotResolvableError(RuntimeError):
    """No registered content kind and no declared domain — so no domain.

    Architect ruling 2026-10-02: *"domain_type comes from the registered
    content kind's declared domain, never a run tag."* With the run-tag read
    gone there is no third source to fall back to, and the `"Training"`
    default that used to sit behind it was a silent semantic claim about an
    unidentified document: it wrote the content into the TRAINING domain's
    Neo4j label and graph. Halting is the same posture ADR-0021 already takes
    for `content_kind` (`UnclassifiableContentKindError`) — the two are no
    longer asymmetric.
    """


def _ensure_weaviate_collection(client, name: str) -> None:
    """Idempotently create the chunk collection using the Weaviate v4 API
    (mirrors ontology_assets). The deployed cluster supplies the default
    vectorizer, so no vectorizer_config is set here."""
    if not client.collections.exists(name):
        client.collections.create(
            name=name,
            properties=[
                wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="doc_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="chunk_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="domain", data_type=wvc.config.DataType.TEXT),
            ],
        )
        # FOLD, NOT HAND-RUN — inside the `if`, in the same act that creates the
        # collection. A marker written by a separate step can be forgotten, and a
        # forgotten marker reads as ABSENT while the collection is perfectly real.
        # Best-effort: never raises, so a diagnostic cannot take down the ingest.
        from doc_tools.utils.collection_marker import write_collection_marker

        write_collection_marker(client, name)


def _index_chunk(client, name: str, properties: dict) -> str:
    """Upsert one chunk object using the Weaviate v4 API, keyed by a
    deterministic uuid derived from the chunk's business key.

    Computes the vector via doc_tools.utils.embed.embed_text() (LiteLLM
    /embeddings, default model nomic-embed-text) and passes it explicitly
    to .data.insert(vector=...). No server-side text2vec module is
    involved — code owns the contract for "what embedding model." See
    doc_tools/utils/embed.py for the rationale.

    Identity: uuid = generate_uuid5(properties["chunk_id"]). chunk_id
    alone is the key — NOT chunk_id + collection name — because mixing in
    the collection would silently re-mint every uuid on a collection
    rename. chunk_id is already unique per collection: built by callers as
    f"{doc_id}_p{page_num}" (page chunks), f"{doc_id}_fig_{stem}" (figure
    chunks), or doc_id + section + text-hash (XML chunks, stamped in
    doc_tools/utils/xml_chunks.py). Without this, a re-ingest of the same
    document minted a fresh random uuid every time and DUPLICATED every
    chunk row.

    Returns one of three verdicts so callers can tally outcomes:
      - "written": wrote (insert or replace) WITH a vector.
      - "written_without_vector": embedding failed/unavailable and no row
        existed yet, so we wrote the row anyway with no vector — BM25
        queries still work, and a follow-up backfill can populate the
        vector once the gateway is restored. The alternative (hard
        failure) would gate ingestion on the LLM stack being healthy,
        which is the fragility we're explicitly avoiding.
      - "skipped_would_strip_vector": embedding failed/unavailable AND a
        row already existed at this uuid. See the comment below — this
        is the load-bearing case.
    """
    from doc_tools.utils.embed import embed_document  # local import: keeps
    # module-load cheap for callers that monkey-patch this for tests.

    chunk_id = properties.get("chunk_id")
    if not chunk_id:
        raise ValueError(
            "_index_chunk requires a non-empty properties['chunk_id'] to "
            "derive a stable uuid; a chunk with no stable identity is "
            "exactly the duplication defect this function exists to fix."
        )
    chunk_uuid = generate_uuid5(chunk_id)

    text = properties.get("text", "")
    try:
        # WRITE path: embed_document applies the search_document: prefix
        # that pairs with embed_query on the iagent reader side.
        vector = embed_document(text) if text else None
    except Exception as e:
        print(f"[semantic_assets] embed_document failed for chunk; "
              f"writing without vector (BM25-only until backfill): {e}")
        vector = None

    collection = client.collections.get(name)
    exists = collection.data.exists(chunk_uuid)

    if vector is not None:
        if exists:
            collection.data.replace(uuid=chunk_uuid, properties=properties, vector=vector)
        else:
            collection.data.insert(uuid=chunk_uuid, properties=properties, vector=vector)
        return "written"

    if not exists:
        # No row yet: write it without a vector (degraded but recoverable
        # — see the "written_without_vector" case in the docstring).
        collection.data.insert(uuid=chunk_uuid, properties=properties)
        return "written_without_vector"

    # vector is None AND a row already exists at this uuid: DO NOT call
    # collection.data.replace(...) here. replace() is a documented
    # whole-object PUT — calling it with no vector STRIPS whatever vector
    # the existing row already had. This collection is self_provided
    # (doc-tools computes vectors itself via LiteLLM; there is no
    # server-side text2vec module to re-embed it later), so a stripped row
    # stays unsearchable by vector until something explicitly repairs it.
    # Skipping this write is recoverable (the next successful embed will
    # upsert it); stripping is a silent, irreversible-until-backfill loss.
    # The asymmetry is the whole argument: "always write something" reads
    # as the safer default, but here the write is the destructive branch.
    return "skipped_would_strip_vector"


# Mirrors Lane 1's `_PART_FIELD_RE` in the deployed gateway: a review row's
# `rows` are the review_items whose field_path matches this, counted by
# DISTINCT part index. That is the row count -- not the item count (one part
# carries several field items) and not `extracted_count` (unstructured
# ELEMENTS) or `extracted_total` (rasterized PAGES).
_PART_FIELD_RE = re.compile(r"^parts\[(\d+)\]\.[A-Za-z0-9_]+$")


def _part_row_count(review_payload) -> int:
    """Distinct part indices over review_payload["review_items"]; 0 if none."""
    items = (review_payload or {}).get("review_items") or []
    idx = set()
    for it in items:
        m = _PART_FIELD_RE.match(str((it or {}).get("field_path") or ""))
        if m:
            idx.add(m.group(1))
    return len(idx)


def _extraction_payload(document_nodes, doc_id: str, domain_type: str) -> dict:
    """Serialize the structured LLM extraction for persistence to S3.

    to_graph_queries only writes Neo4j/Jena; this captures the raw extracted
    records (each node's Pydantic ``domain_augmentation`` -> dict) so the output
    is retrievable / auditable / reprocessable. Domain-generic: works for any
    plugin whose augmentation is a Pydantic model. Nodes without an augmentation
    (e.g. per-chunk no-op augment) are skipped.
    """
    augmentations = [
        n.domain_augmentation.model_dump()
        for n in document_nodes
        if n.domain_augmentation is not None and hasattr(n.domain_augmentation, "model_dump")
    ]
    return {"doc_id": doc_id, "domain_type": domain_type, "augmentations": augmentations}


def _ask_lane1_for_the_leaf(context, manifest: dict):
    """Step 5's dispatch: ask Lane 1 what this format-level drop actually IS.

    The leaf ruling's item 4 put the title read in the parse step, which wrote
    `manifest["leaf"]` and read nothing. This is the half that acts on it, and
    it sits at the ORIGIN-UNRESOLVED gate because that is the gate a
    format-level drop stops at today — Lane 1's own answer to where it
    belongs: *"Your title dispatch should sit at that gate."*

    Returns a `TitleLeafAnswer`, always, or None when there was nothing to
    ask about (no `ingest_id`, or no `leaf` block — the vetted path and every
    pre-leaf image). A None and an `asked=False` answer mean the same thing to
    the caller and are kept distinct only so the log says which.

    THE BODY IS BUILT FIELD BY FIELD, from the final-shape packet's table:

      * `leaf`    -> `doc_type`        (the BFF lowercases it, so the read's
                                       own `pcn` and a header's `PCN` both
                                       work; nothing is re-cased here)
      * `outcome` -> `doc_type_source` (sent as read. Confidence is THEIRS:
                                       *"Do not decide confidence yourself"*,
                                       and their rule is `doc_type_source ==
                                       "title"` with a pcn/pdn doc_type)
      * `candidates`                   (objects `{leaf, score, evidence_ref}`,
                                       max 3, score in [0,1] — all three
                                       already true of the producer)
      * `run_id`                       (the Dagster run, for their log)

    `leaf_source` is NOT sent: *"leaf_source is the BFF's to write. You send
    none."* `outcome` and `evidence_ref` are not sent at top level either —
    the route has no slot for a confident read's evidence, and an extra key
    is a 422. So this is a projection of the block, never the block.
    """
    ingest_id = manifest.get("ingest_id")
    leaf_block = manifest.get("leaf")
    if not ingest_id or not isinstance(leaf_block, dict):
        context.log.info(
            "title_leaf: not asking for doc_id=%r — ingest_id=%s leaf_block=%s. "
            "No Lane 1 row to address, or no title read on this manifest (the "
            "vetted path runs none, and no image before the leaf work wrote "
            "the block).",
            manifest.get("doc_id"), bool(ingest_id), type(leaf_block).__name__,
        )
        return None

    from doc_tools.utils.dagster_resources import IngestStatusResource

    # Instantiated inline, exactly as the `review`/`failed` posts below and
    # the parser's own `extracting` post do. Not a Dagster resource, because
    # the asset is shared with the vetted path, which has no gateway at all.
    return IngestStatusResource().title_leaf(
        ingest_id,
        doc_type=leaf_block.get("leaf"),
        doc_type_source=leaf_block.get("outcome"),
        candidates=leaf_block.get("candidates") or [],
        run_id=_dagster_run_id(context),
    )


def _dagster_run_id(context) -> "str | None":
    """The run id, preferring the accessor Dagster has not deprecated.

    `context.run_id` warns on every call now ("Use context.run.run_id
    instead") and is slated for removal. A bare `getattr(context, "run_id",
    None)` would therefore go quietly to None the day it goes away, and
    `run_id` is what Lane 1 correlates a held row against in their log — so
    its loss would show up as an unexplained gap on their side, not as an
    error on mine.
    """
    run = getattr(context, "run", None)
    rid = getattr(run, "run_id", None)
    if rid:
        return rid
    return getattr(context, "run_id", None)


def _build_knowledge_graph_impl(
    context: AssetExecutionContext,
    config: IngestionConfig,
    process_document_artifact: Dict[str, Any],
    s3: S3Resource,
    neo4j: Neo4jResource,
    weaviate: WeaviateResource,
    llm: LLMExtractorResource,
    jena: JenaResource,
    posted: "dict | None" = None,
):
    """
    Ingests documents into Neo4j using generic labels provided via Configuration.
    Vectorizes document chunks into a Weaviate collection provided via Configuration.

    This is the asset BODY, factored out from the @asset-decorated wrapper so
    one implementation serves both the vetted path (build_knowledge_graph,
    fed by process_document_artifact / pdf_files_partition) and the ADR-0041
    ingress-user path (build_user_knowledge_graph, fed by
    process_user_document_artifact / user_pdf_files_partition) — see
    make_build_knowledge_graph() below.
    """
    manifest = process_document_artifact
    doc_id = manifest["doc_id"]
    text_location = manifest["text_location"]
    
    # Map Configuration Variables to Local Context
    node_label = config.graph_node_label
    child_label = config.graph_child_label
    collection_name = config.vector_collection_name
    
    context.log.info(f"Building Graph for doc: {doc_id} using labels '{node_label}' and '{child_label}'")
    
    # ----------------------------------------------------------------------
    # Domain label for Neo4j segregation.
    #
    # ARCHITECT RULING 2026-10-02: "domain_type comes from the registered
    # content kind's declared domain, never a run tag." This supersedes the
    # 2026-06-20 banking that deferred the question to "a future ADR" and
    # asked that the domain_type/content_kind asymmetry not be collapsed
    # without a ruling. It has been ruled; the asymmetry is collapsed.
    #
    # THREE THINGS WENT AWAY, and they went away for different reasons:
    #
    #  1. `context.run.tags.get("domain_type")` — deleted outright, the
    #     explicit half of the ruling. It was also already inert: AGENTS.md
    #     claims sensors inject a `domain_type` run tag, and the installed
    #     `S3SensorComponent` injects NO run tags at all (measured on this
    #     branch, 2026-10-02, dagster 1.12.21).
    #  2. The `except AttributeError` around it — dead on this dagster
    #     version. `AssetExecutionContext` DOES expose `.run`, and `.get`
    #     returns None WITHOUT raising, so the handler never fired.
    #  3. `metadata.get("project", "Training")` — unreachable, because it sat
    #     inside (2). Its documented intent was "domain_type silently defaults
    #     to Training", which is a semantic claim about an unidentified
    #     document; nothing is put in its place (see
    #     DomainTypeNotResolvableError).
    #
    # ORDERING. The old code resolved domain_type FIRST and then gated the
    # content-kind resolution on `if domain_type == "manufacturing"` — it used
    # domain_type to decide whether to resolve the kind that, under this
    # ruling, SUPPLIES domain_type. The resolver is therefore called first
    # now. It can be: `resolve_content_kind`'s metadata branch
    # (`metadata["content_kind"]`) needs no domain at all. Its PATH-derive
    # branch does need one (`_derive_from_path` matches s3_key's first segment
    # against it), which is why the manifest's declared domain is still read —
    # as the resolver's input and as the kind's fallback, not as the
    # authority.
    # ----------------------------------------------------------------------
    metadata = manifest.get("metadata", {})
    s3_key = manifest.get("source_object_key") or manifest.get("s3_key", "")

    # See doc_tools/utils/content_kind.py for the mapping table + halt rule.
    from doc_tools.utils.content_kind import (
        resolve_content_kind, UnclassifiableContentKindError, KIND_MAPPING,
    )

    declared_domain = metadata.get("domain_type")

    kind_entry = None
    try:
        kind_entry = resolve_content_kind(metadata, s3_key)
        context.log.info(
            f"ADR-0021 content_kind resolved: kind={kind_entry.kind!r} "
            f"target={kind_entry.target_ontology_class!r} "
            f"domain_type={kind_entry.domain_type!r}"
        )
    except UnclassifiableContentKindError:
        # SCOPED MIGRATION — the reason the resolver's halt is not simply
        # propagated for every domain. A domain joins the resolver by GAINING
        # KIND_MAPPING rows, not by this except clause getting narrower.
        #
        # CORRECTED 2026-10-21: this comment used to say KIND_MAPPING held
        # exactly ONE row (work-instructions -> manufacturing) and that
        # "SUSTAINMENT and the whole PCN corpus" was unmigrated with no row to
        # resolve. That has not been true for some time. Measured from
        # doc_tools/utils/content_kind.py: NINE rows, of which FOUR declare a
        # domain — work-instruction -> manufacturing, pcn -> sustainment,
        # pdn -> sustainment, s1000d-data-module -> maintenance — and five are
        # format-level with domain_type=None (pdf, cad, engineering-document,
        # doors-export, xml). Training and compliance remain unmigrated.
        #
        # Manufacturing still HALTS, because a manufacturing document whose
        # kind does not resolve is a document whose registered kind is missing,
        # and ADR-0021 §Precedence has no default for that.
        #
        # SO THERE IS NOW AN ASYMMETRY, AND IT IS DELIBERATELY LEFT: sustainment
        # and maintenance are migrated too, but an unresolvable drop on either
        # still falls through to the declared-domain fallback below instead of
        # halting. Whether the halt widens to every domain that has rows is the
        # architect's call (reported 2026-10-21); it is not widened here,
        # because doing it quietly would start failing live sustainment and
        # maintenance drops that fall back successfully today.
        if declared_domain == "manufacturing":
            context.log.error(
                "ADR-0021 content_kind resolution HALTED for manufacturing "
                "path (no KIND_MAPPING row matches metadata.content_kind "
                "or the path-derived segment)."
            )
            raise
        context.log.info(
            f"ADR-0021: no KIND_MAPPING row matches for doc_id={doc_id!r} "
            f"(declared domain {declared_domain!r}; the table holds "
            f"{len(KIND_MAPPING)} rows, of which "
            f"{sorted({e.domain_type for e in KIND_MAPPING.values() if e.domain_type})} "
            f"declare a domain). Falling back to the manifest's declared "
            f"domain. This is the scoped migration, not a default: only the "
            f"manufacturing path halts here."
        )

    # ----------------------------------------------------------------------
    # STEP 5 — HOLD EXTRACTION ON THE LEAF.
    #
    # Deliberately a SEPARATE `if` on the same condition as the
    # origin-unresolved branch below, rather than an edit inside it. The
    # three outcomes then fall out of one reassignment:
    #
    #   * Lane 1 grants a leaf -> `kind_entry` becomes that kind, which
    #     DECLARES a domain, so the test below is False and the run
    #     continues into the ordinary domain path. Parts extraction runs as
    #     the kind the BFF named.
    #   * Lane 1 holds the row -> this block returns `awaiting_kind`.
    #   * The call could not be made -> `kind_entry` is untouched and the
    #     branch below runs verbatim. That matters more than it looks: the
    #     pre-204 behaviour is not re-implemented here, it is literally the
    #     same code, so a gateway outage cannot change what a drop does.
    # ----------------------------------------------------------------------
    if kind_entry is not None and kind_entry.domain_type is None:
        leaf_answer = _ask_lane1_for_the_leaf(context, manifest)
        if leaf_answer is not None and leaf_answer.proceed and leaf_answer.content_kind:
            # "Run parts extraction AS `content_kind`, the kind the BFF
            # names, not the one your sidecar names." The grant may also be a
            # leaf the row already held — declared at the drop or corrected
            # by a person — and both BEAT this run's title read, so the
            # answer is adopted without being checked against it.
            granted = KIND_MAPPING.get(leaf_answer.content_kind)
            if granted is not None and granted.domain_type:
                context.log.info(
                    f"LEAF GRANTED for doc_id={doc_id!r}: Lane 1 answered "
                    f"proceed=True content_kind={leaf_answer.content_kind!r} "
                    f"(leaf={leaf_answer.leaf!r} leaf_source="
                    f"{leaf_answer.leaf_source!r}). Extraction runs as that "
                    f"kind, domain {granted.domain_type!r} — the "
                    f"origin-unresolved return below is skipped because the "
                    f"origin is now resolved by EVIDENCE (the document's own "
                    f"title, or a human's correction), which is exactly what "
                    f"the 2026-10-02 ruling said it would take."
                )
                kind_entry = granted
            else:
                # Not a 422 and not my call to widen: the BFF's leaf space
                # and this registry's domain-declaring rows are two lists,
                # and the ruling says the registry is the authority on what a
                # leaf may be. A grant this registry cannot honour is
                # reported and the drop stays where it was.
                context.log.error(
                    f"LEAF GRANT UNUSABLE for doc_id={doc_id!r}: Lane 1 "
                    f"granted content_kind={leaf_answer.content_kind!r}, "
                    f"which is not a KIND_MAPPING row that declares a domain "
                    f"(the domain-declaring keys are "
                    f"{sorted(k for k, e in KIND_MAPPING.items() if e.domain_type)}). "
                    f"Extraction does NOT run: picking a plugin for a kind "
                    f"with no declared domain is the hazard ADR-0021 "
                    f"§Precedence has no default for. Falling through to "
                    f"origin_unresolved."
                )
        elif leaf_answer is not None and leaf_answer.held:
            # Lane 1's rule for this, verbatim: "Stop before parts
            # extraction. End the run SUCCESS. Post no `review` and no
            # `failed`." So this is a RETURN with a status, like
            # origin_unresolved — nothing raises, nothing posts, and the
            # parse artifacts the drop already has are what the dropper sees.
            # The row is waiting on a person to pick a kind, which is not a
            # failure of this run.
            context.log.info(
                f"AWAITING KIND for doc_id={doc_id!r}: Lane 1 answered "
                f"proceed=False stage={leaf_answer.stage!r} "
                f"({leaf_answer.detail!r}). No parts extraction, no domain "
                f"graph, no chunks, no triples, and NO further stage post — "
                f"a `review` or `failed` here would overwrite a row that is "
                f"correctly parked for the dropper's picker. Run ends "
                f"SUCCESS."
            )
            return {
                "doc_id": doc_id,
                "status": leaf_answer.stage or "awaiting_kind",
                "content_kind": kind_entry.kind,
                "node_label": node_label,
                "collection": collection_name,
                # The caller's seal on "post nothing further for this run".
                # `stop` is set only for Lane 1's 409/404, where the row has
                # moved on or never existed; `awaiting_kind` posts nothing
                # either way, so this is carried for the log and for the
                # wrapper, not as a second rule.
                "post_no_further_stages": True,
            }

    if kind_entry is not None and kind_entry.domain_type is None:
        # ------------------------------------------------------------------
        # ORIGIN UNRESOLVED — the terminal state for a FORMAT-LEVEL kind.
        #
        # ARCHITECT RULING 2026-10-02: *"engineering-document, doors-export,
        # pdf -> none (origin resolved by evidence, not kind)"*, and *"until
        # origin resolves, such a drop is visible to the dropper only and
        # lands in no domain graph; the stage is 'origin unresolved', not a
        # staging domain. No INGRESS domain class."*
        #
        # So this is a RETURN, not a raise and not a fallback:
        #
        #  - not a raise, because nothing is wrong. The kind resolved; what it
        #    says is that a PDF has no domain of its own. A halt here would
        #    read as a defect in the drop and would put every user drop back
        #    on the floor.
        #  - not a fallback to `declared_domain`, even when the manifest
        #    carries one. Under ruling 1 the kind is the authority over the
        #    manifest, and the manifest value on this path is derived from an
        #    S3 prefix or a Lane-1 sidecar that hardcodes null — neither is
        #    evidence of ORIGIN. Taking it would be choosing a vetted domain
        #    for unvetted content from the file format, which is the hazard
        #    the ruling names.
        #  - and nothing is written: no parent node (it needs a domain label
        #    for the MERGE), no chunks (the Weaviate collection is shared), no
        #    plugin (plugin selection IS by domain), no triples. The parse
        #    artifacts the upstream asset already wrote under the dropper's
        #    own prefix are the whole of what the dropper sees, which is what
        #    "visible to the dropper only" means here.
        #
        # This returns BEFORE any resource client is fetched, so the
        # short-circuit cannot write a byte by accident.
        # ------------------------------------------------------------------
        context.log.info(
            f"ORIGIN UNRESOLVED for doc_id={doc_id!r}: content kind "
            f"{kind_entry.kind!r} is a format-level kind and declares no "
            f"domain (architect ruling 2026-10-02 — origin is resolved by "
            f"evidence, not by kind). Writing nothing: no domain graph, no "
            f"Neo4j label, no chunks, no triples. The drop stays visible to "
            f"the dropper only. Resolving it needs the document-identity pass "
            f"(document number, revision, CAGE code, contract/program "
            f"identifiers) and the seam's match against a system of record — "
            f"neither of which is a domain this asset may pick. "
            f"declared_domain on the manifest was {declared_domain!r} and is "
            f"deliberately NOT used as a fallback."
        )
        return {
            "doc_id": doc_id,
            "status": "origin_unresolved",
            "content_kind": kind_entry.kind,
            "node_label": node_label,
            "collection": collection_name,
        }

    if kind_entry is not None:
        # THE RULING: the registered kind's declared domain is the authority.
        domain_type = kind_entry.domain_type
        if declared_domain and declared_domain != domain_type:
            context.log.warning(
                f"Domain disagreement for doc_id={doc_id!r}: the manifest "
                f"declares {declared_domain!r} but registered content kind "
                f"{kind_entry.kind!r} declares {kind_entry.domain_type!r}. "
                f"The KIND WINS (architect ruling 2026-10-02) — the manifest's "
                f"value is derived from an S3 path or a sidecar, the kind's is "
                f"a registered row with a target_ontology_class behind it. "
                f"Correct the upstream manifest/path if this is unexpected."
            )
    elif declared_domain:
        domain_type = declared_domain
    else:
        raise DomainTypeNotResolvableError(
            f"doc_id={doc_id!r} resolves to no domain: no KIND_MAPPING row "
            f"matches (metadata.content_kind={metadata.get('content_kind')!r}, "
            f"s3_key={s3_key!r}) and the manifest declares no domain_type. "
            f"Per the 2026-10-02 ruling the domain comes from the registered "
            f"content kind's declared domain and never from a run tag, so "
            f"there is no third source to fall back to — and the 'Training' "
            f"default that used to sit here would write this document into "
            f"the TRAINING domain's graph on no evidence at all. Either add a "
            f"KIND_MAPPING row for this content kind (reserved to the "
            f"architect, doc_tools/utils/content_kind.py) or make the "
            f"upstream manifest declare its domain_type."
        )

    domain_label = domain_type.upper().replace(" ", "_").replace("-", "_")

    # ----------------------------------------------------------------------
    # ADR-0041 — a manifest carrying "provenance" means this content is NOT
    # vetted (e.g. it arrived via the ingress-user sensor). It is stamped on
    # the way in for EVERY domain; the stamp rides the parent-document MERGE
    # below, which is the one Cypher write that runs whatever the domain and
    # whatever the plugin. There is no longer a set of domains to be in.
    # ----------------------------------------------------------------------
    provenance = manifest.get("provenance")
    if provenance:
        context.log.info(
            f"ADR-0041: doc_id={doc_id!r} carries a provenance block "
            f"(obtained_via={provenance.get('obtained_via')!r}, "
            f"standing={provenance.get('standing')!r}); it will be stamped "
            f"onto the {domain_label} document node."
        )

    s3_client = s3.get_client()
    neo4j_client = neo4j.get_client()
    weaviate_client = weaviate.get_client()
    llm_client = llm.get_client()
    jena_client = jena.get_client()
    
    # 2. Load Text Data
    import tempfile
    text_elements = []
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            s3_client.download_file(Bucket=config.bucket, Key=text_location, Filename=tmp.name)
            with open(tmp.name, 'r', encoding='utf-8') as f:
                text_elements = json.load(f)
    except Exception as e:
        context.log.warning(f"Could not load text data from Minio: {e}. Using mock elements.")
        text_elements = [{"type": "Text", "text": "Mock extracted text", "metadata": {"page_number": 1}}]
            
    # --- PASS 1: CREATE NODES ---
    
    # Create Parent Node
    #
    # THE PROVENANCE INVARIANT LIVES HERE (architect ruling 2026-10-02). This
    # MERGE is the only Cypher write in the pipeline that runs for every
    # domain and every plugin, which is what lets "provenance persists for
    # every domain" be one implementation instead of five. Property names come
    # from doc_tools/utils/provenance_stamp.py so this site and
    # SustainmentPlugin's own notice-node stamp cannot drift apart.
    #
    # Note the ERROR POLICY SPLIT below: this write stays best-effort for a
    # vetted document (as it always was) and becomes load-bearing for a
    # provenance-bearing one. Logging a failed stamp and continuing would put
    # unvetted content in the graph wearing no mark, which is precisely what
    # the deleted DOMAINS_THAT_PERSIST_PROVENANCE check existed to prevent.
    try:
        title = manifest.get("filename", doc_id)
        set_clause = "SET n.title = $title"
        parent_params = {"id": doc_id, "title": title}
        if provenance:
            set_clause += ", " + provenance_set_fragment("n")
            parent_params.update(provenance_params(provenance))
        neo4j_client.execute_query(
            f"MERGE (n:{node_label}:{domain_label} {{id: $id}}) {set_clause}",
            parent_params
        )
        if provenance:
            context.log.info(
                f"ADR-0041 stamp written onto ({node_label}:{domain_label} "
                f"{{id: {doc_id!r}}}): {len(PROVENANCE_FIELDS)} provenance_* "
                f"properties."
            )
    except Exception as e:
        if provenance:
            raise ProvenanceStampFailedError(
                f"The parent-document MERGE for doc_id={doc_id!r} carried the "
                f"ADR-0041 provenance stamp and FAILED ({e}). Halting the "
                f"ingest rather than continuing: every write after this one "
                f"would land unvetted content in the {domain_label} graph with "
                f"nothing on it to say so, which is the harm the stamp exists "
                f"to prevent. A vetted document would only have logged here."
            ) from e
        context.log.error(f"Parent Node creation failed: {e}")

    # Process Pages/Chunks (Content Extraction)
    from collections import defaultdict
    from doc_tools.utils.layout_detector import detect_layout
    
    pages = defaultdict(list)
    page_elements = defaultdict(list)
    
    for el in text_elements:
        p_metadata = el.get("metadata", {})
        text = el.get("text", "")
        type_ = el.get("type", "Text")
        formatted_text = f"[{type_}] {text}"
        page_num = p_metadata.get("page_number", 1)
        pages[page_num].append(formatted_text)
        page_elements[page_num].append(el)
            
    # Initialize appropriate Plugin
    if domain_type == "manufacturing":
        # ADR-0021 Phase 2/3: target_ontology_class flows from the
        # resolved kind_entry → manufacturing plugin → Cypher MERGE.
        # When no resolver ran (won't happen for manufacturing per the
        # halt above), the plugin's self-consistent default kicks in.
        plugin = ManufacturingPlugin(
            domain_type,
            target_ontology_class=(
                kind_entry.target_ontology_class if kind_entry else None
            ),
        )
    elif domain_type == "maintenance":
        from doc_tools.plugins.maintenance import MaintenancePlugin
        plugin = MaintenancePlugin(domain_type)
    elif domain_type == "compliance":
        try:
            from doc_tools.plugins.compliance import CompliancePlugin
            plugin = CompliancePlugin(domain_type)
        except ImportError:
            context.log.warning("CompliancePlugin not found, falling back to TrainingPlugin")
            plugin = TrainingPlugin(domain_type)
    elif domain_type == "sustainment":
        plugin = SustainmentPlugin(domain_type)
    else:
        plugin = TrainingPlugin(domain_type)
        
    context.log.info(f"Initialized {type(plugin).__name__} for domain: {domain_type}")

    # Ensure Weaviate Collection (v4 API)
    try:
        _ensure_weaviate_collection(weaviate_client, collection_name)
    except Exception as e:
        context.log.error(f"Weaviate Class creation failed: {e}")

    # Reconstruct full text for Global Plugin Pass
    full_text_parts = []
    current_page = -1
    for el in text_elements:
        text = el.get("text", "")
        if not text: continue
        page_num = el.get("metadata", {}).get("page_number")
        if page_num is not None and page_num != current_page:
            full_text_parts.append(f"\n--- Page {page_num} ---\n")
            current_page = page_num
        full_text_parts.append(f"[{el.get('type', 'Text')}] {text}")
    full_text = "\n".join(full_text_parts)

    document_nodes = []
    try:
        context.log.info(f"Executing global full-text pass for {type(plugin).__name__}...")
        # Sustainment's two-pass extractor also needs the manifest (embedded_images
        # map, filename -> S3 URL of each cropped table image), an S3 client to
        # fetch those crops for the vision parts pass, and the bucket. Other
        # plugins ignore these; pass them only for sustainment so no other
        # plugin signature changes.
        _extra = {}
        if domain_type == "sustainment":
            _extra = {"manifest": manifest, "s3_client": s3_client, "bucket": config.bucket}
        global_nodes = plugin.process_fulltext(full_text, doc_id, metadata, elements=text_elements, **_extra)
        if global_nodes:
            document_nodes.extend(global_nodes)
    except Exception as e:
        context.log.error(f"Global plugin extraction failed: {e}")

    # Tally _index_chunk verdicts across both the page-chunk loop and the
    # embedded-image figure loop below, so we can log a single reconciled
    # count of written / degraded / skipped-to-avoid-a-strip / erroring
    # chunk writes for this document.
    chunk_index_tally: collections.Counter = collections.Counter()

    # Process each page/chunk
    for page_num, texts in pages.items():
        chunk_text = "\n".join(texts)
        if not chunk_text.strip(): continue
            
        chunk_id = f"{doc_id}_p{page_num}"
        elements = page_elements.get(page_num, [])
        layout_style = detect_layout(elements)
        
        filename = manifest.get("filename", "")
        file_ext = os.path.splitext(filename)[1].upper().replace('.', '') if filename else "Unknown"
        
        # 1. Instantiate Base Section
        section = BaseSection(title=f"Page {page_num}", level=1, page_start=page_num, content=chunk_text, node_id=chunk_id)
        
        # 2. Augment via Domain Plugin
        try:
            node = plugin.augment(section, config)
            document_nodes.append(node)
        except Exception as e:
            context.log.error(f"Plugin augmentation failed for chunk {chunk_id}: {e}")

        # Neo4j baseline chunk creation
        try:
            neo4j_client.execute_query(
                f"""
                MATCH (parent:{node_label}:{domain_label} {{id: $parent_id}})
                MERGE (child:{child_label}:{domain_label} {{id: $id}})
                SET child.number = $page_num, child.text = $text, child.asset_type = $asset_type,
                    child.layout_style = $layout_style, child.elements = $elements_json
                MERGE (parent)-[:HAS_CHILD]->(child)
                """,
                {"parent_id": doc_id, "id": chunk_id, "page_num": page_num, "text": chunk_text[:500], "asset_type": file_ext, "layout_style": layout_style, "elements_json": json.dumps(elements)}
            )
        except Exception as e:
            context.log.error(f"Neo4j baseline chunk creation failed: {e}")

        # Vector Indexing (Per Chunk, v4 API)
        try:
            verdict = _index_chunk(weaviate_client, collection_name, {
                "text": chunk_text, "doc_id": doc_id, "chunk_id": chunk_id, "domain": domain_label,
            })
            chunk_index_tally[verdict] += 1
        except Exception as e:
            context.log.error(f"Vector indexing failed for chunk {chunk_id}: {e}")
            chunk_index_tally["errors"] += 1

    # ────────────────────────────────────────────────────────────────
    # Per-figure chunks for embedded images (closes the PDF-side
    # figure-in-answer gap surfaced 2026-06-30 alongside the XML
    # graphics manifest work). `process_document_artifact` extracts
    # images via `unstructured` and uploads them to S3, returning the
    # mapping in `manifest["embedded_images"]: {filename: s3_url}`.
    # Previously this map was recorded but never referenced by the
    # chunk writer — so the LLM never saw image references and Engine
    # W's answers were text-only even when the source PDF had
    # diagrams.
    #
    # Each embedded image gets its own DocumentChunk whose text is
    # markdown image syntax. When Engine W's hybrid search returns
    # one of these chunks, the synthesizer typically preserves the
    # markdown verbatim and the cortex-ui's SemanticInterpreter routes
    # the <img src="s3://..."> through FederatedImage for inline
    # display.
    #
    # Per [[failure-mode-pluralism-in-fixes]] sibling of the IADS
    # manifest work — same shape (record-and-don't-reference), same
    # fix (close the loop at the chunk-write layer).
    # ────────────────────────────────────────────────────────────────
    embedded_images = manifest.get("embedded_images") or {}
    if embedded_images:
        for img_filename, img_s3_url in embedded_images.items():
            if not img_s3_url:
                continue
            # Caption from filename (strip extension, replace separators
            # with spaces). e.g. "figure-page2-1.png" -> "figure page2 1".
            stem = os.path.splitext(img_filename)[0]
            caption = stem.replace("-", " ").replace("_", " ").strip() or img_filename
            figure_chunk_id = f"{doc_id}_fig_{stem}"
            figure_text = f"Figure {caption}:\n\n![{caption}]({img_s3_url})"
            try:
                verdict = _index_chunk(weaviate_client, collection_name, {
                    "text": figure_text,
                    "doc_id": doc_id,
                    "chunk_id": figure_chunk_id,
                    "domain": domain_label,
                })
                chunk_index_tally[verdict] += 1
            except Exception as e:
                context.log.error(
                    f"Figure chunk indexing failed for {figure_chunk_id}: {e}"
                )
                chunk_index_tally["errors"] += 1
        context.log.info(
            f"Indexed {len(embedded_images)} embedded-image figure chunks "
            f"for doc {doc_id}."
        )

    context.log.info(
        "Chunk vector indexing for doc %s: written=%d written_without_vector=%d "
        "skipped_would_strip_vector=%d errors=%d" % (
            doc_id,
            chunk_index_tally.get("written", 0),
            chunk_index_tally.get("written_without_vector", 0),
            chunk_index_tally.get("skipped_would_strip_vector", 0),
            chunk_index_tally.get("errors", 0),
        )
    )

    # Aggregated RATES for this document — see doc_tools/utils/ingest_rates.py. This is
    # the ONE call site where written_without_vector is actually OBSERVED: chunk_index_tally
    # above comes straight from real _index_chunk writes, unlike the corpus harness
    # (scripts/pcn_corpus_run.py), which drives the plugin directly and never writes a
    # chunk, so it always passes chunk_tally=None there. This asset runs one document per
    # partition, so the record list is a single record — the block reads "1 of 1", not a
    # run-level aggregate; a nightly job wanting a fleet-wide rate reduces over many of
    # these review.json/log lines itself. `stats` comes from the augmentation's own
    # `stats` field, which is SUSTAINMENT-ONLY today — so a manufacturing, maintenance,
    # training or compliance document arrives here with stats=None having extracted
    # perfectly. It is reported as `not applicable`, NOT as an error: this block exists so
    # a rising rate is the production signal, and a permanent "1 error" on every
    # non-sustainment ingest is precisely the reading that teaches people to stop watching
    # the number. That is why `ok=True` is passed explicitly — summarize_rates treats
    # failure as something the caller DECLARES, never as an inference from a missing field.
    doc_stats = None
    doc_needs_review = False
    for n in document_nodes:
        aug = n.domain_augmentation
        s = getattr(aug, "stats", None)
        if s:
            doc_stats = dict(s)
        if getattr(aug, "needs_review", False):
            doc_needs_review = True
    rate_record = {"ok": True, "needs_review": doc_needs_review, "stats": doc_stats}
    chunk_tally = {
        "written": chunk_index_tally.get("written", 0),
        "written_without_vector": chunk_index_tally.get("written_without_vector", 0),
    }
    rates_summary = summarize_rates([rate_record], chunk_tally=chunk_tally)
    context.log.info(f"Ingest rates for doc {doc_id}:\n{render_rates(rates_summary)}")

    # Derive image_prefix from text_location
    # e.g. text_location: "manufacturing/IID/generated/test_pdf/text.json"
    # base_dir: "manufacturing/IID/generated/test_pdf"
    base_dir = os.path.dirname(text_location)
    image_prefix = f"s3://{config.bucket}/{base_dir}/images/"

    # Persist the structured LLM extraction to S3 (next to text.json) so it can be
    # retrieved/audited/reprocessed — the graph sink below only writes Neo4j + Jena.
    try:
        payload = _extraction_payload(document_nodes, doc_id, domain_type)
        extraction_key = f"{base_dir}/extraction.json"
        s3_client.put_object(
            Bucket=config.bucket,
            Key=extraction_key,
            Body=json.dumps(payload, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        context.log.info(
            f"Wrote extraction to s3://{config.bucket}/{extraction_key} "
            f"({len(payload['augmentations'])} augmentation(s))"
        )
    except Exception as e:
        context.log.error(f"Failed to write extraction.json: {e}")

    review_payload = None  # stays None when no review.json is written (below)
    # Phase 5: persist the human-review payload (provenance + needs_review) to
    # review.json so the review UI has its data contract. Only sustainment
    # augmentations carry a `review` block; other domains have none and skip
    # this. needs_review is surfaced as a WARNING in Dagit (a formal asset_check
    # on the needs_review count is a follow-up).
    try:
        review_nodes = [n for n in document_nodes if getattr(n.domain_augmentation, "review", None)]
        if review_nodes:
            aug0 = review_nodes[0].domain_augmentation
            needs_review = any(getattr(n.domain_augmentation, "needs_review", False)
                               for n in review_nodes)
            review_payload = dict(aug0.review)
            review_payload["needs_review"] = needs_review
            review_payload["review_reasons"] = list(getattr(aug0, "review_reasons", []) or [])
            review_payload["stats"] = dict(getattr(aug0, "stats", {}) or {})
            review_key = f"{base_dir}/review.json"
            s3_client.put_object(
                Bucket=config.bucket, Key=review_key,
                Body=json.dumps(review_payload, indent=2, default=str).encode("utf-8"),
                ContentType="application/json",
            )
            n_flag = sum(1 for it in review_payload.get("review_items", []) if it.get("needs_review"))
            msg = (f"Wrote review payload to s3://{config.bucket}/{review_key} "
                   f"(needs_review={needs_review}, {n_flag} flagged item(s))")
            if needs_review:
                context.log.warning(f"REVIEW REQUIRED for {doc_id}: {msg} — "
                                    f"reasons: {review_payload['review_reasons'][:5]}")
            else:
                context.log.info(msg)
    except Exception as e:
        context.log.error(f"Failed to write review.json: {e}")

    # Phase 5b: the ingest stage POST (`review`, or `failed:extraction_empty`).
    # It lives HERE, not in document_parser.py, because the row count Lane 1
    # serves comes from review.json, which only exists at this point. Posting
    # `review` from the parser filed a `document_promotion` task on zero-row
    # extractions (measured on sha256:fa231498... and sha256:0096a523..., both
    # PCN23-002, extracted_count=2 / extracted_total=1, 0 part rows -- one
    # because the header pass raised BamlValidationError, one because no Table
    # element was detected), so a seal on `extracted_count == 0` catches
    # neither. No ingest_id means no Lane 1 row to address: the vetted
    # sustainment/inbound/ path has no ingest_id and stays unposted.
    if manifest.get("ingest_id"):
        ingest_id = manifest["ingest_id"]
        try:
            # Not a Dagster resource: instantiated inline, exactly as the
            # parser does.
            from doc_tools.utils.dagster_resources import IngestStatusResource

            rows = _part_row_count(review_payload)
            # Only a plugin whose augmentation declares a `review` block has a
            # row contract. Manufacturing / S1000D-via-PDF drops have none;
            # sealing them on a row count they never produce would fail every
            # such drop. Domain-generic on purpose -- not a "sustainment" test.
            rows_are_review_unit = any(
                hasattr(n.domain_augmentation, "review")
                for n in document_nodes if n.domain_augmentation is not None
            )
            _count = manifest.get("element_count")
            _total = len(manifest.get("pages") or []) or None
            _ref = manifest.get("manifest_key")
            status = IngestStatusResource()
            if rows_are_review_unit and rows == 0:
                first = (review_payload or {}).get("review_reasons") or []
                reason = "extraction produced zero part rows"
                if first:
                    reason += f"; first review reason: {first[0]}"
                context.log.info(
                    f"ingest stage for {doc_id}: failed:extraction_empty "
                    f"(part rows={rows}, review-contract document)")
                # `detail` IS NOT OPTIONAL ON A `failed` POST, and omitting it
                # did not degrade the post -- it cancelled it. The guard in
                # IngestStatusResource.update refuses `failed` with a blank
                # detail (Lane 1's own rule at ingest_status.update_status),
                # the `except` below logged the ValueError, and the run went
                # on to report SUCCESS. Measured at work by Lane 1 on MAR053
                # (packet 2026-10-22): every document that sealed
                # `extraction_empty` sat at `extracting` with no review task,
                # because this POST never happened. `reason` is the detail --
                # one string, so the two fields cannot drift apart.
                status.update(
                    ingest_id, "failed", reason_code="extraction_empty",
                    reason=reason, detail=reason, extracted_count=_count,
                    extracted_total=_total, extraction_ref=_ref,
                )
                # Recorded only on a SUCCESSFUL POST: the wrapper reads it to
                # decide whether a later failure may still stamp `failed`.
                if posted is not None:
                    posted["stage"] = "failed"
            else:
                context.log.info(
                    f"ingest stage for {doc_id}: review "
                    f"(part rows={rows}, rows_are_review_unit={rows_are_review_unit})")
                status.update(
                    ingest_id, "review", extracted_count=_count,
                    extracted_total=_total, extraction_ref=_ref,
                )
                if posted is not None:
                    posted["stage"] = "review"
        except Exception as e:  # a stage write must never fail an extraction
            context.log.error(f"Failed to post ingest stage for {doc_id}: {e}")

    # 3. Graph Sink: Convert Augmented Nodes to Cypher/SPARQL
    #
    # ADR-0041, AND THE ONE RESIDUAL OF THE INVARIANT, NAMED.
    #
    # The Neo4j stamp is universal as of 2026-10-02 — it rides the parent
    # MERGE above, for every domain. This thread is about the RDF side, which
    # is not: SustainmentPlugin is still the only to_graph_queries() that
    # emits the PROV-term triples (PROV_DERIVED_FROM / PROV_GENERATED_AT into
    # <http://internal/{DOMAIN}_INSTANCES>), and triples are emitted per
    # plugin because there is no generic RDF write to hang them on the way
    # there is a generic Cypher one. The other four signatures do not accept
    # the kwarg, so it is passed conditionally — same _extra-dict pattern
    # already used for process_fulltext above.
    #
    # Net position after this change: a provenance-bearing document in ANY
    # domain is distinguishable from vetted content in Neo4j, and only a
    # sustainment one is distinguishable in Jena. Widening the other four
    # plugins is the remaining work; it is a residual of the invariant, not a
    # contradiction of it, and it is written down here rather than left for a
    # reader to discover from a missing triple.
    _graph_extra = {}
    if domain_type == "sustainment":
        _graph_extra = {"provenance": provenance}
    context.log.info(f"Generating domain graph queries from {len(document_nodes)} augmented nodes...")
    cypher_queries, sparql_queries = plugin.to_graph_queries(
        document_nodes, config, doc_id=doc_id, image_prefix=image_prefix, **_graph_extra
    )
    
    for idx, c_query in enumerate(cypher_queries):
        try:
            neo4j_client.execute_query(c_query["query"], c_query.get("params", {}))
        except Exception as e:
            context.log.error(f"Failed executing domain cypher query {idx}: {e}")
            
    if sparql_queries:
        context.log.info(f"SPARQL Queries to emit to Jena: {len(sparql_queries)}")
        for idx, s_query in enumerate(sparql_queries):
            try:
                # Runtime instance triples go to the domain's INSTANCE graph, never the
                # vocabulary graph (AGENTS.md "Domain Semantic Graph") — prime DROPs the
                # latter on every re-ingest, so instance data would be wiped if it shared it.
                jena_client.execute_update(
                    s_query, graph_uri=f"http://internal/{plugin.domain_label}_INSTANCES"
                )
            except Exception as e:
                context.log.error(f"Failed executing domain SPARQL query {idx}: {e}")

    # --- PASS 2: LINK & ROLL-UP ---
    try:
        context.log.info(f"Executing Pass 2 Roll-up for {type(plugin).__name__}...")
        plugin.execute_pass2_rollup(neo4j_client, doc_id, config)
    except Exception as e:
        context.log.error(f"Pass 2 Roll-up failed: {e}")

    try:
        neo4j_client.close()
    except Exception:
        pass
    # The Weaviate v4 client holds gRPC/HTTP connections that must be closed
    # explicitly, or it leaks (ResourceWarning Con004) across runs.
    try:
        weaviate_client.close()
    except Exception:
        pass

    return {"doc_id": doc_id, "status": "processed", "node_label": node_label, "collection": collection_name}


def make_build_knowledge_graph(
    name: str = "build_knowledge_graph",
    partitions_def=pdf_files_partition,
    upstream_asset: str = "process_document_artifact",
):
    """Factory for the knowledge-graph-build asset so one BODY
    (_build_knowledge_graph_impl) can serve two separate manifest-producing
    upstreams that must stay on structurally different partition sets.

    Why a factory and not a plain hardcoded @asset: build_knowledge_graph's
    `partitions_def` used to be hardcoded to pdf_files_partition, and Dagster
    resolves a manifest input strictly by the asset's PARAMETER NAME
    (`process_document_artifact`). The ADR-0041 ingress-user path produces
    its manifest from a different upstream asset
    (`process_user_document_artifact`) on a different partition set
    (user_pdf_files_partition — see doc_tools/partitions.py for why the two
    sets must never collapse into one). Selecting both the vetted and
    ingress-user jobs out of one Definitions object previously raised
    `DagsterInvalidDefinitionError: Selected assets must have the same
    partitions definitions` because the single build_knowledge_graph asset
    was pinned to pdf_files_partition and wired, by parameter name only, to
    process_document_artifact.

    The fix: parameterize `partitions_def` (the former hardcode becomes the
    default) and remap the upstream via
    `ins={"process_document_artifact": AssetIn(key=upstream_asset)}` — this
    is the load-bearing part, since it lets the python parameter name stay
    `process_document_artifact` (so _build_knowledge_graph_impl's signature
    never changes) while the actual upstream ASSET it reads from varies per
    instantiation.

    build_knowledge_graph = make_build_knowledge_graph() is the default
    instantiation, referenced by name ("build_knowledge_graph") from
    doc_tools/components/document_parser.py's process_job selection and
    imported/called directly by tests/test_ingress_user_stamp.py.
    build_user_knowledge_graph is the ADR-0041 ingress-user instantiation,
    registered in doc_tools/definitions.py and selected by
    user_document_parser's own process_job (see downstream_graph_asset on
    DocumentParserComponent).
    """

    @asset(
        name=name,
        partitions_def=partitions_def,
        ins={"process_document_artifact": AssetIn(key=upstream_asset)},
        automation_condition=AutomationCondition.on_missing() | AutomationCondition.any_deps_updated()
    )
    def _build_knowledge_graph_asset(
        context: AssetExecutionContext,
        config: IngestionConfig,
        process_document_artifact: Dict[str, Any],
        s3: S3Resource,
        neo4j: Neo4jResource,
        weaviate: WeaviateResource,
        llm: LLMExtractorResource,
        jena: JenaResource
    ):
        posted: dict = {}
        try:
            return _build_knowledge_graph_impl(
                context, config, process_document_artifact,
                s3=s3, neo4j=neo4j, weaviate=weaviate, llm=llm, jena=jena,
                posted=posted,
            )
        except Exception as e:
            if posted.get("stage") is not None:
                # A `failed` after a stage was posted is a backwards move on a
                # row a steward may already hold (Lane 1 409s it or overrides
                # it), and the extraction a steward reviews is complete by the
                # time the stage is posted -- the sinks that failed are
                # downstream of it. The asset still fails loudly in Dagster
                # (re-raised); only the stage overwrite is suppressed.
                context.log.warning(
                    f"Graph build failed after stage {posted['stage']!r} was "
                    f"already posted; not stamping failed: "
                    f"{type(e).__name__}: {e}")
                raise
            # Before the `review` POST moved into the impl, a graph-asset
            # failure left the row at `review` with a missing graph. Now it
            # would leave it at `extracting` until Lane 1's watchdog timed it
            # out, so the failure must be stamped from here. Re-raised: the
            # stamp must never swallow the failure.
            _iid = process_document_artifact.get("ingest_id")
            if _iid:
                try:
                    from doc_tools.utils.dagster_resources import IngestStatusResource
                    # Same defect as the `extraction_empty` post above, and
                    # NOT in Lane 1's packet -- found by the seal, which went
                    # red on both. A `failed` post with no `detail` is
                    # refused, so this stamp has never landed either: the
                    # graph-asset failure it exists to record left the row at
                    # `extracting` exactly as before it was written.
                    _stamp = f"{type(e).__name__}: {e}"[:500]
                    IngestStatusResource().update(
                        _iid, "failed", reason_code="extraction_failed",
                        reason=_stamp, detail=_stamp,
                    )
                except Exception as stamp_err:
                    context.log.error(f"Failed to stamp failed stage: {stamp_err}")
            raise

    return _build_knowledge_graph_asset


# Default (vetted) instantiation — see make_build_knowledge_graph's docstring.
# Kept as a module-level name: document_parser.py's process_job selects it
# by this string, and tests/test_ingress_user_stamp.py imports and calls it
# directly.
build_knowledge_graph = make_build_knowledge_graph()

# ADR-0041 ingress-user instantiation — same body, fed by
# process_user_document_artifact on user_pdf_files_partition. Registered in
# doc_tools/definitions.py's Definitions asset list and selected by
# user_document_parser's own process_job via downstream_graph_asset.
build_user_knowledge_graph = make_build_knowledge_graph(
    name="build_user_knowledge_graph",
    partitions_def=user_pdf_files_partition,
    upstream_asset="process_user_document_artifact",
)


@asset(partitions_def=xml_files_partition)
def upload_to_jena(context: AssetExecutionContext, extract_rdf_from_xml: dict, jena: JenaResource) -> dict:
    """
    Uploads the generic RDF Turtle string to a specific Named Graph in Apache Jena.
    Uses PUT to ensure idempotency (overwrites previous revisions of this file).
    """
    jena_url = f"{jena.url.rstrip('/')}/{jena.dataset}/data"
    user = jena.username
    pw = jena.password
    
    s3_key = extract_rdf_from_xml["s3_key"]
    # Construct Named Graph URI from S3 key
    graph_uri = urllib.parse.quote(f"urn:doc:{s3_key}")
    target_url = f"{jena_url}?graph={graph_uri}"
    
    context.log.info(f"Uploading RDF for {s3_key} to Jena Named Graph: {graph_uri}")
    
    data = extract_rdf_from_xml["rdf_string"].encode('utf-8')
        
    try:
        with httpx.Client(auth=(user, pw), verify=False) as client:
            # Using PUT to completely overwrite the Named Graph for this document
            response = client.put(
                target_url,
                content=data,
                headers={"Content-Type": "text/turtle; charset=utf-8"}
            )
            response.raise_for_status()
    except Exception as e:
        context.log.error(f"Failed to upload to Jena: {e}")
        raise e

    # SECOND WRITE: the module's content triples into the DOMAIN instance graph
    # (architect ruling 2026-10-16), mirroring the PCN path
    # (semantic_assets.py:787-791 over plugins/sustainment.py:2003-2053).
    #  - The graph is http://internal/<DOMAIN>_INSTANCES and NEVER the bare
    #    http://internal/<DOMAIN> vocabulary graph: the peer prime DROPs that one
    #    first on every re-ingest (AGENTS.md:118-140), which already collided once
    #    in production.
    #  - DMC-KEYED SUPERSEDE, not a bare additive insert (architect ruling 2 of
    #    2026-10-17). Once a module can be re-dropped with NEW bytes,
    #    "idempotent" has to mean "the graph holds the CURRENT state of this
    #    module", not the weaker "re-running the same bytes adds nothing" this
    #    comment used to claim. Measured why the bare INSERT was wrong: the ten
    #    MRAD drops are six distinct modules, four of them dropped twice, and
    #    two of those pairs DISAGREE on content (720A at 19 triples vs 14, 520A
    #    at 14 vs 9). Under a pure INSERT the graph accumulates both versions
    #    and no reader can tell which is current; and a re-drop with FEWER
    #    steps leaves step-/proclist- subjects orphaned for ever.
    #  - Still never PUT: the graph is shared by every module of the domain, so
    #    a whole-graph replace would clobber the siblings. The DELETE is scoped
    #    to this one module's subjects.
    #  - DELETE and INSERT go in ONE request, separated by ';'. A SPARQL Update
    #    request is applied in a single Fuseki transaction, so the supersede is
    #    atomic. Issued as two calls, a DELETE that commits followed by an
    #    INSERT that fails would leave the module with NO triples at all --
    #    strictly worse than the duplication being fixed.
    #  - Scope of the DELETE, measured BEFORE it was written
    #    (scratchpad/dmc_supersede_predicate.py; 6 MRAD modules, 36 subjects):
    #      * every subject is either root_uri or contains "-<slug>-": 0 of 36
    #        uncovered, across 9 shapes (dmc- plus the 8 scoped prefixes
    #        part-/tool-/fig-/faultcode-/interval-/item-/step-/proclist-);
    #      * BOTH legs are required. root_uri's local name is
    #        "dmc-ODMRAD-...-040A-A" while the slug is "DMC-ODMRAD-...-040A" --
    #        different case, no leading "DMC-", trailing "-A" -- so the module's
    #        own subject does NOT match the slug test;
    #      * 0 shared subjects and 0 shared triples between modules, so the
    #        blast radius on a sibling is 0. This is the opposite of the PCN
    #        side, where component IRIs ARE shared across notices and
    #        delete-by-subject is destructive;
    #      * no dmRef TARGET is ever a subject (s1000d_rdf.py:243 mints
    #        dmc-<target> in OBJECT position only), so this deletes nothing
    #        another module owns.
    #    The slug is hyphen-delimited in the filter so it cannot match a longer
    #    slug by bare substring; 0 collisions among the six, and a well-formed
    #    DMC does not extend another DMC. tests/ pins that count at 0.
    #  - No doc_slug means the parser does not scope its subjects per document
    #    at all (iads/dita/40051). Those stay ADDITIVE and warn: deleting by
    #    their unscoped subjects would take a SIBLING document's triples, which
    #    is the destructive case above. Currently unreachable -- only
    #    s1000d-data-module is routed -- but it must not silently arm if one of
    #    them is wired up.
    #  - A missing domain is a defect in extract_rdf_from_xml and RAISES: a
    #    tolerated skip is a path nobody fixes. The urn:doc: PUT above is
    #    idempotent, so the retry is safe.
    #  - Failure here RAISES (it is the point of the pin, not a trailing
    #    secondary output like chunk extraction).
    domain = extract_rdf_from_xml.get("domain")
    if not domain:
        context.log.error(
            f"extract_rdf_from_xml for {s3_key} returned no 'domain'; the producing "
            f"asset is the defect. Refusing to skip the instance-graph write."
        )
        raise ValueError(
            f"extract_rdf_from_xml output for {s3_key!r} carries no 'domain'; "
            f"cannot choose the http://internal/<DOMAIN>_INSTANCES graph."
        )
    instance_graph = f"http://internal/{domain}_INSTANCES"
    # Imported here, not at module scope: rdflib is used nowhere else in this
    # module and the Dagster code location imports it at definition load time.
    from rdflib import Graph as _RdfGraph
    g = _RdfGraph()
    g.parse(data=extract_rdf_from_xml["rdf_string"], format="turtle")
    # nt gives absolute IRIs (no prefixes needed inside INSERT DATA); its line
    # order is not stable, hence the sort.
    nt_lines = sorted(
        ln for ln in g.serialize(format="nt").splitlines() if ln.strip()
    )
    insert_op = (
        f"INSERT DATA {{ GRAPH <{instance_graph}> {{\n"
        + "\n".join(nt_lines)
        + "\n} }"
    )

    doc_slug = extract_rdf_from_xml.get("doc_slug")
    root_uri = extract_rdf_from_xml.get("root_uri")
    if doc_slug and root_uri:
        # root_uri is spliced inside <...> and doc_slug inside a "..." literal.
        # Both come from our own builder, but a malformed one would produce a
        # body that deletes MORE than this module. Refuse rather than send it:
        # an over-broad DELETE against a shared graph is not recoverable.
        bad_uri = set('<>"{}|^`\\') & set(str(root_uri))
        if bad_uri or any(c.isspace() for c in str(root_uri)):
            raise ValueError(
                f"root_uri {root_uri!r} for {s3_key!r} is not safe to splice "
                f"into a SPARQL IRI (offending characters: {sorted(bad_uri)}); "
                f"refusing to send a DELETE whose scope cannot be trusted."
            )
        if set('"\\\n\r') & set(str(doc_slug)):
            raise ValueError(
                f"doc_slug {doc_slug!r} for {s3_key!r} is not safe to splice "
                f"into a SPARQL string literal; refusing to send a DELETE "
                f"whose scope cannot be trusted. _fragment() should have "
                f"replaced these -- the parser is the defect."
            )
        # Hyphen-delimited on both sides: "-<slug>-" matches every scoped
        # subject (part-<slug>-X ... proclist-<slug>-N-M) and cannot match a
        # bare substring of a longer slug.
        delete_op = (
            f"DELETE {{ GRAPH <{instance_graph}> {{ ?s ?p ?o }} }}\n"
            f"WHERE {{ GRAPH <{instance_graph}> {{ ?s ?p ?o }}\n"
            f"  FILTER( ?s = <{root_uri}> "
            f"|| CONTAINS(STR(?s), \"-{doc_slug}-\") ) }}"
        )
        body = delete_op + " ;\n" + insert_op
        superseding = True
    else:
        # See the no-doc_slug bullet above. Additive, and LOUD about it.
        context.log.warning(
            f"{s3_key}: no doc_slug from the parser (root_uri={root_uri!r}), so "
            f"the instance-graph write into {instance_graph} is ADDITIVE, not "
            f"superseding. A re-drop with new bytes will accumulate both "
            f"versions. This parser does not scope its subjects per document, "
            f"so a delete-by-subject would take a sibling document's triples."
        )
        body = insert_op
        superseding = False
    try:
        jena.get_client().execute_update(body, graph_uri=instance_graph)
    except Exception as e:
        # Name the GRAPH in the log. A bare propagation reads as "Jena failed"
        # and sends the next reader back to the urn:doc: PUT above, which by
        # this point has already succeeded.
        context.log.error(
            f"Failed the instance-graph "
            f"{'supersede' if superseding else 'additive write'} for {s3_key} "
            f"into {instance_graph} ({len(g)} triples): {e}"
        )
        raise
    context.log.info(
        f"{'Superseded' if superseding else 'Inserted (additive)'} "
        f"{len(g)} triples for {s3_key} into instance graph {instance_graph}"
        + (f" keyed on {root_uri} / -{doc_slug}-" if superseding else "")
    )
    return extract_rdf_from_xml # Pass metadata downstream

@asset(deps=[upload_to_jena], partitions_def=xml_files_partition)
def init_neo4j_n10s(context: AssetExecutionContext, neo4j: Neo4jResource) -> MaterializeResult:
    """
    Idempotently initializes Neosemantics (n10s) config in Neo4j.
    """
    uri = neo4j.uri
    user = neo4j.username
    pw = neo4j.password
    
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    
    with driver.session() as session:
        # Idempotency via PRECONDITION CHECK rather than exception
        # match. n10s.graphconfig.init rejects ANY re-init once the
        # graph has been populated, and the neo4j-python driver wraps
        # the Bolt failure into a ClientError whose `str()` doesn't
        # include the "non-empty" substring the underlying message has
        # — the structured `{message: ...}` format hides it from
        # `str(e).lower() match` patterns. Two prior attempts to
        # catch by string ("already exists", then broadened to
        # "non-empty"/"config cannot be changed") both missed. Precondition
        # check sidesteps the string-format issue entirely: if any
        # :Resource node exists, n10s has been initialized by a prior
        # run; skip init.
        existing = session.run(
            "MATCH (r:Resource) RETURN count(r) AS c"
        ).single()
        resource_count = existing["c"] if existing else 0

        if resource_count > 0:
            context.log.info(
                f"n10s: found {resource_count} existing :Resource node(s); "
                f"graph already initialized — skipping n10s.graphconfig.init "
                f"(idempotent per-partition no-op)."
            )
        else:
            session.run(
                "CALL n10s.graphconfig.init({handleVocabUris: 'IGNORE'})"
            )
            context.log.info("Initialized n10s graph config (graph was empty).")

        session.run("CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS FOR (r:Resource) REQUIRE r.uri IS UNIQUE")
        
    driver.close()
    return MaterializeResult(metadata={"n10s_status": "ready"})

@asset(deps=[init_neo4j_n10s], partitions_def=xml_files_partition)
def sync_jena_to_neo4j(context: AssetExecutionContext, upload_to_jena: dict, jena: JenaResource, neo4j: Neo4jResource) -> MaterializeResult:
    """
    Deletes the previous revision in Neo4j (deep wipe) and fetches the fresh isolated graph from Jena.
    """
    neo4j_client = neo4j.get_client()
    jena_client = jena.get_client()
    
    root_uri = upload_to_jena["root_uri"]
    s3_key = upload_to_jena["s3_key"]
    
    # Construct Named Graph URI from S3 key
    graph_uri = f"urn:doc:{s3_key}"
    
    # 1. Fetch ALL subject URIs from this document's Named Graph in Jena
    # This allows us to perform a clean 'deep delete' in Neo4j
    context.log.info(f"Fetching subjects from Jena Named Graph: {graph_uri}")
    subjects_query = f"""
    SELECT DISTINCT ?s WHERE {{
      GRAPH <{graph_uri}> {{
        ?s ?p ?o
      }}
    }}
    """
    # Per [[silent-degrade-composition]]: this step previously caught
    # the SPARQL-query exception and fell back to [root_uri], leaving
    # the deep-wipe with a one-element list. Combined with the
    # /ds/query 404 bug above, that meant any previous revision's
    # triples for the doc stayed in Neo4j across re-ingests AND the
    # step still reported SUCCESS. The fix: let the exception bubble.
    # If Jena can't be queried, the wipe step can't do its job — the
    # ingest must fail honestly so operators see the broken state
    # instead of an accumulating-prior-revisions silent regression.
    jena_results = jena_client.execute_query(subjects_query)
    uri_list = [row["s"]["value"] for row in jena_results["results"]["bindings"]]
    context.log.info(f"Found {len(uri_list)} unique URIs to wipe from Neo4j.")
    if not uri_list:
        # Empty result is suspicious — upload_to_jena should have
        # written the document's triples to this named graph before
        # this step runs. Zero subjects means either the upload
        # didn't land OR Jena dropped the data. Either is a real
        # failure mode, not benign.
        raise RuntimeError(
            f"sync_jena_to_neo4j: 0 subjects found in named graph "
            f"<{graph_uri}>. upload_to_jena should have populated this "
            f"graph; the empty result indicates the upload didn't land "
            f"or the graph was dropped. Refusing to proceed silently."
        )
        
    # 2. Deep Wipe in Neo4j
    if uri_list:
        context.log.info(f"Wiping {len(uri_list)} Nodes from Neo4j (Deep Detach/Delete)...")
        try:
            # We don't need the domain label for deletion because the URI is unique across the DB
            neo4j_client.execute_query(
                "UNWIND $uri_list AS deleted_uri MATCH (n {uri: deleted_uri}) DETACH DELETE n",
                {"uri_list": uri_list}
            )
        except Exception as e:
            context.log.error(f"Deep wipe failed: {e}")

    # 3. Trigger Neo4j n10s fetch for ONLY this document
    # Scoped CONSTRUCT ensures we only pull the current revision's graph
    context.log.info(f"Triggering Neo4j n10s fetch from Jena Named Graph for: {s3_key}")

    # n10s fetch requires a URL that returns RDF. We point it back to our Jena query endpoint.
    sparql_construct = f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"

    # Construct the fetch URL. Fuseki's default SPARQL Query service is
    # `/sparql`, NOT `/query` (the same bug captured at the top of
    # ontology_assets.py for the previously-deleted n10s-fetch path —
    # this xml pipeline preserved the buggy URL, and the silent-fallback
    # in the wipe-step + n10s's silent-zero-on-fetch-error masked it
    # for months). Caught 2026-06-29 with helmet ingest debug logging.
    jena_base = jena.url.rstrip('/')
    jena_ds = jena.dataset
    encoded_query = urllib.parse.quote(sparql_construct)
    fetch_url = f"{jena_base}/{jena_ds}/sparql?query={encoded_query}"

    # n10s.rdf.import.fetch returns a summary record with triplesLoaded.
    # If the URL 404s, n10s's silent-zero failure mode used to mask the
    # problem. We now RAISE on triplesLoaded=0 because for an XML WP
    # that has any content at all, a zero count signals the same
    # endpoint-404 or named-graph-not-found we just spent hours
    # debugging. Per [[verification-must-fail]] and
    # [[silent-degrade-composition]]: the step that wires Jena→Neo4j
    # MUST be able to report failure honestly.
    result = neo4j_client.execute_query(
        "CALL n10s.rdf.import.fetch($url, 'Turtle', { headerParams: { Accept: 'application/x-turtle' } }) "
        "YIELD triplesLoaded, terminationStatus, extraInfo "
        "RETURN triplesLoaded, terminationStatus, extraInfo",
        {"url": fetch_url}
    )
    # Neo4jClient returns list[Record]; pull the first row.
    rows = list(result) if not isinstance(result, list) else result
    if not rows:
        raise RuntimeError(
            f"n10s.rdf.import.fetch returned no rows for graph {graph_uri} "
            f"(fetch_url={fetch_url}). This indicates the procedure didn't "
            f"execute — check n10s plugin availability."
        )
    first = rows[0]
    triples_imported = first.get("triplesLoaded", 0) if hasattr(first, "get") else first[0]
    termination_status = first.get("terminationStatus") if hasattr(first, "get") else first[1]
    extra_info = first.get("extraInfo") if hasattr(first, "get") else first[2]
    context.log.info(
        f"n10s.rdf.import.fetch: triplesLoaded={triples_imported}, "
        f"terminationStatus={termination_status}, extraInfo={extra_info!r}"
    )
    if termination_status and termination_status.upper() != "OK":
        raise RuntimeError(
            f"n10s.rdf.import.fetch failed for graph {graph_uri}: "
            f"terminationStatus={termination_status!r}, extraInfo={extra_info!r}, "
            f"fetch_url={fetch_url}"
        )

    # 4. Post-Sync: Apply MAINTENANCE domain label to all imported nodes
    # XML tech manuals (S1000D, IADS, DITA, 40051) are maintenance/MRO content
    _apply_post_sync_domain_labels(neo4j_client, uri_list, "MAINTENANCE", context)

        
    return MaterializeResult(
        metadata={
            "triples_to_sync": len(uri_list),
            "root_uri": root_uri,
            "s3_key": s3_key,
            "jena_named_graph": graph_uri
        }
    )


def _apply_post_sync_domain_labels(neo4j_client, uri_list, domain_label: str, context):
    """
    After n10s imports RDF nodes as :Resource nodes, apply the domain segregation
    label so downstream agents can filter by domain in Cypher.
    """
    if not uri_list:
        return
    
    context.log.info(f"Applying :{domain_label} label to {len(uri_list)} imported Resource nodes...")
    try:
        neo4j_client.execute_query(
            f"UNWIND $uri_list AS u MATCH (n:Resource {{uri: u}}) SET n:{domain_label}",
            {"uri_list": uri_list}
        )
        context.log.info(f"Successfully applied :{domain_label} to all synced nodes.")
    except Exception as e:
        context.log.error(f"Failed to apply domain labels: {e}")
