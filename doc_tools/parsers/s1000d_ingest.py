"""B2 — deterministic S1000D data-module ingest.

Per the architect's B2 recipe and B0 §4: format ingestion reads metadata,
maps deterministically (via mil_info_code_map) to a content-kind class,
MERGEs the instance by DMC, writes INSTANCE_OF + mil:hasPart /
mil:requiresTool edges. **No LLM. No content inspection in the
classification path.** The classifier keys off the S1000D info code;
the body is irrelevant to the kind decision.

Architectural invariants encoded here:

  - **G1**: this module NEVER writes :OntologyClass nodes or touches the
    resolver candidate pool. Class names exist only as constants
    imported from mil_info_code_map; they are USED as TARGETS of
    INSTANCE_OF edges, never CREATED. The canonical pipeline owns
    OntologyClass creation; this code owns ABox only.

  - **G2**: every successfully-ingested DMC gets exactly one INSTANCE_OF
    edge to a declared mil:* kind class. The fallback for missing
    info codes is mil:DataModule (the root) — never a missing edge.

  - **G3**: classification is deterministic — same DMC → same
    INSTANCE_OF target on every run. The MERGE by DMC URI is
    idempotent at the substrate layer.

  - **Negative boundary**: the SANDBOXRTX marker, if present in the
    DMC's MIC, flows into the substrate as part of the DMC URI. The B2
    negative-boundary guard reads this and asserts it appears only
    in test graphs.

The function `process_s1000d_data_module` is the entry point. A dagster
asset wrapping it is straightforward (call it inside `ctx.run`); the
function-level seam is useful for direct testing against the
SANDBOXRTX corpus.
"""

from __future__ import annotations

from typing import Iterable
from lxml import etree

from doc_tools.parsers.mil_info_code_map import (
    classify_data_module,
    label_for_kind,
    DATA_MODULE_ROOT,
    MIL_NS,
)


# -----------------------------------------------------------------------------
# Pure-parse layer — extract the deterministic facts from S1000D XML.
# No I/O, no MERGEs. Easy to test in isolation.
# -----------------------------------------------------------------------------

class S1000dFacts:
    """The deterministic facts a single S1000D DM contributes."""

    __slots__ = (
        "dmc", "model_ident_code", "info_code", "system_code",
        "tech_name", "info_name",
        "tools",   # list[(part_number, name)]
        "spares",  # list[(part_number, name)]
        "kind_iri",
    )

    def __init__(self) -> None:
        self.dmc = ""
        self.model_ident_code = ""
        self.info_code = ""
        self.system_code = ""
        self.tech_name = ""
        self.info_name = ""
        self.tools: list[tuple[str, str]] = []
        self.spares: list[tuple[str, str]] = []
        self.kind_iri = DATA_MODULE_ROOT


def extract_facts(xml_bytes: bytes) -> S1000dFacts:
    """Pull the structured facts from an S1000D XML data module.

    Read-only against the XML; classifies via mil_info_code_map.
    Pure function (parser → facts), no I/O, no substrate touch.
    """
    parser = etree.XMLParser(remove_blank_text=True, recover=True)
    root = etree.fromstring(xml_bytes, parser)
    facts = S1000dFacts()

    # ----- DMC -----
    dm_code = root.find(".//dmCode")
    if dm_code is None:
        return facts

    facts.model_ident_code = dm_code.get("modelIdentCode", "")
    facts.info_code = dm_code.get("infoCode", "")
    facts.system_code = dm_code.get("systemCode", "")
    parts = [
        facts.model_ident_code,
        dm_code.get("systemDiffCode", ""),
        facts.system_code,
        dm_code.get("subSystemCode", ""),
        dm_code.get("subSubSystemCode", ""),
        dm_code.get("assyCode", ""),
        dm_code.get("disassyCode", "") or dm_code.get("disasCode", ""),
        dm_code.get("disassyCodeVariant", "") or dm_code.get("disasCodeVariant", ""),
        facts.info_code,
        dm_code.get("infoCodeVariant", ""),
        dm_code.get("itemLocationCode", ""),
    ]
    facts.dmc = "-".join(p for p in parts if p)

    # ----- Title -----
    tech = root.find(".//dmTitle/techName")
    if tech is not None and tech.text:
        facts.tech_name = tech.text.strip()
    info = root.find(".//dmTitle/infoName")
    if info is not None and info.text:
        facts.info_name = info.text.strip()

    # ----- Classification (deterministic, no LLM) -----
    facts.kind_iri = classify_data_module(facts.info_code)

    # ----- Tools (reqSupportEquips → supportEquipDescr) -----
    for descr in root.xpath(".//supportEquipDescr"):
        name_el = descr.find("./name")
        pn_el = descr.find(".//partAndSerialNumber/partNumber")
        pn = pn_el.text.strip() if pn_el is not None and pn_el.text else ""
        nm = name_el.text.strip() if name_el is not None and name_el.text else pn
        if pn:
            facts.tools.append((pn, nm))

    # ----- Spares (reqSpares → spareDescr) -----
    for descr in root.xpath(".//spareDescr"):
        name_el = descr.find("./name")
        pn_el = descr.find(".//partAndSerialNumber/partNumber")
        pn = pn_el.text.strip() if pn_el is not None and pn_el.text else ""
        nm = name_el.text.strip() if name_el is not None and name_el.text else pn
        if pn:
            facts.spares.append((pn, nm))

    return facts


