from lxml import etree
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS
import re

class DitaGraphBuilder:
    """
    Parser for DITA XML files, extracting tasks and topics into an RDF Knowledge Graph.
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
        self.HAS_INSTRUCTION = self.MIL.hasInstructionText
        self.HAS_FIGURE = self.MIL.hasFigure

    def parse_data_module(self, xml_content: bytes) -> str:
        """
        Parses a DITA XML task/topic and adds triples to the graph.
        """
        parser = etree.XMLParser(remove_blank_text=True, recover=True)
        root = etree.fromstring(xml_content, parser)
        
        # 1. Extract ID from <task> or <topic>
        node_id = root.xpath("/task/@id | /topic/@id")
        if not node_id:
            # Fallback to any id at root
            node_id = root.xpath("/*/@id")
            
        id_val = node_id[0] if node_id else "unknown-dita-node"
        node_uri = self.MIL[f"dita-{id_val}"]
        
        # Add root triple
        self.graph.add((node_uri, RDF.type, self.MIL.DitaNode))
        self.graph.add((node_uri, RDFS.label, Literal(id_val)))

        # 2. Extract Prerequisites and Supplies (Tools/Parts)
        # Mapping <prereq> or <supply> to requiresTool/hasPart
        prereqs = root.xpath("//prereq | //supply")
        for p in prereqs:
            text = "".join(p.itertext()).strip()
            if text:
                # Simple heuristic: if it looks like a part number or tool name
                # For this implementation, we map them as generic tools/parts
                clean_text = re.sub(r'[^a-zA-Z0-9_]', '', text.replace(' ', '_'))
                item_uri = self.MIL[f"item-{clean_text}"]
                self.graph.add((node_uri, self.REQUIRES_TOOL, item_uri))
                self.graph.add((item_uri, RDFS.label, Literal(text)))

        # 3. Extract Instruction Text from <steps>
        steps = root.xpath("//steps")
        for s in steps:
            # Flatten all step text
            instruction_text = "".join(s.itertext()).strip()
            if instruction_text:
                self.graph.add((node_uri, self.HAS_INSTRUCTION, Literal(instruction_text)))

        # 4. Extract Figures (DITA uses <fig> with <image href="...">)
        fig_elements = root.xpath("//fig")
        for idx, fig_el in enumerate(fig_elements):
            fig_id = fig_el.get("id", f"fig_{idx}")
            title_el = fig_el.find(".//title")
            title = title_el.text.strip() if title_el is not None and title_el.text else fig_id
            
            # Get image href
            image_el = fig_el.find(".//image")
            href = image_el.get("href", "") if image_el is not None else ""
            
            figure_uri = self.MIL[f"fig-{fig_id}"]
            self.graph.add((figure_uri, RDF.type, self.MIL.Figure))
            self.graph.add((figure_uri, RDFS.label, Literal(title)))
            if href and self.bucket and self.doc_id:
                full_s3_url = f"s3://{self.bucket}/{self.doc_id}/generated/images/{href}.png"
                self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
            elif href:
                self.graph.add((figure_uri, self.MIL.hasURL, Literal(href)))
            self.graph.add((node_uri, self.HAS_FIGURE, figure_uri))

        return str(node_uri)

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)
