"""Unit tests for the MIL-spec XML -> RDF parsers (doc_tools/parsers).

These builders are the core "Semantic Translator" layer: they map S1000D, DITA,
IADS, and MIL-STD-40051 XML into a single unified MIL ontology. They were
previously exercised only at import level (~10% coverage). Each builder is pure
(lxml + rdflib, no I/O), so we feed representative XML and assert the emitted
triples directly against the in-memory graph.
"""
import pathlib

from lxml import etree
from rdflib import Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

from doc_tools.parsers.dmc_canonicalizer import canonicalize_dmc
from doc_tools.parsers.mil_info_code_map import (
    FALLTHROUGH_COUNT,
    reset_fallthrough_count,
)
from doc_tools.parsers.s1000d_rdf import S1000dGraphBuilder
from doc_tools.parsers.dita_rdf import DitaGraphBuilder
from doc_tools.parsers.iads_rdf import IadsGraphBuilder
from doc_tools.parsers.mil_std_40051_rdf import MilStd40051GraphBuilder

MIL = Namespace("http://edgy-solutions.com/ontology/mil#")
PREFIX = "https://cdn.example/img/"
HOTSPOT_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "s1000d" / "hotspot"
MRAD_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "s1000d" / "mrad"
# The two procedural modules of the six. Measured: 520A carries 4
# proceduralStep elements and 720A carries 5, every one a direct child of
# mainProcedure. The other four carry none at all, which is what makes the
# "no procedure emits no head" case a real corpus case and not a contrivance.
MRAD_720A = MRAD_FIXTURES / "DMC-ODMRAD-A-34-10-01-00A-720A-A_001-00_EN-US.xml"
MRAD_040A = MRAD_FIXTURES / "DMC-ODMRAD-A-34-10-01-00A-040A-A_001-00_EN-US.xml"


# --------------------------------------------------------------------------- #
# S1000D
# --------------------------------------------------------------------------- #
S1000D_XML = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="520" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content>
    <reqSupportEquip><supportEquipDescr><partNumber>WRENCH-01</partNumber></supportEquipDescr></reqSupportEquip>
    <reqSpares><spareDescr><partNumber>SEAL-99</partNumber></spareDescr></reqSpares>
    <figure id="fig1"><title>Assembly View</title><graphic infoEntityIdent="ICN-001"/></figure>
  </content>
