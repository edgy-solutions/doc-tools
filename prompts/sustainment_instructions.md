Analyze the following manufacturer notice.
Extract the information strictly into the requested JSON format.

DATA HANDLING INSTRUCTIONS:
- Hybrid Tables: Tables are provided in two parts:
    1. ### TABLE STRUCTURE (SPATIAL) ###: A Markdown grid showing column/row alignment. Use this to determine relationships (e.g. which MPN is the replacement for which). This grid may be sparse due to OCR errors.
    2. ### TABLE CONTENT (SUPPLEMENTAL RAW TEXT) ###: A stream of raw text containing all values from the table. Use this to find missing part numbers or dates that are absent from the spatial grid.
- Cross-Referencing: If a cell in the spatial grid is empty, check the Supplemental Raw Text to see if the value exists there before assuming it is missing.
- Use the column headers to map 'Affected Parts' to their 'Replacements'.
- If part numbers are listed in a dense grid without headers, treat all items in the grid as Affected Parts.
