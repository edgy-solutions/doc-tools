## common

You are reading ONE CROPPED REGION of a manufacturer change or discontinuance notice (PCN/PDN). This is a second, independent reading, used only when the document's own extracted text is suspect, so your answer must stand on its own as a record of what this crop prints.

You are given a small region, not a page. Everything you need is inside it, and anything not inside it is not your concern.

RULES THAT APPLY TO EVERY QUESTION BELOW:
- Answer ONLY from what is printed in this crop. If the crop does not print an answer to a question, write `not printed` for that question. Never infer, complete, or guess a value from context, from a logo, or from what a notice of this kind usually says.
- Copy every value VERBATIM, exactly as printed: the same characters, the same punctuation, the same dashes and slashes, the same capitalisation, the same date format. Do not reformat a date, do not expand an abbreviation, do not normalise a part number, and do not correct what looks like a typo or a misspelling — if the crop prints it that way, that is the answer.
- Read the DIGITS and the MONTH of every date carefully, character by character. A date in this crop is being used to decide what a customer must do and by when, and a single wrong character makes it wrong rather than approximate.
- Answer each question on its own line, in the form `Label: value`, using the labels given below, in the order given. Output PLAIN TEXT ONLY: no markdown, no commentary, no explanation of how you read it, no summary.

## header_block

This crop is the title block at the top of the notice. Answer these questions, one per line:

- `Manufacturer:` the name of the company that ISSUED this notice, as printed in the text of this crop. Take it from printed text only, never from a logo or an image of a brand name. Preserve the spelling exactly as printed even where it looks misspelled or is missing letters.
- `Document Number:` the notice's own identifying number, as printed (for example a PCN, PDN, or change-notice number).
- `Notice Date:` the date THIS NOTICE was issued, as printed. It is usually printed beside the document number and labelled as the notice, publication, change, or PCN date.
- `Current Date:` a date printed in this crop that is labelled as the current date, the date printed, or the date the page was retrieved or viewed — the kind of date a web portal stamps onto a page when it prints it. If this crop prints such a date, report it here, on its own line, and do NOT report it as the `Notice Date`. If no such date is printed, write `not printed`.

The last two questions are deliberately separate. A notice that was retrieved from a portal often prints BOTH its own issue date and the date it was retrieved, and they are different dates with different meanings. Report each on its own line under its own label, and never merge them or let one stand in for the other.

## estimated_dates

This crop is the block of estimated or key dates, usually printed as a small table of labelled dates. Answer these questions, one per line:

- `Last Order Date:` the last date on which an order can be placed, as printed. It may be labelled last order, last time buy, LTB, last buy, or similar.
- `Last Ship Date:` the last date on which product will ship or be delivered, as printed. It may be labelled last ship, last delivery, last shipment, or similar.
- `All Dates:` every date printed anywhere in this crop, with the label printed beside it, one `label = date` pair per date, separated by ` | `. Include every date in the crop, including any you already reported above.

Read the ROWS of this block carefully before answering. These blocks are laid out as labels in one column and dates in another, and adjacent rows hold DIFFERENT dates that are often only a day or two apart. Pair each date with the label printed on its own row, and do not let a neighbouring row's date answer the row above or below it. The `All Dates:` line exists so that a mispairing can be caught: it must list the labels and dates as the rows actually print them.
