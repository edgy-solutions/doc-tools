"""Provenance + image resolution for sustainment extraction (reusable).

Pure-Python and LLM-free. Locations come ONLY from unstructured's positioned
elements (persisted per-element in text.json); an LLM is never asked for a
bounding box (text models can't produce them and vision models hallucinate
them). Verbatim extraction is what makes a value locatable.

Two jobs:
  1. element -> cropped-image S3 URL  (used by the vision parts pass AND review)
  2. value  -> location (page + bbox) (used by the review payload)
"""
import os
import re
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# 1. element -> cropped image
# --------------------------------------------------------------------------- #
def image_basename(image_path: Optional[str]) -> Optional[str]:
    if not image_path:
        return None
    return os.path.basename(str(image_path).replace("\\", "/"))


def resolve_element_image(element: Any, embedded_images: Any) -> Optional[str]:
    """S3 URL of the crop unstructured made for this element, or None.

    unstructured writes each Image/Table crop to disk and records its path in
    ``metadata.image_path``; document_parser uploads every crop keyed by BARE
    FILENAME into ``manifest['embedded_images']``. So ``basename(image_path)``
    is the join key between an element and its uploaded crop.
    """
    if not isinstance(element, dict) or not isinstance(embedded_images, dict):
        return None
    meta = element.get("metadata") or {}
    base = image_basename(meta.get("image_path"))
    if not base:
        return None
    return embedded_images.get(base)


def table_elements(elements: Optional[List[dict]]) -> List[dict]:
    """The Table elements (what the router keys on and the vision pass crops)."""
    return [e for e in (elements or []) if isinstance(e, dict) and e.get("type") == "Table"]


# --------------------------------------------------------------------------- #
# 2. positioned index + value -> location
# --------------------------------------------------------------------------- #
def _points_bbox(points: Any) -> Optional[List[float]]:
    """[x0, y0, x1, y1] from unstructured coordinate 'points' (list of [x, y])."""
    try:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return [min(xs), min(ys), max(xs), max(ys)]
    except Exception:  # noqa: BLE001
        return None


def build_positioned_index(elements: Optional[List[dict]]) -> List[dict]:
    """One record per element carrying its text + page + bbox + page dims.

    page_width/height (unstructured's layout dims, what the bbox is relative
    to) are stored WITH the bbox so a viewer can scale correctly — storing a
    box without the page dims it's relative to is the classic overlay-drift bug.
    """
    idx: List[dict] = []
    for i, e in enumerate(elements or []):
        if not isinstance(e, dict):
            continue
        meta = e.get("metadata") or {}
        coords = meta.get("coordinates") if isinstance(meta.get("coordinates"), dict) else {}
        bbox = _points_bbox(coords.get("points")) if coords else None
        idx.append({
            "element_id": e.get("element_id") or f"el_{i}",
            "type": e.get("type", "Text"),
            "region": "table" if e.get("type") == "Table" else "narrative",
            "page_number": meta.get("page_number"),
            "bbox": bbox,
            "page_width": coords.get("layout_width") if coords else None,
            "page_height": coords.get("layout_height") if coords else None,
            "text": e.get("text", "") or "",
            "text_as_html": meta.get("text_as_html", "") or "",
        })
    return idx


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def resolve_value(source_snippet: Optional[str], index: List[dict],
                  prefer_region: Optional[str] = None) -> dict:
    """Locate a verbatim snippet in the positioned index. Never raises.

    match_method: 'unique' | 'region_preferred' | 'ambiguous' | 'not_found'.
    A 'not_found' is a real hallucination signal — a value the model produced
    that is not present in the document text.
    """
    rec = {
        "source_snippet": source_snippet, "found": False, "page_number": None,
        "bboxes": [], "page_dims": None, "match_method": "not_found",
        "match_confidence": 0.0, "candidate_count": 0,
    }
    snip = _norm(source_snippet)
    if not snip:
        return rec
    cands = []
    for el in index:
        hay = _norm(el["text"]) + " " + _norm(el["text_as_html"])
        if snip in hay:
            cands.append(el)
    rec["candidate_count"] = len(cands)
    if not cands:
        return rec
    chosen = cands
    if len(cands) == 1:
        rec["match_method"], rec["match_confidence"] = "unique", 1.0
    else:
        pref = [c for c in cands if prefer_region and c["region"] == prefer_region]
        if pref:
            chosen, rec["match_method"], rec["match_confidence"] = pref, "region_preferred", 0.7
        else:
            rec["match_method"], rec["match_confidence"] = "ambiguous", 0.4
    first = chosen[0]
    rec["found"] = True
    rec["page_number"] = first["page_number"]
    rec["page_dims"] = ({"width": first["page_width"], "height": first["page_height"]}
                        if first["page_width"] else None)
    rec["bboxes"] = [c["bbox"] for c in chosen
                     if c["bbox"] and c["page_number"] == first["page_number"]]
    return rec
