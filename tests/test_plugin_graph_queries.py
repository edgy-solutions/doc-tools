"""Unit tests for the LLM-free graph-emission of the domain plugins.

`to_graph_queries` turns extracted domain models into Cypher + SPARQL. It needs
no LLM, so we build the augmentation models directly and assert the emitted
nodes/relationships/params. Targets compliance.py and maintenance.py, which were
at 0% coverage (never executed).
"""
import re
import pytest
from types import SimpleNamespace

from doc_tools.plugins.compliance import (
    CompliancePlugin, ComplianceAugmentation, ComplianceRule,
)
from doc_tools.plugins.maintenance import (
    MaintenancePlugin, MroAugmentation, MaintenanceStep,
)
from doc_tools.plugins.training import (
    TrainingPlugin, SlideAugmentation, OutlineAugmentation, Concept, CourseSection,
)
from doc_tools.plugins.sustainment import (
    SustainmentPlugin, SustainmentAugmentation, SustainmentNotice, PartImpact,
)
from doc_tools.plugins.models import BaseSection, DocumentNode


def _blob(queries):
    return "\n".join(q["query"] for q in queries)


def _count(queries, substr):
    return sum(substr in q["query"] for q in queries)


# --------------------------------------------------------------------------- #
# Compliance
# --------------------------------------------------------------------------- #
def test_compliance_to_graph_queries():
    sec = BaseSection(title="Storage Limits", level=1, page_start=3, content="", node_id="sec-1")
    aug = ComplianceAugmentation(rules=[
        ComplianceRule(manual_reference="DAFMAN 91-201", rule_type="Safety",
                       applicable_hazard_class="1.1", target_metric="Max 5",
                       rule_description="Limit net explosive weight."),
        ComplianceRule(manual_reference="DAFI 21-101", rule_type="Process",
                       applicable_hazard_class=None, target_metric=None,
                       rule_description="Document inspections."),
    ])
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)
    config = SimpleNamespace(graph_child_label="Section")

    cypher, sparql = CompliancePlugin(domain_type="compliance").to_graph_queries([node], config)
    blob = _blob(cypher)

    assert "MERGE (p:Section:COMPLIANCE" in blob
    assert "ComplianceRule:COMPLIANCE" in blob
    assert "GOVERNED_BY" in blob
    # rule ids are sanitized (space/./- -> _) and indexed
    ids = [q["params"].get("rule_node_id") for q in cypher if "rule_node_id" in q["params"]]
    assert "rule_sec-1_DAFMAN_91_201_0" in ids
    assert "rule_sec-1_DAFI_21_101_1" in ids
    # only the first rule carries a hazard -> exactly one APPLIES_TO_HAZARD block
    assert _count(cypher, "APPLIES_TO_HAZARD") == 1

    sp = " ".join(sparql)
    assert "iof:ComplianceRule" in sp
    assert "hasManualReference" in sp and "DAFMAN 91-201" in sp
    assert sp.count("hasTargetMetric") == 1        # only rule 0
    assert sp.count("appliesToHazardClass") == 1   # only rule 0


def test_compliance_skips_non_compliance_augmentation():
    sec = BaseSection(title="x", level=0, page_start=0, content="", node_id="n")
    node = DocumentNode(base_extraction=sec, domain_augmentation=None)
    cypher, sparql = CompliancePlugin(domain_type="compliance").to_graph_queries(
        [node], SimpleNamespace(graph_child_label="Section"))
    assert cypher == [] and sparql == []


