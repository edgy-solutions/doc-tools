"""Deterministic MIL-STD-40051 work-package ingest.

The sibling of s1000d_ingest.py for the 40051 (US Army TM) format track.
Per the architect's 2026-06-13 40051-track assignment:

  > "Structure as three layers so EAGLE later swaps only the first:
  > iads_extract (unpack the .iads container — tool-specific) →
  > read_40051_wp (parse WP XML — format-general) →
  > classify_40051 (root-tag → mil: kind — format-general)."

This module is the read_40051_wp + substrate-write layer (the
format-general half — same code regardless of WHICH 40051 container
delivered the XML). The IADS container parser is the separate
iads_extract module; an EAGLE adapter would be a different
iads_extract sibling and feed into this same reader.

Architectural invariants encoded here (mirrors s1000d_ingest's):

  - **G1**: this module NEVER writes :OntologyClass nodes or touches the
    resolver candidate pool. Kind constants are MATCHed, never MERGEd.
    A missing kind class raises loudly — the canonical pipeline must
    materialize mil:* nodes via sync_jena_ontologies_to_neo4j before
    ingest can run.

  - **G2**: every successfully-ingested wpno gets exactly one
    INSTANCE_OF edge to a declared mil:* kind. Fallthrough is
    mil:DataModule (the root), NEVER a missing edge. The
    mil_40051_classifier.FALLTHROUGH_COUNT counter logs each
    fallthrough hit so the morning TBox decision stays visible.

  - **G3**: classification is deterministic — same wpno → same kind on
    every run. The MERGE by wpno URI is idempotent at the substrate
    layer (same as DMC for S1000D).

  - **Boundary**: the helmet TM is the DEMO-watermark public fixture
    (TM 1-1680-TNG-13P, IADS 4.0 Demo Dataset). It lives in
    tests/fixtures/iads_40051_demo/, never in a deploy manifest. The
    DEMO marker is the negative-boundary signal for 40051, analog of
    SANDBOXRTX for S1000D.

The function `process_40051_work_package` is the entry point. The
top-level container processor `process_iads_archive` lives in
iads_extract (the tool-specific layer) and calls this for each WP it
unpacks.
"""

from __future__ import annotations

from typing import Iterable, Optional
from lxml import etree

from doc_tools.parsers.mil_40051_classifier import (
    classify_40051_work_package,
    is_wp_root,
    NON_WP_ROOT_TAGS,
)
from doc_tools.parsers.mil_info_code_map import (
    DATA_MODULE_ROOT,
    MIL_NS,
)
from doc_tools.parsers.dmc_canonicalizer import (
    canonicalize_wpno,
    assemble_canonical_wpno,
)


# -----------------------------------------------------------------------------
# Pure-parse layer — extract the deterministic facts from 40051 WP XML.
# No I/O, no MERGEs. Easy to test in isolation.
# -----------------------------------------------------------------------------

class WP40051Facts:
    """The deterministic facts a single 40051 work package contributes."""

    __slots__ = (
        "wpno",            # canonical (lowercase) wpno string
        "root_tag",        # the XML root element name (the classifier key)
        "maintlvl",        # maintainer level attribute from <maintlvl>
        "title",           # <wpidinfo><title> text
        "tools",           # list[(name_or_id, target_wpno_canonical)]
        "xrefs",           # list[target_wpno_canonical] — inter-WP refs
        "kind_iri",        # canonical full-IRI mil:* class
    )

    def __init__(self) -> None:
        self.wpno: str = ""
        self.root_tag: str = ""
        self.maintlvl: str = ""
        self.title: str = ""
        self.tools: list[tuple[str, str]] = []
        self.xrefs: list[str] = []
        self.kind_iri: str = DATA_MODULE_ROOT


