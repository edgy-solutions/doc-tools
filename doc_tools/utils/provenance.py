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


# --------------------------------------------------------------------------- #
# 3. bbox -> page fractions (the ruled evidence geometry)
# --------------------------------------------------------------------------- #
FRACTION_DIGITS = 6


def to_page_fractions(bbox: Optional[List[float]],
                      width: Optional[float],
                      height: Optional[float]
                      ) -> tuple:
    """Any whole-page box -> page fractions, `[x0, y0, x1, y1]` each in `0..1`.

    ARCHITECT RULING 2026-10-21: *"Crop coordinates: page fractions.
    [x0, y0, x1, y1] in 0..1, origin top-left, plus page. Unit-free, so no extra
    key, and the same everywhere evidence_ref appears. Producers convert layout
    pixels and word-layer points before writing."*

    ONE implementation on purpose. The ruling says *the same everywhere*, and two
    copies of a unit conversion is how two producers end up disagreeing on a
    boundary case -- which, here, is not a cosmetic difference: cortex drops the
    WHOLE candidate list for one out-of-range box.

    Returns `(bbox, note)`. Three cases yield NO box rather than a guess:

    * **no divisor.** The numbers cannot be made unit-free, and emitting them raw
      hands a consumer pixels labelled as fractions -- confidently wrong, which is
      worse than absent.
    * **outside the page.** Clamped to the edge, which is what cutting a crop does
      anyway, and the clamp is NOTED: once the numbers are unit-free, the note is
      the only place a wrong-space box still shows.
    * **no area after clamping.** A box entirely past an edge collapses to
      `[1.0, y, 1.0, y]`. Cortex requires `x0 < x1` and `y0 < y1` strictly and
      drops the whole list for a violation; Lane 1's 204 answers it with a 422. So
      a degenerate box costs every candidate where no box costs only this one.
    """
    if not bbox or len(bbox) != 4:
        return None, None
    if not width or not height:
        return None, ("no page dimensions: the geometry could not be made "
                      "unit-free, so no box is claimed")
    raw = [bbox[0] / width, bbox[1] / height, bbox[2] / width, bbox[3] / height]
    out = [round(min(1.0, max(0.0, v)), FRACTION_DIGITS) for v in raw]
    if out[2] <= out[0] or out[3] <= out[1]:
        return None, ("bbox lies outside the page, or has no area, so there is no "
                      "box to draw")
    clamped = any(v < 0.0 or v > 1.0 for v in raw)
    return out, ("bbox extended past the page edge and was clamped" if clamped
                 else None)
