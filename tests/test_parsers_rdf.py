"""Unit tests for the MIL-spec XML -> RDF parsers (doc_tools/parsers).

These builders are the core "Semantic Translator" layer: they map S1000D, DITA,
IADS, and MIL-STD-40051 XML into a single unified MIL ontology. They were
previously exercised only at import level (~10% coverage). Each builder is pure
(lxml + rdflib, no I/O), so we feed representative XML and assert the emitted
triples directly against the in-memory graph.
"""
from rdflib import Literal, Namespace
from rdflib.namespace import RDF, RDFS

from doc_tools.parsers.s1000d_rdf import S1000dGraphBuilder
from doc_tools.parsers.dita_rdf import DitaGraphBuilder
from doc_tools.parsers.iads_rdf import IadsGraphBuilder
from doc_tools.parsers.mil_std_40051_rdf import MilStd40051GraphBuilder

MIL = Namespace("http://edgy-solutions.com/ontology/mil#")
PREFIX = "https://cdn.example/img/"


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


def test_s1000d_extracts_dmc_tools_parts_and_figures():
    b = S1000dGraphBuilder(image_prefix=PREFIX)
    root = b.parse_data_module(S1000D_XML)
    g = b.graph

    dmc = MIL["dmc-AE-A-32-1-0-00-00-A-520-A-A"]
    assert root == str(dmc)
    assert (dmc, RDF.type, MIL.DataModule) in g
    assert (dmc, MIL.hasSNS, Literal("32")) in g
    assert (dmc, MIL.hasInfoCode, Literal("520")) in g
    # tool
    assert (MIL["part-WRENCH-01"], RDF.type, MIL.Tool) in g
    assert (dmc, MIL.requiresTool, MIL["part-WRENCH-01"]) in g
    # part
    assert (MIL["part-SEAL-99"], RDF.type, MIL.Part) in g
    assert (dmc, MIL.hasPart, MIL["part-SEAL-99"]) in g
    # figure (URL composed from infoEntityIdent + image_prefix)
    assert (MIL["fig-fig1"], RDF.type, MIL.Figure) in g
    assert (MIL["fig-fig1"], RDFS.label, Literal("Assembly View")) in g
    assert (MIL["fig-fig1"], MIL.hasURL, Literal(f"{PREFIX}ICN-001.png")) in g
    assert (dmc, MIL.hasFigure, MIL["fig-fig1"]) in g


def test_s1000d_missing_dmcode_returns_sentinel():
    b = S1000dGraphBuilder()
    assert b.parse_data_module(b"<dmodule><content/></dmodule>") == "unknown-s1000d-dmc"


def test_s1000d_serialize_emits_turtle():
    b = S1000dGraphBuilder()
    b.parse_data_module(S1000D_XML)
    ttl = b.serialize()
    assert isinstance(ttl, str) and "mil:" in ttl and "DataModule" in ttl


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
    assert (MIL["fig-FIG-9"], MIL.hasURL, Literal(f"{PREFIX}FIG-9.png")) in g
    assert (node, MIL.hasFigure, MIL["fig-FIG-9"]) in g


def test_milstd_40051_falls_back_to_unknown_wp():
    b = MilStd40051GraphBuilder()
    root = b.parse_data_module(b"<wp><content/></wp>")
    assert root == str(MIL["wpn-unknown_wp"])