# --------------------------------------------------------------------------- #
# Maintenance (MRO)
# --------------------------------------------------------------------------- #
def test_maintenance_to_graph_queries():
    sec = BaseSection(title="Pump Overhaul", level=1, page_start=2, content="", node_id="mro-1")
    full = MaintenanceStep(
        procedure_id="0010", step_id="1", instruction_text="Torque the bolt.",
        action_verb="Torque", tooling=["Torque Wrench"], consumables=["Grease"],
        hazard_class="1.3C", required_cert="Depot Tech", standard_ref="TM-9-1005",
        inspection_type="Visual", maintenance_level="Depot", is_safety_critical=True,
        torque_spec="35 Nm", justification="Critical fastener.",
        estimated_duration_minutes=20, military_and_industry_standards=["MIL-PRF-23377"],
        internal_part_numbers=["PN-7"], figure_references=["5"],
    )
    minimal = MaintenanceStep(
        procedure_id="0010", step_id="2", instruction_text="Inspect seal.",
        action_verb="Inspect", tooling=[], consumables=[], is_safety_critical=False,
        justification="Routine.", figure_references=[],
    )
    node = DocumentNode(base_extraction=sec,
                        domain_augmentation=MroAugmentation(steps=[full, minimal]))
    config = SimpleNamespace(graph_child_label="Section")

    cypher, sparql = MaintenancePlugin(domain_type="maintenance").to_graph_queries(
        [node], config, image_prefix="img/")
    blob = _blob(cypher)

    assert "MaintenanceStep:MAINTENANCE" in blob
    assert "REQUIRES_PROCEDURE" in blob and "CONTAINS_STEP" in blob
    assert "GOVERNED_BY" in blob and "REQUIRES_PART" in blob and "REQUIRES_TOOL" in blob
    # full step has all three conditionals; minimal step has none
    assert _count(cypher, "HAS_HAZARD") == 1
    assert _count(cypher, "REQUIRES_CERT") == 1
    assert _count(cypher, "REFERENCES_FIGURE") == 1

    by_id = {q["params"]["step_node_id"]: q["params"]
             for q in cypher if "step_node_id" in q["params"]}
    assert "mstep_mro-1_1" in by_id and "mstep_mro-1_2" in by_id
    assert by_id["mstep_mro-1_1"]["is_safety_critical"] is True
    assert by_id["mstep_mro-1_1"]["torque_spec"] == "35 Nm"
    assert by_id["mstep_mro-1_1"]["maintenance_level"] == "Depot"
    assert by_id["mstep_mro-1_2"]["duration"] == -1  # None -> -1 default

    sp = " ".join(sparql)
    assert "mro:MaintenanceStep" in sp
    assert "mro:governedBy mro:TM91005_Standard" in sp   # standard_ref sanitized
    assert 'mro:usesTool "Torque Wrench"' in sp
    assert 'mro:consumesMaterial "Grease"' in sp
    assert "mro:referencesFigure mro:fig_5" in sp


# --------------------------------------------------------------------------- #
# Training (two branches: slide augmentation + course outline) — Neo4j only
# --------------------------------------------------------------------------- #
def test_training_slide_to_graph_queries():
    sec = BaseSection(title="Torque Basics", level=2, page_start=4, content="Body", node_id="slide-1")
    aug = SlideAugmentation(
        concepts=[Concept(name="Torque Control", salience=0.9)],
        objectives=["Understand torque"],
        figure_references=["2"],
    )
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)
    config = SimpleNamespace(graph_node_label="Course", graph_child_label="Slide")

    cypher, sparql = TrainingPlugin(domain_type="training").to_graph_queries(
        [node], config, image_prefix="img/")
    blob = _blob(cypher)

    assert "MERGE (s:Slide:TRAINING" in blob
    assert "Concept:TRAINING" in blob and "TEACHES" in blob
    assert "REFERENCES_FIGURE" in blob
    concept_q = [q for q in cypher if "concept_id" in q["params"]][0]
    # hash(domain, normalized name), not the old `concept_Torque_Control` slug: a slug
    # collides on the characters it drops and forks on the case it keeps.
    from doc_tools.utils.concept_identity import concept_node_id
    assert concept_q["params"]["concept_id"] == concept_node_id("TRAINING",
                                                                "Torque Control")
    assert concept_q["params"]["c_name_normalized"] == "torque control"
    assert concept_q["params"]["c_salience"] == 0.9
    # Training domain emits no RDF
    assert sparql == []


