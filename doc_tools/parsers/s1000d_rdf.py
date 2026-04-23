import os
from lxml import etree
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS

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
        
        # Build unique DMC string
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
        dmc_uri = self.MIL[f"dmc-{dmc_string}"]
        
        # Add root triple
        self.graph.add((dmc_uri, RDF.type, self.MIL.DataModule))
        self.graph.add((dmc_uri, RDFS.label, Literal(dmc_string)))

        # 2. Extract SNS & InfoCode
        system_code = dm_code.get("systemCode")
        info_code = dm_code.get("infoCode")
        
        if system_code:
            self.graph.add((dmc_uri, self.HAS_SNS, Literal(system_code)))
        if info_code:
            self.graph.add((dmc_uri, self.HAS_INFO_CODE, Literal(info_code)))

        # 3. Extract Tools (requiredSupportEquip)
        tool_elements = root.xpath("//reqSupportEquip//partNumber")
        for tool in tool_elements:
            pn = tool.text.strip() if tool.text else None
            if pn:
                tool_uri = self.MIL[f"part-{pn}"]
                self.graph.add((tool_uri, RDF.type, self.MIL.Tool))
                self.graph.add((dmc_uri, self.REQUIRES_TOOL, tool_uri))

        # 4. Extract Parts (requiredSpares)
        part_elements = root.xpath("//reqSpares//partNumber")
        for part in part_elements:
            pn = part.text.strip() if part.text else None
            if pn:
                part_uri = self.MIL[f"part-{pn}"]
                self.graph.add((part_uri, RDF.type, self.MIL.Part))
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
            
            figure_uri = self.MIL[f"fig-{fig_id}"]
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
