You are extracting the AFFECTED PARTS TABLE from a manufacturer change or discontinuance notice (PCN/PDN). You are given three views of the same table. Use them with this STRICT authority order:

1. TABLE IMAGE(S) are AUTHORITATIVE for STRUCTURE: how many rows there are, which columns exist, and which "affected" part maps to which "replacement" part. Read row/column layout and affected->replacement pairing from the image.
2. OCR TEXT is AUTHORITATIVE for the exact CHARACTERS of every part number. When you emit an affected_mpn or replacement_mpn, copy its characters from the OCR TEXT — do NOT transcribe them from the image pixels (long alphanumerics are easily misread). The value and its *_source must match the OCR text verbatim.
3. HTML TABLE is a ROUGH HINT ONLY. It may be sparse, misaligned, or wrong. Use it only to disambiguate; never as the source of truth.

RULES:
- Every affected_mpn you emit MUST appear verbatim somewhere in the OCR TEXT. If a part number is legible in the image but absent from the OCR text, still emit it and copy it as exactly as you can — it will be flagged for human review.
- affected_mpn_source = the exact substring of the OCR TEXT for that part (character-for-character; usually identical to affected_mpn). This is a provenance join key.
- A wrapped, multi-line description is still ONE part. Do not split a single row into multiple parts because its text wraps across lines.
- Preserve part numbers EXACTLY: keep suffixes, slashes, '#' reel codes, module dashes, and spaces. Do NOT normalize, hyphenate, pad, or "correct" them. Non-standard schemes are valid parts — e.g. module numbers like 090-44310-31 or reel suffixes like -E3/81 — never drop a part for "not looking like a part number".
- replacement_mpn: the recommended replacement for THAT row, exactly as written; null if the row lists none. Set replacement_mpn_source to its verbatim OCR substring, or null.
- ltb_date: ONLY if the table row carries its OWN per-row last-time-buy date, emit it (ISO 8601) with ltb_date_source as the verbatim substring. If the notice's last-time-buy date is a single document-level date (not per-row), leave the per-row ltb_date null — the header pass captures the document-level date.
- MIXED tables: some notices list both DISCONTINUED and CONTINUED / UNCHANGED parts in one table. Emit ONLY the affected (discontinued / changed) parts. Do NOT emit continued or unchanged parts.
- Do NOT invent parts, replacements, or dates. If a column is absent, leave the corresponding field null. Emit one entry per distinct affected part.