</dmodule>
"""


# The same data module with ONLY the disassembly code changed. Under S1000D
# these are two distinct data modules; the builder used to read only the short
# `disasCode` spelling, so a 4.x document's disassembly position vanished and
# two modules differing only here collapsed onto one URI.
S1000D_XML_4X_SPELLING = S1000D_XML.replace(
    b'disasCode="00" disasCodeVariant="A"',
    b'disassyCode="11" disassyCodeVariant="B"',
)

# Two documents that each reference the SAME part number and carry an
# unlabelled figure. Pre-scoping this produced one merged part subject and a
# `fig-fig_0` subject named after a loop index.
S1000D_XML_OTHER_DM = S1000D_XML.replace(b'infoCode="520"', b'infoCode="720"')


def test_s1000d_extracts_dmc_tools_parts_and_figures():
    b = S1000dGraphBuilder(doc_id="manual_v2", image_prefix=PREFIX)
    root = b.parse_data_module(S1000D_XML)
    g = b.graph

    dmc = MIL["dmc-AE-A-32-10-00-00A-520A-A"]
    assert root == str(dmc)
    assert (dmc, RDF.type, MIL.DataModule) in g
    assert (dmc, MIL.hasSNS, Literal("32")) in g
    assert (dmc, MIL.hasInfoCode, Literal("520")) in g
    # tool — prefix is `tool-`, not `part-`, and document-scoped
    tool = MIL["tool-manual_v2-WRENCH-01"]
    assert (tool, RDF.type, MIL.Tool) in g
    assert (tool, MIL.hasPartNumber, Literal("WRENCH-01")) in g
    assert (dmc, MIL.requiresTool, tool) in g
    # part
    part = MIL["part-manual_v2-SEAL-99"]
    assert (part, RDF.type, MIL.Part) in g
    assert (part, MIL.hasPartNumber, Literal("SEAL-99")) in g
    assert (dmc, MIL.hasPart, part) in g
    # figure (URL composed from infoEntityIdent + image_prefix)
    fig = MIL["fig-manual_v2-fig1"]
    assert (fig, RDF.type, MIL.Figure) in g
    assert (fig, RDFS.label, Literal("Assembly View")) in g
    assert (fig, MIL.hasURL, Literal(f"{PREFIX}ICN-001.png")) in g
    assert (dmc, MIL.hasFigure, fig) in g


def test_s1000d_dmc_is_the_canonical_form_the_read_path_resolves():
    """The write path's DMC must round-trip through `canonicalize_dmc`.

    dmc_canonicalizer's own docstring states the rule this pins:
    "same-canonicalizer-both-sides" — the ingest writer and Engine E's
    /resolve_dmc read path must agree, or the read returns
    `n_candidates=0` for a document that IS present.

    The inline join this builder used instead emitted
    `AE-A-32-1-0-00-00-A-520-A-A`: eleven hyphen groups where the canonical
    form has eight, because `subSystemCode`+`subSubSystemCode`,
    `disasCode`+variant and `infoCode`+variant each concatenate. That string
    does not match the canonical regex at all, so `canonicalize_dmc` returns
    None for it — no S1000D data module this builder wrote was ever
    resolvable by DMC.
    """
    b = S1000dGraphBuilder(doc_id="d")
    root = b.parse_data_module(S1000D_XML)
    built = root.split("#dmc-")[1]

    assert canonicalize_dmc(built) == built
    # and the shape that was being written before is not even a DMC
    assert canonicalize_dmc("AE-A-32-1-0-00-00-A-520-A-A") is None


def test_s1000d_emits_the_deterministic_content_kind():
    """520 is a maintenance procedure; the root type alone is not enough.

    Measured 2026-10-02 over the six mock OpenDDIL modules: every one landed
    as the bare `mil:DataModule`, so a fault-isolation module, a procedure and
    an IPD were indistinguishable downstream. Both types are emitted — Jena
    serves these graphs without reasoning, so dropping the root would hide
    classified modules from `?s a mil:DataModule`.
    """
    b = S1000dGraphBuilder(doc_id="d")
    dmc = MIL["dmc-AE-A-32-10-00-00A-520A-A"]
    b.parse_data_module(S1000D_XML)
    assert (dmc, RDF.type, MIL.ProcedureDataModule) in b.graph
    assert (dmc, RDF.type, MIL.DataModule) in b.graph


def test_s1000d_unclassifiable_info_code_emits_only_the_root():
    """A 3xx module has no mil:* kind, so it must NOT be mislabelled."""
    reset_fallthrough_count()
    b = S1000dGraphBuilder(doc_id="d")
    root = b.parse_data_module(S1000D_XML.replace(b'infoCode="520"', b'infoCode="320"'))
    kinds = set(b.graph.objects(URIRef(root), RDF.type))
    assert kinds == {MIL.DataModule}
    assert FALLTHROUGH_COUNT == {"3": 1}
    reset_fallthrough_count()


def test_s1000d_reads_the_4x_disassembly_spelling():
    """`disassyCode` is the 4.x attribute name; reading only `disasCode`
    dropped the whole disassembly position and merged distinct modules."""
    b = S1000dGraphBuilder(doc_id="d")
    root = b.parse_data_module(S1000D_XML_4X_SPELLING)
    assert root == str(MIL["dmc-AE-A-32-10-00-11B-520A-A"])
    # distinct from the module that differs ONLY in the disassembly code
    other = S1000dGraphBuilder(doc_id="d")
    assert other.parse_data_module(S1000D_XML) != root


def test_s1000d_part_and_figure_subjects_are_document_scoped():
    """Two documents citing the same part number must not share a subject.

    Pre-scoping, `mil:part-ODM-SE-0001` was coined by two of the six mock
    modules and merged into one node carrying both documents' edges. That
    silently fuses unrelated parts lists on a shared corpus and makes a
    doc_id-keyed rollback impossible — deleting one document's subjects would
    take the other's edges with them.
    """
    a = S1000dGraphBuilder(doc_id="doc_a")
    a.parse_data_module(S1000D_XML)
    b = S1000dGraphBuilder(doc_id="doc_b")
    b.parse_data_module(S1000D_XML_OTHER_DM)

    def scoped(g, pfx):
        return {str(s) for s in set(g.subjects()) if f"#{pfx}-" in str(s)}

    for pfx in ("part", "tool", "fig"):
        assert scoped(a.graph, pfx) and scoped(b.graph, pfx), pfx
        assert not scoped(a.graph, pfx) & scoped(b.graph, pfx), (
            f"{pfx} subjects collide across documents: "
            f"{scoped(a.graph, pfx) & scoped(b.graph, pfx)}"
        )

    # cross-document identity stays recoverable as a literal, not a shared URI
    assert set(a.graph.objects(None, MIL.hasPartNumber)) == {
        Literal("WRENCH-01"), Literal("SEAL-99")
    }
    assert (set(a.graph.objects(None, MIL.hasPartNumber))
            == set(b.graph.objects(None, MIL.hasPartNumber)))


def test_s1000d_a_tool_is_not_also_typed_a_part():
    """One part number used as both tool and spare coined ONE dual-typed
    subject, so "is this a consumable spare" answered yes for a wrench."""
    xml = S1000D_XML.replace(b"<partNumber>SEAL-99</partNumber>",
                             b"<partNumber>WRENCH-01</partNumber>")
    b = S1000dGraphBuilder(doc_id="d")
    b.parse_data_module(xml)
    dual = [s for s in set(b.graph.subjects())
            if {MIL.Tool, MIL.Part} <= set(b.graph.objects(s, RDF.type))]
    assert dual == []


def test_s1000d_unsafe_characters_cannot_break_the_subject_uri():
    """A part number with a space used to be spliced into the URI verbatim."""
    xml = S1000D_XML.replace(b"<partNumber>SEAL-99</partNumber>",
                             b"<partNumber>SEAL 99/B</partNumber>")
    b = S1000dGraphBuilder(doc_id="d")
    b.parse_data_module(xml)
    assert (MIL["part-d-SEAL_99_B"], RDF.type, MIL.Part) in b.graph
    # the ORIGINAL value is preserved on the node, not lost to the scrub
    assert (MIL["part-d-SEAL_99_B"], MIL.hasPartNumber,
            Literal("SEAL 99/B")) in b.graph
    assert b.serialize()  # serializes; a raw space would not


def test_s1000d_missing_dmcode_returns_sentinel():
    b = S1000dGraphBuilder()
    assert b.parse_data_module(b"<dmodule><content/></dmodule>") == "unknown-s1000d-dmc"


def test_s1000d_serialize_emits_turtle():
    b = S1000dGraphBuilder()
    b.parse_data_module(S1000D_XML)
    ttl = b.serialize()
    assert isinstance(ttl, str) and "mil:" in ttl and "DataModule" in ttl


# --------------------------------------------------------------------------- #
# S1000D 2(e): fault codes, dmRef edges, IPD items, planning intervals
# --------------------------------------------------------------------------- #

# A module whose identAndStatusSection/dmStatus/brexDmRef/dmRef names its OWN
# dmCode (520), plus ONE content dmRef pointing at a different module (720).
# //dmRef unfiltered would emit two refersToDataModule triples (one a
# self-loop); [not(ancestor::identAndStatusSection)] must emit exactly one.
S1000D_XML_WITH_DMREF = b"""
<dmodule>
  <identAndStatusSection>
    <dmAddress><dmIdent>
      <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
              subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
              infoCode="520" infoCodeVariant="A" itemLocationCode="A"/>
    </dmIdent></dmAddress>
    <dmStatus>
      <brexDmRef><dmRef><dmRefIdent>
        <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
                subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
                infoCode="520" infoCodeVariant="A" itemLocationCode="A"/>
      </dmRefIdent></dmRef></brexDmRef>
    </dmStatus>
  </identAndStatusSection>
  <content>
    <para>See the removal procedure.
      <dmRef><dmRefIdent>
        <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
                subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
                infoCode="720" infoCodeVariant="A" itemLocationCode="A"/>
      </dmRefIdent></dmRef>
    </para>
  </content>
