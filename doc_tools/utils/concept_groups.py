"""Group a course's slides into concept calls: at most 8 slides a call, aligned to the outline.

Contract: ``docs/contracts/training-workbench.md`` section 4.6 (v4).

A slide belongs to the DEEPEST outline section whose page range holds it.
Consecutive slides of one section form a run. A run longer than ``MAX_SLIDES`` is
split into near-equal pieces; runs are then packed, in page order, into calls of
at most ``MAX_SLIDES`` slides without splitting a run. So a section is split only
when it alone is longer than ``MAX_SLIDES``, and short sections share a call, each
under its own marker and with its own notes in the reply. (A deck whose outline is
one section per slide would otherwise make one call per slide, which is today's
cost.)

Pure: no I/O and no LLM import.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MAX_SLIDES = 8
UNSECTIONED_TITLE = "(no section)"


@dataclass(frozen=True)
class SectionRow:
    """One outline section, flattened. ``id`` is the Section node id (contract 3)."""
    id: str
    title: str
    level: int
    start_page: int
    end_page: int
    parent_id: str
    depth: int


@dataclass(frozen=True)
class ConceptCall:
    pages: Tuple[int, ...]
    # parallel to ``pages``: the id of the section each page belongs to, or None
    page_sections: Tuple[Optional[str], ...]

    def section_ids(self) -> List[Optional[str]]:
        """Sections in marker order: one entry per run, so a repeat is a new marker."""
        out: List[Optional[str]] = []
        for i, sid in enumerate(self.page_sections):
            if i == 0 or sid != self.page_sections[i - 1]:
                out.append(sid)
        return out


def flatten_outline(sections: Iterable[Any], course_id: str) -> List[SectionRow]:
    """Pre-order rows with positional ids ``{parent}_s{i}``; ``end_page`` never < ``start_page``."""
    rows: List[SectionRow] = []

    def walk(secs: Iterable[Any], parent_id: str, depth: int) -> None:
        for i, s in enumerate(secs):
            sid = f"{parent_id}_s{i}"
            rows.append(SectionRow(
                id=sid, title=s.title, level=s.level, start_page=s.start_page,
                end_page=max(s.end_page or s.start_page, s.start_page),
                parent_id=parent_id, depth=depth))
            walk(s.subsections or [], sid, depth + 1)

    walk(sections or [], course_id, 0)
    return rows


def section_of(page: int, rows: Sequence[SectionRow]) -> Optional[SectionRow]:
    """The deepest section holding ``page``; of two at one depth, the later start."""
    best: Optional[SectionRow] = None
    for r in rows:
        if r.start_page <= page <= r.end_page:
            if best is None or (r.depth, r.start_page) > (best.depth, best.start_page):
                best = r
    return best


def plan_calls(pages: Iterable[int], rows: Sequence[SectionRow],
               max_slides: int = MAX_SLIDES) -> List[ConceptCall]:
    if max_slides < 1:
        raise ValueError("max_slides must be >= 1")
    runs: List[Tuple[Optional[str], List[int]]] = []
    for p in sorted(set(pages)):
        s = section_of(p, rows)
        sid = s.id if s else None
        if runs and runs[-1][0] == sid:
            runs[-1][1].append(p)
        else:
            runs.append((sid, [p]))

    pieces: List[Tuple[Optional[str], List[int]]] = []
    for sid, ps in runs:
        if len(ps) <= max_slides:
            pieces.append((sid, ps))
            continue
        n = -(-len(ps) // max_slides)
        size = -(-len(ps) // n)
        pieces.extend((sid, ps[i:i + size]) for i in range(0, len(ps), size))

    calls: List[ConceptCall] = []
    cur: List[Tuple[Optional[str], List[int]]] = []

    def close() -> None:
        if cur:
            pages_ = tuple(p for _, ps in cur for p in ps)
            secs = tuple(sid for sid, ps in cur for _ in ps)
            calls.append(ConceptCall(pages=pages_, page_sections=secs))
            cur.clear()

    for piece in pieces:
        if cur and sum(len(ps) for _, ps in cur) + len(piece[1]) > max_slides:
            close()
        cur.append(piece)
    close()
    return calls


def render_call(call: ConceptCall, texts: Dict[int, str],
                rows_by_id: Dict[str, SectionRow]) -> str:
    """The ``section_text`` the model reads: section and slide markers, then slide text."""
    out: List[str] = []
    for i, (p, sid) in enumerate(zip(call.pages, call.page_sections)):
        if i == 0 or sid != call.page_sections[i - 1]:
            title = rows_by_id[sid].title if sid is not None else UNSECTIONED_TITLE
            out.append(f"=== Section: {title} ===")
        out.append(f"=== Slide {p} ===\n{texts[p]}")
    return "\n\n".join(out)
