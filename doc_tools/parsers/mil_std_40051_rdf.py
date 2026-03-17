import lxml.etree as etree
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS
import re

class MilStd40051GraphBuilder:
    """
    Parser for US Army MIL-STD-40051 XML technical manuals.
    Maps Army Work Packages to a unified military ontology.
    """
    
    def __init__(self):
        self.graph = Graph()
        self.MIL = Namespace("http://edgy-solutions.com/ontology/mil#")
        self.graph.bind("mil", self.MIL)
        self.root_node = None

    def parse_data_module(self, xml_content: bytes) -> str:
        """
        Parses a 40051 Work Package and extracts semantic entities.
        """
        parser = etree.XMLParser(recover=True, remove_blank_text=True)
        tree = etree.fromstring(xml_content, parser=parser)
        
        # 1. Identity Extraction (Work Package Number)
        # Often found in //wpno or //wpid/@wpno
        wp_id = tree.xpath("//wpno/text()") or tree.xpath("//wpid/@wpno")
        if wp_id:
            wp_id = str(wp_id[0]).strip()
        else:
            # Fallback to root id attribute
            wp_id = tree.xpath("/@id")
            wp_id = str(wp_id[0]) if wp_id else "unknown_wp"

        node_uri = URIRef(self.MIL[f"wpn-{wp_id}"])
        self.root_node = node_uri
        
        # Classify as DataModule and WorkPackage
        self.graph.add((node_uri, RDF.type, self.MIL.DataModule))
        self.graph.add((node_uri, RDF.type, self.MIL.WorkPackage))
        self.graph.add((node_uri, RDFS.label, Literal(f"Work Package {wp_id}")))

        # 2. Tools & Support Equipment
        # Looking for //supportreqs//name or //reqtools
        tools = tree.xpath("//supportreqs//name/text()") or tree.xpath("//reqtools/text()")
        for tool in set(tools):
            tool_name = str(tool).strip()
            if tool_name:
                clean_tool_name = re.sub(r'[^a-zA-Z0-9_]', '', tool_name.replace(' ', '_'))
                tool_uri = URIRef(self.MIL[f"tool-{clean_tool_name}"])
                self.graph.add((tool_uri, RDF.type, self.MIL.Tool))
                self.graph.add((tool_uri, RDFS.label, Literal(tool_name)))
                self.graph.add((node_uri, self.MIL.requiresTool, tool_uri))

        # 3. Spare Parts & Materials
        # Looking for //sparesreq//name or //partno
        parts = tree.xpath("//sparesreq//name/text()") or tree.xpath("//partno/text()")
        for part in set(parts):
            part_name = str(part).strip()
            if part_name:
                clean_part_name = re.sub(r'[^a-zA-Z0-9_]', '', part_name.replace(' ', '_'))
                part_uri = URIRef(self.MIL[f"part-{clean_part_name}"])
                self.graph.add((part_uri, RDF.type, self.MIL.Part))
                self.graph.add((part_uri, RDFS.label, Literal(part_name)))
                self.graph.add((node_uri, self.MIL.hasPart, part_uri))

        # 4. Warnings and Cautions
        warnings = tree.xpath("//warning//para/text()") or tree.xpath("//warning/text()")
        cautions = tree.xpath("//caution//para/text()") or tree.xpath("//caution/text()")
        
        for msg in set(warnings + cautions):
            text = str(msg).strip()
            if text:
                self.graph.add((node_uri, self.MIL.hasWarning, Literal(text)))

        # 5. Instructions (Procedures)
        # Extract step text (e.g., //step1/para or //proc//para)
        steps = tree.xpath("//step1//para/text()") or tree.xpath("//proc//para/text()")
        for step in steps:
            text = str(step).strip()
            if text:
                self.graph.add((node_uri, self.MIL.hasInstructionText, Literal(text)))

        return str(node_uri)

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)
