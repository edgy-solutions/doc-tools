"""Pure merge / reconcile / validation / review-payload helpers for the
sustainment two-pass extractor.

Deliberately imports ONLY the light modules (provenance, sustainment_normalize)
so the whole merge+review pipeline is unit-testable without importing the heavy
Dagster/BAML stack. The plugin (doc_tools/plugins/sustainment.py) wires these
together with the two BAML calls.
"""
from typing import Any, List, Optional, Tuple

from doc_tools.utils import provenance
from doc_tools.utils import sustainment_normalize as norm


def _g(obj: Any, name: str):
    return getattr(obj, name, None)


def header_to_dict(h: Any) -> dict:
    """BAML NoticeHeader (or None / any duck-typed object) -> plain dict, with
    doc_type normalized to 'PCN'/'PDN'."""
    cats = [getattr(c, "value", c) for c in (_g(h, "categories") or [])]
    return {
        "doc_id": _g(h, "doc_id"),
        "doc_type": norm.normalize_doc_type(_g(h, "doc_type")),
        "revision": _g(h, "revision"),
        "pub_date": _g(h, "pub_date"),
        "pub_date_source": _g(h, "pub_date_source"),
        "mfr": _g(h, "mfr"),
        "mfr_source": _g(h, "mfr_source"),
        "categories": cats,
        "summary": _g(h, "summary"),
        "doc_level_ltb_date": _g(h, "doc_level_ltb_date"),
        "doc_level_ltb_date_source": _g(h, "doc_level_ltb_date_source"),
    }


def part_to_dict(p: Any) -> dict:
    return {
        "affected_mpn": _g(p, "affected_mpn"),
        "affected_mpn_source": _g(p, "affected_mpn_source"),
        "replacement_mpn": _g(p, "replacement_mpn"),
        "replacement_mpn_source": _g(p, "replacement_mpn_source"),
        "ltb_date": _g(p, "ltb_date"),
        "ltb_date_source": _g(p, "ltb_date_source"),
    }


def empty_header(doc_id: str) -> dict:
    return {"doc_id": doc_id, "doc_type": "PCN", "revision": None, "pub_date": "",
            "pub_date_source": None, "mfr": "", "mfr_source": None, "categories": [],
            "summary": "", "doc_level_ltb_date": None, "doc_level_ltb_date_source": None}


