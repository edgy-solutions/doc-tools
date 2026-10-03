import os
import re
from lxml import etree
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from doc_tools.parsers.dmc_canonicalizer import assemble_canonical_dmc
from doc_tools.parsers.mil_info_code_map import (
    DATA_MODULE_ROOT,
    classify_data_module,
)

# Characters kept in a URI-local fragment. Hyphen and dot are preserved on
# purpose, unlike the sibling parsers' `[^a-zA-Z0-9_]` scrub: in S1000D a part
# number's hyphens are significant (ODM-SE-0001 and ODMSE-0001 are different
# parts), and both characters are legal in a URI fragment, so stripping them
# only loses information. Everything else — spaces included, which would make
# the Turtle unserializable — is replaced.
_FRAGMENT_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")

# Used when a builder is constructed with no doc_id (the bare
# `S1000dGraphBuilder()` form the unit tests use). Explicit, so an unscoped
# subject is READABLE AS unscoped in the graph rather than looking like a
# document called "". Nothing on the ingest path hits this: xml_ingestion.py
# always derives doc_id from the S3 key.
UNSCOPED_DOC_SLUG = "nodoc"


def _fragment(value: str) -> str:
    """Make `value` safe to splice into a URI local name."""
    return _FRAGMENT_UNSAFE.sub("_", value.strip())


