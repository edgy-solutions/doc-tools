// PCN/PDN sustainment extraction.
//
// Two-pass design (see the Phase 1-5 plan):
//   ExtractHeader -> NoticeHeader  (text-only,   client LLM    / gpt-oss)
//   ExtractParts  -> PartImpact[]  (multimodal,  client Vision / Gemma)
// The final SustainmentNotice is assembled + reconciled in Python
// (doc_tools/plugins/sustainment.py), NOT by an LLM.
//
// Provenance (Phase 5): every value the review UI will highlight carries a
// verbatim *_source snippet - the exact substring as it appears in the OCR
// text / table cell. That snippet is the join key the provenance resolver
// uses to attach a page_number + bbox. It MUST be copied verbatim
// (unnormalized) or it will not resolve to a location. Verbatim extraction is
// therefore doubly load-bearing (also the Phase 4 substring guard).

enum DocType {
  PCN
  PDN
}

enum ChangeCategory {
    Material
    Process
    Location
    Discontinuation
    Packaging
    Testing
}

class PartImpact {
    affected_mpn string @description("The affected/discontinued manufacturer part number, EXACTLY as written - preserve suffixes, slashes, '#' reel codes, and module dashes (e.g. 'LTC6226HDC#TRMPBF', 'BYVB32-200-E3/81', '090-44310-31'). Never normalize, hyphenate, or 'correct' it.")
    affected_mpn_source string @description("The exact substring, VERBATIM and unnormalized, as affected_mpn appears in the OCR text / table cell. Copy character-for-character - this is the provenance join key. Usually identical to affected_mpn.")
    replacement_mpn string? @description("The recommended replacement/substitute part number for THIS row, exactly as written. Null if the notice lists no replacement for this part.")
    replacement_mpn_source string? @description("Verbatim source substring for replacement_mpn, or null if none.")
    ltb_date string? @description("The PER-ROW last-time-buy date for this specific part, ISO 8601 (YYYY-MM-DD), IF the table row carries its own date. Null if this row has no per-row date (a single document-level date lives on the header instead).")
    ltb_date_source string? @description("Verbatim source substring for a per-row ltb_date, or null.")
}

class NoticeHeader {
    doc_id string @description("The PCN/PDN/notice number exactly as printed, e.g. 'PDN 23_0120' or 'PCN20250409000.1'.")
    doc_type DocType @description("PCN for process/product changes; PDN for discontinuance / obsolescence / EOL / PTN / product-termination. Pick the PRIMARY class; discontinuation nuance goes in categories.")
    revision string? @description("Document revision as printed, e.g. 'A' or '-'. Null if the notice shows none.")
    pub_date string @description("The notification / publication date in ISO 8601 (YYYY-MM-DD).")
    pub_date_source string? @description("Verbatim source substring for pub_date - the date string as printed - or null.")
    mfr string @description("The issuing manufacturer, e.g. 'Analog Devices, Inc.'.")
    mfr_source string? @description("Verbatim source substring for mfr, or null.")
    categories ChangeCategory[] @description("All applicable change categories (judgment call - may be more than one). Empty list only if truly indeterminate.")
    summary string @description("A 1-2 sentence high-level impact summary. Derived/paraphrased - it has NO source snippet and is not highlighted.")
    doc_level_ltb_date string? @description("A SINGLE document-level last-time-buy / last-order date that applies to ALL affected parts (typically stated once in the header or prose), ISO 8601. Null if there is no single doc-level LTB (dates are only per-row, or there is no LTB at all).")
    doc_level_ltb_date_source string? @description("Verbatim source substring for doc_level_ltb_date, or null.")
}

// Final merged notice. Assembled + reconciled in Python from NoticeHeader +
// PartImpact[] (per-part ltb_date: prefer per-row, fall back to
// doc_level_ltb_date). Retained as a BAML type for the legacy single-pass
// ExtractSustainment and the graph-persistence mirror.
class SustainmentNotice {
    doc_id string @description("The PCN/PDN number, e.g., 23-002")
    doc_type DocType @description("PCN or PDN")
    revision string? @description("Document revision, or null.")
    pub_date string @description("The notification date")
    mfr string @description("The manufacturer, e.g., Mini-Circuits")
    categories ChangeCategory[]
    summary string @description("High-level impact summary (1-2 sentences)")
    doc_level_ltb_date string? @description("Document-level last-time-buy date, or null.")
    impacted_parts PartImpact[]
}

// -- Pass 1: header fields, text-only, on gpt-oss (client LLM). --
function ExtractHeader(doc: string, system_instructions: string) -> NoticeHeader {
  client LLM
  prompt #"
    {{ system_instructions }}

    ### DOCUMENT TEXT ###
    ---
    {{ doc }}
    ---

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}
  "#
}

// Lean per-row output for the vision parts pass. Deliberately WITHOUT the
// _source snippets that PartImpact carries: a table cell's affected_mpn IS its
// verbatim source, and the provenance resolver matches affected_mpn against the
// positioned index in code (sustainment_merge.build_review_items) — so making a
// 31B vision model echo _source back for every row ~doubled its output and made
// dense tables blow the request timeout (2/19 extracted). Mapped to PartImpact
// in Python with source == value.
class PartRow {
    affected_mpn string @description("The affected/discontinued part number, EXACTLY as written - preserve suffixes, slashes, '#' reel codes, module dashes (e.g. 'LTC6226HDC#TRMPBF', '090-44310-31'). Never normalize.")
    replacement_mpn string? @description("The recommended replacement for THIS row, exactly as written; null if none. Qualification / evaluation vehicles are NOT replacements.")
    ltb_date string? @description("Per-row last-time-buy date (ISO 8601) if the row carries its own; else null.")
}

// -- Pass 2: part rows, multimodal, on Gemma (client Vision). --
// Authority split lives in the parts prompt file: image is authoritative for
// row/column structure + affected->replacement pairing; ocr_text is
// authoritative for the exact characters of every MPN (copy, don't re-read
// from pixels); html_table is a rough hint only.
function ExtractParts(ocr_text: string, html_table: string, table_images: image[], system_instructions: string) -> PartRow[] {
  client Vision
  prompt #"
    {{ system_instructions }}

    ### OCR TEXT (AUTHORITATIVE for the exact characters of every MPN - copy, do not re-read from pixels) ###
    ---
    {{ ocr_text }}
    ---

    ### HTML TABLE (rough hint only - may be sparse or wrong) ###
    ---
    {{ html_table }}
    ---

    ### TABLE IMAGE(S) (AUTHORITATIVE for row/column structure and affected->replacement pairing) ###
    {% for img in table_images %}
    {{ img }}
    {% endfor %}

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}
  "#
}

// -- Legacy single-pass extractor. Retained for backward compat
//    (scripts/test_fallback_resilience.py, ad-hoc runs); NOT used by the
//    two-pass router in sustainment.py. --
function ExtractSustainment(doc: string, system_instructions: string) -> SustainmentNotice {
  client LLM
  prompt #"
    {{ system_instructions }}

    ### DOCUMENT TEXT ###
    ---
    {{ doc }}
    ---

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}
  "#
}