def dedup_parts(parts: List[dict]) -> List[dict]:
    """Dedup by affected_mpn across crops (first occurrence wins). Drops rows
    with no affected_mpn. This is the multi-crop reconciliation: a page-spanning
    table extracted per-crop re-emits repeated headers / continued rows."""
    seen, out = set(), []
    for p in parts:
        k = (p.get("affected_mpn") or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def reconcile_ltb(parts: List[dict], doc_level_ltb: Optional[str]) -> List[dict]:
    """Per-part LTB: prefer per-row, fall back to the doc-level date (in place)."""
    for p in parts:
        p["ltb_date"] = norm.effective_ltb(p.get("ltb_date"), doc_level_ltb)
    return parts


def clean_replacements(parts: List[dict]) -> List[dict]:
    """Null out replacement_mpn values that are comma-separated lists (a vision
    model copying a Qualification Vehicle column into replacement on a PCN with
    no replacements). Keeps a genuine single replacement. In place."""
    for p in parts:
        cleaned = norm.clean_replacement(p.get("replacement_mpn"))
        if cleaned is None and p.get("replacement_mpn"):
            p["replacement_mpn_source"] = None
        p["replacement_mpn"] = cleaned
    return parts


def _review_item(field_path, value, source, region, prov=None, needs_review=False, reason=None):
    prov = prov or {}
    return {
        "field_path": field_path, "value": value, "source_snippet": source,
        "region": region, "page_number": prov.get("page_number"),
        "bboxes": prov.get("bboxes", []), "page_dims": prov.get("page_dims"),
        "match_method": prov.get("match_method", "derived" if region == "derived" else "not_found"),
        "match_confidence": prov.get("match_confidence", 0.0),
        "needs_review": needs_review, "review_reason": reason,
        "approval_state": "pending",
    }


def build_review_items(header: dict, parts: List[dict], index: List[dict],
                       ocr_text_norm: str) -> Tuple[List[dict], List[str]]:
    """One review item per approvable value, each with provenance + needs_review.
    Returns (items, doc-level reasons)."""
    items: List[dict] = []
    reasons: List[str] = []

    for fp, val, src in (
        ("header.pub_date", header.get("pub_date"), header.get("pub_date_source")),
        ("header.mfr", header.get("mfr"), header.get("mfr_source")),
        ("header.doc_level_ltb_date", header.get("doc_level_ltb_date"),
         header.get("doc_level_ltb_date_source")),
    ):
        if not val:
            continue
        prov = provenance.resolve_value(src or val, index, prefer_region="narrative")
        nr = not prov["found"]
        reason = "source not located in document" if nr else None
        if nr:
            reasons.append(f"{fp}: source not located")
        items.append(_review_item(fp, val, src or val, "header", prov, nr, reason))

    if header.get("summary"):
        items.append(_review_item("header.summary", header.get("summary"), None, "derived"))
    if header.get("categories"):
        items.append(_review_item("header.categories", header.get("categories"), None, "derived"))

    for i, p in enumerate(parts):
        amp = p.get("affected_mpn")
        amp_src = p.get("affected_mpn_source") or amp
        # TEXT-LAYER parts carry AUTHORITATIVE provenance: the exact bbox of the CELL the
        # value was read out of. Prefer it over resolve_value's string-match, which is a
        # best-effort search of a positioned OCR index — it resolves to the enclosing
        # TABLE region (every part on a page sharing one huge box) and can miss entirely
        # ("source not located"). Overwriting a known cell with a guessed table was
        # discarding the whole point of reading the text layer.
        tl_bbox = p.get("text_layer_bbox")
        if tl_bbox:
            prov = {
                "found": True,
                "page_number": p.get("text_layer_page"),
                "bboxes": [tl_bbox],
                "page_dims": p.get("text_layer_page_dims"),
                "match_method": "text_layer_cell",
                "match_confidence": 1.0,
            }
        else:
            prov = provenance.resolve_value(amp_src, index, prefer_region="table")
        # A text-layer value came OUT of the document, so it cannot be a hallucination —
        # the OCR-verbatim check exists to catch vision transcription/invention and does
        # not apply. (It would also false-positive: the OCR text stream and the table cell
        # can tokenize differently.)
        in_ocr = True if tl_bbox else ((provenance._norm(amp) in ocr_text_norm) if amp else False)
        reason = None
        if not in_ocr:
            reason = "affected_mpn not found verbatim in OCR text (possible hallucination)"
        elif not prov["found"]:
            reason = "source not located"
        nr = reason is not None
        if nr:
            reasons.append(f"parts[{i}].affected_mpn: {reason}")
        items.append(_review_item(f"parts[{i}].affected_mpn", amp, amp_src, "table", prov, nr, reason))

        if p.get("replacement_mpn"):
            # Same authority rule as the affected MPN. The replacement sits in the paired
            # cell on the same row; the row's bbox locates it far better than a string
            # search that would land on the enclosing table (or nothing).
            rep_bbox = p.get("text_layer_replacement_bbox")
            if rep_bbox:
                rprov = {"found": True, "page_number": p.get("text_layer_page"),
                         "bboxes": [rep_bbox], "page_dims": p.get("text_layer_page_dims"),
                         "match_method": "text_layer_cell", "match_confidence": 1.0}
            else:
                rprov = provenance.resolve_value(
                    p.get("replacement_mpn_source") or p["replacement_mpn"], index, prefer_region="table")
            rnr = not rprov["found"]
            items.append(_review_item(f"parts[{i}].replacement_mpn", p["replacement_mpn"],
                                      p.get("replacement_mpn_source"), "table", rprov, rnr,
                                      "source not located" if rnr else None))
        if p.get("ltb_date"):
            lprov = provenance.resolve_value(
                p.get("ltb_date_source") or p["ltb_date"], index, prefer_region="table")
            items.append(_review_item(f"parts[{i}].ltb_date", p["ltb_date"],
                                      p.get("ltb_date_source"), "table", lprov, False, None))
    return items, reasons


def validate_count(header: dict, n_parts: int) -> Optional[str]:
    """Cross-pass sanity check: summary-implied count vs extracted count."""
    stated = norm.summary_stated_count(header.get("summary"))
    if stated is not None and stated != n_parts:
        return f"cross-check: summary implies ~{stated} parts but {n_parts} were extracted"
    return None
