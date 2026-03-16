import os
from lxml import etree
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS

class S1000dGraphBuilder:
    """
    Generic parser that ingests S1000D XML Data Modules and converts them 
    into a formal RDF Knowledge Graph.
    """
    
    def __init__(self):
        self.graph = Graph()
        # Define the custom S1000D namespace
        self.S1000D = Namespace('http://edgy-solutions.com/ontology/s1000d#')
        
        # Bind namespaces for prettier serialization
        self.graph.bind("s1000d", self.S1000D)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        
        # Define core Predicates
        self.REQUIRES_TOOL = self.S1000D.requiresTool
        self.HAS_PART = self.S1000D.hasPart
        self.HAS_INFO_CODE = self.S1000D.hasInfoCode
        self.HAS_SNS = self.S1000D.hasSNS

    def parse_data_module(self, xml_content: bytes) -> str:
        """
        Parses an S1000D XML Data Module and adds triples to the graph.
        Returns the DMC URI of the root node.
        """
        parser = etree.XMLParser(remove_blank_text=True, recover=True)
        root = etree.fromstring(xml_content, parser)
        
        # 1. Extract DMC (Data Module Code) using XPath
        # S1000D dmCode attributes are usually under <identAndStatusSection><dmAddress><dmIdent><dmCode>
        dm_code = root.xpath("//dmCode")[0]
        
        # Build unique DMC string
        # Attributes: modelIdentCode, systemDiffCode, systemCode, subSystemCode, subSubSystemCode, 
        # assyCode, disasCode, disasCodeVariant, infoCode, infoCodeVariant, itemLocationCode
        dmc_parts = [
            dm_code.get("modelIdentCode", ""),
            dm_code.get("systemDiffCode", ""),
            dm_code.get("systemCode", ""),
            dm_code.get("subSystemCode", ""),
            dm_code.get("subSubSystemCode", ""),
            dm_code.get("assyCode", ""),
            dm_code.get("disasCode", ""),
            dm_code.get("disasCodeVariant", ""),
            dm_code.get("infoCode", ""),
            dm_code.get("infoCodeVariant", ""),
            dm_code.get("itemLocationCode", "")
        ]
        dmc_string = "-".join([p for p in dmc_parts if p])
        dmc_uri = self.S1000D[f"dmc-{dmc_string}"]
        
        # Add root triple
        self.graph.add((dmc_uri, RDF.type, self.S1000D.DataModule))
        self.graph.add((dmc_uri, RDFS.label, Literal(dmc_string)))

        # 2. Extract SNS & InfoCode
        system_code = dm_code.get("systemCode")
        info_code = dm_code.get("infoCode")
        
        if system_code:
            self.graph.add((dmc_uri, self.HAS_SNS, Literal(system_code)))
        if info_code:
            self.graph.add((dmc_uri, self.HAS_INFO_CODE, Literal(info_code)))

        # 3. Extract Tools (requiredSupportEquip)
        # XPath for S1000D tools: //reqSupportEquip/supportEquipDescrGroup/nosupply/partnumber
        # (Standard S1000D schema locations vary, but this is a common target)
        tool_elements = root.xpath("//reqSupportEquip//partNumber")
        for tool in tool_elements:
            pn = tool.text.strip() if tool.text else None
            if pn:
                tool_uri = self.S1000D[f"part-{pn}"]
                self.graph.add((tool_uri, RDF.type, self.S1000D.Tool))
                self.graph.add((dmc_uri, self.REQUIRES_TOOL, tool_uri))

        # 4. Extract Parts (requiredSpares)
        # XPath for S1000D spares: //reqSpares/spareDescrGroup/nosupply/partnumber
        part_elements = root.xpath("//reqSpares//partNumber")
        for part in part_elements:
            pn = part.text.strip() if part.text else None
            if pn:
                part_uri = self.S1000D[f"part-{pn}"]
                self.graph.add((part_uri, RDF.type, self.S1000D.Part))
                self.graph.add((dmc_uri, self.HAS_PART, part_uri))

        return str(dmc_uri)

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)
