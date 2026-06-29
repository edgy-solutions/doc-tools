"""Chunk extraction from a parsed XML→RDF graph for Weaviate ingest.

Closes the architectural gap surfaced in the 2026-06-29 corpus-ingest
investigation: the existing ``xml_graph_sync_job`` pipeline writes
structural RDF to Jena and Neo4j but NEVER touches Weaviate's
``DocumentChunk`` collection. Engine W queries DocumentChunk for
hybrid search; with no XML→chunk path, every routed-specialist query
returned 0 sources even after the routing fix shipped.

The pattern this closes is `[[failure-mode-pluralism-in-fixes]]`:
fixing the resolver funnel (routing_domain + PROV contamination)
EXPOSED a previously-masked ingest gap. The fallback was hiding
the empty corpus; now that routing reaches Engine W, the corpus
gap is the surfaced last-mile.

The chunker walks the parser's rdflib Graph for text Literals
attached to the document root, emitting one chunk per searchable
unit (title, instruction step, warning, generic body). The shape
matches the live ``DocumentChunk`` schema:

  - text     : str   — chunk body (what BM25 + vector retrieves)
  - doc_id   : str   — the document URI (root_uri here; Engine W's
                       source projection uses this as the label)
  - domain   : str   — scope segregation (MAINTENANCE for XML
                       military pubs, mirroring
                       _apply_post_sync_domain_labels in
                       semantic_assets)
  - section  : str   — where in the document this chunk came from
                       ("title" | "step:N" | "warning:N" |
                       "prop:<predicate_local>")

Engine W's source projection (agent_fleet/weaviate_expert/service.py
:_collect_weaviate_source) reads these fields and falls back to
``weaviate://chunk-uuid`` for the source URI when no ``source_url``
is present. That's acceptable for first delivery; a follow-up can
extend the schema with ``source_url`` once the chunk-write path
proves out.
"""
from __future__ import annotations

from typing import Iterable

import rdflib
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDFS

_MIL_NS = "http://edgy-solutions.com/ontology/mil#"
_MIL_INSTRUCTION = URIRef(_MIL_NS + "hasInstructionText")
_MIL_WARNING = URIRef(_MIL_NS + "hasWarning")

# Minimum chunk length for the "generic body" sweep. Filters out
# identifiers, codes, and other short Literals that hurt BM25 signal
# more than they help (a one-word "INSPECT" Literal would compete
# with full procedural text for the same query).
_GENERIC_BODY_MIN_CHARS = 20


def extract_chunks_from_graph(
    g: Graph,
    root_uri: str,
    domain: str,
) -> list[dict]:
    """Walk an RDF graph rooted at ``root_uri`` and yield chunk dicts.

    Each chunk dict matches the Weaviate ``DocumentChunk`` live schema
    (text, doc_id, domain, section). Caller passes the result list
    directly to ``_index_chunk`` from doc_tools/assets/semantic_assets
    (which handles the per-row embed + insert).

    Args:
        g: The parser's RDF graph (e.g. ``builder.graph`` after
           ``parse_data_module()``). Stays in-memory per the
           "Zero disk I/O" rule.
        root_uri: The document root URI returned by
           ``parse_data_module()``. Used as the ``doc_id`` on every
           chunk so Engine W's per-doc filters work AND so the
           source-projection's fallback URI is meaningful.
        domain: Scope label (typically "MAINTENANCE" for XML military
           pubs, mirroring ``_apply_post_sync_domain_labels``).

    Returns:
        List of chunk dicts ready for batch-insert. Empty list when
        the graph has no extractable text — caller MUST handle empty
        (a parser that emitted only structural triples is a
        substrate signal, not an error).
    """
    if not root_uri:
        return []
    root = URIRef(root_uri)
    chunks: list[dict] = []
    seen_predicates: set[URIRef] = set()

    # 1. Title chunk — the document's primary label.
    label_obj = next(
        (o for _, _, o in g.triples((root, RDFS.label, None))),
        None,
    )
    if isinstance(label_obj, Literal):
        text = str(label_obj).strip()
        if text:
            chunks.append({
                "text": text,
                "doc_id": root_uri,
                "section": "title",
                "domain": domain,
            })
    seen_predicates.add(RDFS.label)

    # 2. Instruction steps — typed mil:hasInstructionText.
    #    One chunk per Literal so each step is independently
    #    retrievable. Index in order of graph emission (the parser's
    #    XPath walk preserves XML order); section labels make the
    #    ordering visible.
    for idx, txt in enumerate(_literals_of(g, root, _MIL_INSTRUCTION)):
        text = str(txt).strip()
        if text:
            chunks.append({
                "text": text,
                "doc_id": root_uri,
                "section": f"step:{idx + 1}",
                "domain": domain,
            })
    seen_predicates.add(_MIL_INSTRUCTION)

    # 3. Warnings — typed mil:hasWarning. Same per-Literal pattern.
    for idx, txt in enumerate(_literals_of(g, root, _MIL_WARNING)):
        text = str(txt).strip()
        if text:
            chunks.append({
                "text": text,
                "doc_id": root_uri,
                "section": f"warning:{idx + 1}",
                "domain": domain,
            })
    seen_predicates.add(_MIL_WARNING)

    # 4. Generic-body fallback — any other text Literal directly
    #    attached to the root. Catches parsers that don't use the
    #    mil:* predicates (a future S1000D builder may use s1000d:*
    #    instead). The min-chars threshold filters identifiers /
    #    short codes that would hurt retrieval signal.
    for predicate, obj in g.predicate_objects(root):
        if predicate in seen_predicates:
            continue
        if not isinstance(obj, Literal):
            continue
        text = str(obj).strip()
        if len(text) < _GENERIC_BODY_MIN_CHARS:
            continue
        pred_local = _local_name(predicate)
        chunks.append({
            "text": text,
            "doc_id": root_uri,
            "section": f"prop:{pred_local}",
            "domain": domain,
        })

    return chunks


def _literals_of(g: Graph, subj: URIRef, pred: URIRef) -> Iterable[Literal]:
    """Yield the object Literals of (subj, pred, *) triples, preserving
    insertion order (rdflib's iteration is deterministic by default for
    in-memory graphs)."""
    for _, _, obj in g.triples((subj, pred, None)):
        if isinstance(obj, Literal):
            yield obj


def _local_name(uri: URIRef) -> str:
    """Return the local part of a URI for a stable section label.
    Falls back to the full URI when there's no fragment/path separator."""
    s = str(uri)
    if "#" in s:
        return s.rsplit("#", 1)[-1]
    if "/" in s:
        return s.rsplit("/", 1)[-1]
    return s
