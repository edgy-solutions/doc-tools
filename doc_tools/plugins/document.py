"""``DocumentPlugin`` — our own documents: manuals, procedures, specifications.

ARCHITECT ORDER 2026-10-25: *"a drop of a general document (manual, procedure,
spec) that is not a PCN/PDN/S1000D should ingest as kind `document` with
review_shape `document`, chunk to Weaviate with page refs, and land in the graph
as Document -> Section -> Chunk so ask-the-manual can cite page + heading."*

THE ONE PLUGIN WITH NO LLM IN IT, AND THAT IS THE DESIGN
--------------------------------------------------------
Every other plugin here calls BAML. This one calls the two deterministic passes
its ``KIND_MAPPING`` row declares and nothing else: ``identity.document_identity``
for the title block, ``document.document_outline`` for the sections. A citation
is the product, and a citation that moves between fires on the same bytes is
worse than no citation, because it is checkable and wrong. This repo has
measured that movement on header fields more than once.

Two consequences worth stating, because they are departures from the sibling
plugins:

* **No ``REQUIRED_PROMPT_FILES`` and no ``_get_dynamic_prompt``.** There is no
  prompt to be missing, so the "missing prompt file returns zero parts" failure
  cannot occur on this path.
* **NO MOCK FALLBACK.** ``CompliancePlugin`` and its siblings catch
  ``ImportError`` and substitute invented content so tests pass without BAML;
  that pattern has twice produced a whole green graph full of placeholder text
  in this repo. Here a pass that refuses is recorded AS refused and the node
  carries no section rather than a plausible one.

IT RUNS THE PASSES THROUGH THE DISPATCHER, NOT BY DIRECT CALL
-------------------------------------------------------------
``run_passes_for_kind("document", ctx)`` — so the tuple in the registry row is
what EXECUTES, not a second description of it. That matters here specifically:
of the rows that declare passes, only ``doors-export`` actually dispatches them
today, and a declared-but-unrun tuple is a contract nobody is holding. If the
row and this module disagree, the row wins and this plugin extracts nothing,
which is a loud failure rather than a quiet divergence.

WHERE THE PER-PAGE ATTRIBUTION COMES FROM
-----------------------------------------
``semantic_assets.py`` calls ``process_fulltext`` once for the whole document and
then ``augment`` once per page. So the outline is read in ``process_fulltext``
and held on the instance for the page loop that follows — keyed by ``doc_id``,
and a page whose ``doc_id`` does not match the held outline gets NO section
rather than another document's. That key is the whole guard: a plugin instance is
built per run today, but attributing page 3 of one manual to section 2.1 of
another would be the kind of defect that reads as correct.
"""
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode


class DocumentSectionRef(BaseModel):
    """The section a page sits under — the citable half of "page + heading"."""

    section_id: str
    heading: str
    number: str = ""
    level: int = 1
    page_start: int = 0
    page_end: int = 0
    #: How the heading was recognized: element_title | numbered | caps |
    #: synthetic. Carried to the graph because a ``caps`` heading is a shape
    #: match and an ``element_title`` is the parser's own classification, and a
    #: reader auditing a citation should not have to guess which one they have.
    method: str = ""


class DocumentAugmentation(BaseModel):
    """What this plugin adds to one page."""

    section: Optional[DocumentSectionRef] = Field(default=None)
    #: True when the document had NO recognizable heading and the outline is one
    #: synthetic section. Never inferred downstream: an empty heading that looks
    #: read is indistinguishable from one that could not be read.
    outline_synthetic: bool = False


