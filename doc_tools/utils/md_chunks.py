"""Chunk extraction from a markdown playbook for Weaviate ingest.

The only other chunker in the tree is ``xml_chunks.py`` (RDF graph -> chunks).
There was no markdown chunker and no heading splitter; this is it. The contract
is ``docs/contracts/playbook-kind.md`` section 3, and every strict choice below
is downstream of one consumer question -- *"how do we do this"* -- answered with
a citation of the form **repo + path + heading**. A citation that moves between
runs on the same bytes is worse than none, because it is checkable and wrong.

What is split, and what is a chunk
----------------------------------
ATX headings (``#`` .. ``######``) are the structure. A heading inside a fenced
code block (three backticks or three tildes) is NOT one: a shell comment in a
runbook step is not a section. Setext headings (underlined) are not recognized;
the contract says ATX.

One chunk per LEAF heading -- a heading with no deeper heading under it. Its
ancestors are carried as the heading path. Consequences, stated because they
are choices and not accidents:

  - The text a NON-leaf heading carries between itself and its first child, and
    any text before the first heading, is in no chunk. It is still in the
    outline (the pass returns every heading), so it is not invisible, but it is
    not retrievable. Contract section 3 says leaf; widening it is a contract
    change (section 11).
  - A chunk's text is its own heading line plus the body beneath it up to the
    next heading, stripped. The heading line is included so BM25 sees it.

``chunk_id`` is derived from the heading PATH, never from position
------------------------------------------------------------------
``f"{doc_id}_{heading_path_slug}_{sha1(text)[:12]}"``, the same idea as
``xml_chunks.py``: ``_index_chunk`` hashes ``chunk_id`` into the Weaviate uuid,
so a re-ingest overwrites rather than duplicates, and a re-parse that REORDERS
two sections must not re-mint either id. Two chunks identical in path and text
are the same chunk; the second is dropped, deliberately.

Section ids are path-derived too. A heading that repeats an earlier sibling's
path gets a ``_2`` suffix: the one place an ordinal appears, and only on a
collision.

Two invariants, enforced in code
--------------------------------
1. A chunk's heading is a verbatim substring of the source text, or this module
   raises ``MarkdownChunkError``. A heading that is not in the file it cites is
   the failure this design exists to prevent (compare
   ``passes/document.py::_verify``).
2. A file with NO heading gets exactly one chunk, marked ``synthetic: True`` with
   an empty heading -- never silently. An empty heading that looks read is
   indistinguishable from one that could not be read. A file with no text at all
   raises: there is nothing to cite.

Provenance
----------
Every chunk carries ``{source, path, heading}``. ``source`` is the repo URL and
``path`` the repo-relative file path; both are plain inputs here, because this
module reads no repo. ``page`` is ABSENT: a markdown file has no pages, and
``_page_property`` already maps anything that is not a clean integer to None.

NO MOCK CONTENT. Nothing here substitutes text for text it could not read; a
failure raises.
"""
from __future__ import annotations

import hashlib
import posixpath
import re
from dataclasses import dataclass
from typing import Optional

_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_UNSAFE = re.compile(r"[^a-z0-9]+")
PATH_SEP = "__"


class MarkdownChunkError(RuntimeError):
    """An invariant broke, or there was nothing to chunk. Never swallowed."""


@dataclass(frozen=True)
class MdHeading:
    """One ATX heading as read, with enough to verify it against the source."""

    level: int
    heading: str           # the text after the hashes, closing hashes removed
    heading_source: str    # the whole printed line, verbatim
    line: int              # 0-based line index in the source


@dataclass(frozen=True)
class MdNode:
    """A heading placed in the tree: its path, its path-derived id, its parent."""

    heading: MdHeading
    path: tuple            # ancestor headings' text, ending with this one's
    section_id: str
    parent_id: str         # parent section id, or the doc_id at the top level
    is_leaf: bool


def playbook_doc_id(repo_name: str, repo_path: str) -> str:
    """``f"{repo_name}.{extension_stripped_repo_relative_path}"``.

    The DDS asset builds ``f"{repo_name}.{repo_path}"``; this is the same shape
    with the extension removed. A path-fragment doc_id is an already-known shape
    in this repo (``manifest-doc-id-can-be-a-path-fragment``), not a new one.
    """
    if not repo_name or not repo_path:
        raise MarkdownChunkError("a doc_id needs both a repo name and a path")
    norm = repo_path.replace("\\", "/").lstrip("/")
    stem, _ext = posixpath.splitext(norm)
    return f"{repo_name}.{stem}"


def slug(heading: str) -> str:
    """Lower-case ``[a-z0-9]`` runs joined by ``-``. Never empty."""
    return _UNSAFE.sub("-", heading.lower()).strip("-") or "untitled"


