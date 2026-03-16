from typing import List, Optional, Tuple, Any
from pydantic import BaseModel, Field
from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode

# --- BAML-ready Schemas (Domain B: MAT/Manufacturing) ---
class ManufacturingStep(BaseModel):
    procedure_id: str
    step_id: str
    instruction_text: str
    action_verb: str
    tooling: List[str]
    consumables: List[str]
    hazard_class: Optional[str] = Field(default=None)
    required_cert: Optional[str] = Field(default=None)
    standard_ref: Optional[str] = Field(default=None, description="e.g. 'ISO-9001'")
    is_value_added: bool
    is_safety_critical: bool
    process_category: str
    justification: str
    estimated_duration_minutes: Optional[int] = Field(default=None)
    military_and_industry_standards: List[str] = Field(default_factory=list)
    internal_part_numbers: List[str] = Field(default_factory=list)
    material_and_hardware_slang: List[str] = Field(default_factory=list)

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
    
    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        try:
            from doc_tools.baml_client.sync_client import b
            from doc_tools.baml_client.types import MatAugmentation as BamlMatAugmentation
            
            # Populate Dynamic Enums for strict Rust validation via TypeBuilder
            from doc_tools.baml_client.type_builder import TypeBuilder
            tb = TypeBuilder()
            
            # Extract lists from config or defaults
            roles = [r.strip() for r in getattr(config, "valid_personnel_roles", "QC Inspector, Journeyman, Safety Officer").split(",")]
            hazards = [h.strip() for h in getattr(config, "valid_hazard_classes", "1.1D, 1.3C, Hazmat 3, Biohazard").split(",")]
            categories = [c.strip() for c in getattr(config, "valid_process_categories", "Transformation, Inspection, Movement, Rework, Critical Safety Hold").split(",")]
            
            for r in roles: tb.PersonnelRole.add_value(r)
            for h in hazards: tb.HazardClass.add_value(h)
            for c in categories: tb.ProcessCategory.add_value(c)

            # Execute BAML LLM inference
            baml_response: BamlMatAugmentation = b.ExtractWorkInstructions(
                text=section.content,
                procedure_id_format=getattr(config, "procedure_id_format", "^\\d{4}$"),
                step_id_format=getattr(config, "step_id_format", "^\\d+(?:\\.\\d+)*$"),
                baml_options={"tb": tb}
            )
            
            steps = []
            for s in baml_response.steps:
                # BAML Dynamic Enums can return strings or Enum objects depending on registration.
                # We use getattr to safely extract the value if it's an Enum, otherwise use the string.
                steps.append(ManufacturingStep(
                    procedure_id=s.procedure_id,
                    step_id=s.step_id,
                    instruction_text=s.instruction_text,
                    action_verb=s.action_verb,
                    tooling=s.tooling,
                    consumables=s.consumables,
                    hazard_class=getattr(s.hazard_class, 'value', s.hazard_class) if s.hazard_class else None,
                    required_cert=getattr(s.required_cert, 'value', s.required_cert) if s.required_cert else None,
                    standard_ref=s.standard_ref,
                    is_value_added=s.is_value_added,
                    is_safety_critical=s.is_safety_critical,
                    process_category=getattr(s.process_category, 'value', s.process_category),
                    justification=s.justification,
                    estimated_duration_minutes=s.estimated_duration_minutes,
                    military_and_industry_standards=s.military_and_industry_standards,
                    internal_part_numbers=s.internal_part_numbers,
                    material_and_hardware_slang=s.material_and_hardware_slang
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
                        instruction_text="Mock raw text of the procedure step",
                        action_verb=f"Assemble component derived from {section.title}", 
                        tooling=["Wrench", "Calipers"],
                        consumables=["Epoxy #9"],
                        hazard_class="1.1D",
                        required_cert="QC Inspector",
                        standard_ref="ISO-9001",
                        is_value_added=True,
                        is_safety_critical=False,
                        process_category="Transformation",
                        justification="This step physically builds the component.",
                        estimated_duration_minutes=15,
                        military_and_industry_standards=["MIL-PRF-81733"],
                        internal_part_numbers=["99-812"],
                        material_and_hardware_slang=["Epoxy"]
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
                
            # --- NEO4J CYPHER: (Page)-[:REQUIRES_PROCEDURE]->(Procedure) ---
            part_id = sec.node_id or f"part_{sec.page_start}_{sec.title}"
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
                    raw_text: $instruction_text,
                    action: $action,
                    is_value_added: $is_value_added,
                    is_safety_critical: $is_safety_critical,
                    process_category: $process_category,
                    justification: $justification,
                    estimated_duration_minutes: $duration,
                    military_and_industry_standards: $military_and_industry_standards,
                    internal_part_numbers: $internal_part_numbers,
                    material_and_hardware_slang: $material_and_hardware_slang
                }})
                MERGE (proc)-[:CONTAINS_STEP]->(s)
                
                WITH s
                UNWIND $standards AS std_name
                MERGE (std:Standard {id: "std_" + std_name, name: std_name})
                MERGE (s)-[:GOVERNED_BY]->(std)
                
                WITH s
                UNWIND $parts AS pn
                MERGE (part:Part {id: "part_" + pn, part_number: pn})
                MERGE (s)-[:REQUIRES_PART]->(part)
                
                WITH s
                UNWIND $slang AS term
                MERGE (st:SlangTerm {id: "slang_" + term, term: term})
                MERGE (s)-[:USABLE_SLANG]->(st)
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
                        "instruction_text": step.instruction_text,
                        "action": step.action_verb,
                        "is_value_added": step.is_value_added,
                        "is_safety_critical": step.is_safety_critical,
                        "process_category": step.process_category,
                        "justification": step.justification,
                        "duration": step.estimated_duration_minutes if step.estimated_duration_minutes is not None else -1,
                        "standards": step.military_and_industry_standards,
                        "parts": step.internal_part_numbers,
                        "slang": step.material_and_hardware_slang,
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
                        mfg:hasAction "{step.action_verb}" ;
                        mfg:hasText "{step.instruction_text.replace('"', '')}" .
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
