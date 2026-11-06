"""``structural.outline`` -- a course's Section tree, with pages from the elements.

Contract: ``docs/contracts/training-workbench.md`` section 4.5 (v3).

Page numbers are element ``metadata.page_number``, never the LLM's. Two paths:

* the DECK path: a deck that marks its own sections (a slide holding exactly one
  numbered Title, ``"1.1.1 Pumps"``) yields its outline from the elements alone,
  and no LLM is called;
* the LLM path: the LLM outline supplies titles and nesting only; each title is
  anchored to the page whose ``Title`` element carries it.

This module is pure: no I/O and no LLM import. (The pass is named
``structural.outline``; the dispatcher resolves a pass name by its namespace, so
the module is ``structural``.)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel


class CourseSection(BaseModel):
    title: str
    level: int
    start_page: int
    end_page: Optional[int] = None
    subsections: List["CourseSection"] = []


class OutlineBuildError(RuntimeError):
    """The outline could not be built completely; nothing may replace the old one."""


_LEADING_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
_TRAILING_COUNTER = re.compile(r"\s*\(\d+\)\s*$")
_HEADER = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(\S.*)$", re.DOTALL)


def norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKC", t or "")
    t = _LEADING_NUMBER.sub("", t, count=1)
    t = _TRAILING_COUNTER.sub("", t, count=1)
    return " ".join(t.split()).strip().casefold()


def _page(el: dict) -> Optional[int]:
    p = (el.get("metadata") or {}).get("page_number")
    return p if isinstance(p, int) else None


def _last_page(elements: Iterable[dict]) -> int:
    return max((p for p in (_page(e) for e in elements) if p is not None), default=1)


# --- shared assembly --------------------------------------------------------

def _assemble(flat: List[Tuple[int, str, int]], last_page: int) -> List[CourseSection]:
    """Flat pre-order ``(level, title, start_page)`` -> nested CourseSections.

    End page: the start page of the next later entry with level <= its own, minus
    one; else ``last_page``; clamped to >= start_page (so never 0).
    """
    ends: List[int] = []
    for i, (level, _t, start) in enumerate(flat):
        end = last_page
        for lvl2, _t2, start2 in flat[i + 1:]:
            if lvl2 <= level:
                end = start2 - 1
                break
        ends.append(max(end, start))

    roots: List[CourseSection] = []
    stack: List[CourseSection] = []
    for (level, title, start), end in zip(flat, ends):
        node = CourseSection(title=title, level=level, start_page=start, end_page=end,
                             subsections=[])
        while stack and stack[-1].level >= level:
            stack.pop()
        (stack[-1].subsections if stack else roots).append(node)
        stack.append(node)
    return roots


# --- deck path ---------------------------------------------------------------

def outline_from_deck(elements: Optional[List[dict]]) -> Optional[List[CourseSection]]:
    """The deck's own sections, or None when no slide is a section header."""
    if not elements:
        return None
    by_page: Dict[int, List[dict]] = {}
    for el in elements:
        p = _page(el)
        if p is not None:
            by_page.setdefault(p, []).append(el)

    flat: List[Tuple[int, str, int]] = []
    for p in sorted(by_page):
        live = [e for e in by_page[p]
                if e.get("type") != "PageBreak" and (e.get("text") or "").strip()]
        if len(live) != 1:
            continue
        el = live[0]
        depth = (el.get("metadata") or {}).get("category_depth")
        if el.get("type") != "Title" or depth not in (None, 0):
            continue
        m = _HEADER.match(el.get("text") or "")
        if not m:
            continue
        flat.append((m.group(1).count(".") + 1, m.group(2).strip(), p))
    if not flat:
        return None
    return _assemble(flat, _last_page(elements))


# --- LLM path ------------------------------------------------------------------

def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _walk(sections: Iterable[Any], depth: int):
    """Pre-order ``(depth, title)`` of a BAML/dict section tree, depth 1 at the top."""
    for s in sections or []:
        yield depth, (_get(s, "title") or "").strip()
        yield from _walk(_get(s, "subsections") or [], depth + 1)


def outline_from_llm(elements: Optional[List[dict]], llm_outlines: List[Any]) -> List[CourseSection]:
    """Titles and nesting from the LLM; every page from the elements."""
    elements = elements or []
    title_pages: Dict[str, List[int]] = {}
    for el in elements:
        p = _page(el)
        if el.get("type") == "Title" and p is not None:
            title_pages.setdefault(norm_title(el.get("text") or ""), []).append(p)
    for pages in title_pages.values():
        pages.sort()

    cursor = 1
    kept: List[Tuple[int, str, int]] = []
    seen: set = set()
    for outline in llm_outlines or []:
        # (depth, dropped) of the open ancestors, to lift a dropped entry's children.
        chain: List[Tuple[int, bool]] = []
        for depth, title in _walk(_get(outline, "sections") or [], 1):
            while chain and chain[-1][0] >= depth:
                chain.pop()
            lifted = sum(1 for _d, dropped in chain if dropped)
            key = norm_title(title)
            page = next((p for p in title_pages.get(key, []) if p >= cursor), None)
            drop = page is None or (key, page) in seen
            chain.append((depth, drop))
            if drop:
                continue
            seen.add((key, page))
            cursor = page
            kept.append((depth - lifted, title, page))
    return _assemble(kept, _last_page(elements))


# --- entry point ----------------------------------------------------------------

#: ``extract() -> (per-chunk outlines in chunk order, failure messages)``
Extract = Callable[[], Tuple[List[Any], List[str]]]


def build_outline(elements: Optional[List[dict]], extract: Extract) -> Tuple[List[CourseSection], str]:
    """``(sections, "deck" | "llm")``. ``extract`` is called only when the deck has
    no section slides of its own. Raises OutlineBuildError if it raises or if any
    chunk failed: a partial outline must not replace a complete one."""
    deck = outline_from_deck(elements)
    if deck is not None:
        return deck, "deck"
    try:
        outlines, failures = extract()
    except OutlineBuildError:
        raise
    except Exception as e:  # noqa: BLE001
        raise OutlineBuildError(f"outline extraction failed: {type(e).__name__}: {e}") from e
    if failures:
        raise OutlineBuildError(
            f"{len(failures)} outline chunk(s) failed: " + "; ".join(failures))
    return outline_from_llm(elements, outlines), "llm"


#: The pass entry point under its registered name (``structural.outline``).
outline = build_outline
