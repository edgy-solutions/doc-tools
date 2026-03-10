class ManufacturingStep {
  procedure_id string @description("The parent procedure this step belongs to")
  step_id string @description("The specific step identifier")
  action_verb string @description("The concrete action to take, e.g. 'Tighten bolt'")
  tooling string[] @description("List of tools required, e.g. ['Wrench', 'Torque'] If missing, empty list.")
  consumables string[] @description("Consumable materials, e.g. ['Sealant MIL-S-81733']. If missing, empty list.")
  hazard_class string? @description("Explosives Safety Hazard. If none, leave null.")
  required_cert string? @description("Quality/Personnel requirement. If none, leave null.")
  standard_ref string? @description("e.g. 'ISO-9001'. If none, leave null.")
  is_value_added bool @description("True ONLY if the step physically transforms the product (e.g., machining, curing, applying sealant). False if it is an inspection, movement, or waiting.")
  is_safety_critical bool @description("CRITICAL: True if the step involves static grounding, explosive hazard mitigation (Class 1.1, 1.3), environmental safety, or regulatory sign-offs. False otherwise.")
  process_category string @description("The functional category of the manufacturing process.")
  justification string @description("A 1-sentence explanation of why the value-added and safety-critical flags were chosen.")
  estimated_duration_minutes int? @description("Extract any mentioned time constraints, cure times, or labor durations. If none, leave null.")
  
  // Hook 1: Direct link to DLA PUB LOG
  military_and_industry_standards string[] @description("Extract formal standards mentioned. Look for prefixes: MIL-, MS, AN, NAS, AS, DIN, ASTM. Normalize to remove spaces (e.g., 'MIL PRF 81733' -> 'MIL-PRF-81733', 'MS 20426' -> 'MS20426'). Return empty array if none.")

  // Hook 2: Direct link to Windchill
  internal_part_numbers string[] @description("Extract internal proprietary part numbers, assembly numbers, or drawing numbers explicitly mentioned (e.g., 'PN 99-812', 'Assy 104-B'). Strip the 'PN' prefix; return the alphanumeric identifier.")

  // Hook 3: The Semantic Fallback (For Weaviate)
  material_and_hardware_slang string[] @description("Extract generic nouns for consumables/hardware lacking a specific part number (e.g., 'RTV Silicone', 'Loctite', 'Hex Nut', 'Epoxy'). Used for downstream vector similarity searches against a materials index.")
}

class StrategicAssessment {
  proprietary_score float @description("0.0 (Common) to 1.0 (Secret Sauce). Score based on how specific/complex the process is.")
  outsourceable bool @description("If it requires secret sauce or highly sensitive MAT, true. Default to false if unclear.")
}

class MatAugmentation {
  steps ManufacturingStep[]
  assessment StrategicAssessment
}

function ExtractWorkInstructions(text: string, procedure_id_format: string, step_id_format: string, valid_personnel_roles: string, valid_hazard_classes: string, valid_process_categories: string) -> MatAugmentation {
  client Ollama
  prompt #"
    Analyze the following munitions assembly text and extract each discrete manufacturing step.
    
    You are an aerospace manufacturing data extraction agent. Your primary objective is to identify supply chain database hooks. Scan the text meticulously for Military Standards, Industry Standards, and Internal Part Numbers. Do not hallucinate standards. If a technician uses slang (e.g., 'Zip tie', 'Safety wire'), log it in the slang array so our downstream semantic database can resolve the true specification.

    CRITICAL CLASSIFICATION RULES for `is_value_added` and `is_safety_critical`:
    1. **Value-Added (VA):** The step must physically alter the missile or component. 
       - *Examples of VA:* "Apply 50ml of epoxy", "Torque bolt to 15Nm", "Mate warhead to chassis." -> is_value_added: true
    2. **Non-Value-Added (NVA):** The step is an inspection, test, or movement. 
       - *Examples of NVA:* "Verify torque", "Move pallet to Bay 4", "Inspect for cracks." -> is_value_added: false
    3. **The Safety Exception (Essential NVA):** Some steps do not physically change the product but are strictly required to prevent catastrophic failure or loss of life.
       - *Examples of Safety Critical:* "Attach static grounding strap", "Verify Class 1.1 ESQD limits", "Perform stray voltage test." 
       - For these: `is_value_added: false`, but `is_safety_critical: true`.

    If a step is an inspection that DOES NOT involve explosive safety or high-voltage grounding, it is simply `is_safety_critical: false`.
    
    CRITICAL: For every step, identify:
    - The `procedure_id` it belongs to. This must strictly match this pattern or regular expression: '{{ procedure_id_format }}'. Do not include the action text, just the identifier block.
    - The `step_id`. This must strictly match this pattern or regular expression: '{{ step_id_format }}'. Do not include the action text, just the identifier block.
    - The `action_verb` (the core task being performed).
    - Any `tooling` and `consumables` (materials like sealants, epoxies).
    - Any safety `hazard_class` designations. This MUST be exactly one of the following strings if present: {{ valid_hazard_classes }}. If none apply, leave null.
    - Any `required_cert` (Personnel authorizations). This MUST be exactly one of the following strings if present: {{ valid_personnel_roles }}. If none apply, leave null.
    - Compliance `standard_ref` (e.g. ISO-9001, MIL-STD).
    - Whether it `is_value_added` and `is_safety_critical` based on the strict limits above.
    - The `process_category` of the fundamental physics. This MUST be exactly one of the following strings: {{ valid_process_categories }}.
    - The chain-of-thought `justification`.
    - Any `estimated_duration_minutes` (e.g., cure times, labor time).

    Also, generate a strategic assessment assigning a proprietary_score (0 to 1.0) and determination of outsourceability.
    
    Document Text:
    {{ text }}

    {{ ctx.output_format }}
  "#
}