class S1000dGraphBuilder:
    """
    Generic parser that ingests S1000D XML Data Modules and converts them 
    into a formal RDF Knowledge Graph using a unified MIL ontology.
    """
    
    def __init__(self, bucket: str = "", doc_id: str = "", image_prefix: str = ""):
        self.graph = Graph()
        self.bucket = bucket
        self.doc_id = doc_id
        self.image_prefix = image_prefix
        # Define the unified MIL namespace (shared with DITA and IADS)
        self.MIL = Namespace('http://edgy-solutions.com/ontology/mil#')
        
        # Bind namespaces for prettier serialization
        self.graph.bind("mil", self.MIL)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        
        # Define core Predicates
        self.REQUIRES_TOOL = self.MIL.requiresTool
        self.HAS_PART = self.MIL.hasPart
        self.HAS_INFO_CODE = self.MIL.hasInfoCode
        self.HAS_SNS = self.MIL.hasSNS
        self.HAS_FIGURE = self.MIL.hasFigure
        self.HAS_PART_NUMBER = self.MIL.hasPartNumber

    @property
    def doc_slug(self) -> str:
        """The document scope spliced into per-document subject URIs.

        Part, tool and figure subjects are scoped by this so two documents
        cannot coin the same subject. Before scoping, `mil:part-ODM-SE-0001`
        was coined by two of the six mock OpenDDIL modules and MERGED into one
        node carrying both modules' edges (measured 2026-10-02); an unlabelled
        `<figure>` coined `mil:fig-fig_0` — named after a loop index — which
        every other document with an unlabelled figure collides on. On a
        shared corpus that silently fuses unrelated documents' parts lists,
        and it also makes a doc_id-keyed rollback impossible: deleting one
        document's subjects would take another document's edges with them.
        (Same shape as the component-IRI finding on the PCN side: a
        delete-by-subject write must key on the per-document node.)
        """
        return _fragment(self.doc_id) or UNSCOPED_DOC_SLUG

    def parse_data_module(self, xml_content: bytes) -> str:
        """
        Parses an S1000D XML Data Module and adds triples to the graph.
        Returns the DMC URI of the root node.
        """
        parser = etree.XMLParser(remove_blank_text=True, recover=True)
        root = etree.fromstring(xml_content, parser)
        
        # 1. Extract DMC (Data Module Code) using XPath
        dm_code_list = root.xpath("//dmCode")
        if not dm_code_list:
            return "unknown-s1000d-dmc"
            
        dm_code = dm_code_list[0]
        
        # Build the DMC string via the SHARED canonicalizer. Do NOT
        # reimplement the join here — dmc_canonicalizer is the single source
        # of truth and s1000d_ingest.extract_facts assembles through the same
        # function, so the two parsers cannot drift. The inline join this
        # replaced produced a different ID from the same input (measured
        # 2026-10-02: it emitted subSystemCode and subSubSystemCode as
        # separate hyphen groups where the canonical form concatenates them,
        # dropped empty positions instead of preserving them, and did not
        # uppercase), so NO S1000D DMC URI this builder has ever written
        # matched its authored DMC.
        #
        # `disassyCode` / `disassyCodeVariant` are the S1000D 4.x spellings;
        # `disasCode` / `disasCodeVariant` are the short forms. Reading only
        # the short names silently dropped the whole disassembly position on
        # 4.x documents, which also made two modules differing ONLY in that
        # code collide on one URI. Same fallback order as
        # s1000d_ingest.py:113.
        info_code = dm_code.get("infoCode", "")
        dmc_string = assemble_canonical_dmc(
            mic=dm_code.get("modelIdentCode", ""),
            sdc=dm_code.get("systemDiffCode", ""),
            sysc=dm_code.get("systemCode", ""),
            ssc=dm_code.get("subSystemCode", ""),
            sssc=dm_code.get("subSubSystemCode", ""),
            asy=dm_code.get("assyCode", ""),
            dis=dm_code.get("disassyCode", "") or dm_code.get("disasCode", ""),
            dvar=(dm_code.get("disassyCodeVariant", "")
                  or dm_code.get("disasCodeVariant", "")),
            info=info_code,
            ivar=dm_code.get("infoCodeVariant", ""),
            itemloc=dm_code.get("itemLocationCode", ""),
        )
        dmc_uri = self.MIL[f"dmc-{dmc_string}"]

        # Add root triple. The data module is typed with its DETERMINISTIC
        # content kind (mil:DescriptiveDataModule, mil:ProcedureDataModule,
        # mil:FaultIsolationDataModule, mil:IllustratedPartsDataModule) as
        # well as the mil:DataModule root.
        #
        # Before this, the ONLY type emitted here was the bare root, so every
        # data module was indistinguishable downstream — a fault-isolation
        # module, a procedure and an IPD all landed identically (measured
        # 2026-10-02 over the six OpenDDIL modules: zero classified kinds).
        # classify_data_module is the deterministic table, no LLM.
        #
        # BOTH types are emitted on purpose: the kinds are rdfs:subClassOf
        # mil:DataModule in the TBox, but Jena serves these graphs without
        # reasoning, so a consumer querying `?s a mil:DataModule` would stop
        # seeing classified modules if the root were dropped.
        kind_uri = URIRef(classify_data_module(info_code))
        self.graph.add((dmc_uri, RDF.type, self.MIL.DataModule))
        if str(kind_uri) != DATA_MODULE_ROOT:
            self.graph.add((dmc_uri, RDF.type, kind_uri))
        self.graph.add((dmc_uri, RDFS.label, Literal(dmc_string)))

        # 2. Extract SNS & InfoCode
        system_code = dm_code.get("systemCode")

        if system_code:
            self.graph.add((dmc_uri, self.HAS_SNS, Literal(system_code)))
        if info_code:
            self.graph.add((dmc_uri, self.HAS_INFO_CODE, Literal(info_code)))

        scope = self.doc_slug

        # 3. Extract Tools (requiredSupportEquip)
        #
        # The prefix is `tool-`, not `part-`. A tool and a spare with the SAME
        # part number previously coined ONE subject that got both rdf:type
        # mil:Tool and rdf:type mil:Part, so a consumer asking "is this a
        # consumable spare" got yes for a torque wrench. `tool-` also matches
        # what iads_rdf.py:57 and mil_std_40051_rdf.py:166 already use, so
        # S1000D was the sole outlier.
        tool_elements = root.xpath("//reqSupportEquip//partNumber")
        for tool in tool_elements:
            pn = tool.text.strip() if tool.text else None
            if pn:
                tool_uri = self.MIL[f"tool-{scope}-{_fragment(pn)}"]
                self.graph.add((tool_uri, RDF.type, self.MIL.Tool))
                # The bare part number stays on the node as a literal. The
                # subject is document-scoped, so cross-document identity is
                # no longer readable off the URI; this predicate is how a
                # consumer still answers "which documents mention ODM-SE-0001"
                # (join on the literal), without the subjects merging.
                self.graph.add((tool_uri, self.HAS_PART_NUMBER, Literal(pn)))
                self.graph.add((tool_uri, RDFS.label, Literal(pn)))
                self.graph.add((dmc_uri, self.REQUIRES_TOOL, tool_uri))

        # 4. Extract Parts (requiredSpares)
        part_elements = root.xpath("//reqSpares//partNumber")
        for part in part_elements:
            pn = part.text.strip() if part.text else None
            if pn:
                part_uri = self.MIL[f"part-{scope}-{_fragment(pn)}"]
                self.graph.add((part_uri, RDF.type, self.MIL.Part))
                self.graph.add((part_uri, self.HAS_PART_NUMBER, Literal(pn)))
                self.graph.add((part_uri, RDFS.label, Literal(pn)))
                self.graph.add((dmc_uri, self.HAS_PART, part_uri))

        # 5. Extract Figures
        figure_elements = root.xpath("//figure")
        for idx, fig_el in enumerate(figure_elements):
            fig_id = fig_el.get("id", f"fig_{idx}")
            title_el = fig_el.find(".//title")
            title = title_el.text.strip() if title_el is not None and title_el.text else fig_id
            
            # Get graphic filename: try infoEntityIdent first (S1000D), then boardno (IADS-style)
            graphic_el = fig_el.find(".//graphic")
            info_entity = ""
            if graphic_el is not None:
                info_entity = graphic_el.get("infoEntityIdent", "") or graphic_el.get("boardno", "")
            
            figure_uri = self.MIL[f"fig-{scope}-{_fragment(fig_id)}"]
            self.graph.add((figure_uri, RDF.type, self.MIL.Figure))
            self.graph.add((figure_uri, RDFS.label, Literal(title)))
            if info_entity and self.image_prefix:
                full_s3_url = f"{self.image_prefix}{info_entity}.png"
                self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
            elif info_entity:
                self.graph.add((figure_uri, self.MIL.hasURL, Literal(info_entity)))
            self.graph.add((dmc_uri, self.HAS_FIGURE, figure_uri))

        return str(dmc_uri)

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)