# -----------------------------------------------------------------------------
# Substrate-write layer — MERGE the instance + edges into Neo4j.
# -----------------------------------------------------------------------------

INSTANCE_NAMESPACE = "urn:dmc:"  # used to mint instance URIs from the DMC


def dmc_to_instance_uri(dmc: str) -> str:
    """Deterministic instance URI from a DMC. Used by MERGE for idempotency."""
    return INSTANCE_NAMESPACE + dmc


def part_uri(part_number: str) -> str:
    """Deterministic instance URI for a Tool or Part by part number."""
    return f"urn:part:{part_number}"


def merge_data_module_instance(
    *,
    neo4j_client,
    facts: S1000dFacts,
    source_path: str,
) -> dict:
    """MERGE the DM instance + its INSTANCE_OF + tool/spare edges.

    G2: the INSTANCE_OF edge is written unconditionally (the fallback
    kind_iri is DATA_MODULE_ROOT when no info code, never None).

    G1: this function MUST NOT MERGE anything labeled :OntologyClass.
    It MATCHes the canonical kind nodes (which the canonical pipeline
    materialized) — never CREATEs them. A MERGE of a missing kind
    target would silently auto-create the OntologyClass; this code
    uses MATCH + raises if the target isn't there, surfacing the
    canonical-pipeline gap.

    Returns a dict with the merged URIs for the predict-then-verify
    discipline.
    """
    instance_uri = dmc_to_instance_uri(facts.dmc)
    label = label_for_kind(facts.kind_iri)  # :Procedure / :Figure / :IPD / :DataModule etc.

    # Step 1: MATCH the kind class FIRST. If it's missing, fail loudly.
    # This is the G1 contract — ABox ingest never auto-CREATES TBox.
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

    # Step 2: MERGE the DM instance + INSTANCE_OF in one transaction.
    # The label is determined by the kind (B0 §4 mapping). Cypher MERGE
    # with a dynamic label requires APOC.
    cypher = """
    MERGE (dm:DataModule {uri: $instance_uri})
    SET dm.dmc = $dmc,
        dm.modelIdentCode = $mic,
        dm.systemCode = $system_code,
        dm.infoCode = $info_code,
        dm.techName = $tech_name,
        dm.infoName = $info_name,
        dm.last_ingested_at = datetime(),
        dm.source_path = $source_path
    WITH dm
    MATCH (kind:OntologyClass {uri: $kind_iri})
    MERGE (dm)-[:INSTANCE_OF]->(kind)
    RETURN dm.uri AS instance_uri, kind.uri AS kind_uri
    """
    res = neo4j_client.execute_query(
        cypher,
        {
            "instance_uri": instance_uri,
            "dmc": facts.dmc,
            "mic": facts.model_ident_code,
            "system_code": facts.system_code,
            "info_code": facts.info_code,
            "tech_name": facts.tech_name,
            "info_name": facts.info_name,
            "kind_iri": facts.kind_iri,
            "source_path": source_path,
        },
    )

    # Step 3: For each tool/spare, MERGE the artifact + cross-link edge.
    # Same G1 contract — but Tool/Part are NOT :OntologyClass nodes;
    # they're instance-level (ABox) artifacts. The canonical mil:Tool /
    # mil:Part OntologyClass nodes exist (from mil_extension.ttl); we
    # MATCH them and MERGE the relationship.
    tool_uris: list[str] = []
    for pn, name in facts.tools:
        uri = part_uri(pn)
        neo4j_client.execute_query(
            """
            MERGE (t:Tool {uri: $uri})
            SET t.partNumber = $pn, t.name = $name
            WITH t
            MATCH (kind:OntologyClass {uri: $tool_kind_iri})
            MERGE (t)-[:INSTANCE_OF]->(kind)
            WITH t
            MATCH (dm:DataModule {uri: $instance_uri})
            MERGE (dm)-[:REQUIRES_TOOL]->(t)
            """,
            {
                "uri": uri,
                "pn": pn,
                "name": name,
                "tool_kind_iri": MIL_NS + "Tool",
                "instance_uri": instance_uri,
            },
        )
        tool_uris.append(uri)

    spare_uris: list[str] = []
    for pn, name in facts.spares:
        uri = part_uri(pn)
        neo4j_client.execute_query(
            """
            MERGE (p:Part {uri: $uri})
            SET p.partNumber = $pn, p.name = $name
            WITH p
            MATCH (kind:OntologyClass {uri: $part_kind_iri})
            MERGE (p)-[:INSTANCE_OF]->(kind)
            WITH p
            MATCH (dm:DataModule {uri: $instance_uri})
            MERGE (dm)-[:HAS_PART]->(p)
            """,
            {
                "uri": uri,
                "pn": pn,
                "name": name,
                "part_kind_iri": MIL_NS + "Part",
                "instance_uri": instance_uri,
            },
        )
        spare_uris.append(uri)

    return {
        "instance_uri": instance_uri,
        "kind_iri": facts.kind_iri,
        "tools": tool_uris,
        "spares": spare_uris,
    }


