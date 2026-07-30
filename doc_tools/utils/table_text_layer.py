"""Deterministic parts extraction from a PDF's TEXT LAYER — tier 1 of the extraction ladder.

WHY THIS EXISTS. The vision pass reads parts tables from rendered crops. On dense tables
that does not converge: measured 2026-07-29/30 on a real notice (Diodes PCN 2683), a
37-row table generated 16,000+ tokens at work and was still going — the client was cut
off at 60s, and vLLM kept burning GPU for minutes afterwards on output nobody received.
Meanwhile the SAME tables read perfectly from the PDF's own text layer in under a second.

These notices are BORN-DIGITAL. Their tables are not pictures of tables; they are tables.
Asking a 31B vision model to transcribe text that is already machine-readable is the
expensive, unreliable path to a worse answer. So:

    tier 1  TEXT LAYER   (here)  — born-digital: deterministic, sub-second, exact MPNs,
                                   and per-cell bboxes for provenance.
    tier 2  BANDED VISION        — scans with dense tables: N bounded requests, each
                                   inside the infra timeout, partial success honest.
    tier 3  WHOLE-CROP VISION    — scans with small tables: one request fits trivially.

Tier applicability is DETECTABLE, not guessed: `page_has_text_layer` reports whether the
text is really there, and the row count comes from the parsed structure.

PROVENANCE BONUS. pdfplumber yields a bbox PER CELL, so every MPN carries exact
coordinates. That is strictly better than matching an MPN string against a positioned
OCR index (which can, and does, fail with "source not located") and it is far tighter
than a whole-table crop region — the evidence card can highlight the cell, not the table.
Coordinates are emitted in PDF POINTS together with the page's point dimensions, so the
sealed bbox-scale rule (fraction = bbox / page_dims) is unit-agnostic and unchanged.

Pure functions here take plain data (a grid of strings, a header row) so the column logic
is unit-testable without pdfplumber or a PDF.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Column-header VOCABULARY — data, not code, so a new vendor's wording is a list entry
# rather than a branch. Matched case-insensitively against the normalized header cell.
AFFECTED_HEADERS: Tuple[str, ...] = (
    "eol device", "affected part", "affected mpn", "affected device", "discontinued",
    "part number", "part no", "orderable part", "opn", "device", "affected",
)
REPLACEMENT_HEADERS: Tuple[str, ...] = (
    "replacement", "replaces", "substitute", "recommended replacement",
    "suggested replacement", "alternate", "alternative", "successor",
)

_WS = re.compile(r"\s+")


def _norm_header(cell: Optional[str]) -> str:
    return _WS.sub(" ", (cell or "").strip().lower())


def _is_affected(cell: Optional[str]) -> bool:
    h = _norm_header(cell)
    return bool(h) and any(k in h for k in AFFECTED_HEADERS)


def _is_replacement(cell: Optional[str]) -> bool:
    h = _norm_header(cell)
    return bool(h) and any(k in h for k in REPLACEMENT_HEADERS)


# An MPN is a short token carrying digits. find_tables() also returns prose blocks that
# merely look tabular (a 130-char "Unless a Sales representative is contacted..." paragraph
# was emitted as a part before this guard), so a plausibility floor is required. Real MPNs
# here run to ~18 chars ('WL2511F0048.000000'); the ceiling is deliberately loose because
# vendors use non-standard schemes, and the space allowance keeps ids like 'S1613E-20.0000 (T)'.
_MAX_MPN_LEN = 48
_MAX_MPN_SPACES = 2


def looks_like_mpn(value: Optional[str]) -> bool:
    v = (value or "").strip()
    if not v or len(v) > _MAX_MPN_LEN or v.count(" ") > _MAX_MPN_SPACES:
        return False
    return any(ch.isdigit() for ch in v)


def _nonempty(row: Sequence[Optional[str]]) -> int:
    return sum(1 for c in row if (c or "").strip())


def find_header_row(grid: Sequence[Sequence[Optional[str]]], search_depth: int = 6) -> Optional[int]:
    """Index of the row that DECLARES the columns, or None.

    BEST-SCORING row, not the first match. Notices put a TITLE above the header — "Table 1
    - EOL Devices with Life-time Buy Opportunity and Replacement Parts" — and that title
    contains the words the vocabulary looks for. Taking the first match picked the title
    (one labelled cell in an otherwise-empty row), which collapsed a three-pair table into
    a single unpaired column and silently lost two thirds of a 111-part page. So: score
    each candidate by how many columns it labels, and require MORE THAN ONE non-empty cell
    — a lone labelled cell in an empty row is a caption, not a header.
    """
    best, best_score = None, 0
    for i, row in enumerate(grid[:search_depth]):
        if _nonempty(row) < 2:
            continue
        score = sum(1 for c in row if _is_affected(c) or _is_replacement(c))
        if score > best_score:
            best, best_score = i, score
    return best


def find_title_row(grid: Sequence[Sequence[Optional[str]]], search_depth: int = 2) -> Optional[int]:
    """Index of a CAPTION row that names the table's contents, or None.

    Some tables carry no column header at all — Diodes PCN 2683 page 5 is the caption
    "Table 3 - EOL Devices" followed by six columns of part numbers and NO replacements
    column. The caption is then the only statement of what the cells are, and reading it
    is the difference between extracting the page and skipping it.
    """
    for i, row in enumerate(grid[:search_depth]):
        if _nonempty(row) == 1 and any(_is_affected(c) for c in row):
            return i
    return None


def pair_columns(header: Sequence[Optional[str]]) -> List[Tuple[int, Optional[int]]]:
    """[(affected_col, replacement_col|None), ...] from a header row.

    Real notices repeat the pair ACROSS the page to save paper — Diodes PCN 2683 page 3 is
    `EOL Devices | Replacements | EOL Devices | Replacements | EOL Devices | Replacements`,
    i.e. THREE pairs per row, so 37 printed rows carry 111 parts. Reading such a table as
    one part per row loses two thirds of it, so the pairing is derived from the header
    rather than assumed.

    Each affected column takes the nearest replacement column to its right that no earlier
    affected column has claimed; an affected column with no replacement to its right
    (before the next affected column) is unpaired, which is normal for process-change
    notices that list no replacements at all.
    """
    affected = [i for i, c in enumerate(header) if _is_affected(c)]
    replacement = [i for i, c in enumerate(header) if _is_replacement(c)]
    pairs: List[Tuple[int, Optional[int]]] = []
    used: set = set()
    for idx, a in enumerate(affected):
        stop = affected[idx + 1] if idx + 1 < len(affected) else len(header)
        mate = next((r for r in replacement if a < r < stop and r not in used), None)
        if mate is not None:
            used.add(mate)
        pairs.append((a, mate))
    return pairs


def parts_from_grid(
    grid: Sequence[Sequence[Optional[str]]],
    *,
    header_row: Optional[int] = None,
) -> List[Dict[str, Optional[str]]]:
    """[{affected_mpn, replacement_mpn, row, col}] from a grid of cell strings (PURE).

    Values are returned VERBATIM — no normalization, hyphenation or "correction". Part
    numbers legitimately carry slashes, '#' reel codes and module dashes, and the
    downstream contract is that an MPN matches the document exactly.
    """
    if not grid:
        return []
    hi = header_row if header_row is not None else find_header_row(grid)
    if hi is not None:
        pairs = pair_columns(grid[hi])
        start = hi + 1
    else:
        # No column header. If a CAPTION names the contents ("Table 3 - EOL Devices"),
        # every column is an affected part and there are no replacements — the shape of a
        # bare discontinuance list. Without a caption we decline: an unlabelled grid of
        # unknown columns must not be guessed into parts.
        ti = find_title_row(grid)
        if ti is None:
            return []
        width = max((len(r) for r in grid[ti + 1:]), default=0)
        pairs = [(c, None) for c in range(width)]
        start = ti + 1
    if not pairs:
        return []
    out: List[Dict[str, Optional[str]]] = []
    for r in range(start, len(grid)):
        row = grid[r]
        for a_col, r_col in pairs:
            if a_col >= len(row):
                continue
            affected = (row[a_col] or "").strip()
            if not affected:
                continue
            # A repeated header (tables continued across pages) is not a part.
            if _is_affected(affected) or _is_replacement(affected):
                continue
            # find_tables() also returns prose blocks that merely look tabular; a sentence
            # is not a part number.
            if not looks_like_mpn(affected):
                continue
            rep = ""
            if r_col is not None and r_col < len(row):
                rep = (row[r_col] or "").strip()
            keep_rep = bool(rep and looks_like_mpn(rep))
            out.append({
                "affected_mpn": affected,
                "replacement_mpn": rep if keep_rep else None,
                "row": r,
                "col": a_col,
                # the replacement lives in its OWN cell — carried so provenance can
                # highlight THAT cell rather than reusing the affected one.
                "rep_col": r_col if keep_rep else None,
            })
    return out


def page_has_text_layer(page, min_chars: int = 200) -> bool:
    """Is this page born-digital (real text) rather than a scan?

    The tier-1/tier-2 router. A scanned page yields little or no extractable text, so it
    must go to vision; a born-digital page should never be handed to a vision model to
    re-read text it already carries.
    """
    try:
        return len((page.extract_text() or "").strip()) >= min_chars
    except Exception:  # noqa: BLE001 — an unreadable page is simply not tier 1
        return False


def parts_from_page(page, page_number: int) -> List[Dict[str, Any]]:
    """Parts + PER-CELL provenance from one born-digital page (needs pdfplumber).

    Each part carries the exact bbox of the cell its MPN came from, in PDF POINTS, with
    the page's point dimensions alongside — so the sealed `fraction = bbox / page_dims`
    scale rule holds without unit conversion, and the evidence card can highlight the CELL
    instead of the whole table.
    """
    results: List[Dict[str, Any]] = []
    dims = {"width": float(page.width), "height": float(page.height)}
    for table in page.find_tables():
        grid = table.extract()
        rows = table.rows
        # parts_from_grid decides header-vs-caption itself; short-circuiting on a missing
        # HEADER here would skip the caption-only tables entirely (a whole 43-row page).
        def _cell_bbox(r: int, c: Optional[int]):
            """(x0, top, x1, bottom) of one grid cell, or None. A missing cell bbox is an
            honest absence — never fatal, and never a fabricated coordinate."""
            if c is None:
                return None
            try:
                cell = rows[r].cells[c]
                return [float(v) for v in cell] if cell else None
            except Exception:  # noqa: BLE001
                return None

        for p in parts_from_grid(grid):
            results.append({
                "affected_mpn": p["affected_mpn"],
                "replacement_mpn": p["replacement_mpn"],
                "page_number": page_number,
                "bbox": _cell_bbox(p["row"], p["col"]),
                "replacement_bbox": _cell_bbox(p["row"], p.get("rep_col")),
                "page_dims": dims,
                "source": "text_layer",
            })
    return results
