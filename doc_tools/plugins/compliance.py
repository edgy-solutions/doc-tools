from typing import List, Optional, Tuple, Any, Dict
from pydantic import BaseModel, Field
from doc_tools.plugins.base import AugmentationPlugin, sparql_batch
from doc_tools.plugins.models import BaseSection, DocumentNode
from doc_tools.utils.jena_client import escape_sparql_string

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
            
            # Fetch prompt (Exceptions here will be caught by the generic Exception block below)
            dynamic_instructions = self._get_dynamic_prompt(
                prompt_name="compliance_instructions",
                fallback_file="prompts/compliance_instructions.md"
            )

            # Execute BAML LLM inference
            baml_response: BamlComplianceAugmentation = b.ExtractComplianceRules(
                text=section.content,
                system_instructions=dynamic_instructions
            )
            
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
            # Fallback mock for testing environments lacking BAML
            print("[CompliancePlugin] BAML client not found. Using mock fallback.")
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
        except Exception as e:
            # Catch prompt fetching errors, LLM timeouts, or BAML schema errors
            print(f"[CompliancePlugin] Extraction failed: {e}. Using mock fallback.")
            augmentation = ComplianceAugmentation(
                rules=[
                    ComplianceRule(
                        manual_reference=f"ERROR-FALLBACK derived from {section.title}",
                        rule_type="Error",
                        applicable_hazard_class=None,
                        target_metric=None,
                        rule_description=f"Extraction failed due to error: {e}"
                    )
                ]
            )
        
        return DocumentNode(
            base_extraction=section,
            domain_augmentation=augmentation
        )

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any, doc_id: str = "", image_prefix: str = "") -> Tuple[List[str], List[Dict[str, Any]]]:
        cypher_queries = []
        sparql_queries = []
        # Scope instance data to the domain's INSTANCE graph, NOT the vocabulary graph —
        # see the "Domain Semantic Graph" invariant in AGENTS.md. This plugin previously
        # emitted an unscoped INSERT DATA, which landed in Jena's default graph, invisible
        # to the mesh resolver.
        graph_uri = f"http://internal/{self.domain_label}_INSTANCES"
        IOF_NS = "http://example.com/iof#"

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
                
                # --- JENA RDF (batch dict for JenaOntologyWriter.upsert) ---
                # `iri` MUST be the rule IRI, not the section IRI: each rule is its own
                # upsert subject, so a later re-extraction of one rule cannot delete
                # another rule's triples.
                rule_iri = f"{IOF_NS}{rule_node_id}"
                triples = [
                    f'<{rule_iri}> a <{IOF_NS}ComplianceRule> .',
                    f'<{rule_iri}> <{IOF_NS}hasManualReference> "{escape_sparql_string(rule.manual_reference)}" .',
                    f'<{rule_iri}> <{IOF_NS}hasRuleType> "{escape_sparql_string(rule.rule_type)}" .',
                    f'<{rule_iri}> <{IOF_NS}hasDescription> "{escape_sparql_string(rule.rule_description)}" .',
                ]

                if rule.target_metric:
                    triples.append(
                        f'<{rule_iri}> <{IOF_NS}hasTargetMetric> "{escape_sparql_string(rule.target_metric)}" .'
                    )

                if rule.applicable_hazard_class:
                    triples.append(
                        f'<{rule_iri}> <{IOF_NS}appliesToHazardClass> "{escape_sparql_string(rule.applicable_hazard_class)}" .'
                    )

                sparql_queries.append(
                    sparql_batch(graph=graph_uri, iri=rule_iri, triples=triples)
                )

        return cypher_queries, sparql_queries
