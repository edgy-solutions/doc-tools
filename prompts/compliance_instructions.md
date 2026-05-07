Analyze the following compliance manual or logistics document.
Extract any mandatory compliance rules, safety regulations, or constraints.

DATA HANDLING INSTRUCTIONS:
- Hybrid Tables: Tables are provided in two parts:
    1. ### TABLE STRUCTURE (SPATIAL) ###: A Markdown grid showing column/row alignment. This grid may be sparse due to OCR errors.
    2. ### TABLE CONTENT (SUPPLEMENTAL RAW TEXT) ###: A stream of raw text containing all values from the table. Use this to find missing metrics or references absent from the spatial grid.
- Cross-Referencing: If a cell in the spatial grid is empty, check the Supplemental Raw Text to see if the value exists there before assuming it is missing.

For every rule, identify:
- The `manual_reference` (e.g., DAFMAN section).
- The `rule_type` (Safety, Throughput, Storage, etc.).
- Any `applicable_hazard_class` (like explosives class 1.1).
- Any `target_metric` (e.g., maximum limits, distances, times).
- A summary `rule_description`.