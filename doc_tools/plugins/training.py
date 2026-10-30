import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Any, Dict
from pydantic import BaseModel, Field
from doc_tools.utils.concept_identity import (concept_node_id, normalize_concept_name)
from doc_tools.utils import concept_groups
from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode
from doc_tools.utils.formatters import convert_element_to_markdown
from doc_tools.utils.graph_overlay import overlay_for
# --- BAML-ready Schemas (Domain A: Training) ---
class Concept(BaseModel):
    name: str
    salience: float = Field(ge=0.0, le=1.0)
    related_terms: List[str] = Field(default_factory=list)

class SlideAugmentation(BaseModel):
    concepts: List[Concept]
    figure_references: List[str] = Field(default_factory=list, description="Explicit figure/image IDs referenced in the slide")

class SectionNote(BaseModel):
    summary: Optional[str] = None
    objectives: List[str] = Field(default_factory=list)

from doc_tools.passes.structural import CourseSection, OutlineBuildError, build_outline  # noqa: F401


class OutlineAugmentation(BaseModel):
    sections: List[CourseSection]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    outline_source: str  # "deck" | "llm" (contract v3 section 4.5)
    # Section id -> notes from the concept calls (contract v4 section 4.1). Filled by
    # ``augment_course`` after the outline exists; empty when no call ran.
    section_notes: Dict[str, SectionNote] = Field(default_factory=dict)


@dataclass
class CourseAugmentation:
    """What ``augment_course`` returns: a node or a failure per page, plus the notes."""
    nodes: Dict[int, DocumentNode] = field(default_factory=dict)
    failures: Dict[int, str] = field(default_factory=dict)  # page -> "<ExcType>: <msg>"
    section_notes: Dict[str, SectionNote] = field(default_factory=dict)
    calls: List[dict] = field(default_factory=list)  # per call: pages, seconds, attempts, ok


def _fold(text: str) -> str:
    return " ".join((text or "").casefold().split())


