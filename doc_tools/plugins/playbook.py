"""``PlaybookPlugin`` -- markdown playbooks cloned from git.

Contract: ``docs/contracts/playbook-kind.md``. A playbook is read to answer
*"how do we do this"* with a citation of repo + path + heading.

NO LLM, NO PROMPTS, NO MOCK FALLBACK
------------------------------------
Like ``DocumentPlugin`` this calls only the deterministic pass its
``KIND_MAPPING`` row declares, through the dispatcher:
``run_passes_for_kind("playbook", ctx)``, so the row is what EXECUTES. A pass
that refuses is recorded as refused and the node carries no section rather than
a plausible one. Nothing here catches ``ImportError`` and substitutes content.

WHY THIS CLASS EXISTS AT ALL
----------------------------
The plugin selector's ``else`` in ``semantic_assets.py`` is ``TrainingPlugin``,
not a default. A ``playbook`` domain with no branch of its own would get
course-concept extraction run over a runbook, and it would look like it worked.

THE TIERS
---------
``:Playbook:PLAYBOOK`` -> ``:Section:PLAYBOOK`` -> ``:Chunk:PLAYBOOK``, labels
from the DOMAIN, not the kind. Two guarantees carried over from ``document``:

* ``MATCH`` the chunk, never ``MERGE`` it. A MERGE would mint an empty chunk node
  if the write loop never ran, and coverage counted off an empty node is worse
  than a missing edge.
* Another document's outline writes nothing: ``to_graph_queries`` returns empty
  when ``doc_id`` disagrees with the held outline.

No SPARQL: ``mesh:PlaybookArtifact`` is a phantom output (no ``owl:Class`` yet),
and triples against an undeclared class are data no shape can validate.
"""
from typing import Any, Dict, List, Tuple

from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode


class PlaybookPlugin(AugmentationPlugin):
    """Heading sections and citations for a markdown playbook. No LLM."""

    REQUIRED_PROMPT_FILES: List[str] = []

    def __init__(self, domain_type: str):
        super().__init__(domain_type)
        self._outline = None      # the PlaybookOutline for _outline_doc_id
        self._outline_doc_id = ""
        self._pass_results: Tuple = ()

    def process_fulltext(self, full_text: str, doc_id: str,
                         metadata: Dict[str, Any] = None,
                         elements: List[Dict[str, Any]] = None) -> List[DocumentNode]:
        """Dispatch the row's pass and hold the outline, keyed by ``doc_id``.

        Returns no ``DocumentNode``: sections are a tier written by
        ``to_graph_queries`` from the held outline, and returning them here too
        would write each one twice through two code paths.
        """
        from doc_tools.passes.dispatch import PassContext, run_passes_for_kind

        ctx = PassContext(text=full_text, doc_id=doc_id)
        self._pass_results = run_passes_for_kind("playbook", ctx)
        self._outline = None
        self._outline_doc_id = doc_id
        for result in self._pass_results:
            if (result.status == "ok" and result.value is not None
                    and result.name.endswith("playbook_outline")):
                self._outline = result.value
        return []

    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        """No per-page attribution: a markdown file has no pages."""
        return DocumentNode(base_extraction=section, domain_augmentation=None)

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any,
                         doc_id: str = "", image_prefix: str = "") -> Tuple[List, List]:
        cypher: List = []
        if self._outline is None:
            return cypher, []
        if doc_id and self._outline_doc_id and doc_id != self._outline_doc_id:
            # Not this document's outline: write nothing rather than the wrong
            # sections.
            return cypher, []

        document_id = doc_id or self._outline_doc_id
        label = self.domain_label

        for sec in self._outline.sections:
            cypher.append({
                "query": f"""
                MERGE (s:Section:{label} {{id: $id}})
                SET s.heading = $heading, s.level = $level,
                    s.method = $method, s.synthetic = $synthetic
                """,
                "params": {
                    "id": sec.id, "heading": sec.heading, "level": sec.level,
                    "method": sec.method,
                    "synthetic": bool(self._outline.synthetic),
                },
            })
            if sec.parent == document_id:
                cypher.append({
                    "query": f"""
                    MATCH (d:Playbook:{label} {{id: $doc_id}})
                    MATCH (s:Section:{label} {{id: $id}})
                    MERGE (d)-[:HAS_SECTION]->(s)
                    """,
                    "params": {"doc_id": document_id, "id": sec.id},
                })
            else:
                cypher.append({
                    "query": f"""
                    MATCH (p:Section:{label} {{id: $parent}})
                    MATCH (s:Section:{label} {{id: $id}})
                    MERGE (p)-[:HAS_SUBSECTION]->(s)
                    """,
                    "params": {"parent": sec.parent, "id": sec.id},
                })
            if sec.chunk_id:
                # MATCH, not MERGE: the asset writes the chunk, this attaches it.
                cypher.append({
                    "query": f"""
                    MATCH (s:Section:{label} {{id: $section_id}})
                    MATCH (c:Chunk:{label} {{id: $chunk_id}})
                    SET c.heading = $heading, c.section_id = $section_id
                    MERGE (s)-[:HAS_CHUNK]->(c)
                    """,
                    "params": {"section_id": sec.id, "chunk_id": sec.chunk_id,
                               "heading": sec.heading},
                })
        return cypher, []