</dmodule>
"""

# A brexDmRef dmCode authored BEFORE the dmIdent. The bare `//dmCode[0]`
# lookup this replaces would pick the brex module (ZZ-...-999Z-Z) instead of
# the authored own ident (AE-...-520A-A).
S1000D_XML_BREX_BEFORE_IDENT = b"""
<dmodule>
  <identAndStatusSection>
    <dmStatus>
      <brexDmRef><dmRef><dmRefIdent>
        <dmCode modelIdentCode="ZZ" systemDiffCode="Z" systemCode="99" subSystemCode="9"
                subSubSystemCode="9" assyCode="99" disasCode="99" disasCodeVariant="Z"
                infoCode="999" infoCodeVariant="Z" itemLocationCode="Z"/>
      </dmRefIdent></dmRef></brexDmRef>
    </dmStatus>
    <dmAddress><dmIdent>
      <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
              subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
              infoCode="520" infoCodeVariant="A" itemLocationCode="A"/>
    </dmIdent></dmAddress>
  </identAndStatusSection>
  <content/>
</dmodule>
"""

S1000D_XML_FAULT = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="421" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content>
    <faultIsolation>
      <faultCode faultCodeValue="BIT-0417">
        <faultCodeText>Array module fault.</faultCodeText>
      </faultCode>
    </faultIsolation>
  </content>
</dmodule>
"""

S1000D_XML_INTERVAL = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="320" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content>
    <scheduling><mpSystem><mpSystemChap>
      <mpSection><title>Periodic Array Inspection</title>
        <limit><threshold thresholdUnitOfMeasure="days">
          <thresholdValue>180</thresholdValue>
        </threshold></limit>
      </mpSection>
    </mpSystemChap></mpSystem></scheduling>
  </content>
</dmodule>
"""

S1000D_XML_IPD = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="941" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content>
    <illustratedPartsCatalog>
      <figure>
        <title>Array Module Assembly</title>
        <graphic infoEntityIdent="ICN-ODMRAD-00001"/>
        <catalogSeqNumberGroup>
          <catalogSeqNumber item="0001">
            <description><name>array module</name>
              <identNumber><manufacturerCode>ODM</manufacturerCode>
                <partAndSerialNumber><partNumber>ODM-AM-0001</partNumber></partAndSerialNumber>
              </identNumber>
            </description>
            <reqQuantity>1</reqQuantity>
          </catalogSeqNumber>
        </catalogSeqNumberGroup>
      </figure>
    </illustratedPartsCatalog>
  </content>
</dmodule>
"""

# Same part number cited in BOTH reqSpares and an IPD catalog item, in one
# document — must mint ONE part- subject, not two.
S1000D_XML_IPD_AND_REQSPARES = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="720" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content>
    <reqSpares><spareDescr><partNumber>ODM-AM-0001</partNumber></spareDescr></reqSpares>
    <illustratedPartsCatalog>
      <figure>
        <title>Array Module Assembly</title>
        <catalogSeqNumberGroup>
          <catalogSeqNumber item="0001">
            <description><name>array module</name>
              <identNumber><manufacturerCode>ODM</manufacturerCode>
                <partAndSerialNumber><partNumber>ODM-AM-0001</partNumber></partAndSerialNumber>
              </identNumber>
            </description>
            <reqQuantity>1</reqQuantity>
          </catalogSeqNumber>
        </catalogSeqNumberGroup>
      </figure>
    </illustratedPartsCatalog>
  </content>
</dmodule>
"""

S1000D_XML_FIGURE_NO_ID = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="941" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content>
    <figure><title>Array</title><graphic infoEntityIdent="ICN-X-1"/></figure>
  </content>
</dmodule>
"""

# A graphic with ONLY a boardno, no infoEntityIdent — the conflation guard
# (1a/1b): mil:hasICN must never carry a boardno.
S1000D_XML_FIGURE_BOARDNO_ONLY = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="941" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content>
    <figure id="figB"><title>Board Figure</title><graphic boardno="BD-999"/></figure>
  </content>
</dmodule>
"""

# Hotspot nested directly inside the catalog item — unambiguous, case (a).
S1000D_XML_IPD_HOTSPOT_NESTED = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="941" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content>
    <illustratedPartsCatalog>
      <figure>
        <title>Hotspot Nested</title>
        <graphic infoEntityIdent="ICN-HS-1"/>
        <catalogSeqNumberGroup>
          <catalogSeqNumber item="0001">
            <description><name>widget</name>
              <identNumber><manufacturerCode>ODM</manufacturerCode>
                <partAndSerialNumber><partNumber>ODM-W-0001</partNumber></partAndSerialNumber>
              </identNumber>
            </description>
            <hotspot applicationStructureIdent="HS-N-1"/>
            <reqQuantity>1</reqQuantity>
          </catalogSeqNumber>
        </catalogSeqNumberGroup>
      </figure>
    </illustratedPartsCatalog>
  </content>
</dmodule>
"""

# Hotspot under the graphic, joined by key — case (b) plus the
# no-guessing-by-position guard: a SECOND graphic hotspot ("NO-MATCH")
# matches neither item's @item and must attach to nothing.
S1000D_XML_IPD_HOTSPOT_JOIN = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="941" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content>
    <illustratedPartsCatalog>
      <figure>
        <title>Hotspot Join</title>
        <graphic infoEntityIdent="ICN-HS-2">
          <hotspot applicationStructureIdent="0002"/>
          <hotspot applicationStructureIdent="NO-MATCH"/>
        </graphic>
        <catalogSeqNumberGroup>
          <catalogSeqNumber item="0001">
            <description><name>widget one</name>
              <identNumber><manufacturerCode>ODM</manufacturerCode>
                <partAndSerialNumber><partNumber>ODM-W-0001</partNumber></partAndSerialNumber>
              </identNumber>
            </description>
            <reqQuantity>1</reqQuantity>
          </catalogSeqNumber>
          <catalogSeqNumber item="0002">
            <description><name>widget two</name>
              <identNumber><manufacturerCode>ODM</manufacturerCode>
                <partAndSerialNumber><partNumber>ODM-W-0002</partNumber></partAndSerialNumber>
              </identNumber>
            </description>
            <reqQuantity>1</reqQuantity>
          </catalogSeqNumber>
        </catalogSeqNumberGroup>
      </figure>
    </illustratedPartsCatalog>
  </content>
