from typing import List, Optional, Tuple, Any, Dict
from pydantic import BaseModel, ConfigDict, Field
from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode
from doc_tools.plugins import manufacturing_overlay as overlay
from doc_tools.utils.formatters import convert_element_to_markdown
from doc_tools.utils.jena_client import escape_sparql_string, safe_iri_local
# --- BAML-ready Schemas (Domain B: MAT/Manufacturing) ---
class ManufacturingStep(BaseModel):
    # extra="allow" lets proprietary overlay fields (injected at runtime via
    # TypeBuilder) ride through this mirror model into to_graph_queries.
    model_config = ConfigDict(extra="allow")

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
    figure_references: List[str] = Field(default_factory=list, description="Explicit figure/image IDs referenced by this step")

class StrategicAssessment(BaseModel):
    proprietary_score: float = Field(ge=0.0, le=1.0, description="0.0 (Common) to 1.0 (Secret Sauce)")
    outsourceable: bool

class MatAugmentation(BaseModel):
    # extra="allow" lets document-level overlay fields (injected via TypeBuilder
    # onto the @@dynamic MatAugmentation) ride through into extraction.json.
    model_config = ConfigDict(extra="allow")

    steps: List[ManufacturingStep]
    assessment: StrategicAssessment

# --- Plugin Implementation ---
class ManufacturingPlugin(AugmentationPlugin):
    """
    New Munitions Acceleration & Manufacturing (MAT) extraction logic.
    """
    def execute_global_pass(self, all_chunks: List[Dict[str, Any]], max_chars: int, config: Any) -> List[Any]:
        """
        Converts elements to Markdown and chunks them based on token limits.
        Extracts Work Instructions from each chunk.
        """
        # FIXED: Resilient fetch and compile
        dynamic_instructions = self._get_dynamic_prompt(
            prompt_name="manufacturing_instructions",
            fallback_file="prompts/manufacturing_instructions.md",
            procedure_id_format=getattr(config, "procedure_id_format", r"^\d{4}$"),
            step_id_format=getattr(config, "step_id_format", r"^\d+(?:\.\d+)*$")
        )

        # 1. Convert all elements to Markdown strings
        md_elements = [convert_element_to_markdown(chunk) for chunk in all_chunks]
        
        # 2. Chunk the Markdown strings safely
        current_chunk = ""
        safe_chunks = []
        
        for el in md_elements:
            if len(current_chunk) + len(el) < max_chars:
                current_chunk += f"\n\n{el}" if current_chunk else el
            else:
                if current_chunk:
                    safe_chunks.append(current_chunk)
                current_chunk = el 
                
        if current_chunk:
            safe_chunks.append(current_chunk)

        # 3. Process each safe chunk through BAML
        from doc_tools.baml_client.sync_client import b
        from doc_tools.baml_client.type_builder import TypeBuilder
        
        baml_responses = []
        for i, chunk_text in enumerate(safe_chunks):
            print(f"[ManufacturingPlugin] Processing Markdown chunk {i+1}/{len(safe_chunks)}")
            
            tb = TypeBuilder()
            roles = [r.strip() for r in getattr(config, "valid_personnel_roles", "QC Inspector, Journeyman, Safety Officer").split(",")]
            hazards = [h.strip() for h in getattr(config, "valid_hazard_classes", "1.1D, 1.3C, Hazmat 3, Biohazard").split(",")]
            categories = [c.strip() for c in getattr(config, "valid_process_categories", "Transformation, Inspection, Movement, Rework, Critical Safety Hold").split(",")]
            for r in roles: tb.PersonnelRole.add_value(r)
            for h in hazards: tb.HazardClass.add_value(h)
            for c in categories: tb.ProcessCategory.add_value(c)
            # Inject proprietary overlay fields (from the MANUFACTURING_OVERLAY_SPEC
            # secret) onto the @@dynamic ManufacturingStep; no-op when unset.
            overlay.inject_proprietary_properties(tb, overlay.active_overlay())

            try:
                partial = b.ExtractWorkInstructions(
                    text=chunk_text,
                    system_instructions=dynamic_instructions,
                    baml_options={"tb": tb}
                )
                baml_responses.append(partial)
            except Exception as e:
                print(f"[ManufacturingPlugin] Extraction failed on chunk {i+1}: {e}")
                
        return baml_responses

    def process_fulltext(self, full_text: str, doc_id: str, metadata: Dict[str, Any] = None, elements: List[Dict[str, Any]] = None) -> List[DocumentNode]:
        """
        Extract instructions from the entire document elements using Markdown pre-processing.
        """
        if not elements:
            return []

        # We need config for regex patterns and dynamic enums
        # In build_knowledge_graph, we don't easily have 'config' here unless we pass it.
        # But we can reconstruct it or assume defaults for the global pass.
        # Actually, let's look at how TrainingPlugin does it.
        # It doesn't use config in execute_global_pass.
        
        # For Manufacturing, we'll try to get config from metadata or use defaults.
        class MockConfig:
            procedure_id_format = r"^\d{4}$"
            step_id_format = r"^\d+(?:\.\d+)*$"
            valid_personnel_roles = "QC Inspector, Journeyman, Safety Officer"
            valid_hazard_classes = "1.1D, 1.3C, Hazmat 3, Biohazard"
            valid_process_categories = "Transformation, Inspection, Movement, Rework, Critical Safety Hold"
        
        config = MockConfig()

        try:
            import os
            context_size = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
            reserved_tokens = 4000
            chars_per_token = 3
            max_chars = (context_size - reserved_tokens) * chars_per_token
            
            baml_responses = []

            if elements:
                print(f"[ManufacturingPlugin] Using Markdown pre-processor on {len(elements)} elements")
                try:
                    baml_responses = self.execute_global_pass(elements, max_chars, config)
                except Exception as e:
                    print(f"[ManufacturingPlugin] Global pass failed, falling back to raw text chunking: {e}")
                    elements = None

            if not elements:
                # FIXED: Fetch the instructions before entering the legacy text loops
                dynamic_instructions = self._get_dynamic_prompt(
                    prompt_name="manufacturing_instructions",
                    fallback_file="prompts/manufacturing_instructions.md",
                    procedure_id_format=config.procedure_id_format,
                    step_id_format=config.step_id_format
                )

                from doc_tools.baml_client.sync_client import b
                from doc_tools.baml_client.type_builder import TypeBuilder
                
                def run_baml(txt):
                    tb = TypeBuilder()
                    roles = [r.strip() for r in config.valid_personnel_roles.split(",")]
                    hazards = [h.strip() for h in config.valid_hazard_classes.split(",")]
                    categories = [c.strip() for c in config.valid_process_categories.split(",")]
                    for r in roles: tb.PersonnelRole.add_value(r)
                    for h in hazards: tb.HazardClass.add_value(h)
                    for c in categories: tb.ProcessCategory.add_value(c)
                    overlay.inject_proprietary_properties(tb, overlay.active_overlay())

                    return b.ExtractWorkInstructions(
                        text=txt,
                        system_instructions=dynamic_instructions,
                        baml_options={"tb": tb}
                    )

                if len(full_text) <= max_chars:
                    print(f"[ManufacturingPlugin] Document fits in context ({len(full_text)} chars)")
                    baml_responses.append(run_baml(full_text))
                else:
                    print(f"[ManufacturingPlugin] Document too large ({len(full_text)} chars), chunking...")
                    # Note: Using overlap from TrainingPlugin pattern
                    overlap_chars = max(1000, max_chars // 10)
                    chunks = []
                    start = 0
                    while start < len(full_text):
                        end = start + max_chars
                        chunks.append(full_text[start:end])
                        start = end - overlap_chars
                    
                    for i, chunk_text in enumerate(chunks):
                        print(f"[ManufacturingPlugin] Processing chunk {i+1}/{len(chunks)}")
                        try:
                            baml_responses.append(run_baml(chunk_text))
                        except Exception as e:
                            print(f"[ManufacturingPlugin] Chunk {i+1} failed: {e}")
            
            all_steps = []
            final_assessment = StrategicAssessment(proprietary_score=0.0, outsourceable=False)
            overlay_fields = overlay.active_overlay()

            for resp in baml_responses:
                for s in resp.steps:
                    all_steps.append(ManufacturingStep(
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
                        material_and_hardware_slang=s.material_and_hardware_slang,
                        figure_references=getattr(s, 'figure_references', []) or [],
                        # proprietary overlay fields: object_list items normalized
                        # to plain dicts, scalars enum-unwrapped.
                        **overlay.coerce_extracted(overlay_fields, s)
                    ))
                # Update assessment (max score)
                if resp.assessment.proprietary_score > final_assessment.proprietary_score:
                    final_assessment.proprietary_score = resp.assessment.proprietary_score
                if resp.assessment.outsourceable:
                    final_assessment.outsourceable = True
            
            augmentation = MatAugmentation(
                steps=all_steps,
                assessment=final_assessment,
                # document-level overlay fields (summary, extraction notes, ...)
                # merged across chunks; empty when no document-scope fields exist.
                **overlay.extract_document_fields(baml_responses, overlay_fields),
            )
            global_section = BaseSection(title="Full Manufacturing Plan", level=0, page_start=0, content="", node_id=doc_id)
            return [DocumentNode(base_extraction=global_section, domain_augmentation=augmentation)]
            
        except Exception as e:
            print(f"[ManufacturingPlugin] Global pass failed: {e}")
            return []

    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        # We process manufacturing instructions globally via process_fulltext, so per-chunk augmentation is a no-op
        return DocumentNode(
            base_extraction=section,
            domain_augmentation=None
        )

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any, doc_id: str = "", image_prefix: str = "") -> Tuple[List[str], List[str]]:
        """Emit Cypher + SPARQL for each manufacturing node.

        Base fields (identity, instruction text, action, tooling, figures) are
        rendered here; everything else is data-driven by the overlay descriptors
        in ``manufacturing_overlay`` (default + secret-loaded proprietary), so a
        new field never requires editing this method. See
        ``tests/test_manufacturing_graph_golden.py`` for the pinned output.
        """
        dom = self.domain_label
        overlay_fields = overlay.active_overlay()
        cypher_queries = []
        sparql_queries = []

        for node in nodes:
            sec = node.base_extraction
            aug = node.domain_augmentation

            if not isinstance(aug, MatAugmentation):
                continue

            # --- Part node + strategic assessment ---
            safe_title = sec.title.replace(" ", "_").replace("'", "").replace('"', "")
            part_id = sec.node_id or f"part_{sec.page_start}_{safe_title}"
            cypher_queries.append({
                "query": f"""
                MERGE (p:{config.graph_child_label}:{dom} {{id: $part_id}})
                SET p.title = $title, p.proprietary_score = $score, p.outsourceable = $out
                """,
                "params": {
                    "part_id": part_id,
                    "title": sec.title,
                    "score": aug.assessment.proprietary_score,
                    "out": aug.assessment.outsourceable,
                },
            })

            for step in aug.steps:
                step_node_id = f"step_{part_id}_{step.step_id}"
                proc_node_id = f"proc_{part_id}_{step.procedure_id}"

                # Base step attributes + overlay attributes.
                base_set = [
                    "s.step_id = $step_id",
                    "s.raw_text = $instruction_text",
                    "s.action = $action",
                ]
                attr_clauses, attr_params = overlay.render_step_attrs(overlay_fields, step)
                set_clause = ",\n                    ".join(base_set + attr_clauses)

                params = {
                    "part_id": part_id,
                    "proc_node_id": proc_node_id,
                    "proc_id": step.procedure_id,
                    "step_node_id": step_node_id,
                    "step_id": step.step_id,
                    "instruction_text": step.instruction_text,
                    "action": step.action_verb,
                    "tools": step.tooling,
                    "image_prefix": image_prefix,
                }
                params.update(attr_params)

                # Base: Part -> Procedure -> Step, plus base tooling relationship.
                edge_cypher = f"""
                MERGE (p:{config.graph_child_label}:{dom} {{id: $part_id}})
                MERGE (proc:Procedure:{dom} {{id: $proc_node_id}})
                SET proc.procedure_id = $proc_id
                MERGE (p)-[:REQUIRES_PROCEDURE]->(proc)

                MERGE (s:ManufacturingStep:{dom} {{id: $step_node_id}})
                SET {set_clause}

                MERGE (proc)-[:CONTAINS_STEP]->(s)

                WITH s
                MERGE (k:OntologyClass {{uri: "http://edgy-solutions.com/ontology/mfg#WorkInstruction"}})
                MERGE (s)-[:INSTANCE_OF]->(k)

                WITH s
                UNWIND $tools AS t_name
                MERGE (tool:Tool:{dom} {{id: "tool_" + t_name}})
                SET tool.part_number = t_name
                MERGE (s)-[:REQUIRES_TOOL]->(tool)
                """
                # ADR-0021 Step 4: stamp the canonical content-kind edge above.
                # The :ManufacturingStep label stays for backward compat
                # (existing MATCH queries filter on it). The new edge makes
                # the step reachable through the substrate class chain
                # (ADR-0018 symmetric (S,P) routing) — a verb typed against
                # mfg:WorkInstruction can now reach manufacturing content.
                # Single general kind today per architect's ruling 2026-06-18;
                # sub-kinds become rows in the kind-selection mapping table
                # only when routing pressure justifies them (Wave-3).

                # Overlay: typed relationship nodes (hazard, cert, standards, parts, slang, ...).
                rel_blocks, rel_params = overlay.render_related_blocks(overlay_fields, step)
                params.update(rel_params)
                for block in rel_blocks:
                    edge_cypher += "\n                " + block.replace("{domain}", dom)

                # Overlay: object_list nodes (e.g. BOM items, tooling items) — each
                # item becomes a typed node with its sub-fields as properties.
                obj_blocks, obj_params = overlay.render_object_blocks(overlay_fields, step)
                params.update(obj_params)
                for block in obj_blocks:
                    edge_cypher += "\n                " + block.replace("{domain}", dom)

                # Base: figure references are core/cross-cutting.
                if step.figure_references:
                    params["figures"] = step.figure_references
                    edge_cypher += f"""
                    WITH s
                    UNWIND $figures AS fig_ref
                    MERGE (f:Figure:{dom} {{id: "fig_" + fig_ref}})
                    ON CREATE SET f.url = $image_prefix + fig_ref + ".png", f.title = fig_ref
                    MERGE (s)-[:REFERENCES_FIGURE]->(f)
                    """

                cypher_queries.append({"query": edge_cypher, "params": params})

                # --- JENA SPARQL/RDF ---
                # Sanitize the IRI local part: step_node_id derives from the doc id
                # (e.g. "inbound/22"), and a raw "/" is illegal in a prefixed name
                # -> Fuseki 400 Bad Request on the whole Update.
                step_uri = f"mfg:{safe_iri_local(step_node_id)}"
                # ADR-0021 Step 4: canonical mfg namespace + general kind.
                # Old placeholder ns http://example.com/manufacturing# was the
                # pre-canonical direct-load shape (see STATE_GATEWAY_V02.md
                # 2026-06-17 Step 1 — 7 legacy classes there are residue).
                # Canonical ns is http://edgy-solutions.com/ontology/mfg#
                # (declared in setup/ontologies/mfg_extension.ttl). The
                # general kind is mfg:WorkInstruction — sensors / electronics
                # / munitions / mechanical-assemblies are what is described,
                # not separate kinds (architect's ruling 2026-06-18).
                sparql = f"""
                PREFIX mfg: <http://edgy-solutions.com/ontology/mfg#>
                PREFIX iof: <http://example.com/iof#>

                INSERT DATA {{
                    {step_uri} a mfg:WorkInstruction ;
                        mfg:hasAction "{escape_sparql_string(step.action_verb)}" ;
                        mfg:hasText "{escape_sparql_string(step.instruction_text)}" .
                """
                # Base tooling literals.
                for t in (step.tooling or []):
                    sparql += f'\n                    {step_uri} mfg:usesTool "{escape_sparql_string(t)}" .'
                # Overlay literals/relations.
                for line in overlay.render_sparql_lines(overlay_fields, step, step_uri):
                    sparql += f"\n                    {line}"
                # Base figure triples.
                for fig in (step.figure_references or []):
                    safe_fig = safe_iri_local(fig)
                    sparql += f"\n                    {step_uri} mfg:referencesFigure mfg:fig_{safe_fig} ."
                    sparql += f"\n                    mfg:fig_{safe_fig} a mfg:Figure ."
                sparql += "\n                }"

                sparql_queries.append(sparql)

        return cypher_queries, sparql_queries
