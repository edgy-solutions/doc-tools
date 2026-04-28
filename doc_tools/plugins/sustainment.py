from typing import List, Optional, Tuple, Any
from pydantic import BaseModel, Field
from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode

# --- BAML-ready Schemas (Domain: Sustainment) ---
class PartImpact(BaseModel):
    affected_mpn: str
    replacement_mpn: Optional[str] = None
    ltb_date: Optional[str] = None

class SustainmentNotice(BaseModel):
    doc_id: str
    doc_type: str
    pub_date: str
    mfr: str
    categories: List[str]
    summary: str
    impacted_parts: List[PartImpact]

class SustainmentAugmentation(BaseModel):
    notice: SustainmentNotice

# --- Plugin Implementation ---
class SustainmentPlugin(AugmentationPlugin):
    """
    Sustainment (PCN/PDN) extraction logic.
    """
    
    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        try:
            from doc_tools.baml_client.sync_client import b
            from doc_tools.baml_client.types import SustainmentNotice as BamlSustainmentNotice
            
            # Execute BAML LLM inference
            baml_response: BamlSustainmentNotice = b.ExtractSustainment(doc=section.content)
            
            parts = []
            for p in baml_response.impacted_parts:
                parts.append(PartImpact(
                    affected_mpn=p.affected_mpn,
                    replacement_mpn=p.replacement_mpn,
                    ltb_date=p.ltb_date
                ))
                
            notice = SustainmentNotice(
                doc_id=baml_response.doc_id,
                doc_type=baml_response.doc_type,
                pub_date=baml_response.pub_date,
                mfr=baml_response.mfr,
                categories=[getattr(c, 'value', c) for c in baml_response.categories],
                summary=baml_response.summary,
                impacted_parts=parts
            )
                
            augmentation = SustainmentAugmentation(notice=notice)
            
        except ImportError:
            # Fallback mock for testing environments
            augmentation = SustainmentAugmentation(
                notice=SustainmentNotice(
                    doc_id="MOCK-PDN-123",
                    doc_type="PDN",
                    pub_date="2026-04-28",
                    mfr="Mock Manufacturer",
                    categories=["Discontinuation"],
                    summary="Mock summary of discontinuation.",
                    impacted_parts=[
                        PartImpact(
                            affected_mpn="MOCK-PART-1",
                            replacement_mpn="MOCK-PART-2",
                            ltb_date="2026-12-31"
                        )
                    ]
                )
            )
        
        return DocumentNode(
            base_extraction=section,
            domain_augmentation=augmentation
        )

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any, doc_id: str = "", image_prefix: str = "") -> Tuple[List[str], List[str]]:
        cypher_queries = []
        sparql_queries = []
        
        for node in nodes:
            sec = node.base_extraction
            aug = node.domain_augmentation
            
            if not isinstance(aug, SustainmentAugmentation):
                continue
                
            notice = aug.notice
            
            # Use unified hardware ID linking Graph to Vector DB
            section_id = sec.node_id or f"section_{sec.page_start}_{sec.title}"
            
            # Create Section node
            cypher_queries.append({
                "query": f"""
                MERGE (p:{config.graph_child_label}:{self.domain_label} {{id: $section_id}})
                SET p.title = $title
                """,
                "params": {
                    "section_id": section_id,
                    "title": sec.title
                }
            })
            
            # --- NEO4J CYPHER ---
            edge_cypher = f"""
            MERGE (p:{config.graph_child_label}:{self.domain_label} {{id: $section_id}})
            MERGE (n:SustainmentNotice:{self.domain_label} {{id: $notice_id}})
            SET n.pub_date = $pub_date, n.mfr = $mfr, n.type = $doc_type
            MERGE (p)-[:GOVERNED_BY]->(n)
            
            WITH n
            UNWIND $impacted_parts AS part
            MERGE (c:Component:{self.domain_label} {{mpn: part.affected_mpn}})
            MERGE (c)-[:SUBJECT_TO]->(n)
            
            WITH n, c, part
            FOREACH (r IN CASE WHEN part.replacement_mpn IS NOT NULL AND part.replacement_mpn <> "" THEN [1] ELSE [] END |
                MERGE (alt:Component:{self.domain_label} {{mpn: part.replacement_mpn}})
                MERGE (c)-[:REPLACED_BY {{ltb_date: part.ltb_date}}]->(alt)
            )
            """
            
            parts_params = [
                {
                    "affected_mpn": p.affected_mpn,
                    "replacement_mpn": p.replacement_mpn,
                    "ltb_date": p.ltb_date
                } for p in notice.impacted_parts
            ]
            
            cypher_queries.append({
                "query": edge_cypher,
                "params": {
                    "section_id": section_id,
                    "notice_id": notice.doc_id,
                    "pub_date": notice.pub_date,
                    "mfr": notice.mfr,
                    "doc_type": notice.doc_type,
                    "impacted_parts": parts_params
                }
            })
            
            # --- JENA SPARQL/RDF ---
            # Safe URIs
            safe_notice_id = notice.doc_id.replace(' ', '_').replace('"', '')
            
            # Determine class based on doc_type
            if notice.doc_type.upper() == "PDN":
                notice_class = "pcn:ProductDiscontinuationNotice"
            else:
                notice_class = "pcn:ProcessChangeNotification"
                
            sparql = f"""
            PREFIX pcn: <http://internal/sustainment/pcn#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            
            INSERT DATA {{
                <http://internal/sustainment/doc/{safe_notice_id}> a {notice_class} .
            """
            
            for cat in notice.categories:
                safe_cat = cat.replace(' ', '_')
                sparql += f"""
                <http://internal/sustainment/doc/{safe_notice_id}> pcn:hasChangeCategory pcn:{safe_cat} .
                """
                
            for part in notice.impacted_parts:
                safe_mpn = part.affected_mpn.replace(' ', '_')
                sparql += f"""
                <http://internal/components/{safe_mpn}> pcn:subjectToNotice <http://internal/sustainment/doc/{safe_notice_id}> .
                """
                if part.ltb_date:
                    sparql += f"""
                    <http://internal/components/{safe_mpn}> pcn:hasLastTimeBuyDate "{part.ltb_date}"^^xsd:date .
                    """
                if part.replacement_mpn:
                    safe_rep = part.replacement_mpn.replace(' ', '_')
                    sparql += f"""
                    <http://internal/components/{safe_mpn}> pcn:hasReplacement <http://internal/components/{safe_rep}> .
                    """
                    
            sparql += "}"
            
            sparql_queries.append(sparql)
            
        return cypher_queries, sparql_queries