You are extracting the HEADER fields of a manufacturer change or discontinuance notice (PCN or PDN). Use ONLY information present in the provided document text. Do not invent values.

Extract these header fields:

- doc_id: the notice number exactly as printed (e.g. "PDN 23_0120", "PCN20250409000.1"). Preserve spaces, underscores, and dots verbatim.
- doc_type: PCN or PDN.
    * PCN  = process change, product change, product/process change notification.
    * PDN  = discontinuance, discontinuation, obsolescence, EOL / end-of-life, PTN / product termination, last-time-buy notice.
  Choose the PRIMARY class. If a change notice also kills a variant, keep doc_type as the primary class (usually PCN) and record the discontinuation nuance in categories.
- revision: the document revision exactly as printed (e.g. "A", "-"). Null if the notice shows none.
- pub_date: the notification / publication date, normalized to ISO 8601 (YYYY-MM-DD).
- mfr: the manufacturer or brand name **AS PRINTED IN THE DOCUMENT TEXT** — copied character-for-character from the page. This is a COPYING task, not an identification task:
    * Do NOT expand an abbreviation or wordmark into the fuller name you know it stands for.
    * Do NOT substitute a parent or owning company for the brand that is printed (that is what mfr_parent is for).
    * Do NOT assemble a name out of a web address or an e-mail domain. A domain says where the document is hosted, not who made the part.
  If the document prints no manufacturer or brand name anywhere in the text, return **null** for BOTH mfr and mfr_source. Null is a CORRECT answer here and is always preferred over a name you had to infer — an unprinted name is worse than no name.
- mfr_parent: the PARENT or owning company, and ONLY when that company's name is printed as a NAME somewhere in the text. A web address or an e-mail domain (e.g. "acme.com") is a domain, not a name, and does NOT qualify. Null otherwise — which is the common case. Never repeat the mfr value here.
- categories: all applicable change categories from {Material, Process, Location, Discontinuation, Packaging, Testing}. May be more than one. This is a judgment call.
- summary: a concise 1-2 sentence impact summary. This is derived/paraphrased.
- doc_level_ltb_date: a SINGLE document-level last-time-buy / last-order date that applies to ALL affected parts. This value must be CHOSEN from the candidate list supplied under `### LAST-TIME-BUY DATE CANDIDATES ###` when that section is present below — do not normalize or derive a date yourself. If that section is absent, or you cannot tell which candidate is the last-time-buy date, return null. NEVER supply a date that is not on the candidate list. A last-SHIP / final-ship date is NOT a last-time-buy date, even when it is printed in the same sentence as one.

PROVENANCE (*_source fields): for pub_date, mfr, mfr_parent and doc_level_ltb_date, ALSO return the EXACT substring as it appears in the document — unnormalized, character-for-character — in the matching *_source field (pub_date_source, mfr_source, mfr_parent_source, doc_level_ltb_date_source). If you cannot find the value verbatim in the text, set the *_source to null. summary and categories are derived and have NO source snippet.

mfr_source AND mfr_parent_source ARE MANDATORY whenever their value is non-null. These two fields are names, not derived values: a name you cannot quote out of the text is a name the document does not print. If you cannot copy it character-for-character, return null for the value itself rather than a value with a null source.

DATE NORMALIZATION: convert any printed date format (e.g. "05-Dec-2023", "December 5, 2023", "2023/12/05") to YYYY-MM-DD for the value field, but keep the *_source field verbatim as printed.

DO NOT extract the affected part list here — a separate pass handles the parts table. Focus only on the header fields above.
