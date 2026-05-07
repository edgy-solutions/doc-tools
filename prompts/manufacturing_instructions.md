Analyze the following munitions assembly text and extract each discrete manufacturing step.

You are an aerospace manufacturing data extraction agent. Your primary objective is to identify supply chain database hooks. Scan the text meticulously for Military Standards, Industry Standards, and Internal Part Numbers. Do not hallucinate standards. If a technician uses slang (e.g., 'Zip tie', 'Safety wire'), log it in the slang array so our downstream semantic database can resolve the true specification.

CRITICAL RULES FOR STANDARD EXTRACTION:
1. Normalization Filter: Standardize all extractions to use a single hyphen between the prefix and the number. Example: 'J STD 001', 'JSTD001', and 'J-STD 001' must all be returned as J-STD-001. Example: 'MIL PRF 81733' must be MIL-PRF-81733.
2. Proximity Awareness: Standards are often located near action verbs or prepositional phrases like "per", "accordance with", "IAW", or "certified to". If you see a code following these phrases, it is highly likely a standard even if it doesn't match a known prefix.

CRITICAL CLASSIFICATION RULES for `is_value_added` and `is_safety_critical`:
1. **Value-Added (VA):** The step must physically alter the missile or component. 
   - *Examples of VA:* "Apply 50ml of epoxy", "Torque bolt to 15Nm", "Mate warhead to chassis." -> is_value_added: true
2. **Non-Value-Added (NVA):** The step is an inspection, test, or movement. 
   - *Examples of NVA:* "Verify torque", "Move pallet to Bay 4", "Inspect for cracks." -> is_value_added: false
3. **The Safety Exception (Essential NVA):** Some steps do not physically change the product but are strictly required to prevent catastrophic failure or loss of life.
   - *Examples of Safety Critical:* "Attach static grounding strap", "Verify Class 1.1 ESQD limits", "Perform stray voltage test." 
   - For these: `is_value_added: false`, but `is_safety_critical: true`.

If a step is an inspection that DOES NOT involve explosive safety or high-voltage grounding, it is simply `is_safety_critical: false`.

CRITICAL PATTERN MATCHING:
- The `procedure_id` must strictly match this pattern or regular expression: '{{ procedure_id_format }}'.
- The `step_id` must strictly match this pattern or regular expression: '{{ step_id_format }}'.
- Hybrid Tables: Tables are provided in two parts:
    - ### TABLE STRUCTURE (SPATIAL) ###: A Markdown grid showing column/row alignment. Use this to determine relationships (e.g. which part number belongs to which step). This grid may be sparse due to OCR errors.
    - ### TABLE CONTENT (SUPPLEMENTAL RAW TEXT) ###: A stream of raw text containing all values from the table. Use this to find missing part numbers, quantities, or slang terms that are absent from the spatial grid.
    - Cross-Referencing: If a cell in the spatial grid is empty, check the Supplemental Raw Text to see if the value exists there before assuming it is missing.

CRITICAL: For every step, identify:
- The `procedure_id` it belongs to.
- The `step_id`.
- The `instruction_text` (the full verbatim text exactly as it appears in the document).
- The `action_verb` (the core task being performed).
- Any `tooling` and `consumables` (materials like sealants, epoxies).
- Any safety `hazard_class` designations. If none apply, leave null.
- Any `required_cert` (Personnel authorizations). If none apply, leave null.
- Compliance `standard_ref` (e.g. ISO-9001, MIL-STD).
- Whether it `is_value_added` and `is_safety_critical` based on the strict limits above.
- The `process_category` of the fundamental physics.
- The chain-of-thought `justification`.
- Any explicit `figure_references` (e.g., 'Figure 3', 'Fig. 12A'). Only extract resolvable identifiers, never vague references.
- Any `estimated_duration_minutes` (e.g., cure times, labor time).