def read_40051_wp(xml_bytes: bytes) -> Optional[WP40051Facts]:
    """Pull the structured facts from a 40051 WP XML document.

    Pure function (parser → facts), no I/O, no substrate touch.

    Returns None if the root element is NOT a recognized WP type (e.g.,
    the XML is a TOC, front cover, or other front-matter that lives in
    an IADS package but isn't ABox-ingestable). This is "honest skip"
    — the IADS container has lots of non-WP entries; the format reader
    should not try to ingest them.

    Raises if the root IS a WP but the wpno attribute is missing or
    un-canonicalizable (a corrupt WP, not a non-WP). Same idea as
    s1000d_ingest's "missing DMC = raise" — without a deterministic
    identity, MERGE can't be idempotent (G3 violation in waiting).
    """
    parser = etree.XMLParser(remove_blank_text=True, recover=True, resolve_entities=False)
    root = etree.fromstring(xml_bytes, parser)

    # 40051 uses no XML namespace — the DTD declares element names
    # unprefixed. Take the local-name verbatim.
    root_tag = etree.QName(root.tag).localname if root.tag else ""

    # Skip non-WP front-matter (toc, frntcover, titleblk, etc.)
    if root_tag in NON_WP_ROOT_TAGS:
        return None

    # If we got something that isn't in the classifier's map AND isn't
    # explicitly listed as a non-WP, raise. Better to fail loud than
    # silently absorb an unknown root.
    if not is_wp_root(root_tag):
        raise ValueError(
            f"Unknown 40051 root element {root_tag!r}. Add it to "
            f"NON_WP_ROOT_TAGS (skip cleanly) or WP_ROOT_TO_KIND "
            f"(ingest with a kind assignment) in mil_40051_classifier."
        )

    facts = WP40051Facts()
    facts.root_tag = root_tag

    # ----- wpno (the instance identifier) -----
    raw_wpno = root.get("wpno", "")
    canonical = canonicalize_wpno(raw_wpno)
    if not canonical:
        raise ValueError(
            f"40051 WP {root_tag!r} is missing or has an un-canonicalizable "
            f"wpno attribute: {raw_wpno!r}. The wpno is the WP's identity; "
            f"without it MERGE cannot be idempotent (G3)."
        )
    facts.wpno = canonical

    # ----- maintlvl + title (from wpidinfo) -----
    wpidinfo = root.find("./wpidinfo")
    if wpidinfo is not None:
        ml = wpidinfo.find("./maintlvl")
        if ml is not None:
            facts.maintlvl = ml.get("level", "").strip()
        ti = wpidinfo.find("./title")
        if ti is not None and ti.text:
            facts.title = ti.text.strip()

    # ----- Classification (deterministic, no LLM) -----
    facts.kind_iri = classify_40051_work_package(root_tag)

    # ----- Tools (initial_setup/tools/tools-setup-item) -----
    # The architect's framing: "<initial_setup><tools><tools-setup-item>
    # as mil:requiresTool edges". Each tool item may contain an
    # <itemref><xref wpid=.../></itemref> pointing at a TOOL WP (sNNNN-*).
    # We emit (name, target_wpno) and let the substrate-write layer
    # MERGE the tool node as a DataModule (it IS its own WP).
    for tsi in root.xpath(".//initial_setup/tools/tools-setup-item"):
        name_el = tsi.find("./name")
        name = name_el.text.strip() if name_el is not None and name_el.text else ""
        target_wpno = ""
        for xref in tsi.xpath(".//xref[@wpid]"):
            cw = canonicalize_wpno(xref.get("wpid", ""))
            if cw:
                target_wpno = cw
                break
        if target_wpno:
            facts.tools.append((name or target_wpno, target_wpno))

    # ----- Inter-WP cross-references (xrefs with wpid OUTSIDE tools) -----
    # All <xref wpid="..."> that aren't inside an initial_setup/tools
    # block. These are the document-graph edges — what the architect
    # called "inter-document edges."
    for xref in root.xpath(".//xref[@wpid]"):
        # skip those already counted as tools
        anc_tools = xref.xpath("ancestor::initial_setup")
        if anc_tools:
            continue
        cw = canonicalize_wpno(xref.get("wpid", ""))
        if cw and cw != facts.wpno:
            facts.xrefs.append(cw)

    # Dedup xrefs while preserving order (rdflib-style determinism)
    seen = set()
    facts.xrefs = [x for x in facts.xrefs if not (x in seen or seen.add(x))]

    return facts


