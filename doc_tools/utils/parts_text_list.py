"""Deterministic salvage of a plain-text `Family / Model` parts list.

The defect this exists for: ADI_PCN_24_0003 lists ~1,577 affected parts as plain
`Family / Model` text on pages 2-7, and its only `Table` element is the page-1 contact
block. The router takes the table branch, vision correctly finds no parts column and
returns 0 rows, and nothing flags the empty result. The text-only route could never fire
either, because ADI writes "Affected ADI Models" and the old label tuple missed it.

This module is DETERMINISTIC and pure: no I/O, no BAML, no S3, no vision. A full-text
vision call over ~1,577 rows would hit VISION_MAX_TOKENS and be marked a failed crop, so
vision is the wrong tool for this shape.

The affected-section vocabulary widened here is consumed only by plugins/sustainment.py.
It deliberately does NOT live in table_text_layer, whose column/caption vocabulary is
tier 1's and must not move.
"""
import re
from typing import List, Optional, Sequence, Tuple

from doc_tools.utils import table_text_layer as text_layer

# forward: affected [one word] models|parts|part numbers|devices
# reverse: models|parts|devices affected
AFFECTED_HEADING_RE = re.compile(
    r"\baffected\s+(?:[A-Za-z][A-Za-z0-9&/-]{0,14}\s+)?"
    r"(?:models?|parts?(?:\s+numbers?)?|devices?)\b"
    r"|\b(?:models?|parts?|devices?)\s+affected\b",
    re.IGNORECASE,
)

_CAPTION_COUNT_RE = re.compile(r"\((\d{1,3}(?:,\d{3})*|\d{2,})\)\s*$")
_PARTS_CUES = ("part", "model number", "device")

PAIR_RE = re.compile(
    r"(?<![\w/#.-])([A-Za-z0-9][\w.+#-]{1,30})\s*/\s*([A-Za-z0-9][\w.+#-]{1,40})(?![\w/-])"
)

# A shortfall is only declared below this fraction of the caption count: the parse and the
# caption legitimately disagree by a few (1,578 pairs / 1,575 distinct vs a caption of 1,577).
SHORTFALL_TOLERANCE = 0.9


def names_affected_section(text: str) -> bool:
    """True when text names an affected-parts section (a widening of the old label tuple)."""
    return bool(AFFECTED_HEADING_RE.search(text or ""))


def caption_part_count(text: str) -> Optional[int]:
    """The document's own advertised parts count, e.g.
    "Added Parts On This Revision - Product Family / Model Number (1,577)". Largest wins."""
    best: Optional[int] = None
    for line in (text or "").split("\n"):
        low = line.lower()
        if not any(cue in low for cue in _PARTS_CUES):
            continue
        m = _CAPTION_COUNT_RE.search(line)
        if not m:
            continue
        n = int(m.group(1).replace(",", ""))
        if n < 2:  # (1) is a footnote marker far more often than a parts count
            continue
        if best is None or n > best:
            best = n
    return best


def parse_family_model(text: str, page_number: Optional[int] = None) -> List[dict]:
    """Parse `FAMILY / MODEL` pairs out of flattened text into tier-1-shaped rows."""
    rows: List[dict] = []
    for m in PAIR_RE.finditer(text or ""):
        family, model = m.group(1), m.group(2)
        if not (len(model) >= 4 and text_layer.looks_like_mpn(model)
                and any(ch.isalpha() for ch in model)):
            continue
        if not any(ch.isalpha() for ch in family):
            continue
        # The family is dropped deliberately: no downstream consumer reads it, and
        # affected_mpn_source must stay verbatim-equal to the value it supports (tier 1's
        # rule: the cell IS the source). So no eleventh key.
        rows.append({
            "affected_mpn": model,
            "affected_mpn_source": model,
            "replacement_mpn": None,
            "replacement_mpn_source": None,
            "ltb_date": None,
            "ltb_date_source": None,
            "text_layer_bbox": None,
            "text_layer_replacement_bbox": None,
            "text_layer_page": page_number,
            "text_layer_page_dims": None,
        })
    return rows


def salvage(pages: Sequence[Tuple[Optional[int], str]], min_rows: int = 2) -> Tuple[List[dict], dict]:
    """Salvage Family/Model rows from per-page text. Returns (rows, stats)."""
    pages = list(pages)
    joined = "\n".join(t or "" for _, t in pages)
    caption = caption_part_count(joined)
    doc_names = names_affected_section(joined)
    stats = {
        "text_list_parts": 0,
        "text_list_caption_count": caption,
        "text_list_pages": 0,
        "text_list_shortfall": False,
        "text_list_shortfall_detail": None,
    }
    rows: List[dict] = []
    contributing = 0
    for pno, ptext in pages:
        ptext = ptext or ""
        if not (names_affected_section(ptext) or caption_part_count(ptext) is not None
                or doc_names):
            continue
        got = parse_family_model(ptext, pno)
        if got:
            contributing += 1
            rows.extend(got)
    if len(rows) < min_rows:
        return [], stats
    stats["text_list_parts"] = len(rows)
    stats["text_list_pages"] = contributing
    if caption is not None and len(rows) < caption * SHORTFALL_TOLERANCE:
        stats["text_list_shortfall"] = True
        stats["text_list_shortfall_detail"] = (
            f"parsed {len(rows)} Family/Model pairs against a caption of {caption}")
    return rows, stats