# --- Plugin Implementation ---
class TrainingPlugin(AugmentationPlugin):
    """
    Original extraction logic generalized for Training content.
    """
    def _extract_section(self, section_text: str, instructions: str):
        """The one LLM seam of the concept calls (tests stub this)."""
        from doc_tools.baml_client.sync_client import b
        return b.ExtractSectionConcepts(section_text=section_text, system_instructions=instructions)

    @staticmethod
    def _slide_node(section: BaseSection, entry: Any) -> DocumentNode:
        concepts = []
        for c in entry.concepts:
            # A salience outside [0, 1] must not lose the other slides of the call.
            sal = min(1.0, max(0.0, float(c.salience)))
            concepts.append(Concept(name=c.name, salience=sal,
                                    related_terms=list(getattr(c, "related_terms", None) or [])))
        return DocumentNode(
            base_extraction=section,
            domain_augmentation=SlideAugmentation(
                concepts=concepts,
                figure_references=list(getattr(entry, "figure_references", None) or [])))

    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        try:
            instructions = self._get_dynamic_prompt(
                prompt_name="training_section_instructions",
                fallback_file="prompts/training_section_instructions.md"
            )
            call = concept_groups.ConceptCall(pages=(section.page_start,), page_sections=(None,))
            text = concept_groups.render_call(call, {section.page_start: section.content}, {})
            reply = self._extract_section(text, instructions)
            entry = next((s for s in reply.slides if s.slide == section.page_start), None)
            if entry is None:
                raise ValueError(f"no entry for slide {section.page_start} in the section reply")
            return self._slide_node(section, entry)
        except ImportError:
            # Fallback mock for testing environments where BAML isn't compiled
            augmentation = SlideAugmentation(
                concepts=[
                    Concept(name=f"Key Concept from {section.title}", salience=0.8)
                ],
                figure_references=[]
            )
            return DocumentNode(base_extraction=section, domain_augmentation=augmentation)

    def _run_call(self, call: "concept_groups.ConceptCall", text: str, instructions: str) -> dict:
        """One concept call, retried once when it raises or omits a page of the call."""
        t0 = time.time()
        reply, err, attempts = None, None, 0
        for attempts in (1, 2):
            try:
                reply, err = self._extract_section(text, instructions), None
            except Exception as e:  # noqa: BLE001 -- recorded per page, never raised
                reply, err = None, e
                continue
            have = {s.slide for s in reply.slides}
            if all(p in have for p in call.pages):
                break
        return {"call": call, "reply": reply, "error": err, "attempts": attempts,
                "seconds": round(time.time() - t0, 2)}

    def augment_course(self, texts: Dict[int, str], chunk_ids: Dict[int, str],
                       sections: List[CourseSection], course_id: str,
                       config: Any = None) -> CourseAugmentation:
        """Concepts for a whole course: one call per slide group (contract v4 section 4.6)."""
        rows = concept_groups.flatten_outline(sections, course_id)
        rows_by_id = {r.id: r for r in rows}
        calls = concept_groups.plan_calls(sorted(texts), rows)
        rendered = [concept_groups.render_call(c, texts, rows_by_id) for c in calls]
        result = CourseAugmentation()
        if not calls:
            return result
        # Fetched once per course, not once per call.
        instructions = self._get_dynamic_prompt(
            prompt_name="training_section_instructions",
            fallback_file="prompts/training_section_instructions.md")
        workers = max(1, int(os.getenv("TRAINING_CONCEPT_CONCURRENCY", "1")))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # map() yields in submission order whatever the completion order
            outcomes = list(pool.map(lambda a: self._run_call(a[0], a[1], instructions),
                                     zip(calls, rendered)))

        merged: Dict[str, SectionNote] = {}
        for call, out in zip(calls, outcomes):
            reply, err = out["reply"], out["error"]
            if reply is None:
                for p in call.pages:
                    result.failures[p] = f"{type(err).__name__}: {err}"
                result.calls.append({"pages": list(call.pages), "seconds": out["seconds"],
                                     "attempts": out["attempts"], "ok": False})
                continue
            ok = True
            entries: Dict[int, Any] = {}
            for s in reply.slides:
                if s.slide not in call.pages:
                    print(f"[training] ignoring reply entry for slide {s.slide}: not in the call {list(call.pages)}")
                elif s.slide not in entries:
                    entries[s.slide] = s
            for p in call.pages:
                if p in entries:
                    section = BaseSection(title=f"Page {p}", level=1, page_start=p,
                                          content=texts[p], node_id=chunk_ids[p])
                    result.nodes[p] = self._slide_node(section, entries[p])
                else:
                    ok = False
                    result.failures[p] = f"MissingSlideError: no entry for slide {p} in the section reply"
            result.calls.append({"pages": list(call.pages), "seconds": out["seconds"],
                                 "attempts": out["attempts"], "ok": ok})
            self._merge_notes(call, reply, rows_by_id, merged)
        result.section_notes = merged
        return result

    @staticmethod
    def _merge_notes(call: "concept_groups.ConceptCall", reply: Any,
                     rows_by_id: Dict[str, "concept_groups.SectionRow"],
                     merged: Dict[str, SectionNote]) -> None:
        """Pair the reply section notes with the call markers; best effort, never a failure."""
        sids = call.section_ids()
        notes = list(reply.sections or [])
        pairs: List[Tuple[Optional[str], Any]] = []
        if len(notes) == len(sids):
            pairs = list(zip(sids, notes))
        else:
            used = set()
            for sid in sids:
                if sid is None:
                    continue
                want = _fold(rows_by_id[sid].title)
                for i, n in enumerate(notes):
                    if i not in used and _fold(n.section) == want:
                        used.add(i)
                        pairs.append((sid, n))
                        break
        for sid, n in pairs:
            if sid is None:
                continue
            cur = merged.setdefault(sid, SectionNote())
            summary = (n.summary or "").strip()
            if summary:
                cur.summary = f"{cur.summary} {summary}" if cur.summary else summary
            seen = {_fold(o) for o in cur.objectives}
            for o in n.objectives or []:
                if o and _fold(o) not in seen:
                    seen.add(_fold(o))
                    cur.objectives.append(o)

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

    def execute_global_pass(self, all_chunks: List[Dict[str, Any]], max_chars: int) -> Tuple[List[Any], List[str]]:
        """
        Converts elements to Markdown and chunks them based on token limits.
        Extracts the LLM outline (titles and nesting only) from each chunk.
        Returns (outlines in chunk order, failure messages): a failed chunk is
        reported, not swallowed, so the outline build can refuse a partial result.
        """
        # FIXED: Resilient fetch
        dynamic_instructions = self._get_dynamic_prompt(
            prompt_name="core_instructions",
            fallback_file="prompts/core_instructions.md"
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
        baml_responses = []
        failures: List[str] = []
        
        for i, chunk_text in enumerate(safe_chunks):
            print(f"[TrainingPlugin] Processing Markdown chunk {i+1}/{len(safe_chunks)}")
            try:
                # FIXED: Now passing both document_text and dynamic instructions
                partial = b.ExtractOutline(
                    document_text=chunk_text,
                    system_instructions=dynamic_instructions
                )
                baml_responses.append(partial)
            except Exception as e:
                print(f"[TrainingPlugin] Outline extraction failed on chunk {i+1}: {e}")
                failures.append(f"chunk {i+1}/{len(safe_chunks)}: {type(e).__name__}: {e}")
                
        return baml_responses, failures

    def _extract_raw_text_outlines(self, full_text: str, max_chars: int, overlap_chars: int) -> Tuple[List[Any], List[str]]:
        """The raw-text ExtractOutline chunk loop (no elements): (outlines, failures)."""
        from doc_tools.baml_client.sync_client import b
        dynamic_instructions = self._get_dynamic_prompt(
            prompt_name="core_instructions",
            fallback_file="prompts/core_instructions.md"
        )
        if len(full_text) <= max_chars:
            print(f"[TrainingPlugin] Document fits in context ({len(full_text)} chars)")
            return [b.ExtractOutline(document_text=full_text,
                                     system_instructions=dynamic_instructions)], []
        print(f"[TrainingPlugin] Document too large ({len(full_text)} chars), chunking...")
        chunks = self._chunk_text(full_text, max_chars, overlap_chars)
        outlines: List[Any] = []
        failures: List[str] = []
        for i, (chunk_text, _start) in enumerate(chunks):
            print(f"[TrainingPlugin] Processing chunk {i+1}/{len(chunks)}")
            try:
                outlines.append(b.ExtractOutline(document_text=chunk_text,
                                                 system_instructions=dynamic_instructions))
            except Exception as e:
                print(f"[TrainingPlugin] Chunk {i+1} failed: {e}")
                failures.append(f"chunk {i+1}/{len(chunks)}: {type(e).__name__}: {e}")
        return outlines, failures

    def process_fulltext(self, full_text: str, doc_id: str, metadata: Dict[str, Any] = None, elements: List[Dict[str, Any]] = None) -> List[DocumentNode]:
        """
        Build the Course -> Section outline (structural.outline). A deck that marks
        its own sections yields it from the elements alone; otherwise the LLM's
        titles and nesting are anchored to element pages. Raises OutlineBuildError
        if the outline cannot be built completely (no mock, no partial result).
        """
        if metadata is None:
            metadata = {}

        import os
        context_size = int(os.getenv("LLM_NUM_CTX", "8192"))
        reserved_tokens = 4000
        chars_per_token = 3
        max_chars = (context_size - reserved_tokens) * chars_per_token
        overlap_chars = max(1000, max_chars // 10)

        def extract() -> Tuple[List[Any], List[str]]:
            # The BAML import happens in here, so the deck path never imports it.
            if elements:
                print(f"[TrainingPlugin] Using Markdown pre-processor on {len(elements)} elements")
                return self.execute_global_pass(elements, max_chars)
            return self._extract_raw_text_outlines(full_text, max_chars, overlap_chars)

        final_sections, outline_source = build_outline(elements, extract)
        augmentation = OutlineAugmentation(
            sections=final_sections, metadata=metadata, outline_source=outline_source)

        # Return as a special "Global" DocumentNode
        global_section = BaseSection(title="Course Outline", level=0, page_start=0, content="", node_id=doc_id)
        return [DocumentNode(base_extraction=global_section, domain_augmentation=augmentation)]

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any, doc_id: str = "", image_prefix: str = "") -> Tuple[List[str], List[str]]:
        cypher_queries = []
        alias_pairs: List[Tuple[str, str]] = []
        alias_seen = set()
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
                MATCH (c:{config.graph_node_label}:{self.domain_label} {{id: $id}})
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

                # Flat pre-order rows. Section.id stays positional (contract 3):
                # {parent}_s{i}. end_page is never 0 (contract 4.5). One id scheme,
                # shared with the concept calls and the Weaviate section objects.
                rows: List[Dict[str, Any]] = []
                for r in concept_groups.flatten_outline(aug.sections, course_id):
                    note = aug.section_notes.get(r.id)
                    rows.append({
                        "id": r.id,
                        "title": r.title,
                        "level": r.level,
                        "start_page": r.start_page,
                        "end_page": r.end_page,
                        "parent_id": r.parent_id,
                        "summary": (note.summary or None) if note else None,
                        "objectives": list(note.objectives) if note else [],
                    })


                # ONE statement, one transaction: delete this Course's old Sections
                # (reached by HAS_SECTION, or orphaned under the id prefix), set
                # outline_source, write the new ones. It names only Section:{label}
                # as a delete target (contract 4.4 rule 4).
                label = self.domain_label
                replace_cypher = f"""
                MATCH (c:{config.graph_node_label}:{label} {{id: $course_id}})
                OPTIONAL MATCH (c)-[:HAS_SECTION*]->(o1:Section:{label})
                WITH c, collect(DISTINCT o1) AS reached
                OPTIONAL MATCH (o2:Section:{label}) WHERE o2.id STARTS WITH $id_prefix
                WITH c, reached, collect(DISTINCT o2) AS orphans
                WITH c, reached + [o IN orphans WHERE NOT o IN reached] AS olds
                FOREACH (o IN olds | DETACH DELETE o)
                SET c.outline_source = $outline_source
                WITH c
                UNWIND $sections AS row
                MERGE (s:Section:{label} {{id: row.id}})
                SET s.title = row.title, s.level = row.level,
                    s.start_page = row.start_page, s.end_page = row.end_page,
                    s.summary = row.summary, s.objectives = row.objectives
                WITH c, collect(row) AS rows
                UNWIND rows AS row
                MATCH (s:Section:{label} {{id: row.id}})
                MATCH (p:{label} {{id: row.parent_id}})
                MERGE (p)-[:HAS_SECTION]->(s)
                """
                cypher_queries.append({
                    "query": replace_cypher,
                    "params": {
                        "course_id": course_id,
                        "id_prefix": course_id + "_s",
                        "outline_source": aug.outline_source,
                        "sections": rows,
                    }
                })
                continue
                
            # 2. Handle Individual Slide Processing
            if not isinstance(aug, SlideAugmentation):
                continue
                
            # Use unified hardware ID linking Graph to Vector DB
            section_id = sec.node_id or f"section_{sec.page_start}_{sec.title}"
            # WARNING: String parameterization used per instructions because neo4j drivers cannot param labels
            cypher = f"""
            MERGE (s:{config.graph_child_label}:{self.domain_label} {{id: $section_id}})
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
            
            # Map Concepts -> (Section)-[:TEACHES {salience}]->(Concept)
            #
            # Salience is on the EDGE (#163: in the node key it meant one node per
            # salience). The node merges on `id = hash(domain, normalized name)` --
            # architect's ruling 2026-10-24, after lane tr found Neo4j has no
            # uniqueness on Concept at all. Merging on `name` kept the contract's "one
            # Concept:TRAINING per name across courses" but left the key unnormalized
            # and unconstrained: `Torque control` and `Torque  Control` were two nodes
            # and nothing in the database refused a third. The id is one property, so
            # `concept_id_unique` can constrain it; the domain is inside it, so
            # `Torque Control` in two domains stays two concepts. NOT a name
            # constraint, for that reason. See doc_tools/utils/concept_identity.py and
            # scripts/neo4j_concept_id_migration.py.
            #
            # `name` is set ON CREATE only: the id is derived from the NORMALIZED name,
            # so two spellings share a node and the first spelling seen is the one kept
            # -- a plain SET would make the node's display name depend on slide order.
            # `name_normalized` is stored so the id can be recomputed from the node.
            for raw_concept in aug.concepts:
                concept_id = concept_node_id(self.domain_label, raw_concept.name)
                related = [t.strip() for t in raw_concept.related_terms if t and t.strip()]
                for term in related:
                    if normalize_concept_name(term) != normalize_concept_name(raw_concept.name):
                        pair = (concept_id, concept_node_id(self.domain_label, term))
                        if pair not in alias_seen:
                            alias_seen.add(pair)
                            alias_pairs.append(pair)
                edge_cypher = f"""
                MERGE (s:{config.graph_child_label}:{self.domain_label} {{id: $section_id}})
                MERGE (c:Concept:{self.domain_label} {{id: $concept_id}})
                ON CREATE SET c.name = $c_name
                SET c.domain = $c_domain, c.name_normalized = $c_name_normalized
                MERGE (s)-[t:TEACHES]->(c)
                SET t.salience = $c_salience, t.related_terms = $c_related_terms
                """
                cypher_queries.append({
                    "query": edge_cypher,
                    "params": {
                        "section_id": section_id,
                        "concept_id": concept_id,
                        "c_name": raw_concept.name,
                        "c_name_normalized": normalize_concept_name(raw_concept.name),
                        "c_domain": self.domain_label,
                        "c_salience": raw_concept.salience,
                        "c_related_terms": related
                    }
                })

            # Map Figure References -> (Slide)-[:REFERENCES_FIGURE]->(Figure)
            if aug.figure_references:
                fig_cypher = f"""
                MERGE (s:{config.graph_child_label}:{self.domain_label} {{id: $section_id}})
                WITH s
                UNWIND $figures AS fig_ref
                MERGE (f:Figure:{self.domain_label} {{id: "fig_" + fig_ref}})
                ON CREATE SET f.url = $image_prefix + fig_ref + ".png", f.title = fig_ref
                MERGE (s)-[:REFERENCES_FIGURE]->(f)
                """
                cypher_queries.append({
                    "query": fig_cypher,
                    "params": {
                        "section_id": section_id,
                        "figures": aug.figure_references,
                        "image_prefix": image_prefix
                    }
                })

        # Candidate ALIAS_OF edges (contract v4 section 4.2), AFTER every TEACHES so the
        # Concepts of this run exist. MATCH, not MERGE, on the target: the edge reaches
        # only a Concept that already exists (this run's, or an earlier course's); a term
        # naming no Concept creates nothing. Never a merge of the nodes -- unification
        # is the normalisation pass's job, and these edges are only its candidates.
        for (from_id, to_id) in alias_pairs:
            cypher_queries.append({
                "query": f"""
                MATCH (a:Concept:{self.domain_label} {{id: $from_id}})
                MATCH (b:Concept:{self.domain_label} {{id: $to_id}})
                MERGE (a)-[r:ALIAS_OF]->(b)
                ON CREATE SET r.status = 'candidate', r.source = 'related_terms', r.course_id = $course_id
                """,
                "params": {"from_id": from_id, "to_id": to_id, "course_id": doc_id},
            })

        # Domain A uses Neo4j strictly, no Jena graphs
        return cypher_queries, sparql_queries

    def execute_pass2_rollup(self, neo4j_client: Any, doc_id: str, config: Any) -> None:
        """
        Legacy Pass 2: Link Slides to Sections and roll up Concept hierarchies.
        """
        # 1. Link Slides (Pages) to Sections based on Page Numbers
        # Contract training-workbench.md 4.2: the overlay edge (HAS_SLIDE) is
        # written alongside HAS_CHILD, range-wide, same predicate.
        slide_edge = overlay_for("training").edge
        link_query = f"""
        MATCH (c:{config.graph_node_label}:{self.domain_label} {{id: $doc_id}})-[:HAS_SECTION*]->(sec:Section:{self.domain_label})
        MATCH (c)-[:HAS_CHILD]->(s:{config.graph_child_label}:{self.domain_label})
        WHERE s.number >= sec.start_page 
          AND (sec.end_page = 0 OR s.number <= sec.end_page)
        MERGE (sec)-[:HAS_CHILD]->(s)
        MERGE (sec)-[:{slide_edge}]->(s)
        """
        neo4j_client.execute_query(link_query, {"doc_id": doc_id})

        # 2. Roll-up Concepts to Sections (COVERS Relationship)
        rollup_query = f"""
        MATCH (c:{config.graph_node_label}:{self.domain_label} {{id: $doc_id}})-[:HAS_SECTION*]->(sec:Section:{self.domain_label})
        MATCH (sec)-[:HAS_CHILD]->(s:{config.graph_child_label}:{self.domain_label})-[t:TEACHES]->(con:Concept:{self.domain_label})
        WITH sec, con, avg(t.salience) as avg_score, count(s) as frequency
        MERGE (sec)-[r:COVERS]->(con)
        SET r.score = avg_score, r.frequency = frequency
        """
        neo4j_client.execute_query(rollup_query, {"doc_id": doc_id})

        # 3. Create Lightweight Summaries
        summary_query = f"""
        MATCH (c:{config.graph_node_label}:{self.domain_label} {{id: $doc_id}})-[:HAS_SECTION*]->(sec:Section:{self.domain_label})
        OPTIONAL MATCH (sec)-[r:COVERS]->(con:Concept:{self.domain_label})
        WITH sec, con, r.score as score
        ORDER BY score DESC
        WITH sec, collect(con.name) as concepts
        SET sec.concept_summary = concepts[0..10]
        """
        neo4j_client.execute_query(summary_query, {"doc_id": doc_id})
