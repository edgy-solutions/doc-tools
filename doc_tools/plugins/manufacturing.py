from typing import List, Optional, Tuple, Any
from pydantic import BaseModel, Field
from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode

# --- BAML-ready Schemas (Domain B: MAT/Manufacturing) ---
class ManufacturingStep(BaseModel):
    procedure_id: str
    step_id: str
    action_verb: str
    tooling: List[str]
    consumables: List[str]
    hazard_class: Optional[str] = Field(default=None)
    required_cert: Optional[str] = Field(default=None)
    standard_ref: Optional[str] = Field(default=None, description="e.g. 'ISO-9001'")

class StrategicAssessment(BaseModel):
    proprietary_score: float = Field(ge=0.0, le=1.0, description="0.0 (Common) to 1.0 (Secret Sauce)")
    outsourceable: bool

class MatAugmentation(BaseModel):
    steps: List[ManufacturingStep]
    assessment: StrategicAssessment

# --- Plugin Implementation ---
class ManufacturingPlugin(AugmentationPlugin):
    """
    New Munitions Acceleration & Manufacturing (MAT) extraction logic.
    """
    
    def augment(self, section: BaseSection) -> DocumentNode:
        try:
            from doc_tools.baml_client import b
            from doc_tools.baml_client.types import MatAugmentation as BamlMatAugmentation
            
            # Execute BAML LLM inference
            baml_response: BamlMatAugmentation = b.ExtractWorkInstructions(text=section.content)
            
            steps = []
            for s in baml_response.steps:
                steps.append(ManufacturingStep(
                    procedure_id=s.procedure_id,
                    step_id=s.step_id,
                    action_verb=s.action_verb,
                    tooling=s.tooling,
                    consumables=s.consumables,
                    hazard_class=s.hazard_class,
                    required_cert=s.required_cert,
                    standard_ref=s.standard_ref
                ))
                
            augmentation = MatAugmentation(
                steps=steps,
                assessment=StrategicAssessment(
                    proprietary_score=baml_response.assessment.proprietary_score,
                    outsourceable=baml_response.assessment.outsourceable
                )
            )
            
        except ImportError:
            # Fallback mock for testing environments
            augmentation = MatAugmentation(
                steps=[
                    ManufacturingStep(
                        procedure_id="PROC-MOCK",
                        step_id="3.2.1",
                        action_verb=f"Assemble component derived from {section.title}", 
                        tooling=["Wrench", "Calipers"],
                        consumables=["Epoxy #9"],
                        hazard_class="1.1D",
                        required_cert="QC Inspector",
                        standard_ref="ISO-9001"
                    )
                ],
                assessment=StrategicAssessment(
                    proprietary_score=0.95,
                    outsourceable=False
                )
            )
        
        return DocumentNode(
            base_extraction=section,
            domain_augmentation=augmentation
        )

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any) -> Tuple[List[str], List[str]]:
        cypher_queries = []
        sparql_queries = []
        
        for node in nodes:
            sec = node.base_extraction
            aug = node.domain_augmentation
            
            if not isinstance(aug, MatAugmentation):
                continue
                
            # --- NEO4J CYPHER: (Part)-[:REQUIRES_STEP]->(ManufacturingStep) ---
            part_id = f"part_{sec.page_start}_{sec.title}"
            cypher_queries.append({
                "query": f"""
                MERGE (p:{config.graph_child_label} {{id: $part_id}})
                SET p.title = $title, p.proprietary_score = $score, p.outsourceable = $out
                """,
                "params": {
                    "part_id": part_id,
                    "title": sec.title,
                    "score": aug.assessment.proprietary_score,
                    "out": aug.assessment.outsourceable
                }
            })
            
            for step_idx, step in enumerate(aug.steps):
                step_node_id = f"step_{part_id}_{step.step_id}"
                proc_node_id = f"proc_{part_id}_{step.procedure_id}"
                
                # Create Procedure Node & link Part -> Procedure -> Step
                edge_cypher = f"""
                MERGE (p:{config.graph_child_label} {{id: $part_id}})
                MERGE (proc:Procedure {{id: $proc_node_id, procedure_id: $proc_id}})
                MERGE (p)-[:REQUIRES_PROCEDURE]->(proc)
                MERGE (s:ManufacturingStep {{
                    id: $step_node_id, 
                    step_id: $step_id, 
                    action: $action
                }})
                MERGE (proc)-[:CONTAINS_STEP]->(s)
                """
                
                # Append conditional nodes for Hazards and Certifications
                if step.hazard_class:
                    hazard_id = f"hazard_{step.hazard_class}"
                    edge_cypher += f"""
                    MERGE (h:Hazard {{id: $hazard_id, class: $hazard}})
                    MERGE (s)-[:HAS_HAZARD]->(h)
                    """
                    
                if step.required_cert:
                    cert_id = f"cert_{step.required_cert}"
                    edge_cypher += f"""
                    MERGE (c:Certification {{id: $cert_id, certification: $cert}})
                    MERGE (s)-[:REQUIRES_CERT]->(c)
                    """
                    
                cypher_queries.append({
                    "query": edge_cypher,
                    "params": {
                        "part_id": part_id,
                        "proc_node_id": proc_node_id,
                        "proc_id": step.procedure_id,
                        "step_node_id": step_node_id,
                        "step_id": step.step_id,
                        "action": step.action_verb,
                        "hazard_id": f"hazard_{step.hazard_class}" if step.hazard_class else "",
                        "hazard": step.hazard_class or "",
                        "cert_id": f"cert_{step.required_cert}" if step.required_cert else "",
                        "cert": step.required_cert or ""
                    }
                })
                
                # --- JENA SPARQL/RDF: Map MAT properties to OWL Classes ---
                sparql = f"""
                PREFIX mfg: <http://example.com/manufacturing#>
                PREFIX iof: <http://example.com/iof#>
                
                INSERT DATA {{
                    mfg:{step_node_id} a mfg:ManufacturingStep ;
                        mfg:hasAction "{step.action_verb}" .
                """
                
                if step.standard_ref:
                    sparql += f"""
                        mfg:{step_node_id} mfg:governedBy iof:{step.standard_ref.replace("-", "")}_Standard .
                    """
                
                if step.tooling:
                    for t in step.tooling:
                        sparql += f"""
                            mfg:{step_node_id} mfg:usesTool "{t}" .
                        """
                        
                if step.consumables:
                    for c in step.consumables:
                        sparql += f"""
                            mfg:{step_node_id} mfg:consumesMaterial "{c}" .
                        """
                        
                if step.hazard_class:
                    sparql += f"""
                        mfg:{step_node_id} mfg:hasHazardClass "{step.hazard_class}" .
                    """
                    
                if step.required_cert:
                    sparql += f"""
                        mfg:{step_node_id} mfg:requiresCertification "{step.required_cert}" .
                    """
                    
                sparql += "}"
                
                sparql_queries.append(sparql)
                
        return cypher_queries, sparql_queries