</dmodule>
"""


def test_s1000d_brex_dmref_is_not_a_cross_reference():
    b = S1000dGraphBuilder(doc_id="d")
    root = b.parse_data_module(S1000D_XML_WITH_DMREF)
    refs = list(b.graph.objects(URIRef(root), MIL.refersToDataModule))
    assert len(refs) == 1
    assert refs[0] == MIL["dmc-AE-A-32-10-00-00A-720A-A"]
    assert refs[0] != URIRef(root)


def test_s1000d_dmref_target_matches_the_referenced_modules_own_subject():
    """The STRONG test: an inline join could pass a label test and still
    fail this, because it depends on BOTH sides using the same
    canonicalizer-and-argument-mapping, not on the two strings looking
    similar."""
    a = S1000dGraphBuilder(doc_id="doc_a")
    root_a = a.parse_data_module(S1000D_XML_WITH_DMREF)
    ref_obj = next(iter(a.graph.objects(URIRef(root_a), MIL.refersToDataModule)))

    b = S1000dGraphBuilder(doc_id="doc_b")
    root_b = b.parse_data_module(S1000D_XML_OTHER_DM)  # infoCode 720

    assert str(ref_obj) == root_b


def test_s1000d_own_ident_is_not_taken_from_a_dmref():
    b = S1000dGraphBuilder(doc_id="d")
    root = b.parse_data_module(S1000D_XML_BREX_BEFORE_IDENT)
    assert root == str(MIL["dmc-AE-A-32-10-00-00A-520A-A"])


def test_s1000d_emits_the_fault_code_node():
    b = S1000dGraphBuilder(doc_id="d")
    root = b.parse_data_module(S1000D_XML_FAULT)
    fc = MIL["faultcode-d-BIT-0417"]
    assert (fc, RDF.type, MIL.FaultCode) in b.graph
    assert (fc, RDFS.label, Literal("BIT-0417")) in b.graph
    assert (fc, MIL.hasFaultCodeValue, Literal("BIT-0417")) in b.graph
    assert (fc, MIL.hasFaultCodeText, Literal("Array module fault.")) in b.graph
    assert (URIRef(root), MIL.hasFaultCode, fc) in b.graph


def test_s1000d_fault_code_subjects_are_document_scoped():
    a = S1000dGraphBuilder(doc_id="doc_a")
    a.parse_data_module(S1000D_XML_FAULT)
    c = S1000dGraphBuilder(doc_id="doc_c")
    c.parse_data_module(S1000D_XML_FAULT)

    fc_a = MIL["faultcode-doc_a-BIT-0417"]
    fc_c = MIL["faultcode-doc_c-BIT-0417"]
    assert fc_a != fc_c
    assert (fc_a, RDF.type, MIL.FaultCode) in a.graph
    assert (fc_c, RDF.type, MIL.FaultCode) in c.graph
    assert set(a.graph.objects(None, MIL.hasFaultCodeValue)) == {Literal("BIT-0417")}
    assert (set(a.graph.objects(None, MIL.hasFaultCodeValue))
            == set(c.graph.objects(None, MIL.hasFaultCodeValue)))


def test_s1000d_emits_the_planning_interval():
    b = S1000dGraphBuilder(doc_id="d")
    root = b.parse_data_module(S1000D_XML_INTERVAL)
    ivs = list(b.graph.subjects(RDF.type, MIL.PlanningInterval))
    assert len(ivs) == 1
    iv = ivs[0]
    # subject is named after the mpSection title, not a loop index
    assert "Periodic_Array_Inspection" in str(iv)
    assert (iv, RDFS.label, Literal("180 days")) in b.graph
    assert (iv, MIL.hasIntervalValue, Literal("180")) in b.graph
    assert (iv, MIL.hasIntervalUnit, Literal("days")) in b.graph
    assert (URIRef(root), MIL.hasPlanningInterval, iv) in b.graph


def test_s1000d_emits_ipd_items_with_part_number_and_quantity():
    b = S1000dGraphBuilder(doc_id="d")
    root = b.parse_data_module(S1000D_XML_IPD)
    g = b.graph

    items = list(g.subjects(RDF.type, MIL.CatalogItem))
    assert len(items) == 1
    it = items[0]
    assert (it, MIL.hasPartNumber, Literal("ODM-AM-0001")) in g
    qty = list(g.objects(it, MIL.hasQuantity))
    assert qty == [Literal(1)]
    assert qty[0].datatype == URIRef("http://www.w3.org/2001/XMLSchema#integer")

    fig = next(iter(g.subjects(RDF.type, MIL.Figure)))
    assert (fig, MIL.hasCatalogItem, it) in g
    assert (URIRef(root), MIL.hasCatalogItem, it) in g


def test_s1000d_an_ipd_part_and_a_reqspares_part_share_one_subject():
    b = S1000dGraphBuilder(doc_id="d")
    root = b.parse_data_module(S1000D_XML_IPD_AND_REQSPARES)
    g = b.graph

    parts = set(g.subjects(RDF.type, MIL.Part))
    assert parts == {MIL["part-d-ODM-AM-0001"]}
    part = MIL["part-d-ODM-AM-0001"]

    assert (URIRef(root), MIL.hasPart, part) in g
    items = list(g.subjects(RDF.type, MIL.CatalogItem))
    assert len(items) == 1
    assert (items[0], MIL.hasPart, part) in g


def test_s1000d_figure_identity_falls_back_to_the_authored_icn():
    b = S1000dGraphBuilder(doc_id="d")
    b.parse_data_module(S1000D_XML_FIGURE_NO_ID)
    figs = {str(s) for s in set(b.graph.subjects(RDF.type, MIL.Figure))}
    assert any("ICN-X-1" in f for f in figs)
    assert not any("fig_0" in f for f in figs)


def test_s1000d_figure_emits_icn_from_info_entity_ident():
    b = S1000dGraphBuilder(doc_id="d", image_prefix=PREFIX)
    b.parse_data_module(S1000D_XML)
    fig = MIL["fig-d-fig1"]
    assert (fig, MIL.hasICN, Literal("ICN-001")) in b.graph


def test_s1000d_boardno_only_graphic_yields_no_icn():
    """The conflation guard (1a/1b): a boardno must never be emitted as an
    ICN, because an ICN is not a boardno."""
    b = S1000dGraphBuilder(doc_id="d")
    b.parse_data_module(S1000D_XML_FIGURE_BOARDNO_ONLY)
    fig = MIL["fig-d-figB"]
    assert not list(b.graph.objects(fig, MIL.hasICN))


def test_s1000d_icn_with_no_image_prefix_emits_no_url():
    """Pins 1c, the confabulation-kill, for THIS parser: now that the ICN
    has its own predicate, the deleted `elif info_entity:` branch must not
    be missed — an ICN with no image_prefix emits hasICN only, never a
    fabricated hasURL built from the bare ICN string."""
    b = S1000dGraphBuilder(doc_id="d")  # no image_prefix
    b.parse_data_module(S1000D_XML)
    fig = MIL["fig-d-fig1"]
    assert (fig, MIL.hasICN, Literal("ICN-001")) in b.graph
    assert not list(b.graph.objects(fig, MIL.hasURL)), (
        "no image_prefix and no bare-ICN fallback means no hasURL at all"
    )


def test_s1000d_hotspot_nested_in_item_attaches_to_that_item():
    b = S1000dGraphBuilder(doc_id="d")
    b.parse_data_module(S1000D_XML_IPD_HOTSPOT_NESTED)
    items = list(b.graph.subjects(RDF.type, MIL.CatalogItem))
    assert len(items) == 1
    assert (items[0], MIL.hasHotspotId, Literal("HS-N-1")) in b.graph


def test_s1000d_hotspot_joined_by_key_attaches_to_the_right_item_only():
    """Case (b) plus the no-guessing-by-position guard: the graphic's
    SECOND hotspot ("NO-MATCH") matches no item's key and must attach to
    NOTHING — not item 0001, not item 0002, not by falling back to
    position."""
    b = S1000dGraphBuilder(doc_id="d")
    b.parse_data_module(S1000D_XML_IPD_HOTSPOT_JOIN)
    g = b.graph
    cat_items = {
        str(pn): it
        for it in g.subjects(RDF.type, MIL.CatalogItem)
        for pn in g.objects(it, MIL.hasPartNumber)
    }
    item_0001 = cat_items["ODM-W-0001"]
    item_0002 = cat_items["ODM-W-0002"]

    assert not list(g.objects(item_0001, MIL.hasHotspotId)), (
        "item 0001's key doesn't match either graphic hotspot"
    )
    assert (item_0002, MIL.hasHotspotId, Literal("0002")) in g
    assert Literal("NO-MATCH") not in set(g.objects(None, MIL.hasHotspotId)), (
        "a hotspot ident matching no item must attach to nothing"
    )


def test_s1000d_icn_is_identical_across_documents_but_figure_subjects_differ():
    """The figure subject stays document-scoped while the ICN literal is
    identical across two publications — the "two publications' figures
    can't collide" claim, as an assertion."""
    a = S1000dGraphBuilder(doc_id="doc_a")
    a.parse_data_module(S1000D_XML)
    c = S1000dGraphBuilder(doc_id="doc_c")
    c.parse_data_module(S1000D_XML)

    fig_a = MIL["fig-doc_a-fig1"]
    fig_c = MIL["fig-doc_c-fig1"]
    assert fig_a != fig_c
    assert (fig_a, MIL.hasICN, Literal("ICN-001")) in a.graph
    assert (fig_c, MIL.hasICN, Literal("ICN-001")) in c.graph


