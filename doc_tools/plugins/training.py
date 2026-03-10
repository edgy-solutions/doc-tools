from typing import List, Optional, Tuple, Any, Dict
from pydantic import BaseModel, Field
from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode

# --- BAML-ready Schemas (Domain A: Training) ---
class Concept(BaseModel):
    name: str
    salience: float = Field(ge=0.0, le=1.0)

class SlideAugmentation(BaseModel):
    concepts: List[Concept]
    objectives: List[str]

class CourseSection(BaseModel):
    title: str
    level: int
    start_page: int
    end_page: Optional[int] = None
    subsections: List['CourseSection'] = []

class OutlineAugmentation(BaseModel):
    sections: List[CourseSection]
    metadata: Dict[str, Any] = Field(default_factory=dict)

# --- Plugin Implementation ---
class TrainingPlugin(AugmentationPlugin):
    """
    Original extraction logic generalized for Training content.
    """
    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        try:
            from doc_tools.baml_client import b
            from doc_tools.baml_client.types import SlideAugmentation as BamlSlideAugmentation
            
            # Execute BAML LLM inference
            baml_response: BamlSlideAugmentation = b.ExtractConcepts(slide_text=section.content)
            
            # Map BAML response back to Native Python/Pydantic models
            concepts = []
            for c in baml_response.concepts:
                concepts.append(Concept(name=c.name, salience=c.salience))
                
            augmentation = SlideAugmentation(
                concepts=concepts,
                objectives=baml_response.objectives
            )
            
        except ImportError:
            # Fallback mock for testing environments where BAML isn't compiled
            augmentation = SlideAugmentation(
                concepts=[
                    Concept(name=f"Key Concept from {section.title}", salience=0.8)
                ],
                objectives=["Understand the fundamentals."]
            )
        
        return DocumentNode(
            base_extraction=section,
            domain_augmentation=augmentation
        )

    def _chunk_text(self, document_text: str, max_chars: int = 15000, overlap_chars: int = 1500) -> List[Tuple[str, int]]:
        """
        Split document into overlapping chunks.
        Returns list of (chunk_text, start_char_position).
        """
        if len(document_text) <= max_chars:
            return [(document_text, 0)]
        
        chunks = []
        start = 0
        
        while start < len(document_text):
            end = start + max_chars
            chunk = document_text[start:end]
            chunks.append((chunk, start))
            
            # Move start forward, accounting for overlap
            start = end - overlap_chars
            
            # Avoid infinite loop if overlap >= chunk size
            if start <= chunks[-1][1]:
                break
                
        return chunks

    def _merge_outlines(self, partial_outlines: List[Any]) -> List[CourseSection]:
        """
        Merge multiple partial BAML outlines into one list of CourseSections, deduplicating by page number.
        """
        if not partial_outlines:
            return []
            
        all_sections = []
        seen_pages = set()
        
        for outline in partial_outlines:
            if not outline or not hasattr(outline, 'sections'):
                continue
                
            for section in outline.sections:
                start_page = getattr(section, 'start_page', None)
                
                # Skip if we've already seen this explicit page start
                if start_page is not None and start_page in seen_pages:
                    continue
                
                if start_page is not None:
                    seen_pages.add(start_page)
                    
                # Recursive map helper
                def map_sec(s) -> CourseSection:
                    subs = [map_sec(sub) for sub in getattr(s, 'subsections', [])]
                    return CourseSection(
                        title=getattr(s, 'title', 'Untitled'),
                        level=getattr(s, 'level', 1),
                        start_page=getattr(s, 'start_page', 0),
                        end_page=getattr(s, 'end_page', None),
                        subsections=subs
                    )
                
                all_sections.append(map_sec(section))
        
        # Sort sequentially by start_page
        all_sections.sort(key=lambda s: s.start_page or 0)
        return all_sections

    def process_fulltext(self, full_text: str, doc_id: str, metadata: Dict[str, Any] = None) -> List[DocumentNode]:
        """
        Legacy override: Parse the entire document text using Map-Reduce to hallucinate a 
        Table of Contents (Course -> Section -> Section) before chunking.
        """
        if metadata is None:
            metadata = {}
        try:
            from doc_tools.baml_client import b
            # Token estimation constants
            import os
            context_size = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
            reserved_tokens = 4000
            chars_per_token = 3
            max_chars = (context_size - reserved_tokens) * chars_per_token
            overlap_chars = max(1000, max_chars // 10)
            
            if len(full_text) <= max_chars:
                print(f"[TrainingPlugin] Document fits in context ({len(full_text)} chars)")
                baml_response = b.ExtractOutline(text=full_text)
                final_sections = self._merge_outlines([baml_response])
            else:
                print(f"[TrainingPlugin] Document too large ({len(full_text)} chars), chunking...")
                chunks = self._chunk_text(full_text, max_chars, overlap_chars)
                
                partial_outlines = []
                for i, (chunk_text, start_pos) in enumerate(chunks):
                    print(f"[TrainingPlugin] Processing chunk {i+1}/{len(chunks)}")
                    try:
                        partial = b.ExtractOutline(text=chunk_text)
                        partial_outlines.append(partial)
                    except Exception as e:
                        print(f"[TrainingPlugin] Chunk {i+1} failed: {e}")
                        
                final_sections = self._merge_outlines(partial_outlines)
                
            augmentation = OutlineAugmentation(sections=final_sections, metadata=metadata)
            
        except ImportError:
            # Fallback mock for testing environments
            augmentation = OutlineAugmentation(
                sections=[
                    CourseSection(
                        title="Chapter 1: Introduction", 
                        level=1, 
                        start_page=1, 
                        end_page=5,
                        subsections=[
                            CourseSection(title="1.1 Overview", level=2, start_page=1, end_page=2)
                        ]
                    )
                ]
            )
            
        # Return as a special "Global" DocumentNode
        global_section = BaseSection(title="Course Outline", level=0, page_start=0, content="", node_id=doc_id)
        return [DocumentNode(base_extraction=global_section, domain_augmentation=augmentation)]

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any) -> Tuple[List[str], List[str]]:
        cypher_queries = []
        sparql_queries = []
        
        for node in nodes:
            sec = node.base_extraction
            aug = node.domain_augmentation
            
            # 1. Handle Global Outline Execution (The legacy Course -> Section tree)
            if isinstance(aug, OutlineAugmentation):
                course_id = sec.node_id
                
                # Append the course metadata update (legacy code)
                # Note: Because the generic pipeline creates the root Course node, we just MATCH and SET
                course_meta_cypher = f"""
                MATCH (c:{config.graph_node_label} {{id: $id}})
                SET c.business_unit = $business_unit,
                    c.version = $version,
                    c.delivery_method = $delivery,
                    c.duration_hours = $duration,
                    c.audience = $audience,
                    c.level = $level,
                    c.discipline = $discipline
                """
                cypher_queries.append({
                    "query": course_meta_cypher,
                    "params": {
                        "id": course_id,
                        "business_unit": aug.metadata.get("business_unit"),
                        "version": aug.metadata.get("version"),
                        "delivery": aug.metadata.get("current_delivery_method"),
                        "duration": aug.metadata.get("duration_hours"),
                        "audience": aug.metadata.get("audience"),
                        "level": aug.metadata.get("level_of_material"),
                        "discipline": aug.metadata.get("engineering_discipline")
                    }
                })
                
                # Recursive function to build the Cypher strings for Sections
                def build_section_cypher(sections: List[CourseSection], parent_id: str):
                    for i, outline_sec in enumerate(sections):
                        sec_id = f"{parent_id}_s{i}"
                        
                        cypher = f"""
                        MERGE (s:Section {{id: $id}})
                        SET s.title = $title,
                            s.level = $level,
                            s.start_page = $start_page,
                            s.end_page = $end_page
                        WITH s
                        MATCH (p {{id: $parent_id}})
                        MERGE (p)-[:HAS_SECTION]->(s)
                        """
                        cypher_queries.append({
                            "query": cypher,
                            "params": {
                                "id": sec_id,
                                "title": outline_sec.title,
                                "level": outline_sec.level,
                                "parent_id": parent_id,
                                "start_page": outline_sec.start_page,
                                "end_page": outline_sec.end_page if outline_sec.end_page else 0
                            }
                        })
                        build_section_cypher(outline_sec.subsections, sec_id)
                
                build_section_cypher(aug.sections, course_id)
                continue
                
            # 2. Handle Individual Slide Processing
            if not isinstance(aug, SlideAugmentation):
                continue
                
            # Use unified hardware ID linking Graph to Vector DB
            section_id = sec.node_id or f"section_{sec.page_start}_{sec.title}"
            # WARNING: String parameterization used per instructions because neo4j drivers cannot param labels
            cypher = f"""
            MERGE (s:{config.graph_child_label} {{id: $section_id}})
            SET s.title = $title, s.content = $content, s.page_start = $page_start
            """
            # Store just the query string (the DAGSTER execution layer will bind the parameters securely)
            # In a fully fleshed out plugin, we'd return (query, params) tuples.
            # Due to architecture requirements, we return strict strings here mapped for processing later.
            
            cypher_queries.append({
                "query": cypher,
                "params": {
                    "section_id": section_id,
                    "title": sec.title,
                    "content": sec.content,
                    "page_start": sec.page_start
                }
            })
            
            # Map Concepts -> (Section)-[:TEACHES]->(Concept)
            for raw_concept in aug.concepts:
                concept_id = f"concept_{raw_concept.name.replace(' ', '_')}"
                edge_cypher = f"""
                MERGE (s:{config.graph_child_label} {{id: $section_id}})
                MERGE (c:Concept {{id: $concept_id, name: $c_name, salience: $c_salience}})
                MERGE (s)-[:TEACHES]->(c)
                """
                cypher_queries.append({
                    "query": edge_cypher,
                    "params": {
                        "section_id": section_id,
                        "concept_id": concept_id,
                        "c_name": raw_concept.name,
                        "c_salience": raw_concept.salience
                    }
                })
                
        # Domain A uses Neo4j strictly, no Jena graphs
        return cypher_queries, sparql_queries

    def execute_pass2_rollup(self, neo4j_client: Any, doc_id: str, config: Any) -> None:
        """
        Legacy Pass 2: Link Slides to Sections and roll up Concept hierarchies.
        """
        try:
            # 1. Link Slides (Pages) to Sections based on Page Numbers
            link_query = f"""
            MATCH (c:{config.graph_node_label} {{id: $doc_id}})-[:HAS_SECTION*]->(sec:Section)
            MATCH (c)-[:HAS_CHILD]->(s:{config.graph_child_label})
            WHERE s.number >= sec.start_page 
              AND (sec.end_page = 0 OR s.number <= sec.end_page)
            MERGE (sec)-[:HAS_CHILD]->(s)
            """
            neo4j_client.execute_query(link_query, {"doc_id": doc_id})

            # 2. Roll-up Concepts to Sections (COVERS Relationship)
            rollup_query = f"""
            MATCH (c:{config.graph_node_label} {{id: $doc_id}})-[:HAS_SECTION*]->(sec:Section)
            MATCH (sec)-[:HAS_CHILD]->(s:{config.graph_child_label})-[t:TEACHES]->(con:Concept)
            WITH sec, con, avg(t.salience) as avg_score, count(s) as frequency
            MERGE (sec)-[r:COVERS]->(con)
            SET r.score = avg_score, r.frequency = frequency
            """
            neo4j_client.execute_query(rollup_query, {"doc_id": doc_id})

            # 3. Create Lightweight Summaries
            summary_query = f"""
            MATCH (c:{config.graph_node_label} {{id: $doc_id}})-[:HAS_SECTION*]->(sec:Section)
            OPTIONAL MATCH (sec)-[r:COVERS]->(con:Concept)
            WITH sec, con, r.score as score
            ORDER BY score DESC
            WITH sec, collect(con.name) as concepts
            SET sec.concept_summary = concepts[0..10]
            """
            neo4j_client.execute_query(summary_query, {"doc_id": doc_id})
            print(f"Pass 2 successfully executed for {doc_id}")
            
        except Exception as e:
            print(f"Pass 2 Rollup failed in TrainingPlugin: {e}")
