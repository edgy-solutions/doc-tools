import os
import hashlib
from abc import ABC, abstractmethod
from typing import List, Any, Dict
from doc_tools.plugins.models import BaseSection, DocumentNode
import logging
from langfuse import Langfuse

class AugmentationPlugin(ABC):
    """
    The abstract base class for a Domain-Specific LLM Extractor plugin.
    Plugins must implement the extract logic (to query LLMs/BAML) and
    the persistence mapping to emit Cypher/SPARQL statements.
    """

    def __init__(self, domain_type: str):
        self.domain_type = domain_type
        self.logger = logging.getLogger(self.__class__.__name__)
        # Langfuse is initialized lazily (see ``langfuse`` property) so that the
        # default, file-canonical prompt source needs no Langfuse creds/network.
        self._langfuse = None
        # prompt_name -> content ref: a sha1 of the canonical file for ``file`` mode,
        # the label version for ``langfuse`` mode. The "ruleset_ref for prompts" —
        # telemetry stamps these so a trace names WHICH prompt version produced an
        # extraction (ADR-0038 Phase 4). Populated as prompts are resolved.
        self._prompt_refs: Dict[str, str] = {}

    @property
    def langfuse(self) -> Langfuse:
        """Lazily construct the Langfuse client.

        Only touched when ``PROMPT_SOURCE=langfuse`` (the opt-in SME/dev path).
        In the default ``file`` mode this is never instantiated, so production
        carries no runtime dependency on Langfuse.
        """
        if self._langfuse is None:
            self._langfuse = Langfuse()
        return self._langfuse

    def _get_dynamic_prompt(self, prompt_name: str, fallback_file: str, **compile_kwargs) -> str:
        """Resolve a prompt's text for execution.

        The source is controlled by the ``PROMPT_SOURCE`` environment variable:

        - ``file`` (DEFAULT): load the canonical, git-committed prompt from
          ``fallback_file``. What runs is exactly what was reviewed and merged
          via PR — reproducible and audit-friendly. Langfuse is never contacted.
          This is the intended production configuration.
        - ``langfuse``: fetch live from the Langfuse GUI at the label given by
          ``LANGFUSE_PROMPT_LABEL`` (default ``production``), falling back to the
          canonical file if Langfuse is unreachable. This is the opt-in SME / dev
          iteration path — handy for hot-tuning, but NOT canonical.
        """
        source = os.getenv("PROMPT_SOURCE", "file").strip().lower()

        if source == "langfuse":
            label = os.getenv("LANGFUSE_PROMPT_LABEL", "production")
            try:
                lf_prompt = self.langfuse.get_prompt(prompt_name, label=label, cache_ttl_seconds=0)
                self._prompt_refs[prompt_name] = f"lf:{getattr(lf_prompt, 'version', '?')}"
                if compile_kwargs:
                    return lf_prompt.compile(**compile_kwargs)
                return lf_prompt.prompt
            except Exception as e:
                self.logger.warning(
                    f"PROMPT_SOURCE=langfuse but Langfuse was unreachable for "
                    f"'{prompt_name}' (label='{label}'); using canonical file. Error: {e}"
                )
                return self._load_prompt_from_file(fallback_file, prompt_name=prompt_name, **compile_kwargs)

        if source != "file":
            self.logger.warning(
                f"Unknown PROMPT_SOURCE='{source}'; defaulting to canonical file source."
            )
        return self._load_prompt_from_file(fallback_file, prompt_name=prompt_name, **compile_kwargs)

    def _load_prompt_from_file(self, fallback_file: str, prompt_name: str = None,
                               **compile_kwargs) -> str:
        """Read a canonical prompt from disk and substitute ``{{ var }}`` placeholders."""
        try:
            with open(fallback_file, 'r') as file:
                raw_text = file.read().strip()
            if prompt_name is not None:
                # Hash the CANONICAL template (pre-substitution) so the ref identifies
                # the reviewed prompt version, independent of this call's variables.
                self._prompt_refs[prompt_name] = "sha1:" + hashlib.sha1(
                    raw_text.encode("utf-8")).hexdigest()[:12]
            for key, val in compile_kwargs.items():
                raw_text = raw_text.replace(f"{{{{ {key} }}}}", str(val))
            return raw_text
        except Exception as file_error:
            self.logger.error(f"Could not read canonical prompt file {fallback_file}: {file_error}")
            raise

    @property
    def prompt_refs(self) -> str:
        """Compact ``name:ref,name:ref`` of the prompt versions this plugin has
        resolved this run — for telemetry (which prompt produced an extraction)."""
        return ",".join(f"{n}:{r}" for n, r in sorted(self._prompt_refs.items()))

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
