"""Unit tests for the MIL-spec XML -> RDF parsers (doc_tools/parsers).

These builders are the core "Semantic Translator" layer: they map S1000D, DITA,
IADS, and MIL-STD-40051 XML into a single unified MIL ontology. They were
previously exercised only at import level (~10% coverage). Each builder is pure
(lxml + rdflib, no I/O), so we feed representative XML and assert the emitted
triples directly against the in-memory graph.
"""
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
