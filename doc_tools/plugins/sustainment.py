"""Sustainment (PCN/PDN) extraction — two-pass, provenance-aware.

Pass 1  ExtractHeader (gpt-oss, text-only)  -> header fields
Pass 2  ExtractParts  (Gemma, multimodal)   -> affected-parts table rows
The final SustainmentNotice is assembled + reconciled HERE in Python.

Design notes:
  * Router: run the vision parts pass only when unstructured detected >=1 Table
    element AND a vision endpoint is configured. No table -> header-only.
  * Per-crop parts calls + dedup: a page-spanning table becomes multiple crops;
    each crop is extracted independently and parts are de-duplicated across
    crops (repeated headers / continued rows). Per-crop also keeps each call's
    OCR+image well inside the vision model's context (e.g. gemma 32k).
  * Models are fully config-driven (BAML clients read LLM_* / VISION_LLM_* env);
    images go as base64 so any OpenAI-compatible backend works — Ollama,
    LiteLLM, vLLM, OpenAI. Nothing is hardcoded.
  * ltb_date ownership (empirical, MinIO corpus scan): per-row primary,
    doc-level fallback (sustainment_merge.reconcile_ltb).
  * Validation -> review lane, never a silent mock. On any failure the node is
    flagged needs_review with reasons; the old MOCK-PDN-123 fabrication is gone.
  * Provenance: every located value carries a verbatim *_source snippet resolved
    to a page + bbox by doc_tools.utils.provenance (Phase 5 review.json).
"""
import os
from typing import List, Optional, Tuple, Any, Dict

from pydantic import BaseModel, Field

from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode
from doc_tools.utils.jena_client import escape_sparql_string
from doc_tools.utils import provenance
from doc_tools.utils import sustainment_normalize as norm
from doc_tools.utils.sustainment_merge import (
    header_to_dict, part_to_dict, dedup_parts, reconcile_ltb,
    build_review_items, validate_count, empty_header,
)


# --------------------------------------------------------------------------- #
# Mirror models (carry _source, revision, doc_level_ltb_date + the review lane)
# --------------------------------------------------------------------------- #
class PartImpact(BaseModel):
    affected_mpn: str
    affected_mpn_source: Optional[str] = None
    replacement_mpn: Optional[str] = None
    replacement_mpn_source: Optional[str] = None
    ltb_date: Optional[str] = None
    ltb_date_source: Optional[str] = None


class SustainmentNotice(BaseModel):
    doc_id: str
    doc_type: str
    revision: Optional[str] = None
    pub_date: str
    mfr: str
    categories: List[str]
    summary: str
    doc_level_ltb_date: Optional[str] = None
    impacted_parts: List[PartImpact]


class SustainmentAugmentation(BaseModel):
    notice: SustainmentNotice
    review: dict = Field(default_factory=dict)          # review.json payload
    needs_review: bool = False
    review_reasons: List[str] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)           # router / coverage instrumentation


def _fetch_image_b64(s3_client, s3_url: str):
    """('image/png'|'image/jpeg', base64str) for an s3://bucket/key crop, or (None, None).

    base64 (not a URL) so the image is portable across Ollama / LiteLLM / vLLM /
    OpenAI — the backend never has to fetch it.
    """
    if not s3_url or not str(s3_url).startswith("s3://"):
        return None, None
    _, _, rest = str(s3_url).partition("s3://")
    bkt, _, key = rest.partition("/")
    try:
        data = s3_client.get_object(Bucket=bkt, Key=key)["Body"].read()
    except Exception as e:  # noqa: BLE001
        print(f"[SustainmentPlugin] failed to fetch crop {s3_url}: {e}")
        return None, None
    import base64
    ext = os.path.splitext(key)[1].lower()
    media = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return media, base64.b64encode(data).decode("ascii")


def _baml_call_opts() -> dict:
    """Fresh BAML call options with a generous request timeout.

    Dense-table vision extraction on a 31B model is slow and was 408-timing-out
    on multi-row crops under the default request ceiling. AbortController is
    single-use ('once aborted, forever aborted'), so build a fresh one per call.
    Tunable via LLM_REQUEST_TIMEOUT_MS (default 600000 = 10 min).
    """
    from baml_py import AbortController
    ms = int(os.getenv("LLM_REQUEST_TIMEOUT_MS", "600000"))
    return {"abort_controller": AbortController(timeout_ms=ms)}


