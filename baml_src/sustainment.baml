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
    mfr string? @description("The manufacturer or brand name AS PRINTED in this document, copied character-for-character from the text. Null when the document prints no manufacturer or brand name anywhere - null is a correct answer here, not a failure. Never expand an abbreviation, never substitute a parent or owning company, and never assemble a name out of a web address.")
    mfr_source string? @description("Verbatim source substring for mfr - MANDATORY whenever mfr is non-null. If you cannot copy the name out of the text character-for-character, the correct answer is mfr = null, not a name with a null source.")
    mfr_parent string? @description("The PARENT or owning company, ONLY when that company's name is printed as a NAME in the text. A web or e-mail domain ('acme.com') is a domain, not a name, and does NOT qualify. Null otherwise, which is the common case.")
    mfr_parent_source string? @description("Verbatim source substring for mfr_parent, or null.")
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
    mfr_parent string? @description("The parent / owning company, when the document prints its name as a name. Null otherwise.")
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
    {{ _.role("system") }}
    {{ system_instructions }}

    {{ _.role("user") }}
    ### OCR TEXT (AUTHORITATIVE for the exact characters of every MPN - copy, do not re-read from pixels) ###
    ---
    {{ ocr_text }}
    ---

    ### HTML TABLE (rough hint only - may be sparse or wrong) ###
    ---
    {{ html_table }}
    ---

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}

    ### TABLE IMAGE(S) (AUTHORITATIVE for row/column structure and affected->replacement pairing) ###
    {% for img in table_images %}
    {{ img }}
    {% endfor %}
  "#
}
// NOTE: the image MUST be in a user message (via _.role("user")), not the
// default single system message. vLLM's gemma multimodal template only inserts
// the image placeholder for images in USER turns; an image in a system message
// -> "Failed to apply prompt replacement for mm_items['image']" (litellm 500).
// Ollama tolerates images in system messages; vLLM does not.
// NOTE: the image block is LAST on purpose. BAML splits the prompt into content
// blocks at image boundaries; any TEXT AFTER the image makes the request
// [text, image, text]. vLLM's gemma multimodal template fails to place the image
// token in that shape ("Failed to apply prompt replacement for mm_items['image']")
// though Ollama tolerates it. Image-last yields a clean [text, image] that both
// backends accept. Do NOT move ctx.output_format below the image.

// -- Grid forwarding (tier-1 declined grid -> tier-2 LABELS ONLY, never re-transcribes). --
// When pdfplumber reads a table's grid but cannot decide what the columns MEAN, the grid
// itself is exact — it came from the PDF's own text layer, not a pixel re-read. Handing
// THAT grid to vision instead of a fresh crop means vision's only remaining job is naming
// which column is which. GridColumnRoles therefore returns INDICES ONLY, never part
// strings, and `affected_col` may be NULL to say the table holds no parts at all -- see
// _GRID_NO_PARTS_COL_NOTE in doc_tools/plugins/sustainment.py, where a forced guess on a
// change-description table emitted a wire-bond material as an MPN and cost 898 -> 897 on
// the corpus. Pixels are not a trustworthy source for MPN characters (long alphanumerics are
// easily misread — SYTX9-122HP-1+ on PCN23-002 is the measured case), and a clipped or
// re-cut crop must be able to cost a column LABEL but must NEVER be allowed to cost a ROW
// or corrupt an MPN's characters. Part strings are read verbatim from the grid cells in
// Python (doc_tools/plugins/sustainment.py), not from this function's output.
class GridColumnRoles {
    affected_col int? @description("Index of the grid column holding the affected/discontinued manufacturer part number, read off its cN heading. NULL when this table has NO affected-part column at all - a change-description table, a spec/material table, a revision history. Null is a real answer, not a failure: guessing a column on a table that holds no parts emits whatever sits in the guessed column as if it were a part number.")
    replacement_col int? @description("0-based index of the column holding the recommended replacement/substitute part number, or null if this table has no replacement column at all.")
    ltb_date_col int? @description("0-based index of a PER-ROW last-time-buy date column, or null if the table carries no per-row dates.")
    header_rows int[] @description("0-based indices of rows that are headers, captions or spacers rather than parts. Empty list if every row is a part row.")
    reason string @description("One sentence naming the evidence in the image or grid for this column assignment.")
}