def read_headings(text: str) -> list[MdHeading]:
    """Every ATX heading in ``text``, in order, outside fenced code blocks."""
    found: list[MdHeading] = []
    fence: Optional[str] = None
    for index, raw in enumerate(text.splitlines()):
        marker = _FENCE.match(raw)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = run[0] * len(run)
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        hit = _ATX.match(raw)
        if hit is None:
            continue
        body = _CLOSING_HASHES.sub("", hit.group(2) or "").strip()
        if not body:
            continue            # a bare hash names nothing and cannot be cited
        found.append(MdHeading(level=len(hit.group(1)), heading=body,
                               heading_source=raw.rstrip(), line=index))
    return found


def _verify(heading: MdHeading, text: str) -> None:
    if heading.heading_source not in text or heading.heading not in heading.heading_source:
        raise MarkdownChunkError(
            f"heading {heading.heading!r} (line {heading.line + 1}) is not a "
            f"verbatim substring of the source; a heading that cannot be found "
            f"in the file it cites cannot be cited")


def layout(text: str, doc_id: str) -> list[MdNode]:
    """Every heading placed in the tree, verified against ``text``.

    The one place ids are minted, shared by the chunker and the outline pass so
    they cannot disagree. A level that skips a depth nests under the deepest open
    heading rather than inventing an ancestor.
    """
    headings = read_headings(text)
    for h in headings:
        _verify(h, text)
    stack: list[tuple[MdHeading, str, tuple]] = []   # heading, section id, path
    seen: dict[str, int] = {}
    nodes: list[MdNode] = []
    for i, h in enumerate(headings):
        while stack and stack[-1][0].level >= h.level:
            stack.pop()
        path = (stack[-1][2] if stack else ()) + (h.heading,)
        base = f"{doc_id}_{PATH_SEP.join(slug(p) for p in path)}"
        n = seen.get(base, 0) + 1
        seen[base] = n
        sid = base if n == 1 else f"{base}_{n}"
        is_leaf = i + 1 >= len(headings) or headings[i + 1].level <= h.level
        nodes.append(MdNode(heading=h, path=path, section_id=sid,
                            parent_id=stack[-1][1] if stack else doc_id,
                            is_leaf=is_leaf))
        stack.append((h, sid, path))
    return nodes


def split_markdown(text: str, doc_id: str) -> list[dict]:
    """Leaf-heading units of ``text``, without provenance.

    Each dict: ``text, doc_id, chunk_id, section_id, heading, heading_path,
    level, synthetic``.
    """
    if not doc_id:
        raise MarkdownChunkError("doc_id is required: every chunk_id is prefixed with it")
    if not text.strip():
        raise MarkdownChunkError(f"{doc_id}: no text to chunk")

    nodes = layout(text, doc_id)
    if not nodes:
        body = text.strip()
        return [{
            "text": body, "doc_id": doc_id,
            "chunk_id": _chunk_id(doc_id, "", body),
            "section_id": f"{doc_id}_synthetic", "heading": "",
            "heading_path": [], "level": 0, "synthetic": True,
        }]

    lines = text.splitlines()
    out: list[dict] = []
    seen_ids: set[str] = set()
    for i, node in enumerate(nodes):
        if not node.is_leaf:
            continue
        h = node.heading
        end = nodes[i + 1].heading.line if i + 1 < len(nodes) else len(lines)
        body = "\n".join(lines[h.line:end]).strip()
        path_slug = PATH_SEP.join(slug(p) for p in node.path)
        chunk_id = _chunk_id(doc_id, path_slug, body)
        if chunk_id in seen_ids:
            continue            # same path, same text: the same chunk
        seen_ids.add(chunk_id)
        out.append({
            "text": body, "doc_id": doc_id, "chunk_id": chunk_id,
            "section_id": node.section_id, "heading": h.heading,
            "heading_path": list(node.path), "level": h.level,
            "synthetic": False,
        })
    return out


def chunk_markdown(text: str, doc_id: str, source: str, path: str) -> list[dict]:
    """Chunk dicts ready for ``_index_chunk``, with the citation triple.

    ``source`` (repo URL) and ``path`` (repo-relative file path) are required and
    non-empty: a chunk that cites a heading but not where it lives is half a
    citation. No ``page`` key is emitted.
    """
    if not source or not path:
        raise MarkdownChunkError(
            "source and path are required: a citation is repo + path + heading")
    chunks = split_markdown(text, doc_id)
    for chunk in chunks:
        chunk["source"] = source
        chunk["path"] = path
    return chunks


def _chunk_id(doc_id: str, path_slug: str, text: str) -> str:
    text_key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"{doc_id}_{path_slug}_{text_key}"
