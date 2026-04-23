from typing import List, Optional, Tuple, Any
from pydantic import BaseModel, Field
from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode

# --- BAML-ready Schemas (Domain D: MRO/Maintenance) ---
class MaintenanceStep(BaseModel):
    procedure_id: str
    step_id: str
    instruction_text: str
    action_verb: str
    tooling: List[str]
    consumables: List[str]
    hazard_class: Optional[str] = Field(default=None)
    required_cert: Optional[str] = Field(default=None)
    standard_ref: Optional[str] = Field(default=None, description="e.g. 'TM-9-1005-317-23'")
    inspection_type: Optional[str] = Field(default=None)
    maintenance_level: Optional[str] = Field(default=None)
    is_safety_critical: bool
    torque_spec: Optional[str] = Field(default=None)
    justification: str
    estimated_duration_minutes: Optional[int] = Field(default=None)
    military_and_industry_standards: List[str] = Field(default_factory=list)
    internal_part_numbers: List[str] = Field(default_factory=list)
    figure_references: List[str] = Field(default_factory=list, description="Explicit figure/image IDs referenced by this step")

class MroAugmentation(BaseModel):
    steps: List[MaintenanceStep]

# --- Plugin Implementation ---
class MaintenancePlugin(AugmentationPlugin):
    """
    Maintenance, Repair, and Overhaul (MRO) extraction logic.
    Handles depot and field-level maintenance procedures.
    """
    
    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        try:
            from doc_tools.baml_client.sync_client import b
            from doc_tools.baml_client.types import MroAugmentation as BamlMroAugmentation
            
            # Populate Dynamic Enums via TypeBuilder
            from doc_tools.baml_client.type_builder import TypeBuilder
            tb = TypeBuilder()
            
            # Default inspection types and maintenance levels
            inspection_types = ["Visual", "Dimensional", "NDI", "Functional", "Operational"]
            maintenance_levels = ["Organizational", "Direct Support", "General Support", "Depot"]
            
            for it in inspection_types: tb.InspectionType.add_value(it)
            for ml in maintenance_levels: tb.MaintenanceLevel.add_value(ml)

            # Execute BAML LLM inference
            baml_response: BamlMroAugmentation = b.ExtractMaintenanceProcedures(
                text=section.content,
                baml_options={"tb": tb}
            )
            
            steps = []
            for s in baml_response.steps:
                steps.append(MaintenanceStep(
                    procedure_id=s.procedure_id,
                    step_id=s.step_id,
                    instruction_text=s.instruction_text,
                    action_verb=s.action_verb,
                    tooling=s.tooling,
                    consumables=s.consumables,
                    hazard_class=getattr(s.hazard_class, 'value', s.hazard_class) if s.hazard_class else None,
                    required_cert=getattr(s.required_cert, 'value', s.required_cert) if s.required_cert else None,
                    standard_ref=s.standard_ref,
                    inspection_type=getattr(s.inspection_type, 'value', s.inspection_type) if s.inspection_type else None,
                    maintenance_level=getattr(s.maintenance_level, 'value', s.maintenance_level) if s.maintenance_level else None,
                    is_safety_critical=s.is_safety_critical,
                    torque_spec=s.torque_spec,
                    justification=s.justification,
                    estimated_duration_minutes=s.estimated_duration_minutes,
                    military_and_industry_standards=s.military_and_industry_standards,
                    internal_part_numbers=s.internal_part_numbers,
                    figure_references=getattr(s, 'figure_references', []) or []
                ))
                
            augmentation = MroAugmentation(steps=steps)
            
        except ImportError:
            # Fallback mock for testing environments
            augmentation = MroAugmentation(
                steps=[
                    MaintenanceStep(
                        procedure_id="TM-9-MOCK",
                        step_id="1.1",
                        instruction_text="Mock: Remove access panel and inspect for corrosion",
                        action_verb=f"Inspect component from {section.title}",
                        tooling=["Socket Set", "Flashlight"],
                        consumables=["CLP"],
                        hazard_class=None,
                        required_cert=None,
                        standard_ref="TM-9-1005-317-23",
                        inspection_type="Visual",
                        maintenance_level="Organizational",
                        is_safety_critical=False,
                        torque_spec=None,
                        justification="Standard visual inspection does not involve safety-critical components.",
                        estimated_duration_minutes=10,
                        military_and_industry_standards=["TM-9-1005-317-23"],
                        internal_part_numbers=["5340-01-123-4567"],
                        figure_references=["Fig1"]
                    )
                ]
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
            
            if not isinstance(aug, MroAugmentation):
                continue
                
            safe_title = sec.title.replace(" ", "_").replace("'", "").replace('"', "")
            section_id = sec.node_id or f"mro_section_{sec.page_start}_{safe_title}"
            
            # Create Section node
            cypher_queries.append({
                "query": f"""
                MERGE (s:{config.graph_child_label}:{self.domain_label} {{id: $section_id}})
                SET s.title = $title
                """,
                "params": {
                    "section_id": section_id,
                    "title": sec.title
                }
            })
            
            for step_idx, step in enumerate(aug.steps):
                step_node_id = f"mstep_{section_id}_{step.step_id}"
                proc_node_id = f"mproc_{section_id}_{step.procedure_id}"
                
                edge_cypher = f"""
                MERGE (s:{config.graph_child_label}:{self.domain_label} {{id: $section_id}})
                MERGE (proc:Procedure:{self.domain_label} {{id: $proc_node_id}})
                SET proc.procedure_id = $proc_id
                MERGE (s)-[:REQUIRES_PROCEDURE]->(proc)
                
                MERGE (ms:MaintenanceStep:{self.domain_label} {{id: $step_node_id}})
                SET ms.step_id = $step_id,
                    ms.raw_text = $instruction_text,
                    ms.action = $action,
                    ms.is_safety_critical = $is_safety_critical,
                    ms.justification = $justification,
                    ms.torque_spec = $torque_spec,
                    ms.inspection_type = $inspection_type,
                    ms.maintenance_level = $maintenance_level,
                    ms.estimated_duration_minutes = $duration,
                    ms.military_and_industry_standards = $standards,
                    ms.internal_part_numbers = $parts
                
                MERGE (proc)-[:CONTAINS_STEP]->(ms)
                
                WITH ms
                UNWIND $standards AS std_name
                MERGE (std:Standard:{self.domain_label} {{id: "std_" + std_name}})
                SET std.name = std_name
                MERGE (ms)-[:GOVERNED_BY]->(std)
                
                WITH ms
                UNWIND $parts AS pn
                MERGE (part:Part:{self.domain_label} {{id: "part_" + pn}})
                SET part.part_number = pn
                MERGE (ms)-[:REQUIRES_PART]->(part)
                
                WITH ms
                UNWIND $tools AS t_name
                MERGE (tool:Tool:{self.domain_label} {{id: "tool_" + t_name}})
                SET tool.part_number = t_name
                MERGE (ms)-[:REQUIRES_TOOL]->(tool)
                """
                
                if step.hazard_class:
                    hazard_id = f"hazard_{step.hazard_class}"
                    edge_cypher += f"""
                    MERGE (h:Hazard:{self.domain_label} {{id: $hazard_id}})
                    SET h.class = $hazard
                    MERGE (ms)-[:HAS_HAZARD]->(h)
                    """
                    
                if step.required_cert:
                    cert_id = f"cert_{step.required_cert}"
                    edge_cypher += f"""
                    MERGE (c:Certification:{self.domain_label} {{id: $cert_id}})
                    SET c.certification = $cert
                    MERGE (ms)-[:REQUIRES_CERT]->(c)
                    """

                if step.figure_references:
                    edge_cypher += f"""
                    WITH ms
                    UNWIND $figures AS fig_ref
                    MERGE (f:Figure:{self.domain_label} {{id: "fig_" + fig_ref}})
                    ON CREATE SET f.url = $image_prefix + fig_ref + ".png", f.title = fig_ref
                    MERGE (ms)-[:REFERENCES_FIGURE]->(f)
                    """
                    
                cypher_queries.append({
                    "query": edge_cypher,
                    "params": {
                        "section_id": section_id,
                        "proc_node_id": proc_node_id,
                        "proc_id": step.procedure_id,
                        "step_node_id": step_node_id,
                        "step_id": step.step_id,
                        "instruction_text": step.instruction_text,
                        "action": step.action_verb,
                        "is_safety_critical": step.is_safety_critical,
                        "justification": step.justification,
                        "torque_spec": step.torque_spec or "",
                        "inspection_type": step.inspection_type or "",
                        "maintenance_level": step.maintenance_level or "",
                        "duration": step.estimated_duration_minutes if step.estimated_duration_minutes is not None else -1,
                        "standards": step.military_and_industry_standards,
                        "parts": step.internal_part_numbers,
                        "tools": step.tooling,
                        "hazard_id": f"hazard_{step.hazard_class}" if step.hazard_class else "",
                        "hazard": step.hazard_class or "",
                        "cert_id": f"cert_{step.required_cert}" if step.required_cert else "",
                        "cert": step.required_cert or "",
                        "figures": step.figure_references,
                        "image_prefix": image_prefix
                    }
                })
                
                # --- JENA SPARQL/RDF ---
                sparql = f"""
                PREFIX mro: <http://example.com/maintenance#>
                
                INSERT DATA {{
                    mro:{step_node_id} a mro:MaintenanceStep ;
                        mro:hasAction "{step.action_verb}" ;
                        mro:hasText "{step.instruction_text.replace('"', '')}" .
                """
                
                if step.standard_ref:
                    safe_std = step.standard_ref.replace("-", "").replace(" ", "_")
                    sparql += f"""
                        mro:{step_node_id} mro:governedBy mro:{safe_std}_Standard .
                    """
                
                if step.tooling:
                    for t in step.tooling:
                        sparql += f"""
                            mro:{step_node_id} mro:usesTool "{t}" .
                        """
                        
                if step.consumables:
                    for c in step.consumables:
                        sparql += f"""
                            mro:{step_node_id} mro:consumesMaterial "{c}" .
                        """

                if step.figure_references:
                    for fig in step.figure_references:
                        safe_fig = fig.replace(" ", "_").replace('"', '')
                        sparql += f"""
                            mro:{step_node_id} mro:referencesFigure mro:fig_{safe_fig} .
                            mro:fig_{safe_fig} a mro:Figure .
                        """
                        
                sparql += "}"
                
                sparql_queries.append(sparql)
                
        return cypher_queries, sparql_queries