# -----------------------------------------------------------------------------
# Substrate-write layer — MERGE the WP instance + edges into Neo4j.
# Mirrors s1000d_ingest.merge_data_module_instance — same G1 contract,
# same Cypher shape, same idempotent MERGE on the canonical identity.
# -----------------------------------------------------------------------------

INSTANCE_NAMESPACE_WPNO = "urn:wpno:"   # mints WP instance URIs


def wpno_to_instance_uri(wpno_canonical: str) -> str:
    """Deterministic instance URI from a canonical wpno. Used by MERGE for
    idempotency (G3)."""
    return INSTANCE_NAMESPACE_WPNO + wpno_canonical


def merge_40051_wp_instance(
    *,
    neo4j_client,
    facts: WP40051Facts,
    source_path: str,
) -> dict:
    """MERGE the WP instance + its INSTANCE_OF + tool/xref edges.

    G1: MATCHes the kind OntologyClass; raises if missing.
    G2: writes INSTANCE_OF unconditionally to facts.kind_iri.
    G3: MERGE by URI is idempotent; re-ingest produces the same shape.

    Tool WPs and cross-referenced WPs are MERGEd as :DataModule nodes
    with their canonical wpno URI. They get a placeholder INSTANCE_OF
    edge to the root mil:DataModule class (since we may not know their
    actual type without seeing their XML — the cross-link is enough
    for ABox connectivity; the right kind lands when THAT WP is
    ingested directly via this same path, MERGE updates the same
    node).
    """
    instance_uri = wpno_to_instance_uri(facts.wpno)

    # Step 1: MATCH the kind class FIRST. G1 contract.
    kind_present = neo4j_client.execute_query(
        "MATCH (c:OntologyClass {uri: $uri}) RETURN c.uri AS uri LIMIT 1",
        {"uri": facts.kind_iri},
    )
    if not kind_present.records:
        raise Exception(
            f"G1 contract violation prevented: kind class {facts.kind_iri!r} "
            f"does not exist in Neo4j. The canonical pipeline must materialize "
            f"this class via sync_jena_ontologies_to_neo4j (from "
            f"mil_extension.ttl) BEFORE format ingest can MERGE instances "
            f"against it. Do NOT change this code to MERGE the missing class — "
            f"the architectural rule is that format ingest writes ABox only."
        )

    # Step 2: MERGE the WP instance + INSTANCE_OF in one transaction.
    cypher = """
    MERGE (wp:DataModule {uri: $instance_uri})
    SET wp.wpno = $wpno,
        wp.root_tag = $root_tag,
        wp.maintlvl = $maintlvl,
        wp.title = $title,
        wp.format = '40051',
        wp.last_ingested_at = datetime(),
        wp.source_path = $source_path
    WITH wp
    MATCH (kind:OntologyClass {uri: $kind_iri})
    MERGE (wp)-[:INSTANCE_OF]->(kind)
    RETURN wp.uri AS instance_uri, kind.uri AS kind_uri
    """
    neo4j_client.execute_query(
        cypher,
        {
            "instance_uri": instance_uri,
            "wpno": facts.wpno,
            "root_tag": facts.root_tag,
            "maintlvl": facts.maintlvl,
            "title": facts.title,
            "kind_iri": facts.kind_iri,
            "source_path": source_path,
        },
    )

    # Step 3: Tool WPs (REQUIRES_TOOL).
    # The tool target IS a WP (its own wpno). We MERGE it as a
    # DataModule placeholder — NO INSTANCE_OF on placeholders. The
    # real INSTANCE_OF edge lands when the tool's own XML gets
    # ingested directly via this same path (MERGE-by-URI hits the
    # same node and adds the edge then). Writing a placeholder
    # INSTANCE_OF→ROOT would race with the real ingest's
    # INSTANCE_OF→ProcedureDataModule (etc.) and produce a duplicate
    # — the failure mode observed when t0003's xref-to-m0004
    # appended a second INSTANCE_OF edge to the already-ingested
    # m0004 node. A placeholder is explicitly an orphan; the
    # `placeholder=true` property marks it so callers know the
    # state.
    tool_uris: list[str] = []
    for name, tool_wpno in facts.tools:
        tool_uri = wpno_to_instance_uri(tool_wpno)
        neo4j_client.execute_query(
            """
            MERGE (t:DataModule {uri: $tool_uri})
            ON CREATE SET t.wpno = $tool_wpno,
                          t.title = $name,
                          t.format = '40051',
                          t.placeholder = true
            WITH t
            MATCH (wp:DataModule {uri: $instance_uri})
            MERGE (wp)-[:REQUIRES_TOOL]->(t)
            """,
            {
                "tool_uri": tool_uri,
                "tool_wpno": tool_wpno,
                "name": name,
                "instance_uri": instance_uri,
            },
        )
        tool_uris.append(tool_uri)

    # Step 4: Cross-references (REFERENCES). Same placeholder discipline
    # as tools — no INSTANCE_OF on placeholders.
    xref_uris: list[str] = []
    for target_wpno in facts.xrefs:
        target_uri = wpno_to_instance_uri(target_wpno)
        neo4j_client.execute_query(
            """
            MERGE (other:DataModule {uri: $target_uri})
            ON CREATE SET other.wpno = $target_wpno,
                          other.format = '40051',
                          other.placeholder = true
            WITH other
            MATCH (wp:DataModule {uri: $instance_uri})
            MERGE (wp)-[:REFERENCES]->(other)
            """,
            {
                "target_uri": target_uri,
                "target_wpno": target_wpno,
                "instance_uri": instance_uri,
            },
        )
        xref_uris.append(target_uri)

    return {
        "instance_uri": instance_uri,
        "kind_iri": facts.kind_iri,
        "tools": tool_uris,
        "xrefs": xref_uris,
        "wpno": facts.wpno,
        "root_tag": facts.root_tag,
    }