def test_s1000d_hotspot_ids_resolve_into_the_svg_artwork():
    """Every hotspot id the parser extracts from the authored hotspot
    fixture module must be an id actually present in the sibling SVG
    artwork. The converse is NOT required: the SVG carries one extra,
    unclaimed id, and that must NOT cause a failure — a graphic may carry
    hotspots no catalog item references. See
    tests/fixtures/s1000d/hotspot/README.md."""
    b = S1000dGraphBuilder(doc_id="hotspot-fixture")
    xml_bytes = (HOTSPOT_FIXTURES / "ipd-hotspot-authored.xml").read_bytes()
    b.parse_data_module(xml_bytes)
    extracted_ids = {str(v) for v in b.graph.objects(None, MIL.hasHotspotId)}
    assert extracted_ids, "the fixture should yield at least one hotspot id"

    svg_root = etree.parse(str(HOTSPOT_FIXTURES / "graphic-hotspot-authored.svg")).getroot()
    svg_ids = {el.get("id") for el in svg_root.iter() if el.get("id")}

    missing = extracted_ids - svg_ids
    assert not missing, f"hotspot ids not present in the SVG artwork: {missing}"
    # The converse is explicitly NOT asserted: an id present in the SVG but
    # not extracted (the "unclaimed" id) must not fail this seal.
    assert svg_ids - extracted_ids, (
        "expected at least one SVG id with no claiming catalog item"
    )


def _walk_steps(graph, head):
    """Follow rdf:first/rdf:rest from `head` and return the step URIs in order.

    Deliberately a manual walk and not rdflib's Collection: Collection is
    tolerant of a list that runs off the end, and the thing most worth
    asserting about this list is that it TERMINATES at rdf:nil.
    """
    steps, cell, seen = [], head, set()
    while cell != RDF.nil:
        assert cell not in seen, f"cycle in the procedure list at {cell}"
        seen.add(cell)
        first = list(graph.objects(cell, RDF.first))
        rest = list(graph.objects(cell, RDF.rest))
        assert len(first) == 1, f"cell {cell} has {len(first)} rdf:first objects"
        assert len(rest) == 1, f"cell {cell} has {len(rest)} rdf:rest objects"
        steps.append(first[0])
        cell = rest[0]
    return steps


