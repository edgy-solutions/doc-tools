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
import io
import os
from typing import List, Optional, Tuple, Any, Dict

from pydantic import BaseModel, Field

from doc_tools.plugins.base import AugmentationPlugin
from doc_tools.plugins.models import BaseSection, DocumentNode
from doc_tools.utils.jena_client import escape_sparql_string
from doc_tools.utils import provenance
from doc_tools.utils import sustainment_normalize as norm
from doc_tools.utils import table_text_layer as text_layer
from doc_tools.utils.sustainment_merge import (
    header_to_dict, part_to_dict, dedup_parts, reconcile_ltb, clean_replacements,
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


# Output BOUND for the vision pass. MEASURED at both ends (Diodes PCN 2683, 2026-07-29/30):
#
#   * RUNAWAY IS REAL: the dense tables (37 and 41 rows) do not converge. Locally they blew
#     past 6000 tokens still generating; the WORK vLLM log shows ~6.5 MINUTES of continuous
#     output on one crop (~16,000+ tokens) at `Running: 1 reqs, Waiting: 0` — so it is the
#     decode, not queueing.
#   * THE BUDGET IS SMALL: work generates at ~46 tok/s (observed, single-stream 31B), and
#     LiteLLM cuts the client off at 60s. That is a ceiling of ~2,700 tokens — far less than
#     the "H200 is fast so tokens are cheap" intuition suggests.
#
# So the bound must satisfy: (prefill + max_tokens/throughput) < the infra timeout. At
# 46 tok/s with a 60s ceiling and a few seconds of prefill, 2048 lands near ~45s and
# COMPLETES; 4096 would need ~89s and would still be killed — a cap that never fires is
# not a cap. Tune VISION_MAX_TOKENS per deployment: it is a function of that deployment's
# throughput and timeout, not a universal constant.
#
# NB a legitimately huge table can exceed this (Diodes p3 is THREE (EOL, Replacement)
# column-pairs per row => ~111 parts => ~3,900 tokens, which simply does not fit in a 60s
# 46 tok/s budget). That is correct behaviour here: it truncates, is DETECTED, and the
# reviewer is told parts may be missing — instead of 3x60s of retries and an opaque
# timeout. Actually EXTRACTING those parts wants the text-layer path (these notices are
# born-digital; pdfplumber reads the same tables exactly, in under a second), not a
# bigger token budget.
VISION_MAX_TOKENS = int(os.getenv("VISION_MAX_TOKENS", "2048"))


def _vision_call_opts():
    """(baml_options, collector) for the VISION pass: an output bound + truncation detection.

    Returns a collector because BAML **FAILS OPEN** on a truncated response — verified
    against the live model: a response cut at the cap raised NOTHING and returned a
    short/empty list. So a bound WITHOUT a truncation check would silently hand back
    "25 of 41 parts" as though it were the whole table — fabricated completeness, the
    exact laundering the review chain exists to prevent. The caller MUST treat a
    truncated call as a FAILED crop (see _extract_parts).

    `finish_reason` is not exposed by the collector for this provider, so truncation is
    detected as `usage.output_tokens >= VISION_MAX_TOKENS` — provider-independent and
    using what IS observable.

    The bound is applied via ClientRegistry rather than in `main.baml` DELIBERATELY: it
    keeps ONE source of truth (this constant) for both the cap and the check, and avoids
    the BAML deploy seam where an edited .baml is not live until `baml-cli generate` runs.
    """
    from baml_py import AbortController, ClientRegistry, Collector
    ms = int(os.getenv("LLM_REQUEST_TIMEOUT_MS", "600000"))
    cr = ClientRegistry()
    cr.add_llm_client("VisionBounded", "openai-generic", {
        "base_url": os.environ.get("VISION_LLM_BASE_URL", ""),
        "api_key": os.environ.get("VISION_LLM_API_KEY", "") or "any",
        "model": os.environ.get("VISION_LLM_MODEL", ""),
        "max_tokens": VISION_MAX_TOKENS,
    })
    cr.set_primary("VisionBounded")
    collector = Collector(name="vision")
    return ({"abort_controller": AbortController(timeout_ms=ms),
             "client_registry": cr, "collector": collector}, collector)


def _vision_output_tokens(collector) -> Optional[int]:
    """Output tokens of the collector's last call, or None if unavailable (never raises —
    a missing usage figure must not itself break an extraction)."""
    try:
        return collector.last.usage.output_tokens
    except Exception:  # noqa: BLE001
        return None


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

    def _extract_parts_text_layer(self, manifest: Optional[dict], s3_client,
                                  bucket: Optional[str]) -> Tuple[List[dict], dict]:
        """TIER 1: read the parts tables from the PDF's own TEXT LAYER (deterministic).

        These notices are born-digital — their tables are not pictures of tables. Measured
        on Diodes PCN 2683: the vision pass produced ZERO parts at work (runaway decode
        killed at 60s) while the text layer yielded 402 parts with exact per-cell bboxes
        in under a second. So vision is the FALLBACK for scans, not the default for text.

        Returns ([], stats) when the tier does not apply — no source PDF, no text layer,
        or no recognizable parts table — and the caller falls through to vision. Never
        raises: a tier-1 miss must degrade to tier 2, not fail the document.
        """
        stats = {"text_layer_pages": 0, "text_layer_parts": 0, "text_layer_used": False}
        key = (manifest or {}).get("source_key")
        if not key or s3_client is None or not bucket:
            return [], stats
        try:
            import pdfplumber  # noqa: PLC0415 — heavy import, only on the text-layer path
        except Exception as e:  # noqa: BLE001
            # LOUD, not silent. A missing tier-1 dependency means EVERY born-digital
            # document silently falls through to the vision path — which on dense tables
            # fabricates (measured: 84 invented MPNs, 100 of 111 real ones missed). A
            # quiet degrade here would hide a deployment error behind plausible garbage.
            print(f"[SustainmentPlugin] TEXT-LAYER TIER UNAVAILABLE — pdfplumber not importable "
                  f"({e}). Every born-digital notice will fall back to the vision pass, which is "
                  f"slower AND less accurate on dense tables. Install pdfplumber.")
            stats["text_layer_unavailable"] = True
            return [], stats
        try:
            body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
            parts: List[dict] = []
            with pdfplumber.open(io.BytesIO(body)) as pdf:
                for pno, page in enumerate(pdf.pages, start=1):
                    if not text_layer.page_has_text_layer(page):
                        continue
                    stats["text_layer_pages"] += 1
                    parts.extend(text_layer.parts_from_page(page, pno))
        except Exception as e:  # noqa: BLE001 — degrade to vision, never fail the doc
            print(f"[SustainmentPlugin] text-layer pass unavailable ({e}); falling back to vision")
            return [], stats
        if not parts:
            return [], stats
        stats["text_layer_parts"] = len(parts)
        stats["text_layer_used"] = True
        # Shape to the same per-part dict the vision pass produces. The bbox/page ride
        # along as PROVENANCE — strictly better than string-matching an MPN against a
        # positioned OCR index, and tight to the CELL rather than the whole table.
        out = [{
            "affected_mpn": p["affected_mpn"],
            "affected_mpn_source": p["affected_mpn"],   # verbatim: the cell IS the source
            "replacement_mpn": p.get("replacement_mpn"),
            "replacement_mpn_source": p.get("replacement_mpn"),
            "ltb_date": None,          # per-row dates are not a column in this shape;
            "ltb_date_source": None,   # the header pass supplies the doc-level date
            "text_layer_bbox": p.get("bbox"),
            "text_layer_page": p.get("page_number"),
            "text_layer_page_dims": p.get("page_dims"),
        } for p in parts]
        return out, stats

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
        n_crops, missing, failed, truncated = 0, 0, 0, 0
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
                opts, collector = _vision_call_opts()
                res = b.ExtractParts(ocr_text=ocr, html_table=html,
                                     table_images=images, system_instructions=prompt,
                                     baml_options=opts)
                # TRUNCATION IS A FAILURE, NOT A PARTIAL SUCCESS. BAML fails OPEN here:
                # a response cut at the cap parses to whatever complete objects it can
                # and raises nothing, so accepting it would report "25 of 41 parts" as
                # the whole table — a silent partial that looks clean, which is the one
                # thing this pipeline must never produce. Drop the rows and count the
                # crop failed; that flags the doc and the reviewer is TOLD parts may be
                # missing (doc_flags -> the review card's warning banner).
                used = _vision_output_tokens(collector)
                if used is not None and used >= VISION_MAX_TOKENS:
                    failed += 1
                    truncated += 1
                    print(f"[SustainmentPlugin] ExtractParts TRUNCATED at the {VISION_MAX_TOKENS}-token "
                          f"bound (runaway decode on a dense table) — discarding this crop's "
                          f"{len(res or [])} partial row(s) rather than reporting them as complete")
                    continue
                for p in (res or []):
                    all_parts.append(part_to_dict(p))
            except Exception as e:  # noqa: BLE001
                # A per-crop failure (commonly a vision timeout on a dense table)
                # loses that crop's rows. Count it so process_fulltext can flag
                # the doc needs_review — a silent partial must never look clean.
                failed += 1
                print(f"[SustainmentPlugin] ExtractParts failed on a table crop: {e}")
        # crops_truncated is a SUBSET of crops_failed, surfaced separately because it names a
        # DIFFERENT cause with a different fix: not "the model was slow / errored" but "the
        # decode did not converge on this table". Distinguishing them is how we'll know whether
        # banding (or a text-layer path) actually helps, instead of inferring it.
        return all_parts, {"n_crops_used": n_crops, "crops_missing": missing,
                           "crops_failed": failed, "crops_truncated": truncated}

    def process_fulltext(self, full_text: str, doc_id: str, metadata: Dict[str, Any] = None,
                         elements: List[Dict[str, Any]] = None, manifest: Dict[str, Any] = None,
                         s3_client: Any = None, bucket: str = None) -> List[DocumentNode]:
        index = provenance.build_positioned_index(elements)
        ocr_norm = provenance._norm(full_text)
        stats = {"n_tables": 0, "n_crops_used": 0, "crops_missing": 0, "crops_failed": 0,
                 "crops_truncated": 0, "vision_used": False}
        reasons: List[str] = []
        needs_review = False
        # The doc-level reasons that FORCE review — i.e. the extraction telling us its own
        # output is not fully trustworthy (header failed, a vision crop timed out, parts pass
        # died). These MUST REACH THE REVIEWER: if a review proceeds on degraded extraction,
        # the human deciding dispositions has to see the degradation, or a partial parts list
        # reads as a complete one. `reasons` keeps EVERYTHING for the record (advisory notes,
        # per-item detail); this is the reviewer-facing subset. Live case: Diodes PCN 2683 —
        # "2/5 table crops failed, extracted parts are likely INCOMPLETE" was recorded and
        # then reached nobody, because nothing downstream carried review_reasons at all.
        doc_flags: List[str] = []

        # ---- Pass 1: header (text-only, gpt-oss) ----
        header = None
        try:
            header = self._extract_header(full_text)
        except Exception as e:  # noqa: BLE001
            reasons.append(f"header pass failed: {e}")
            doc_flags.append(f"header extraction failed: {e}")
            needs_review = True
        header_d = header_to_dict(header) if header is not None else empty_header(doc_id)
        if not header_d.get("doc_id"):
            header_d["doc_id"] = doc_id
        # ONE authoritative, key-safe doc_id. Both sources are messy — the LLM's
        # 'as printed' number (spaces / '#') or a path-derived fallback — and
        # doc_id is a KEY for the workflow id, the MinIO prefix, the graph IRI and
        # the provenance index. Normalize HERE so every downstream consumer keys
        # on the SAME clean slug; stash the raw printed form for faithful display.
        header_d["doc_id_raw"] = header_d.get("doc_id")
        header_d["doc_id"] = norm.normalize_doc_id(header_d.get("doc_id"))
        if header is not None and not norm.is_known_doc_type(getattr(header, "doc_type", None)):
            reasons.append("doc_type unclassifiable — defaulted to PCN")
            doc_flags.append("notice type could not be classified — defaulted to PCN "
                             "(dispositions proposed under PCN rules may be wrong)")
            needs_review = True

        # ---- Router + Pass 2: parts (multimodal, Gemma) ----
        tables = provenance.table_elements(elements)
        stats["n_tables"] = len(tables)
        parts_d: List[dict] = []
        vision_ok = bool(os.getenv("VISION_LLM_BASE_URL"))
        # TIER 1 — the text layer, when the document has one. Deterministic, sub-second,
        # exact MPNs, per-cell provenance. Vision is the FALLBACK for scans; it is not the
        # default for text that is already machine-readable.
        tl_parts, tl_stats = self._extract_parts_text_layer(manifest, s3_client, bucket)
        stats.update(tl_stats)
        if tl_parts:
            parts_d = tl_parts
        elif tables and vision_ok and s3_client is not None:
            try:
                parts_d, ps = self._extract_parts(tables, manifest, s3_client, full_text)
                stats.update(ps)
                stats["vision_used"] = True
                if ps.get("crops_failed"):
                    trunc = ps.get("crops_truncated") or 0
                    cause = (f"{trunc} of them hit the {VISION_MAX_TOKENS}-token output bound "
                             f"(the model did not converge on a dense table)" if trunc
                             else "e.g. vision timeout")
                    msg = (f"{ps['crops_failed']}/{len(tables)} table crops failed "
                           f"({cause}) — extracted parts are likely INCOMPLETE")
                    reasons.append(msg)
                    # THE reviewer-facing case: a partial parts list is indistinguishable from
                    # a complete one unless we say so. Parts MISSING here get no disposition
                    # and nobody would know.
                    doc_flags.append(f"PARTS MAY BE MISSING: {msg}")
                    needs_review = True
            except Exception as e:  # noqa: BLE001
                reasons.append(f"parts pass failed: {e}")
                doc_flags.append(f"PARTS MAY BE MISSING: the parts pass failed ({e})")
                needs_review = True
        elif tables and not vision_ok:
            reasons.append("tables present but VISION_LLM_BASE_URL unset — parts NOT extracted")
            doc_flags.append("PARTS NOT EXTRACTED: this document has parts tables but the vision "
                             "model was unavailable")
            needs_review = True
        elif not tables:
            # No table detected -> header-only. Instrumented so the borderless
            # miss-rate is visible (Phase 0 decision #3: build the coordinate
            # page-crop fallback only if this fires on parts-bearing docs).
            reasons.append("no Table element detected — parts pass skipped (header-only)")

        # dedup across crops, then reconcile per-part LTB (per-row primary,
        # doc-level fallback)
        parts_d = clean_replacements(
            reconcile_ltb(dedup_parts(parts_d), header_d.get("doc_level_ltb_date")))

        # ---- Validation + review payload ----
        items, item_reasons = build_review_items(header_d, parts_d, index, ocr_norm)
        reasons += item_reasons
        cnt = validate_count(header_d, len(parts_d))
        if cnt:
            # INFORMATIONAL ONLY — deliberately does NOT set needs_review.
            # This cross-check reads the LLM-GENERATED summary, so its input varies run to
            # run for the SAME document: onsemi PD26044X1 reviewed fine once, then failed
            # later with nothing about the document changed. A gate whose input is
            # nondeterministic produces FLAKY refusals, and its two observed firings in
            # production were BOTH false positives (a part number's digits, then a year).
            # So it degrades to a note a human can read in review_reasons, never a flag.
            # A real under-extraction check wants a DETERMINISTIC reference — extracted rows
            # vs the parts TABLE's row count (structure vs structure), not prose vs structure.
            reasons.append(cnt)
        # `or reasons` REMOVED (2026-07-29): it promoted EVERY diagnostic — including notes the
        # code deliberately declines to flag on (the "no Table element detected" instrumentation
        # above explicitly sets no flag, then this line set it anyway) — into a doc-level review
        # flag, which downstream becomes a HARD REFUSAL. "We noted something" is not "a human must
        # review this"; conflating them made the file contradict its own stated intent and turned
        # one misparsed number into a refused notice (Qorvo 23-0171). Every review-forcing
        # condition now says so AT ITS OWN SITE; `reasons` stays the full, honest narrative
        # surfaced as review_reasons.
        if any(it["needs_review"] for it in items):
            needs_review = True

        review = {"doc_id": header_d.get("doc_id") or doc_id,
                  # the raw printed notice number ('PCN # 23-002') for DISPLAY;
                  # doc_id above is the normalized key. Display may prefer this.
                  "doc_id_raw": header_d.get("doc_id_raw") or header_d.get("doc_id") or doc_id,
                  # doc_type + categories DRIVE the disposition proposer's rule match:
                  # every PCN rule requires a change category, so without these the
                  # proposer returns UNCLASSIFIABLE for every part and the UI shows
                  # 'needs a disposition' on all of them. review.json is the sensor's
                  # ONLY source for the start_review payload (the graph drops per-part
                  # needs_review), so these MUST live here, not only in the graph.
                  # Categories stringified to their enum values (== the ruleset's
                  # pcn:changeClass category keys: 'Material','Process',…).
                  "doc_type": header_d.get("doc_type") or "PCN",
                  "categories": [str(getattr(c, "value", c))
                                 for c in (header_d.get("categories") or [])],
                  # EXTRACTION-QUALITY WARNINGS the reviewer must see (the doc-level reasons
                  # that forced review). Distinct from `review_reasons`, which is the complete
                  # record including advisory notes and per-item detail — those either aren't
                  # trustworthy enough to act on (the count cross-check) or are already visible
                  # per row (the needs_review badge). If a review proceeds on degraded
                  # extraction, THIS is what tells the human so.
                  "doc_review_reasons": doc_flags,
                  "review_items": items,
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
            # notice.doc_id is already normalized at finalization; normalize again
            # here (idempotent) so the graph IRI keys on the SAME canonical slug as
            # review.json / the workflow id. (safe_mpn below stays a bare space->_
            # replace — MPNs keep '#' reel codes verbatim as provenance join keys.)
            safe_notice_id = norm.normalize_doc_id(notice.doc_id)
            if str(notice.doc_type).upper() == "PDN":
                notice_class = "pcn:ProductDiscontinuationNotice"
            else:
                notice_class = "pcn:ProcessChangeNotification"

            # Scope instance data to the domain's INSTANCE graph, NOT the vocabulary graph.
            # Two reasons, one invariant: (1) an unscoped INSERT DATA lands in Jena's DEFAULT
            # graph where the mesh can't see it (the graph-name/semantic-domain seam); (2) the
            # vocabulary graph <http://internal/{DOMAIN}> is MANIFEST-reproducible and gets
            # DROP-first wiped on every prime re-ingest — runtime INSTANCE data is NOT
            # reproducible, so it must live in a graph prime never touches. Producers with
            # different reproducibility must not share a graph (AGENTS.md). domain_label ==
            # 'SUSTAINMENT' -> instances land in <http://internal/SUSTAINMENT_INSTANCES>, which
            # the pcn resolveInstance provider queries and clear_ontology_graphs never drops.
            graph_uri = f"http://internal/{self.domain_label}_INSTANCES"
            sparql = f"""
            PREFIX pcn: <http://internal/sustainment/pcn#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT DATA {{
              GRAPH <{graph_uri}> {{
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
            sparql += "  }\n}"  # close GRAPH, then INSERT DATA
            sparql_queries.append(sparql)

        return cypher_queries, sparql_queries
