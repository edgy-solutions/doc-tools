You are extracting the HEADER fields of a manufacturer change or discontinuance notice (PCN or PDN). Use ONLY information present in the provided document text. Do not invent values.

Extract these header fields:

- doc_id: the notice number exactly as printed (e.g. "PDN 23_0120", "PCN20250409000.1"). Preserve spaces, underscores, and dots verbatim.
- doc_type: PCN or PDN.
    * PCN  = process change, product change, product/process change notification.
    * PDN  = discontinuance, discontinuation, obsolescence, EOL / end-of-life, PTN / product termination, last-time-buy notice.
  Choose the PRIMARY class. If a change notice also kills a variant, keep doc_type as the primary class (usually PCN) and record the discontinuation nuance in categories.
- revision: the document revision exactly as printed (e.g. "A", "-"). Null if the notice shows none.
- pub_date: the notification / publication date, normalized to ISO 8601 (YYYY-MM-DD).
- mfr: the issuing manufacturer (e.g. "Analog Devices, Inc.").
- categories: all applicable change categories from {Material, Process, Location, Discontinuation, Packaging, Testing}. May be more than one. This is a judgment call.
- summary: a concise 1-2 sentence impact summary. This is derived/paraphrased.
- doc_level_ltb_date: a SINGLE document-level last-time-buy / last-order date that applies to ALL affected parts, IF the notice states one once (in the header or prose), normalized to ISO 8601. Null if there is no single doc-level LTB (e.g. the dates are only per-row in the table, or there is no LTB at all).

PROVENANCE (*_source fields): for pub_date, mfr, and doc_level_ltb_date, ALSO return the EXACT substring as it appears in the document — unnormalized, character-for-character — in the matching *_source field (pub_date_source, mfr_source, doc_level_ltb_date_source). If you cannot find the value verbatim in the text, set the *_source to null. summary and categories are derived and have NO source snippet.

DATE NORMALIZATION: convert any printed date format (e.g. "05-Dec-2023", "December 5, 2023", "2023/12/05") to YYYY-MM-DD for the value field, but keep the *_source field verbatim as printed.

DO NOT extract the affected part list here — a separate pass handles the parts table. Focus only on the header fields above.