def test_training_outline_builds_nested_section_tree():
    sec = BaseSection(title="Course", level=0, page_start=0, content="", node_id="course-1")
    outline = OutlineAugmentation(
        sections=[CourseSection(title="Intro", level=1, start_page=1, end_page=3,
                                subsections=[CourseSection(title="Sub", level=2, start_page=1)])],
        metadata={"business_unit": "Avionics", "version": "v1"},
    )
    node = DocumentNode(base_extraction=sec, domain_augmentation=outline)
    config = SimpleNamespace(graph_node_label="Course", graph_child_label="Slide")

    cypher, _ = TrainingPlugin(domain_type="training").to_graph_queries([node], config)
    blob = _blob(cypher)

    # course metadata MATCH/SET
    assert "MATCH (c:Course:TRAINING" in blob and "business_unit" in blob
    meta_q = [q for q in cypher if q["params"].get("id") == "course-1"][0]
    assert meta_q["params"]["business_unit"] == "Avionics"
    # nested section ids: course-1_s0 and course-1_s0_s0
    ids = [q["params"].get("id") for q in cypher]
    assert "course-1_s0" in ids and "course-1_s0_s0" in ids
    assert "HAS_SECTION" in blob


# --------------------------------------------------------------------------- #
# Sustainment (PCN/PDN) — uses graph_node_label, Component/REPLACED_BY, PCN RDF
# --------------------------------------------------------------------------- #
def test_sustainment_to_graph_queries():
    sec = BaseSection(title="Sustainment Notice", level=0, page_start=0, content="", node_id="doc-1")
    notice = SustainmentNotice(
        doc_id="PDN-500", doc_type="PDN", pub_date="2026-04-28", mfr="Acme",
        categories=["Discontinuation", "LastTimeBuy"], summary="EOL notice.",
        impacted_parts=[
            PartImpact(affected_mpn="MPN-A", replacement_mpn="MPN-B", ltb_date="2026-12-31"),
            PartImpact(affected_mpn="MPN-C", replacement_mpn=None, ltb_date=None),
        ],
    )
    node = DocumentNode(base_extraction=sec,
                        domain_augmentation=SustainmentAugmentation(notice=notice))
    config = SimpleNamespace(graph_node_label="Document", graph_child_label="Section")

    cypher, sparql = SustainmentPlugin(domain_type="sustainment").to_graph_queries([node], config)
    blob = _blob(cypher)

    assert "MERGE (p:Document:SUSTAINMENT" in blob   # uses graph_node_label
    assert "SustainmentNotice:SUSTAINMENT" in blob and "GOVERNED_BY" in blob
    assert "Component:SUSTAINMENT" in blob and "REPLACED_BY" in blob
    edge_q = [q for q in cypher if "impacted_parts" in q["params"]][0]
    assert edge_q["params"]["notice_id"] == "PDN-500"
    assert len(edge_q["params"]["impacted_parts"]) == 2

    sp = " ".join(sparql)
    assert "pcn:ProductDiscontinuationNotice" in sp        # PDN -> discontinuation class
    assert "pcn:hasChangeCategory pcn:Discontinuation" in sp
    assert "pcn:hasChangeCategory pcn:LastTimeBuy" in sp
    assert "http://internal/components/MPN-A" in sp
    assert sp.count("pcn:hasReplacement") == 1            # only MPN-A has a replacement
    assert sp.count("pcn:hasLastTimeBuyDate") == 1        # only MPN-A has an LTB date


def test_a_null_ltb_date_is_not_merged_into_the_replaced_by_pattern():
    """A part with a replacement but NO LTB date must not put a null in a MERGE.

    Neo4j raises Neo.ClientError.Statement.SemanticError on a MERGE whose
    relationship pattern carries a null property, and that aborts the whole
    statement -- GOVERNED_BY and every SUBJECT_TO edge for the notice go with
    it. Measured 2026-10-24: 10 of 39 retained build_knowledge_graph runs died
    exactly here, all of them recorded SUCCESS because the write was swallowed.

    The case the older fixture never reached: it has (replacement=None,
    ltb=None), which the `replacement_mpn` guard skips, and (replacement,
    ltb) which is fine. It has no row with a replacement and a null date --
    the only shape that reaches the MERGE with a null.
    """
    sec = BaseSection(title="Sustainment Notice", level=0, page_start=0, content="", node_id="doc-9")
    notice = SustainmentNotice(
        doc_id="PCN-NULLTB", doc_type="PCN", pub_date="2026-05-01", mfr="Acme",
        categories=["Discontinuation"], summary="Replacement named, no LTB date.",
        impacted_parts=[
            PartImpact(affected_mpn="MPN-D", replacement_mpn="MPN-E", ltb_date=None),
        ],
    )
    node = DocumentNode(base_extraction=sec,
                        domain_augmentation=SustainmentAugmentation(notice=notice))
    config = SimpleNamespace(graph_node_label="Document", graph_child_label="Section")

    cypher, _ = SustainmentPlugin(domain_type="sustainment").to_graph_queries([node], config)
    edge_q = [q for q in cypher if "impacted_parts" in q["params"]][0]
    q = edge_q["query"]

    # The row that triggers it is present and carries a null date...
    assert edge_q["params"]["impacted_parts"] == [
        {"affected_mpn": "MPN-D", "replacement_mpn": "MPN-E", "ltb_date": None}
    ]
    # ...and the date is set as a property, never merged on.
    assert "REPLACED_BY {ltb_date" not in q, "a null ltb_date in the MERGE pattern aborts the statement"
    assert "[rep:REPLACED_BY]->(alt)" in q
    assert "SET rep.ltb_date = part.ltb_date" in q