# --------------------------------------------------------------------------- #
# Plugin
# --------------------------------------------------------------------------- #
class SustainmentPlugin(AugmentationPlugin):
    """PCN/PDN two-pass extraction with a router, merge, validation + review lane."""

    def _extract_header(self, full_text: str):
        from doc_tools.baml_client.sync_client import b
        prompt = self._get_dynamic_prompt(
            prompt_name="sustainment_header_instructions",
            fallback_file="prompts/sustainment_header_instructions.md",
        )
        return b.ExtractHeader(doc=full_text, system_instructions=prompt,
                               baml_options=_baml_call_opts())

    def _extract_parts(self, tables: List[dict], manifest: Optional[dict],
                       s3_client, full_text: str) -> Tuple[List[dict], dict]:
        from doc_tools.baml_client.sync_client import b
        from baml_py import Image
        prompt = self._get_dynamic_prompt(
            prompt_name="sustainment_parts_instructions",
            fallback_file="prompts/sustainment_parts_instructions.md",
        )
        embedded = (manifest or {}).get("embedded_images", {}) or {}
        all_parts: List[dict] = []
        n_crops, missing, failed = 0, 0, 0
        for el in tables:
            meta = el.get("metadata") or {}
            html = meta.get("text_as_html", "") or ""
            ocr = el.get("text", "") or full_text
            images = []
            url = provenance.resolve_element_image(el, embedded)
            if url:
                media, b64 = _fetch_image_b64(s3_client, url)
                if b64:
                    images.append(Image.from_base64(media, b64))
                    n_crops += 1
                else:
                    missing += 1
            else:
                missing += 1  # borderless / undetected-crop table -> OCR+HTML only
            try:
                res = b.ExtractParts(ocr_text=ocr, html_table=html,
                                     table_images=images, system_instructions=prompt,
                                     baml_options=_baml_call_opts())
                for p in (res or []):
                    all_parts.append(part_to_dict(p))
            except Exception as e:  # noqa: BLE001
                # A per-crop failure (commonly a vision timeout on a dense table)
                # loses that crop's rows. Count it so process_fulltext can flag
                # the doc needs_review — a silent partial must never look clean.
                failed += 1
                print(f"[SustainmentPlugin] ExtractParts failed on a table crop: {e}")
        return all_parts, {"n_crops_used": n_crops, "crops_missing": missing, "crops_failed": failed}

    def process_fulltext(self, full_text: str, doc_id: str, metadata: Dict[str, Any] = None,
                         elements: List[Dict[str, Any]] = None, manifest: Dict[str, Any] = None,
                         s3_client: Any = None, bucket: str = None) -> List[DocumentNode]:
        index = provenance.build_positioned_index(elements)
        ocr_norm = provenance._norm(full_text)
        stats = {"n_tables": 0, "n_crops_used": 0, "crops_missing": 0, "crops_failed": 0, "vision_used": False}
        reasons: List[str] = []
        needs_review = False

        # ---- Pass 1: header (text-only, gpt-oss) ----
        header = None
        try:
            header = self._extract_header(full_text)
        except Exception as e:  # noqa: BLE001
            reasons.append(f"header pass failed: {e}")
            needs_review = True
        header_d = header_to_dict(header) if header is not None else empty_header(doc_id)
        if not header_d.get("doc_id"):
            header_d["doc_id"] = doc_id
        if header is not None and not norm.is_known_doc_type(getattr(header, "doc_type", None)):
            reasons.append("doc_type unclassifiable — defaulted to PCN")
            needs_review = True

        # ---- Router + Pass 2: parts (multimodal, Gemma) ----
        tables = provenance.table_elements(elements)
        stats["n_tables"] = len(tables)
        parts_d: List[dict] = []
        vision_ok = bool(os.getenv("VISION_LLM_BASE_URL"))
        if tables and vision_ok and s3_client is not None:
            try:
                parts_d, ps = self._extract_parts(tables, manifest, s3_client, full_text)
                stats.update(ps)
                stats["vision_used"] = True
                if ps.get("crops_failed"):
                    reasons.append(
                        f"{ps['crops_failed']}/{len(tables)} table crops failed "
                        f"(e.g. vision timeout) — extracted parts are likely INCOMPLETE")
                    needs_review = True
            except Exception as e:  # noqa: BLE001
                reasons.append(f"parts pass failed: {e}")
                needs_review = True
        elif tables and not vision_ok:
            reasons.append("tables present but VISION_LLM_BASE_URL unset — parts NOT extracted")
            needs_review = True
        elif not tables:
            # No table detected -> header-only. Instrumented so the borderless
            # miss-rate is visible (Phase 0 decision #3: build the coordinate
            # page-crop fallback only if this fires on parts-bearing docs).
            reasons.append("no Table element detected — parts pass skipped (header-only)")

        # dedup across crops, then reconcile per-part LTB (per-row primary,
        # doc-level fallback)
        parts_d = reconcile_ltb(dedup_parts(parts_d), header_d.get("doc_level_ltb_date"))

        # ---- Validation + review payload ----
        items, item_reasons = build_review_items(header_d, parts_d, index, ocr_norm)
        reasons += item_reasons
        cnt = validate_count(header_d, len(parts_d))
        if cnt:
            reasons.append(cnt)
        if any(it["needs_review"] for it in items) or reasons:
            needs_review = True

        review = {"doc_id": header_d.get("doc_id") or doc_id, "review_items": items,
                  # page rasters for the viewer are Phase 5.8 (needs a renderer);
                  # the data contract carries the field now, populated later.
                  "pages": []}

        notice = SustainmentNotice(
            doc_id=header_d.get("doc_id") or doc_id,
            doc_type=header_d.get("doc_type") or "PCN",
            revision=header_d.get("revision"),
            pub_date=header_d.get("pub_date") or "",
            mfr=header_d.get("mfr") or "",
            categories=header_d.get("categories") or [],
            summary=header_d.get("summary") or "",
            doc_level_ltb_date=header_d.get("doc_level_ltb_date"),
            impacted_parts=[PartImpact(**p) for p in parts_d],
        )
        aug = SustainmentAugmentation(notice=notice, review=review, needs_review=needs_review,
                                      review_reasons=reasons, stats=stats)
        section = BaseSection(title="Sustainment Notice", level=0, page_start=0,
                              content="", node_id=doc_id)
        return [DocumentNode(base_extraction=section, domain_augmentation=aug)]

    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        # Sustainment is processed globally via process_fulltext; per-chunk augment is a no-op.
        return DocumentNode(base_extraction=section, domain_augmentation=None)

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any, doc_id: str = "",
                         image_prefix: str = "") -> Tuple[List[str], List[str]]:
        cypher_queries: List[dict] = []
        sparql_queries: List[str] = []

        for node in nodes:
            sec = node.base_extraction
            aug = node.domain_augmentation
            if not isinstance(aug, SustainmentAugmentation):
                continue
            notice = aug.notice
            section_id = sec.node_id or f"section_{sec.page_start}_{sec.title}"

            cypher_queries.append({
                "query": f"""
                MERGE (p:{config.graph_node_label}:{self.domain_label} {{id: $section_id}})
                SET p.title = $title
                """,
                "params": {"section_id": section_id, "title": sec.title},
            })

            edge_cypher = f"""
            MERGE (p:{config.graph_node_label}:{self.domain_label} {{id: $section_id}})
            MERGE (n:SustainmentNotice:{self.domain_label} {{id: $notice_id}})
            SET n.pub_date = $pub_date, n.mfr = $mfr, n.type = $doc_type,
                n.revision = $revision, n.doc_level_ltb_date = $doc_level_ltb_date,
                n.needs_review = $needs_review
            MERGE (p)-[:GOVERNED_BY]->(n)

            WITH n
            UNWIND $impacted_parts AS part
            MERGE (c:Component:{self.domain_label} {{mpn: part.affected_mpn}})
            MERGE (c)-[:SUBJECT_TO]->(n)

            WITH n, c, part
            FOREACH (r IN CASE WHEN part.replacement_mpn IS NOT NULL AND part.replacement_mpn <> "" THEN [1] ELSE [] END |
                MERGE (alt:Component:{self.domain_label} {{mpn: part.replacement_mpn}})
                MERGE (c)-[:REPLACED_BY {{ltb_date: part.ltb_date}}]->(alt)
            )
            """
            parts_params = [
                {"affected_mpn": p.affected_mpn, "replacement_mpn": p.replacement_mpn,
                 "ltb_date": p.ltb_date}
                for p in notice.impacted_parts
            ]
            cypher_queries.append({
                "query": edge_cypher,
                "params": {
                    "section_id": section_id, "notice_id": notice.doc_id,
                    "pub_date": notice.pub_date, "mfr": notice.mfr,
                    "doc_type": notice.doc_type, "revision": notice.revision or "",
                    "doc_level_ltb_date": notice.doc_level_ltb_date or "",
                    "needs_review": aug.needs_review, "impacted_parts": parts_params,
                },
            })

            # --- JENA SPARQL/RDF ---
            safe_notice_id = notice.doc_id.replace(' ', '_').replace('"', '')
            if str(notice.doc_type).upper() == "PDN":
                notice_class = "pcn:ProductDiscontinuationNotice"
            else:
                notice_class = "pcn:ProcessChangeNotification"

            sparql = f"""
            PREFIX pcn: <http://internal/sustainment/pcn#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT DATA {{
                <http://internal/sustainment/doc/{safe_notice_id}> a {notice_class} .
            """
            for cat in notice.categories:
                safe_cat = str(cat).replace(' ', '_')
                sparql += f"""
                <http://internal/sustainment/doc/{safe_notice_id}> pcn:hasChangeCategory pcn:{safe_cat} .
                """
            for part in notice.impacted_parts:
                safe_mpn = part.affected_mpn.replace(' ', '_')
                sparql += f"""
                <http://internal/components/{safe_mpn}> pcn:subjectToNotice <http://internal/sustainment/doc/{safe_notice_id}> .
                """
                if part.ltb_date:
                    sparql += f"""
                    <http://internal/components/{safe_mpn}> pcn:hasLastTimeBuyDate "{escape_sparql_string(part.ltb_date)}"^^xsd:date .
                    """
                if part.replacement_mpn:
                    safe_rep = part.replacement_mpn.replace(' ', '_')
                    sparql += f"""
                    <http://internal/components/{safe_mpn}> pcn:hasReplacement <http://internal/components/{safe_rep}> .
                    """
            sparql += "}"
            sparql_queries.append(sparql)

        return cypher_queries, sparql_queries
