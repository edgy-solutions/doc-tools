from typing import List, Optional, Tuple, Any
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

# --- Plugin Implementation ---
class TrainingPlugin(AugmentationPlugin):
    """
    Original extraction logic generalized for Training content.
    """
    
    def augment(self, section: BaseSection) -> DocumentNode:
        try:
            from baml_client import b
            from baml_client.types import SlideAugmentation as BamlSlideAugmentation
            
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

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any) -> Tuple[List[str], List[str]]:
        cypher_queries = []
        sparql_queries = []
        
        for node in nodes:
            sec = node.base_extraction
            aug = node.domain_augmentation
            
            if not isinstance(aug, SlideAugmentation):
                continue
                
            # Create the Section Node
            section_id = f"section_{sec.page_start}_{sec.title}"
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