def test_sustainment_pcn_uses_process_change_class():
    sec = BaseSection(title="Notice", level=0, page_start=0, content="", node_id="doc-2")
    notice = SustainmentNotice(
        doc_id="PCN-1", doc_type="PCN", pub_date="2026-01-01", mfr="Acme",
        categories=["ProcessChange"], summary="Process change.", impacted_parts=[],
    )
    node = DocumentNode(base_extraction=sec,
                        domain_augmentation=SustainmentAugmentation(notice=notice))
    config = SimpleNamespace(graph_node_label="Document", graph_child_label="Section")
    _, sparql = SustainmentPlugin(domain_type="sustainment").to_graph_queries([node], config)
    assert "pcn:ProcessChangeNotification" in " ".join(sparql)


def test_an_mpn_with_ocr_ditto_quotes_does_not_break_the_iriref():
    """A quote or newline inside an MPN must not reach a SPARQL IRIREF.

    Measured case, not hypothetical: TYC-PCN-24-210412's text layer preserves OCR
    ditto quotes inside 16 of its 38 affected_mpn values ('"4503-5023-00"') and an
    embedded newline in a wrapped cell holding two part numbers. The IRIREF grammar
    forbids '"' and every codepoint <= #x20, so the emitted <...> terminated early
    and Fuseki rejected the WHOLE INSERT DATA with HTTP 400 -- confirmed against
    Fuseki's own response body: 'Encountered " "<" "< "" ... Was expecting <IRIref>'.
    to_graph_queries emits ONE query per node, the caller swallows the exception into
    context.log.error, and the Dagster run still reports SUCCESS -- so the notice's
    entire instance graph went missing silently.
    """
    forbidden = set('<>"{}|^`' + chr(92))
    sec = BaseSection(title="Notice", level=0, page_start=0, content="", node_id="doc-1")
    notice = SustainmentNotice(
        doc_id="PCN-24-210412", doc_type="PCN", pub_date="2024-06-10", mfr="Acme",
        categories=["Discontinuation", "Location"], summary="",
        impacted_parts=[
            PartImpact(affected_mpn='"4503-5023-00"', replacement_mpn=None, ltb_date=None),
            PartImpact(affected_mpn="TYC1056344-1," + chr(10) + "9501815SP-1",
                       replacement_mpn='"2052-8002-92"', ltb_date=None),
        ],
    )
    node = DocumentNode(base_extraction=sec,
                        domain_augmentation=SustainmentAugmentation(notice=notice))
    config = SimpleNamespace(graph_node_label="Document", graph_child_label="Section")

    _, sparql = SustainmentPlugin(domain_type="sustainment").to_graph_queries([node], config)
    body = " ".join(sparql)

    # The grammar rule itself, applied to every IRIREF the builder emitted.
    irirefs = re.findall(r"<([^<>]*)>", body)
    assert irirefs, "no IRIREFs emitted -- the assertion below would pass vacuously"
    for iri in irirefs:
        bad = [(i, ch) for i, ch in enumerate(iri)
               if ch in forbidden or ord(ch) <= 0x20 or ord(ch) == 0x7F]
        assert not bad, "IRIREF <%s> carries forbidden characters %r" % (iri, bad)

    # The quote is encoded, not dropped: the row stays joinable to its provenance.
    assert "http://internal/components/%224503-5023-00%22" in body
    assert "%0A" in body                                  # the wrapped-cell newline

    # A second, independent parser agrees with Fuseki on all three shapes (the '#'
    # reel code parses, the raw quoted MPN is rejected, the encoded one parses), so
    # this asserts the body is PARSEABLE and not merely character-legal.
    prepare_update = pytest.importorskip("rdflib.plugins.sparql").prepareUpdate
    for query in sparql:
        prepare_update(query)


