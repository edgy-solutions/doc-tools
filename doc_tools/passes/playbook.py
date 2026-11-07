"""``playbook.playbook_outline`` -- the heading outline of a markdown playbook.

Contract: ``docs/contracts/playbook-kind.md``. Deterministic and LLM-free: a
heading is printed, not inferred, and a citation (repo + path + heading) that
moves between runs on the same bytes is worse than none.

THE SIGNATURE IS THE DISPATCHER'S VOCABULARY, AND NOTHING ELSE
--------------------------------------------------------------
``PassContext`` binds pass parameters by name from ``pages, text, raw_bytes,
doc_id``; a parameter outside it raises ``PassContractError``. So this takes
``text`` and ``doc_id`` only. ``source`` and ``path`` are NOT in the vocabulary
and are supplied at the write site (``md_chunks.chunk_markdown``), not here.

The outline lists EVERY heading as a section (so the graph has its tiers) and
names, on each section that has prose of its own, the ``chunk_id`` the chunker
gives it -- every heading with prose, not only a leaf, since the ruling of
2026-11-07. It also carries one ``method="preamble"`` section for the text
before the first heading, so that chunk is reachable. Ids come from
``utils/md_chunks`` so the outline and the Weaviate chunks cannot disagree. The
verbatim invariant and the synthetic-section rule live there and raise
``MarkdownChunkError``, which the dispatcher records as a refusal.
"""
from __future__ import annotations

from dataclasses import dataclass

from doc_tools.utils.md_chunks import layout, split_markdown


@dataclass(frozen=True)
class PlaybookSection:
    id: str
    parent: str            # parent section id, or the doc_id for a top-level one
    heading: str
    level: int
    heading_source: str
    method: str            # "atx" | "synthetic" | "preamble"
    chunk_id: str          # "" for a heading with no prose of its own

    def as_dict(self) -> dict:
        return {
            "id": self.id, "parent": self.parent, "heading": self.heading,
            "level": self.level, "heading_source": self.heading_source,
            "method": self.method, "chunk_id": self.chunk_id,
        }


@dataclass(frozen=True)
class PlaybookOutline:
    doc_id: str
    sections: tuple
    synthetic: bool

    def as_dict(self) -> dict:
        return {"doc_id": self.doc_id, "synthetic": self.synthetic,
                "sections": [s.as_dict() for s in self.sections]}


def playbook_outline(text: str, doc_id: str = "") -> PlaybookOutline:
    """Read the heading tree off a markdown playbook.

    Raises ``MarkdownChunkError`` for an empty file, a missing doc_id, or a
    heading that fails the verbatim invariant; the dispatcher records that as
    ``refused``.
    """
    chunks = split_markdown(text, doc_id)
    if chunks[0]["synthetic"]:
        lone = chunks[0]
        return PlaybookOutline(
            doc_id=doc_id, synthetic=True,
            sections=(PlaybookSection(
                id=lone["section_id"], parent=doc_id, heading="", level=0,
                heading_source="", method="synthetic",
                chunk_id=lone["chunk_id"]),))

    chunk_by_section = {c["section_id"]: c["chunk_id"] for c in chunks}
    nodes = layout(text, doc_id)
    sections = [
        PlaybookSection(
            id=n.section_id, parent=n.parent_id, heading=n.heading.heading,
            level=n.heading.level, heading_source=n.heading.heading_source,
            method="atx", chunk_id=chunk_by_section.get(n.section_id, ""))
        for n in nodes]

    # A CHUNK WITH NO SECTION IS UNREACHABLE. The pre-heading chunk (ruled
    # 2026-11-07) has a section id the heading tree does not contain, because
    # it is under no heading. Without a section for it, the plugin writes no
    # HAS_CHUNK edge and the chunk sits in Weaviate reachable by nothing in
    # Neo4j -- a hole that no test of either store alone would show. Derived
    # from the chunks rather than from a flag, so a later chunk kind that is
    # not a heading cannot reintroduce the same hole.
    placed = {n.section_id for n in nodes}
    for c in chunks:
        if c["section_id"] in placed:
            continue
        sections.insert(0, PlaybookSection(
            id=c["section_id"], parent=doc_id, heading=c["heading"],
            level=c["level"], heading_source="", method="preamble",
            chunk_id=c["chunk_id"]))

    return PlaybookOutline(doc_id=doc_id, sections=tuple(sections),
                           synthetic=False)
