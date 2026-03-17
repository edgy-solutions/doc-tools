from lxml import etree
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS
import re

class IadsGraphBuilder:
    """
    Parser for IADS XML files, extracting node-based structures into an RDF Knowledge Graph.
    """
    
    def __init__(self):
        self.graph = Graph()
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

        return str(node_uri)

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)