# -----------------------------------------------------------------------------
# Top-level orchestrator — what a dagster asset (or a direct caller) invokes.
# -----------------------------------------------------------------------------

def process_s1000d_data_module(
    *,
    neo4j_client,
    xml_bytes: bytes,
    source_path: str,
) -> dict:
    """End-to-end: parse XML → classify → MERGE substrate.

    Deterministic + idempotent. Same XML re-ingested produces the same
    result (G3). Pure metadata path — no body inspection.

    Args:
        neo4j_client: an object with `execute_query(cypher, params) -> Result`
            that exposes `.records` per the existing JenaResource /
            Neo4jResource shape in doc-tools.
        xml_bytes: the raw S1000D XML.
        source_path: a free-form provenance string (S3 key, local path,
            test-fixture name). Stored on the instance for audit.

    Returns:
        A dict with `instance_uri`, `kind_iri`, `tools`, `spares` —
        the predict-then-verify shape the B2 test asserts against.
    """
    facts = extract_facts(xml_bytes)
    if not facts.dmc:
        raise Exception(
            f"Could not extract a DMC from {source_path!r}. The XML "
            f"may be malformed or missing the <dmCode> element. Format "
            f"ingest cannot proceed without a deterministic DMC for the "
            f"MERGE identity (idempotency requirement / G3)."
        )
    return merge_data_module_instance(
        neo4j_client=neo4j_client,
        facts=facts,
        source_path=source_path,
    )


def process_corpus(
    *,
    neo4j_client,
    xml_files: Iterable[tuple[str, bytes]],
) -> list[dict]:
    """Convenience: ingest a sequence of (path, xml_bytes) pairs.

    Returns the per-file result dicts in input order. Useful for the
    B2 SANDBOXRTX fixture's "ingest 8 modules, assert against the
    coverage table" test pattern.
    """
    return [
        process_s1000d_data_module(
            neo4j_client=neo4j_client, xml_bytes=xml, source_path=path,
        )
        for path, xml in xml_files
    ]