# -----------------------------------------------------------------------------
# Top-level orchestrator — what iads_extract (or a direct caller) invokes.
# -----------------------------------------------------------------------------

def process_40051_work_package(
    *,
    neo4j_client,
    xml_bytes: bytes,
    source_path: str,
) -> Optional[dict]:
    """End-to-end: parse XML → classify → MERGE substrate.

    Returns None if the XML is non-WP front-matter (skip cleanly).
    Returns a result dict (the same shape s1000d's
    process_s1000d_data_module returns) for any successful WP.

    Deterministic + idempotent. Same XML re-ingested produces the same
    substrate (G3). No LLM. No content inspection beyond the
    structural extraction read_40051_wp performs.
    """
    facts = read_40051_wp(xml_bytes)
    if facts is None:
        return None
    return merge_40051_wp_instance(
        neo4j_client=neo4j_client,
        facts=facts,
        source_path=source_path,
    )


def process_40051_corpus(
    *,
    neo4j_client,
    xml_files: Iterable[tuple[str, bytes]],
) -> list[Optional[dict]]:
    """Convenience: ingest a sequence of (path, xml_bytes) pairs.

    Non-WP entries return None; the caller can filter. Useful for the
    helmet TM "ingest 8 WPs + 5 non-WP entries" test pattern.
    """
    return [
        process_40051_work_package(
            neo4j_client=neo4j_client, xml_bytes=xml, source_path=path,
        )
        for path, xml in xml_files
    ]
