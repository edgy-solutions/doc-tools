You are given a table's GRID — every cell of a parts table, extracted losslessly from the PDF's own text layer by pdfplumber — plus an image of the same table. The columns in this grid have NOT been labeled: a header row could not be identified automatically, so the meaning of each column is unknown.

Your ONLY job is to say which column is which, by INDEX. You are NOT extracting part numbers, and you must NEVER transcribe, correct, retype, or otherwise re-read any part number, date, or other cell value. The grid text is authoritative and already exact; the image is provided only so you can understand the table's structure (how columns are laid out, which column visually pairs with which).

RULES:
The grid is printed with its indices already in it, so that no index has to be counted.
The first line names the DATA COLUMNS (`c0`, `c1`, ...), and every following line starts
with a `[row N]` label. Read the numbers off those labels: the N in `cN` is what
affected_col / replacement_col / ltb_date_col expect, and the N in `[row N]` is what
header_rows expects. `[row N]` is a ROW NAME, never a data column -- counting it as one
would shift every column index by one and mispair the whole table.

- affected_col: the index (the N in `cN`) of the column holding the affected / discontinued manufacturer part number. Always pick your best candidate, even if you are not fully certain.
- replacement_col: the index (the N in `cN`) of the column holding a recommended replacement / substitute part number, or null if this table has no replacement column at all.
- ltb_date_col: the index (the N in `cN`) of a column holding a PER-ROW last-time-buy date, or null if the table carries no per-row dates (a single document-level date is handled elsewhere).
- header_rows: the `[row N]` numbers of rows that are headers, captions, titles, or blank/spacer rows rather than actual part rows. Empty list if every row is a part row.
- reason: one sentence naming the evidence — in the grid text or the image — for your column assignment.
- If the image is clipped, blurry, or otherwise unreadable, label the columns from the grid text alone; do not guess structure from a part of the image you cannot actually see, and do not let a bad image stop you from answering — the grid text alone is normally enough to identify which column holds an affected part number (it looks like a part number) and which column, if any, holds a replacement.
- NEVER invent a column that is not present in the grid. Every index you return must be a real column index of the grid you were given.
- Do NOT output any part number, date value, or other cell content. Output ONLY the column indices, the header row indices, and your one-sentence reason.