// -- Grid-forwarding pass: LABELS ONLY, multimodal, on Gemma (client Vision). --
// Section order matches ExtractParts above (load-bearing for vLLM/gemma - see its NOTEs):
// grid text, then the column-count hint, then OUTPUT FORMAT, then the image(s) LAST with
// no text after them. The grid, not the image, is authoritative for cell text.
function LabelGridColumns(grid_text: string, n_cols: int, table_images: image[], system_instructions: string) -> GridColumnRoles {
  client Vision
  prompt #"
    {{ _.role("system") }}
    {{ system_instructions }}

    {{ _.role("user") }}
    ### GRID (AUTHORITATIVE for all cell text) ###
    ---
    {{ grid_text }}
    ---
    The FIRST line above names the DATA COLUMNS: c0, c1, ... ({{ n_cols }} in all).
    Return the N from cN for affected_col, replacement_col and ltb_date_col - read the
    number off the heading, do not count columns.

    The `[row N]` label starting every line is a ROW NAME, NOT a data column. Use its N
    for header_rows. Never count it as a column: answering 1 for the first data column
    would mispair every row in the table.

    If NO column in this table holds manufacturer part numbers - it describes a change, a
    material, a process or a revision history rather than listing parts - return
    affected_col as null and say so in reason. Do NOT pick a closest candidate: every row
    of the column you name is emitted verbatim as a part number, so naming a description
    column turns its text into parts that do not exist.

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}

    ### TABLE IMAGE(S) (structure/pairing hint ONLY - never a source of part characters) ###
    {% for img in table_images %}
    {{ img }}
    {% endfor %}
  "#
}

// -- Second witness: one full page raster, transcribed verbatim, multimodal on Gemma
// (client Vision). Used ONLY when doc_tools.utils.text_layer_health flags a document's
// text layer as degraded (see doc_tools/utils/sustainment_header_trust.py's witness_index
// parameter) — a header value the broken text layer cannot corroborate gets one more
// chance against the page's own pixels before it is refused. Plain string output, not a
// typed class: this is a raw transcription, not an extraction, and has no fields to name.
//
// NO `### OUTPUT FORMAT ###` / `{{ ctx.output_format }}` HERE, unlike the house layout in
// AGENTS.md — deliberately, and it was measured, not assumed. `ctx.output_format` renders
// the schema of the return type; for a typed extraction class (NoticeHeader, PartsGrid,
// ...) that is real content the model needs. This function returns a bare `string`, which
// has no fields to describe, so `ctx.output_format` renders to the EMPTY STRING. Rendering
// the actual request (b.request.TranscribePage) with the section header left in showed the
// user turn as a `### OUTPUT FORMAT ###` heading over nothing, immediately before the
// image — a dangling section at best, and at worst an invitation for the model to try to
// satisfy an empty format spec, directly against this prompt's own "plain text only" rule.
// `### PAGE ###` below is a plain section label, not a request for a format.
function TranscribePage(page_image: image, system_instructions: string) -> string {
  client Vision
  prompt #"
    {{ _.role("system") }}
    ### INSTRUCTIONS ###
    {{ system_instructions }}

    {{ _.role("user") }}
    ### PAGE ###

    {{ page_image }}
  "#
}
// NOTE: same image-placement rules as ExtractParts/LabelGridColumns above, and for the
// same reason (vLLM's gemma multimodal template only inserts the image placeholder for an
// image in a USER turn, and fails to place it at all when text follows it in that turn).
// The image is therefore the LAST thing in the user block, with nothing after it, and
// system_instructions rides in the system role rather than the user block.

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
