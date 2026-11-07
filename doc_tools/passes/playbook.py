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
names, on each leaf, the ``chunk_id`` the chunker gives it. Ids come from
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
    method: str            # "atx" | "synthetic"
    chunk_id: str          # "" for a non-leaf heading, which has no chunk

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
    sections = tuple(
        PlaybookSection(
            id=n.section_id, parent=n.parent_id, heading=n.heading.heading,
            level=n.heading.level, heading_source=n.heading.heading_source,
            method="atx", chunk_id=chunk_by_section.get(n.section_id, ""))
        for n in layout(text, doc_id))
    return PlaybookOutline(doc_id=doc_id, sections=sections, synthetic=False)