def test_a_legal_mpn_iri_is_byte_identical_so_join_keys_do_not_fork():
    """Component IRIs are SHARED join keys across notices, so the sanitiser must be
    identity-preserving for values that were already legal. If it ever starts
    rewriting '#' reel codes, '/' or ',', it mints a DIFFERENT IRI from the one
    already in the graph and silently forks the join -- which is why this is pinned
    rather than left to safe_iri_local's regex-strip.
    """
    sec = BaseSection(title="Notice", level=0, page_start=0, content="", node_id="doc-1")
    notice = SustainmentNotice(
        doc_id="PDN-500", doc_type="PDN", pub_date="2026-04-28", mfr="Acme",
        categories=["Discontinuation"], summary="",
        impacted_parts=[
            PartImpact(affected_mpn="LTC6226HDC#TRMPBF", replacement_mpn="BYVB32-200-E3/81",
                       ltb_date=None),
            PartImpact(affected_mpn="090-44310-31", replacement_mpn=None, ltb_date=None),
        ],
    )
    node = DocumentNode(base_extraction=sec,
                        domain_augmentation=SustainmentAugmentation(notice=notice))
    config = SimpleNamespace(graph_node_label="Document", graph_child_label="Section")

    _, sparql = SustainmentPlugin(domain_type="sustainment").to_graph_queries([node], config)
    body = " ".join(sparql)

    assert "http://internal/components/LTC6226HDC#TRMPBF" in body
    assert "http://internal/components/BYVB32-200-E3/81" in body
    assert "http://internal/components/090-44310-31" in body
    assert "%" not in body, "a legal notice must emit NO percent-escapes at all"


def test_a_path_fragment_doc_id_keys_both_stores_identically():
    """The Neo4j :SustainmentNotice id and the Jena IRI must be the SAME key.

    doc_id is normalized at finalization, but the path fallback can still deliver a
    fragment ('inbound/adi_23_0120'). The Jena IRI normalized it while the Neo4j
    MERGE took doc_id VERBATIM, so the same notice was keyed two ways and the two
    stores never joined. Asserted as an EQUALITY between the two emitted keys, not
    against a hardcoded slug, so the invariant survives a change to the normalizer.
    """
    from doc_tools.utils import sustainment_normalize as norm

    sec = BaseSection(title="Notice", level=0, page_start=0, content="", node_id="doc-1")
    notice = SustainmentNotice(
        doc_id="inbound/adi_23_0120", doc_type="PDN", pub_date="2026-04-28",
        mfr="Acme", categories=["Discontinuation"], summary="",
        impacted_parts=[PartImpact(affected_mpn="MPN-A", replacement_mpn=None, ltb_date=None)],
    )
    node = DocumentNode(base_extraction=sec,
                        domain_augmentation=SustainmentAugmentation(notice=notice))
    config = SimpleNamespace(graph_node_label="Document", graph_child_label="Section")

    cypher, sparql = SustainmentPlugin(domain_type="sustainment").to_graph_queries(
        [node], config, provenance={"obtained_via": "ingress-user", "ingested_at": "",
                                    "derived_from": ""})
    body = " ".join(sparql)
    expected = norm.normalize_doc_id("inbound/adi_23_0120")

    # EVERY Cypher site that keys a notice -- the edge query and the ADR-0041
    # provenance query -- not just the first one found.
    keyed = [q["params"]["notice_id"] for q in cypher if "notice_id" in q.get("params", {})]
    assert len(keyed) >= 2, "expected both :SustainmentNotice MERGE sites to key a notice"
    assert set(keyed) == {expected}, keyed

    # The raw fragment must appear in NEITHER store.
    assert "inbound/adi_23_0120" not in body
    assert "inbound/adi_23_0120" not in " ".join(q["query"] for q in cypher)
    assert "http://internal/sustainment/doc/%s" % expected in body
    assert "/" not in expected, "a normalized key must not still carry a path separator"
