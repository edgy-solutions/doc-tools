from abc import ABC, abstractmethod
from typing import List, Any, Dict
from doc_tools.plugins.models import BaseSection, DocumentNode

class AugmentationPlugin(ABC):
    """
    The abstract base class for a Domain-Specific LLM Extractor plugin.
    Plugins must implement the extract logic (to query LLMs/BAML) and 
    the persistence mapping to emit Cypher/SPARQL statements.
    """
    
    def __init__(self, domain_type: str):
        self.domain_type = domain_type

    @property
    def domain_label(self) -> str:
        """
        Sanitizes and returns the uppercase domain label for Neo4j.
        Example: 'manufacturing' -> 'MANUFACTURING'
        """
        return self.domain_type.upper().replace(" ", "_").replace("-", "_")

    @abstractmethod
    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        """
        Receives a raw text section, queries the domain-specific LLM layer, 
        and returns the augmented DocumentNode.
        """
        pass

    @abstractmethod
    def to_graph_queries(self, nodes: List[DocumentNode], config: Any, doc_id: str = "", image_prefix: str = "") -> tuple[List[str], List[str]]:
        """
        Generates the database insertion statements.
        Returns a tuple of (List[Cypher Queries], List[SPARQL Queries]).
        If a database is unused by the domain, return an empty list.
        """
        pass

        
    def process_fulltext(self, full_text: str, doc_id: str, metadata: Dict[str, Any] = None, elements: List[Dict[str, Any]] = None) -> List[DocumentNode]:
        """
        Optional hook for plugins to process the entire document text at once
        (e.g., extracting a hierarchical outline or synthesizing summaries).
        Defaults to a no-op returning an empty list.
        """
        return []

    def execute_pass2_rollup(self, neo4j_client: Any, doc_id: str, config: Any) -> None:
        """
        Optional hook executed after all nodes and edges are inserted into the graph.
        Used for domain-specific cross-linking (e.g. linking Sections to Slides) 
        and mathematical rollups (e.g. averaging concept salience scores).
        Defaults to a no-op.
        """
        pass