def test_s1000d_procedure_steps_are_an_ordered_rdf_list():
    """The 720A module's five steps must come back in DOCUMENT order from a
    list hung off the MODULE subject and terminated by rdf:nil.

    rdf:List, not mil:stepIndex, because mil:stepIndex does not exist:
    measured against the deployed vocabulary graph
    <http://internal/MAINTENANCE>, an ASK for it is False in subject,
    predicate AND object position. (16 other mil: terms ARE declared there;
    the earlier "none at all" reading came from scanning only predicate
    position, where a TBox declaration never appears.)"""
    b = S1000dGraphBuilder(doc_id="mrad-720a")
    dmc_uri = b.parse_data_module(MRAD_720A.read_bytes())

    heads = list(b.graph.objects(URIRef(dmc_uri), MIL.hasProcedureSteps))
    assert len(heads) == 1, f"expected one procedure list head, got {heads}"

    steps = _walk_steps(b.graph, heads[0])
    assert len(steps) == 5, f"expected 5 ordered steps, got {len(steps)}"
    for step in steps:
        assert (step, RDF.type, MIL.ProceduralStep) in b.graph

    texts = [str(next(b.graph.objects(s, MIL.hasStepText))) for s in steps]
    # Order is the assertion. These are the first words of the five steps as
    # the fixture prints them, in the fixture's order.
    assert [t.split()[0] for t in texts] == [
        "Position", "Install", "Connect", "Restore", "Run",
    ], texts
    # A hard-wrapped <para> must not leave its newline and indent in the
    # literal (step 2 wraps before "ODM-SE-0001").
    assert "\n" in MRAD_720A.read_text(encoding="utf-8")
    assert all("\n" not in t and "  " not in t for t in texts), texts
    assert "ODM-SE-0001" in texts[1], texts[1]


def test_s1000d_procedure_list_cells_are_uris_so_re_ingest_cannot_duplicate():
    """The list must contain NO blank nodes, and re-parsing the same bytes
    must not grow the graph.

    This is not style. The instance-graph write serializes this graph to
    N-Triples and sends it as SPARQL INSERT DATA, which mints a FRESH blank
    node per execution — so a blank-node list (rdflib's Collection default)
    would append an entire second procedure on every re-ingest, and the
    idempotency proof the architect asked for would fail for a reason nothing
    in the parser's own tests would show."""
    xml_bytes = MRAD_720A.read_bytes()
    b = S1000dGraphBuilder(doc_id="mrad-720a")
    b.parse_data_module(xml_bytes)

    head = next(iter(b.graph.objects(None, MIL.hasProcedureSteps)))
    cells = [head] + [
        o for o in b.graph.objects(None, RDF.rest) if o != RDF.nil
    ]
    assert cells, "no list cells found"
    for term in cells + _walk_steps(b.graph, head):
        assert isinstance(term, URIRef), f"{term!r} is not a URIRef"

    before = len(b.graph)
    b.parse_data_module(xml_bytes)
    assert len(b.graph) == before, (
        f"re-parsing the same bytes grew the graph by {len(b.graph) - before} "
        f"triples; the re-ingest would not be set-idempotent"
    )

    other = S1000dGraphBuilder(doc_id="mrad-720a")
    other.parse_data_module(xml_bytes)
    assert sorted(other.graph.serialize(format="nt").splitlines()) == sorted(
        b.graph.serialize(format="nt").splitlines()
    ), "two builders over the same bytes disagree, so the subjects are not deterministic"


def test_s1000d_a_module_with_no_procedure_emits_no_list_head():
    """Four of the six MRAD modules carry no proceduralStep. Those must emit
    no head at all — never an empty list, which a consumer would walk into
    and render as a procedure with no steps rather than as no procedure."""
    b = S1000dGraphBuilder(doc_id="mrad-040a")
    dmc_uri = b.parse_data_module(MRAD_040A.read_bytes())
    assert list(b.graph.objects(URIRef(dmc_uri), MIL.hasProcedureSteps)) == []
    assert list(b.graph.subjects(RDF.type, MIL.ProceduralStep)) == []


def test_s1000d_a_nested_procedural_step_is_folded_not_dropped():
    """S1000D permits proceduralStep nesting and the MRAD corpus has none, so
    only direct children are ORDERED. A nested step must still not vanish:
    its text is folded into the enclosing step's literal, where it is
    visible, rather than silently discarded."""
    xml = b"""
<dmodule>
  <identAndStatusSection><dmAddress><dmIdent>
    <dmCode modelIdentCode="AE" systemDiffCode="A" systemCode="32" subSystemCode="1"
            subSubSystemCode="0" assyCode="00" disasCode="00" disasCodeVariant="A"
            infoCode="720" infoCodeVariant="A" itemLocationCode="A"/>
  </dmIdent></dmAddress></identAndStatusSection>
  <content><procedure><mainProcedure>
    <proceduralStep>
      <para>Outer step.</para>
      <proceduralStep><para>Inner step.</para></proceduralStep>
    </proceduralStep>
  </mainProcedure></procedure></content>
</dmodule>
"""
    b = S1000dGraphBuilder(doc_id="nested")
    dmc_uri = b.parse_data_module(xml)
    head = next(iter(b.graph.objects(URIRef(dmc_uri), MIL.hasProcedureSteps)))
    steps = _walk_steps(b.graph, head)
    assert len(steps) == 1, f"only the direct child is ordered, got {len(steps)}"
    text = str(next(b.graph.objects(steps[0], MIL.hasStepText)))
    assert "Outer step." in text and "Inner step." in text, text


# --------------------------------------------------------------------------- #
# DITA
# --------------------------------------------------------------------------- #
DITA_XML = b"""
<task id="task-100">
  <taskbody>
    <prereq>Torque Wrench</prereq>
    <steps><step><cmd>Remove the panel.</cmd></step></steps>
  </taskbody>
  <fig id="figA"><title>Panel</title><image href="img/panel"/></fig>
</task>
"""


def test_dita_extracts_node_prereq_steps_and_figure():
    b = DitaGraphBuilder(image_prefix=PREFIX)
    root = b.parse_data_module(DITA_XML)
    g = b.graph

    node = MIL["dita-task-100"]
    assert root == str(node)
    assert (node, RDF.type, MIL.DitaNode) in g
    # prereq -> requiresTool with cleaned id + readable label
    assert (node, MIL.requiresTool, MIL["item-Torque_Wrench"]) in g
    assert (MIL["item-Torque_Wrench"], RDFS.label, Literal("Torque Wrench")) in g
    # steps -> instruction text
    assert (node, MIL.hasInstructionText, Literal("Remove the panel.")) in g
    # figure -> URL from href
    assert (MIL["fig-figA"], RDF.type, MIL.Figure) in g
    assert (MIL["fig-figA"], MIL.hasURL, Literal(f"{PREFIX}img/panel.png")) in g
    assert (node, MIL.hasFigure, MIL["fig-figA"]) in g