class DocumentPlugin(AugmentationPlugin):
    """Sections and page citations for a general document. No LLM, no prompts."""

    REQUIRED_PROMPT_FILES: List[str] = []

    def __init__(self, domain_type: str):
        super().__init__(domain_type)
        self._outline = None      # the DocumentOutline for _outline_doc_id
        self._outline_doc_id = ""
        self._identity = None
        self._pass_results: Tuple = ()

    # ------------------------------------------------------------------
    # Document-level: run the declared passes once.
    # ------------------------------------------------------------------
    def process_fulltext(self, full_text: str, doc_id: str,
                         metadata: Dict[str, Any] = None,
                         elements: List[Dict[str, Any]] = None) -> List[DocumentNode]:
        """Dispatch the row's passes and keep the outline for the page loop.

        Returns no ``DocumentNode``: the sections are not document NODES in the
        per-page sense, they are a tier written by ``to_graph_queries`` from the
        held outline. Returning them here as well would MERGE each section twice
        per run through two different code paths.
        """
        from doc_tools.passes.dispatch import PassContext, run_passes_for_kind

        pages = _pages_from_elements(elements) or _pages_from_full_text(full_text)
        ctx = PassContext(pages=tuple(pages), text=full_text, doc_id=doc_id)
        self._pass_results = run_passes_for_kind("document", ctx)
        self._outline = None
        self._outline_doc_id = doc_id
        self._identity = None
        for result in self._pass_results:
            if result.status != "ok" or result.value is None:
                continue
            if result.name.endswith("document_outline"):
                self._outline = result.value
            elif result.name.endswith("document_identity"):
                self._identity = result.value
        return []

    # ------------------------------------------------------------------
    # Per page: attribute it to a section. No model call.
    # ------------------------------------------------------------------
    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        aug = DocumentAugmentation()
        if self._outline is not None:
            aug.outline_synthetic = bool(self._outline.synthetic)
            hit = self._outline.section_for_page(section.page_start)
            if hit is not None:
                aug.section = DocumentSectionRef(
                    section_id=hit.id, heading=hit.heading, number=hit.number,
                    level=hit.level, page_start=hit.start_page,
                    page_end=hit.end_page, method=hit.method)
        return DocumentNode(base_extraction=section, domain_augmentation=aug)

    # ------------------------------------------------------------------
    # The Document -> Section -> Chunk tier.
    # ------------------------------------------------------------------
    def to_graph_queries(self, nodes: List[DocumentNode], config: Any,
                         doc_id: str = "", image_prefix: str = "") -> Tuple[List, List]:
        """Cypher for the section tier. No SPARQL: the output class is a phantom.

        ``outputs=("mesh:GeneralDocumentArtifact",)`` has no ``owl:Class`` yet
        (it is in ``PHANTOM_OUTPUTS``, owed by Lane 1), and emitting triples
        against an undeclared class writes data no shape can validate. The
        SPARQL arm is empty for that reason and not because the domain has no
        use for it.
        """
        cypher: List = []
        if self._outline is None:
            return cypher, []
        if doc_id and self._outline_doc_id and doc_id != self._outline_doc_id:
            # Not this document's outline. Write nothing rather than the wrong
            # sections -- see the module docstring.
            return cypher, []

        parent_label = getattr(config, "graph_node_label", "Document")
        child_label = getattr(config, "graph_child_label", "Chunk")
        document_id = doc_id or self._outline_doc_id

        # 1. The sections themselves, parented in outline order so a parent
        #    always exists before its child is attached.
        for sec in self._outline.sections:
            cypher.append({
                "query": f"""
                MERGE (s:Section:{self.domain_label} {{id: $id}})
                SET s.heading = $heading, s.number = $number, s.level = $level,
                    s.page_start = $page_start, s.page_end = $page_end,
                    s.method = $method, s.synthetic = $synthetic
                """,
                "params": {
                    "id": sec.id, "heading": sec.heading, "number": sec.number,
                    "level": sec.level, "page_start": sec.start_page,
                    "page_end": sec.end_page, "method": sec.method,
                    "synthetic": bool(self._outline.synthetic),
                },
            })
            if sec.parent == document_id:
                cypher.append({
                    "query": f"""
                    MATCH (d:{parent_label}:{self.domain_label} {{id: $doc_id}})
                    MATCH (s:Section:{self.domain_label} {{id: $id}})
                    MERGE (d)-[:HAS_SECTION]->(s)
                    """,
                    "params": {"doc_id": document_id, "id": sec.id},
                })
            else:
                cypher.append({
                    "query": f"""
                    MATCH (p:Section:{self.domain_label} {{id: $parent}})
                    MATCH (s:Section:{self.domain_label} {{id: $id}})
                    MERGE (p)-[:HAS_SUBSECTION]->(s)
                    """,
                    "params": {"parent": sec.parent, "id": sec.id},
                })

        # 2. Section -> Chunk, for the page chunks the asset's own loop wrote.
        #    MATCH, not MERGE, on the chunk: the asset creates it and this
        #    attaches it. A MERGE here would mint an empty chunk node if the
        #    loop had not run, which would look like coverage.
        for node in nodes:
            aug = node.domain_augmentation
            if not isinstance(aug, DocumentAugmentation) or aug.section is None:
                continue
            chunk_id = node.base_extraction.node_id
            if not chunk_id:
                continue
            cypher.append({
                "query": f"""
                MATCH (s:Section:{self.domain_label} {{id: $section_id}})
                MATCH (c:{child_label}:{self.domain_label} {{id: $chunk_id}})
                SET c.heading = $heading, c.section_id = $section_id
                MERGE (s)-[:HAS_CHUNK]->(c)
                """,
                "params": {
                    "section_id": aug.section.section_id, "chunk_id": chunk_id,
                    "heading": aug.section.heading,
                },
            })
        return cypher, []


def _pages_from_elements(elements) -> List[str]:
    """Page texts in the ``[Type] text`` shape the asset's full text uses.

    Preferred over the reconstructed string because the element TYPE is the
    outline pass's highest-confidence heading signal -- it is the only one
    produced by something that saw the font and the position.
    """
    if not elements:
        return []
    by_page: Dict[int, List[str]] = {}
    for el in elements:
        text = (el.get("text") or "").strip()
        if not text:
            continue
        page = (el.get("metadata") or {}).get("page_number")
        if page is None:
            continue
        by_page.setdefault(int(page), []).append(
            f"[{el.get('type', 'Text')}] {text}")
    if not by_page:
        return []
    return ["\n".join(by_page.get(n, []))
            for n in range(1, max(by_page) + 1)]


def _pages_from_full_text(full_text: str) -> List[str]:
    """Split the asset's reconstructed text on its own ``--- Page N ---`` markers.

    The fallback for a parse that carried no per-element page numbers. Page
    NUMBERS are taken from the markers rather than from the split order, so a
    document whose first marked page is not 1 is not silently renumbered.
    """
    if not full_text:
        return []
    import re

    parts = re.split(r"\n?--- Page (\d+) ---\n?", full_text)
    if len(parts) < 3:
        return [full_text]
    by_page: Dict[int, List[str]] = {}
    for i in range(1, len(parts) - 1, 2):
        by_page.setdefault(int(parts[i]), []).append(parts[i + 1])
    return ["\n".join(by_page.get(n, []))
            for n in range(1, max(by_page) + 1)]
