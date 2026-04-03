from typing import List, Optional, Tuple, Any
from pydantic import BaseModel, Field
from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode

# --- BAML-ready Schemas (Domain C: Compliance) ---
class ComplianceRule(BaseModel):
    manual_reference: str
    rule_type: str
    applicable_hazard_class: Optional[str] = Field(default=None)
    target_metric: Optional[str] = Field(default=None)
    rule_description: str

class ComplianceAugmentation(BaseModel):
    rules: List[ComplianceRule]

# --- Plugin Implementation ---
class CompliancePlugin(AugmentationPlugin):
    """
    Logistics and Compliance validation logic (e.g. DAFMAN).
    """
    
    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        try:
            from doc_tools.baml_client.sync_client import b
            from doc_tools.baml_client.types import ComplianceAugmentation as BamlComplianceAugmentation
            
            # Execute BAML LLM inference
            baml_response: BamlComplianceAugmentation = b.ExtractComplianceRules(text=section.content)
            
            rules = []
            for r in baml_response.rules:
                rules.append(ComplianceRule(
                    manual_reference=r.manual_reference,
                    rule_type=r.rule_type,
                    applicable_hazard_class=r.applicable_hazard_class,
                    target_metric=r.target_metric,
                    rule_description=r.rule_description
                ))
                
            augmentation = ComplianceAugmentation(rules=rules)
            
        except ImportError:
            # Fallback mock for testing environments
            augmentation = ComplianceAugmentation(
                rules=[
                    ComplianceRule(
                        manual_reference=f"DAFMAN-DEFAULT derived from {section.title}",
                        rule_type="Safety",
                        applicable_hazard_class="1.1",
                        target_metric="Max 5 Units",
                        rule_description=f"Auto-generated mock compliance rule for {section.title}."
                    )
                ]
            )
        
        return DocumentNode(
            base_extraction=section,
            domain_augmentation=augmentation
        )

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any, doc_id: str = "") -> Tuple[List[str], List[str]]:
        cypher_queries = []
        sparql_queries = []
        
        for node in nodes:
            sec = node.base_extraction
            aug = node.domain_augmentation
            
            if not isinstance(aug, ComplianceAugmentation):
                continue
                
            # Use unified hardware ID linking Graph to Vector DB
            section_id = sec.node_id or f"section_{sec.page_start}_{sec.title}"
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
            
            for rule_idx, rule in enumerate(aug.rules):
                # Generate unique rule ID
                raw_ref = rule.manual_reference.replace(' ', '_').replace('.', '_').replace('-', '_')
                rule_node_id = f"rule_{section_id}_{raw_ref}_{rule_idx}"
                
                # --- NEO4J CYPHER: (Section)-[:GOVERNED_BY]->(ComplianceRule) ---
                edge_cypher = f"""
                MERGE (p:{config.graph_child_label}:{self.domain_label} {{id: $section_id}})
                MERGE (r:ComplianceRule:{self.domain_label} {{
                    id: $rule_node_id, 
                    manual_reference: $ref, 
                    rule_type: $type,
                    description: $desc,
                    target_metric: $metric
                }})
                MERGE (p)-[:GOVERNED_BY]->(r)
                """
                
                # Link applicable hazards
                if rule.applicable_hazard_class:
                    hazard_id = f"hazard_{rule.applicable_hazard_class}"
                    edge_cypher += f"""
                    MERGE (h:Hazard:{self.domain_label} {{id: $hazard_id, class: $hazard}})
                    MERGE (r)-[:APPLIES_TO_HAZARD]->(h)
                    """
                    
                cypher_queries.append({
                    "query": edge_cypher,
                    "params": {
                        "section_id": section_id,
                        "rule_node_id": rule_node_id,
                        "ref": rule.manual_reference,
                        "type": rule.rule_type,
                        "desc": rule.rule_description,
                        "metric": rule.target_metric or "",
                        "hazard_id": f"hazard_{rule.applicable_hazard_class}" if rule.applicable_hazard_class else "",
                        "hazard": rule.applicable_hazard_class or ""
                    }
                })
                
                # --- JENA SPARQL/RDF: Map Compliance properties to IOF Ontology ---
                sparql = f"""
                PREFIX iof: <http://example.com/iof#>
                PREFIX mfg: <http://example.com/manufacturing#>
                
                INSERT DATA {{
                    iof:{rule_node_id} a iof:ComplianceRule ;
                        iof:hasManualReference "{rule.manual_reference}" ;
                        iof:hasRuleType "{rule.rule_type}" ;
                        iof:hasDescription "{rule.rule_description}" .
                """
                
                if rule.target_metric:
                    sparql += f"""
                        iof:{rule_node_id} iof:hasTargetMetric "{rule.target_metric}" .
                    """
                        
                if rule.applicable_hazard_class:
                    sparql += f"""
                        iof:{rule_node_id} iof:appliesToHazardClass "{rule.applicable_hazard_class}" .
                    """
                    
                sparql += "}"
                
                sparql_queries.append(sparql)
                
        return cypher_queries, sparql_queries