# --------------------------------------------------------------------------- #
# IADS
# --------------------------------------------------------------------------- #
IADS_XML = b"""
<iadsModule id="node-7">
  <tool>Hex Key</tool>
  <part>Bolt-12</part>
  <warning>High voltage present.</warning>
  <step>Disconnect power.</step>
  <graphic boardno="BD-100"/>
</iadsModule>
"""


def test_iads_extracts_tools_parts_warnings_and_boardno_figure():
    b = IadsGraphBuilder(image_prefix=PREFIX)
    root = b.parse_data_module(IADS_XML)
    g = b.graph

    node = MIL["iads-node-7"]
    assert root == str(node)
    assert (node, RDF.type, MIL.IadsNode) in g
    assert (node, MIL.requiresTool, MIL["tool-Hex_Key"]) in g
    # non-alphanumerics are stripped from ids: "Bolt-12" -> "Bolt12"
    assert (node, MIL.hasPart, MIL["part-Bolt12"]) in g
    assert (node, MIL.hasWarning, Literal("High voltage present.")) in g
    assert (node, MIL.hasInstructionText, Literal("Disconnect power.")) in g
    # boardno graphic -> figure keyed by boardno (not cleaned)
    assert (MIL["fig-BD-100"], RDF.type, MIL.Figure) in g
    assert (MIL["fig-BD-100"], MIL.hasURL, Literal(f"{PREFIX}BD-100.png")) in g
    assert (node, MIL.hasFigure, MIL["fig-BD-100"]) in g


# --------------------------------------------------------------------------- #
# MIL-STD-40051
# --------------------------------------------------------------------------- #
MILSTD_XML = b"""
<wp>
  <wpno>WP0012</wpno>
  <supportreqs><item><name>Multimeter</name></item></supportreqs>
  <sparesreq><item><name>Fuse 5A</name></item></sparesreq>
  <warning><para>Explosive hazard.</para></warning>
  <proc><step1><para>Install the bracket.</para></step1></proc>
  <graphic boardno="FIG-9"/>
</wp>
"""


def test_milstd_40051_extracts_workpackage_tools_parts_and_figure():
    b = MilStd40051GraphBuilder(image_prefix=PREFIX)
    root = b.parse_data_module(MILSTD_XML)
    g = b.graph

    node = MIL["wpn-WP0012"]
    assert root == str(node)
    # classified as both DataModule and WorkPackage
    assert (node, RDF.type, MIL.DataModule) in g
    assert (node, RDF.type, MIL.WorkPackage) in g
    assert (node, RDFS.label, Literal("Work Package WP0012")) in g
    assert (node, MIL.requiresTool, MIL["tool-Multimeter"]) in g
    assert (node, MIL.hasPart, MIL["part-Fuse_5A"]) in g
    assert (node, MIL.hasWarning, Literal("Explosive hazard.")) in g
    assert (node, MIL.hasInstructionText, Literal("Install the bracket.")) in g
    # 40051 keeps hyphens in figure ids
    assert (MIL["fig-FIG-9"], RDF.type, MIL.Figure) in g
    assert (node, MIL.hasFigure, MIL["fig-FIG-9"]) in g
    # NO manifest was passed, so the figure is UNRESOLVED and carries no URL.
    # This assertion used to demand f"{PREFIX}FIG-9.png" — the parser predicted
    # a filename from the boardno and an assumed extension. That prediction was
    # a URL the pipeline had no evidence for: downstream it is indistinguishable
    # from a resolved one, so a figure that was never uploaded rendered as a 404
    # that reads like a broken pipeline instead of an honest "unresolved" card.
    # See the CONFABULATION-KILL comment in parsers/mil_std_40051_rdf.py.
    assert (MIL["fig-FIG-9"], MIL.renderingOrigin, Literal("unresolved")) in g
    assert not list(g.objects(MIL["fig-FIG-9"], MIL.hasURL)), (
        "a figure with no manifest entry must carry NO url — a predicted one "
        "cannot be told apart downstream from a real one"
    )


def test_milstd_40051_figure_url_comes_from_the_manifest():
    """The resolved half of the contract above. The URL is the manifest's
    `uploaded_filename` — the name the extractor ACTUALLY wrote to S3, extension
    and all — never one derived from the boardno."""
    manifest = {"figures": {"FIG-9": {"uploaded_filename": "FIG-9.svg",
                                      "rendering_origin": "rendered"}}}
    b = MilStd40051GraphBuilder(image_prefix=PREFIX, graphics_manifest=manifest)
    b.parse_data_module(MILSTD_XML)
    g = b.graph

    assert (MIL["fig-FIG-9"], MIL.hasURL, Literal(f"{PREFIX}FIG-9.svg")) in g
    assert (MIL["fig-FIG-9"], MIL.renderingOrigin, Literal("rendered")) in g
    # `rendered` and `unresolved` are the discriminant the UI keys on; a
    # resolved figure must never also claim unresolved.
    assert (MIL["fig-FIG-9"], MIL.renderingOrigin, Literal("unresolved")) not in g


def test_milstd_40051_falls_back_to_unknown_wp():
    b = MilStd40051GraphBuilder()
    root = b.parse_data_module(b"<wp><content/></wp>")
    assert root == str(MIL["wpn-unknown_wp"])


# --------------------------------------------------------------------------- #
# S1000D MRAD four gaps: warnings, isolation tree, tool name, planning prose.
# Real fixtures only; the point is that these six documents extract.
# --------------------------------------------------------------------------- #
def _mrad(infocode, doc_id="d"):
    path = next(MRAD_FIXTURES.glob(f"*-{infocode}-A_001-*.xml"))
    b = S1000dGraphBuilder(doc_id=doc_id)
    root = b.parse_data_module(path.read_bytes())
    return b, URIRef(root)


