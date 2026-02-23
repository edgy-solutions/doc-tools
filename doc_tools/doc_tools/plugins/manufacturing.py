from typing import List, Optional, Tuple, Any
from pydantic import BaseModel, Field
from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode

# --- BAML-ready Schemas (Domain B: MAT/Manufacturing) ---
class ManufacturingStep(BaseModel):
    action: str
    tooling: List[str]
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
            from baml_client import b
            from baml_client.types import MatAugmentation as BamlMatAugmentation
            
            # Execute BAML LLM inference
            baml_response: BamlMatAugmentation = b.ExtractWorkInstructions(text=section.content)
            
            steps = []
            for s in baml_response.steps:
                steps.append(ManufacturingStep(
                    action=s.action,
                    tooling=s.tooling,
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
                        action=f"Assemble component derived from {section.title}", 
                        tooling=["Wrench", "Calipers"],
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
                step_id = f"step_{part_id}_{step_idx}"
                edge_cypher = f"""
                MERGE (p:{config.graph_child_label} {{id: $part_id}})
                MERGE (s:ManufacturingStep {{id: $step_id, action: $action}})
                MERGE (p)-[:REQUIRES_STEP]->(s)
                """
                cypher_queries.append({
                    "query": edge_cypher,
                    "params": {
                        "part_id": part_id,
                        "step_id": step_id,
                        "action": step.action
                    }
                })
                
                # --- JENA SPARQL/RDF: Map standard_ref to OWL Class ---
                if step.standard_ref:
                    # e.g., mfg:Step123 mfg:governedBy iof:ISO9001_Standard .
                    sparql = f"""
                    PREFIX mfg: <http://example.com/manufacturing#>
                    PREFIX iof: <http://example.com/iof#>
                    
                    INSERT DATA {{
                        mfg:{step_id} mfg:governedBy iof:{step.standard_ref.replace("-", "")}_Standard .
                        mfg:{step_id} mfg:usesTool "{','.join(step.tooling)}" .
                    }}
                    """
                    sparql_queries.append(sparql)
                
        return cypher_queries, sparql_queries
