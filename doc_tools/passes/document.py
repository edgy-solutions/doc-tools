"""``document.document_outline`` — the section outline of one of our own documents.

The architect's 2026-10-25 order:

    *"A drop of a general document (manual, procedure, spec) that is not a
    PCN/PDN/S1000D should ingest as kind `document` with review_shape
    `document`, chunk to Weaviate with page refs, and land in the graph as
    Document → Section → Chunk so ask-the-manual can cite page + heading."*

This pass is the Section layer of that shape. It answers one question for every
page of a document: **which heading is this page under?** A chunk can then carry
its page number and its section's heading, and an answer can cite both.

DETERMINISTIC AND LLM-FREE, for the same reason ``identity.py`` is
---------------------------------------------------------------------
A heading is printed. It does not need to be inferred, and inferring it costs
the one property that makes a citation worth anything: that the same document
yields the same citation on every fire. This repo has a long record of
model-read fields that moved between fires on byte-identical input; a page
reference that moves is worse than none, because it is checkable and wrong.

So the outline is read off the page with three ordered recognizers, and a page
with no heading above it is NOT given one.

WHAT COUNTS AS A HEADING
------------------------
In declared order, highest confidence first:

1. ``element_title`` — the parser already classified the line. The ingest
   pipeline renders each element as ``[Title] 3.2 Torque sequence``
   (``semantic_assets.py`` builds page text that way), so ``unstructured``'s own
   Title/Header classification is available here as data. When it is present it
   wins: it is the only signal produced by something that saw the font, the
   position and the whitespace rather than just the characters.
2. ``numbered`` — ``3``, ``3.2``, ``3.2.1`` followed by text. The level is the
   number of components, so the printed numbering IS the hierarchy; nothing
   guesses depth from indentation or font size, neither of which survives a text
   layer.
3. ``caps`` — a short, unnumbered, upper-case line (``PURPOSE``, ``SCOPE``,
   ``SAFETY PRECAUTIONS``). Level 1 only. Deliberately the last recognizer and
   the most constrained one: it is a shape match, and a shape match on body text
   is how a parts table's column header becomes a section.

A page-furniture line (``Page 3 of 6``, a bare page number, a revision stamp) is
excluded by name before any recognizer runs. This repo has already shipped a
defect where page furniture became a manufacturer
(``clause-1-writes-page-furniture-as-a-manufacturer``); furniture that becomes a
*heading* would be quieter, because every page has some.

ONE INVARIANT, ENFORCED IN CODE
-------------------------------
Every section's ``heading_source`` is a verbatim substring of the text of the
page it is attributed to. ``_verify`` checks it on the way out and raises
``OutlineError`` rather than returning a section. A heading that cannot be found
on its own page cannot be cited, and a citation that does not resolve is the
failure mode this repo has already met once from the other direction: a
resolving citation that wrapped a fabrication
(``a-resolving-citation-can-wrap-a-fabrication``). Both halves are needed, so
this pass owns the half it can prove.

A DOCUMENT WITH NO HEADINGS GETS ONE SYNTHETIC SECTION, MARKED
--------------------------------------------------------------
Not zero sections, because every chunk must hang off a Section for the graph
shape to be uniform and for a query to have one path. Not a *silent* section,
either: ``DocumentOutline.synthetic`` is True and the lone section's ``method``
is ``"synthetic"`` with an empty heading. An empty heading that looks read is
indistinguishable from a document whose headings this pass could not see
(``a-ruled-none-is-indistinguishable-from-a-missing-one``), so the flag is the
whole point of returning one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


class OutlineError(RuntimeError):
    """An invariant broke. Never raised for a document with no headings — that
    is the synthetic-section case, which is a result, not a fault."""


#: ``[Title] text`` / ``[NarrativeText] text`` — how ``semantic_assets.py``
#: renders one element into page text. The marker is stripped before any
#: recognizer sees the line, and remembered: it is recognizer 1's whole input.
_ELEMENT_MARKER = re.compile(r"^\[([A-Za-z]+)\]\s*(.*)$")

#: Element types that ARE a heading. ``unstructured`` emits ``Title`` for both
#: document titles and section headings and ``Header`` for running heads; the
#: latter is excluded deliberately — a running head repeats on every page, so
#: taking it as a heading would open a new section per page.
_HEADING_ELEMENTS = frozenset({"title", "sectionheader", "subtitle"})

#: ``3``, ``3.2``, ``3.2.1`` (optionally with a trailing dot) then the text.
#: Requires real text after the number so a bare ``3`` -- a page number, a table
#: cell, a step count -- is not a section.
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")

#: An unnumbered upper-case line. Length-capped: a long upper-case run is a
#: notice, a warning block or a legal paragraph, not a heading.
_CAPS_MAX_CHARS = 48

#: Admonition labels, excluded from the ``caps`` arm ONLY. A procedure prints
#: these above a step, not as a section, and a six-page procedure can print
#: `WARNING` four times -- which the caps arm would read as four sections, each
#: capturing the pages under it until the next real heading. Matched bare and
#: whole-line, so a genuine heading that CONTAINS the word (`WARNINGS AND
#: CAUTIONS`, a real S1000D section) still opens a section. Still recognized
#: when numbered: `2.1 WARNING` was given a section number by whoever wrote the
#: document, and that is their declaration, not our inference.
_ADMONITIONS = re.compile(
    r"^(warning|caution|note|notes|danger|notice|important|attention)"
    r"\s*[:.!]?$", re.I)

#: Page furniture, excluded before any recognizer. Anchored and whole-line, so a
#: heading that merely CONTAINS one of these words survives.
_FURNITURE = (
    re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.I),
    re.compile(r"^\d+$"),
    re.compile(r"^(rev(ision)?|issue)\.?\s*[:\-]?\s*[A-Z0-9.\-]{1,12}$", re.I),
    re.compile(r"^(confidential|uncontrolled copy|controlled copy|draft)$", re.I),
    re.compile(r"^\(?(continued|cont\.?)\)?$", re.I),
    re.compile(r"^(effective|issued|approved)(\s+date)?\s*[:\-].*$", re.I),
)


@dataclass(frozen=True)
class OutlineSection:
    """One section of the outline.

    ``id`` is path-encoded (``<doc_id>_s2_s1``) rather than sequential, so the
    id itself carries the hierarchy and a child's id cannot be read without its
    parent's -- the same convention the training workbench contract uses for
    course sections, kept deliberately so the two shapes read alike.
    """

    id: str
    parent: str
    heading: str
    level: int
    start_page: int
    end_page: int
    method: str
    heading_source: str
    number: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "parent": self.parent, "heading": self.heading,
            "level": self.level, "start_page": self.start_page,
            "end_page": self.end_page, "method": self.method,
            "heading_source": self.heading_source, "number": self.number,
        }


@dataclass(frozen=True)
class DocumentOutline:
    """The outline, plus the page → section map the chunk writer needs."""

    doc_id: str
    sections: tuple[OutlineSection, ...]
    page_count: int
    synthetic: bool

    def section_for_page(self, page: int) -> OutlineSection | None:
        """The DEEPEST section covering ``page``.

        Deepest, not first: a chunk should cite the most specific heading it sits
        under, which is what a reader would quote. Ties break on start_page so a
        page carrying two headings cites the one it opens under.
        """
        covering = [s for s in self.sections
                    if s.start_page <= page <= s.end_page]
        if not covering:
            return None
        return sorted(covering, key=lambda s: (-s.level, -s.start_page))[0]

    def as_dict(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "page_count": self.page_count,
            "synthetic": self.synthetic,
            "sections": [s.as_dict() for s in self.sections],
        }


def _page_texts(pages: Sequence[str] | str) -> list[str]:
    if isinstance(pages, str):
        return [pages]
    return [p or "" for p in pages]


def _is_furniture(line: str) -> bool:
    return any(p.match(line) for p in _FURNITURE)


def _recognize(line: str) -> tuple[str, str, int, str] | None:
    """``(method, heading, level, number)`` for a heading line, else None."""
    marker = _ELEMENT_MARKER.match(line)
    element, text = (marker.group(1), marker.group(2)) if marker else ("", line)
    text = text.strip()
    if not text or _is_furniture(text):
        return None

    numbered = _NUMBERED.match(text)
    if element.lower() in _HEADING_ELEMENTS:
        # The parser said heading. Take its level from the printed numbering
        # when there is one -- the number is better evidence of DEPTH than the
        # classification is, which only says "this is a heading".
        if numbered:
            return ("element_title", numbered.group(2).strip(),
                    numbered.group(1).count(".") + 1, numbered.group(1))
        return ("element_title", text, 1, "")

    if numbered:
        return ("numbered", numbered.group(2).strip(),
                numbered.group(1).count(".") + 1, numbered.group(1))

    if (len(text) <= _CAPS_MAX_CHARS and text == text.upper()
            and any(c.isalpha() for c in text)
            and not _ADMONITIONS.match(text)):
        return ("caps", text, 1, "")

    return None


def _verify(section: OutlineSection, page_text: str) -> None:
    if section.method == "synthetic":
        return
    if section.heading_source not in page_text:
        raise OutlineError(
            f"section {section.id!r} attributes heading_source "
            f"{section.heading_source!r} to page {section.start_page}, where it "
            f"does not appear verbatim; a heading that cannot be found on its "
            f"own page cannot be cited")


def document_outline(pages: Sequence[str] | str, doc_id: str = "") -> DocumentOutline:
    """Read the section outline off the pages, deterministically.

    ``pages`` is a sequence of page texts (page numbers come out 1-based) or a
    single string (page 1) -- the same shape ``identity.document_identity``
    takes, and both names are in the dispatcher's vocabulary
    (``doc_tools/passes/dispatch.py``), so this pass runs under
    ``run_passes_for_kind("document", ...)`` with nothing format-specific in the
    call.

    Never raises for a document this pass cannot read. It raises only if a
    section it DID produce fails the verbatim invariant, which is a defect in
    this module rather than in the document.
    """
    texts = _page_texts(pages)
    found: list[tuple[int, str, str, int, str]] = []   # page, method, heading, level, number
    for index, text in enumerate(texts, start=1):
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            hit = _recognize(line)
            if hit is None:
                continue
            method, heading, level, number = hit
            found.append((index, method, heading, level, number))

    if not found:
        lone = OutlineSection(
            id=f"{doc_id}_s1", parent=doc_id, heading="", level=1,
            start_page=1, end_page=max(len(texts), 1), method="synthetic",
            heading_source="", number="")
        return DocumentOutline(doc_id=doc_id, sections=(lone,),
                               page_count=len(texts), synthetic=True)

    # Path-encoded ids: a stack of (level, id, child counter). A level that
    # SKIPS a depth (1 then 3, which a document with a missing 2.x prints) does
    # not invent the missing ancestor -- it nests under the deepest open
    # section, so the id stays a real path through sections that exist.
    stack: list[list] = []
    built: list[OutlineSection] = []
    sources: list[str] = []
    for page, method, heading, level, number in found:
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else doc_id
        if stack:
            stack[-1][2] += 1
            ordinal = stack[-1][2]
        else:
            ordinal = sum(1 for s in built if s.parent == doc_id) + 1
        sid = f"{parent}_s{ordinal}"
        # heading_source is the printed line reassembled from what the
        # recognizer split, so the invariant checks what the page actually
        # carries rather than the normalized heading.
        printed = f"{number} {heading}".strip() if number else heading
        section = OutlineSection(
            id=sid, parent=parent, heading=heading, level=level,
            start_page=page, end_page=page, method=method,
            heading_source=printed, number=number)
        built.append(section)
        sources.append(texts[page - 1])
        stack.append([level, sid, 0])

    # Spans: a section runs to the page before the next section that is not one
    # of its descendants, and therefore CONTAINS its subsections. The last
    # section runs to the last page.
    last_page = max(len(texts), 1)
    spans: list[OutlineSection] = []
    for i, section in enumerate(built):
        end = last_page
        for later in built[i + 1:]:
            if not later.id.startswith(section.id + "_s"):
                end = max(section.start_page, later.start_page - 1)
                break
        spans.append(OutlineSection(**{**section.as_dict(), "end_page": end}))

    for section, page_text in zip(spans, sources):
        _verify(section, page_text)

    return DocumentOutline(doc_id=doc_id, sections=tuple(spans),
                           page_count=len(texts), synthetic=False)