def _mrad_chunks(infocode):
    from doc_tools.utils.xml_chunks import extract_chunks_from_graph
    b, root = _mrad(infocode)
    return extract_chunks_from_graph(b.graph, str(root), "MAINTENANCE")


_WARN = "Disconnect power before removal."


def _dmc_for(infocode):
    return _mrad(infocode)[1]


def test_mrad_520a_and_720a_emit_the_warning_literal_and_node():
    for code in ("520A", "720A"):
        b, root = _mrad(code)
        g = b.graph
        assert (root, MIL.hasWarning, Literal(_WARN)) in g
        assert (MIL["warning-d-1"], MIL.hasWarningText, Literal(_WARN)) in g
        assert (MIL["warning-d-1"], RDF.type, MIL.Warning) in g
        assert (root, MIL.hasWarningNode, MIL["warning-d-1"]) in g


def test_mrad_modules_without_reqsafety_emit_no_warning_at_all():
    for code in ("040A", "320A", "421A", "941A"):
        b, root = _mrad(code)
        assert not list(b.graph.triples((None, MIL.hasWarning, None))), code
        assert not list(b.graph.triples((None, MIL.hasWarningNode, None))), code


def test_mrad_520a_warning_chunks_once_with_no_duplicate_row():
    chunks = _mrad_chunks("520A")
    warn = [c for c in chunks if c["text"] == _WARN]
    assert len(warn) == 1
    assert warn[0]["section"] == "warning:1"


def test_mrad_421a_isolation_tree_is_keyed_on_the_path():
    b, root = _mrad("421A")
    g = b.graph
    steps = {str(s) for s in g.subjects(RDF.type, MIL.IsolationStep)}
    assert steps == {str(MIL[f"isostep-d-{p}"])
                     for p in ("1", "1-yes-1", "1-yes-1-yes-1")}
    ans = MIL["isoanswer-d-1-yes-1-yes-1-yes"]
    assert (ans, MIL.hasActionText, Literal("Replace array module.")) in g
    targets = set(g.objects(ans, MIL.refersToDataModule))
    assert targets == {_dmc_for("520A"), _dmc_for("720A")}
    # the nesting is linked answer -> next step
    assert (MIL["isoanswer-d-1-yes"], MIL.hasNextStep, MIL["isostep-d-1-yes-1"]) in g
    # a dmRef of the deepest answer is not credited to a shallower one
    assert not list(g.objects(MIL["isoanswer-d-1-yes"], MIL.refersToDataModule))


def test_mrad_421a_module_level_dmrefs_are_unchanged():
    b, root = _mrad("421A")
    # brexDmRef self-reference is excluded; the two answer dmRefs remain.
    assert set(b.graph.objects(root, MIL.refersToDataModule)) == {
        _dmc_for("520A"), _dmc_for("720A")}
    assert len(list(b.graph.objects(root, MIL.refersToDataModule))) == 2


def test_mrad_421a_chunks_the_isolation_tree():
    chunks = _mrad_chunks("421A")
    by_section = {}
    for c in chunks:
        by_section.setdefault(c["section"], []).append(c["text"])
    assert by_section["isolation:1-yes-1-yes-1:yes"] == ["Replace array module."]
    assert by_section["isolation:1"] == [
        "Re-run BIT. Does fault code MRAD-ARR-0417 report again?"]
    assert len(by_section["isolation:1-yes-1"]) == 1
    assert len(by_section["isolation:1-yes-1-yes-1"]) == 1


def test_mrad_520a_tool_is_labelled_by_name_and_keeps_its_part_number():
    b, root = _mrad("520A")
    g = b.graph
    tool = MIL["tool-d-ODM-SE-0001"]
    assert (tool, MIL.hasPartNumber, Literal("ODM-SE-0001")) in g
    assert (tool, RDFS.label, Literal("array module extraction tool")) in g
    assert (tool, MIL.hasName, Literal("array module extraction tool")) in g
    assert {str(t) for t in g.subjects(RDF.type, MIL.Tool)} == {str(tool)}


def test_mrad_spares_and_catalog_items_are_not_tools():
    for code in ("720A", "941A"):
        b, root = _mrad(code)
        g = b.graph
        tools = set(g.subjects(RDF.type, MIL.Tool))
        for spare_name in ("array module", "connector gasket", "screw"):
            assert not any((t, RDFS.label, Literal(spare_name)) in g for t in tools)
        assert not list(g.triples((None, MIL.hasName, Literal("array module")))), code
    assert not list(_mrad("941A")[0].graph.subjects(RDF.type, MIL.Tool))


def test_mrad_320a_planning_sections_carry_prose_and_the_interval():
    b, root = _mrad("320A")
    g = b.graph
    secs = set(g.subjects(RDF.type, MIL.PlanningSection))
    assert len(secs) == 2
    periodic = MIL["mpsection-d-Periodic_Array_Inspection"]
    oncond = MIL["mpsection-d-On-Condition_Replacement"]
    assert secs == {periodic, oncond}
    iv = MIL["interval-d-Periodic_Array_Inspection"]
    assert (periodic, MIL.hasPlanningInterval, iv) in g
    assert (iv, RDFS.label, Literal("180 days")) in g
    assert any("inspect the array face" in str(t)
               for t in g.objects(periodic, MIL.hasPlanningText))
    assert any(str(t).startswith("Replace the array module on a confirmed BIT")
               for t in g.objects(oncond, MIL.hasPlanningText))
    assert not list(g.objects(oncond, MIL.hasPlanningInterval))
    assert list(g.objects(root, MIL.hasPlanningInterval)) == [iv]


def test_mrad_320a_chunks_the_planning_prose():
    chunks = _mrad_chunks("320A")
    plan = [c for c in chunks if c["section"].startswith("planning:")]
    assert any("inspect the array face" in c["text"] for c in plan)
    assert {c["section"] for c in plan} == {
        "planning:Periodic_Array_Inspection", "planning:On-Condition_Replacement"}


def test_mrad_extraction_is_deterministic_and_mints_no_blank_node():
    for code in ("520A", "421A", "320A"):
        outs = []
        for _ in range(2):
            b, _root = _mrad(code)
            outs.append(b.graph.serialize(format="nt"))
        assert outs[0] == outs[1], code
        assert "_:" not in outs[0], code
