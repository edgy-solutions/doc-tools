from lxml import etree
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS
import re

class IadsGraphBuilder:
    """
    Parser for IADS XML files, extracting node-based structures into an RDF Knowledge Graph.
    """
    
    def __init__(self, bucket: str = "", doc_id: str = ""):
        self.graph = Graph()
        self.bucket = bucket
        self.doc_id = doc_id
        # Define the unified MIL namespace
        self.MIL = Namespace('http://edgy-solutions.com/ontology/mil#')
        
        # Bind namespaces
        self.graph.bind("mil", self.MIL)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        
        # Standard MIL Predicates
        self.REQUIRES_TOOL = self.MIL.requiresTool
        self.HAS_PART = self.MIL.hasPart
        self.HAS_WARNING = self.MIL.hasWarning
        self.HAS_INSTRUCTION = self.MIL.hasInstructionText
        self.HAS_FIGURE = self.MIL.hasFigure

    def parse_data_module(self, xml_content: bytes) -> str:
        """
        Parses an IADS XML module and adds triples to the graph.
        """
        parser = etree.XMLParser(remove_blank_text=True, recover=True)
        root = etree.fromstring(xml_content, parser)
        
        # 1. Extract Unique Node ID
        # IADS often uses <node> elements with id attributes
        node_id = root.xpath("//@id")
        id_val = node_id[0] if node_id else "unknown-iads-node"
        node_uri = self.MIL[f"iads-{id_val}"]
        
        # Add root triple
        self.graph.add((node_uri, RDF.type, self.MIL.IadsNode))
        self.graph.add((node_uri, RDFS.label, Literal(id_val)))

        # 2. Extract Tools, Parts, and Warnings
        # Standardizing on MIL predicates
        
        # Tools
        tools = root.xpath("//tool | //supportEquip")
        for t in tools:
            name = "".join(t.itertext()).strip()
            if name:
                clean_name = re.sub(r'[^a-zA-Z0-9_]', '', name.replace(' ', '_'))
                tool_uri = self.MIL[f"tool-{clean_name}"]
                self.graph.add((node_uri, self.REQUIRES_TOOL, tool_uri))
                self.graph.add((tool_uri, RDFS.label, Literal(name)))

        # Parts
        parts = root.xpath("//part | //spare")
        for p in parts:
            name = "".join(p.itertext()).strip()
            if name:
                clean_name = re.sub(r'[^a-zA-Z0-9_]', '', name.replace(' ', '_'))
                part_uri = self.MIL[f"part-{clean_name}"]
                self.graph.add((node_uri, self.HAS_PART, part_uri))
                self.graph.add((part_uri, RDFS.label, Literal(name)))

        # Warnings
        warnings = root.xpath("//warning | //caution")
        for w in warnings:
            text = "".join(w.itertext()).strip()
            if text:
                self.graph.add((node_uri, self.HAS_WARNING, Literal(text)))

        # Instruction Text (if available in a body/content tag)
        content = root.xpath("//content | //body | //step")
        if content:
            full_text = " ".join(["".join(c.itertext()).strip() for c in content if "".join(c.itertext()).strip()])
            if full_text:
                self.graph.add((node_uri, self.HAS_INSTRUCTION, Literal(full_text)))

        # 5. Extract Figures & Graphics
        # IADS uses <graphic boardno="..."> as primary figure reference
        fig_idx = 0
        seen_figs = set()
        
        # Primary: <graphic boardno="..."> elements
        graphic_elements = root.xpath("//graphic[@boardno]")
        for g in graphic_elements:
            boardno = g.get("boardno", "").strip()
            if boardno and boardno not in seen_figs:
                seen_figs.add(boardno)
                figure_uri = self.MIL[f"fig-{boardno}"]
                self.graph.add((figure_uri, RDF.type, self.MIL.Figure))
                self.graph.add((figure_uri, RDFS.label, Literal(boardno)))
                if self.bucket and self.doc_id:
                    full_s3_url = f"s3://{self.bucket}/{self.doc_id}/generated/images/{boardno}.png"
                    self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
                else:
                    self.graph.add((figure_uri, self.MIL.hasURL, Literal(boardno)))
                self.graph.add((node_uri, self.HAS_FIGURE, figure_uri))

        # Fallback: <figure> tags with id attribute
        figure_elements = root.xpath("//figure[@id]")
        for fig_el in figure_elements:
            fig_id = fig_el.get("id", "").strip()
            if fig_id and fig_id not in seen_figs:
                seen_figs.add(fig_id)
                title_el = fig_el.find(".//title")
                title = title_el.text.strip() if title_el is not None and title_el.text else fig_id
                figure_uri = self.MIL[f"fig-{fig_id}"]
                self.graph.add((figure_uri, RDF.type, self.MIL.Figure))
                self.graph.add((figure_uri, RDFS.label, Literal(title)))
                # Check for nested graphic with boardno
                nested_graphic = fig_el.find(".//graphic")
                if nested_graphic is not None:
                    info_entity = nested_graphic.get("boardno", "") or nested_graphic.get("infoEntityIdent", "")
                    if info_entity:
                        if self.bucket and self.doc_id:
                            full_s3_url = f"s3://{self.bucket}/{self.doc_id}/generated/images/{info_entity}.png"
                            self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
                        else:
                            self.graph.add((figure_uri, self.MIL.hasURL, Literal(info_entity)))
                self.graph.add((node_uri, self.HAS_FIGURE, figure_uri))

        return str(node_uri)

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)
