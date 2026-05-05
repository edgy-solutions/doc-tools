enum ProcessCategory {
  @@dynamic
}

enum HazardClass {
  @@dynamic
}

enum PersonnelRole {
  @@dynamic
}

class ManufacturingStep {
  procedure_id string @description("The parent procedure this step belongs to")
  step_id string @description("The specific step identifier")
  instruction_text string @description("The full, verbatim raw text of the step from the document.")
  action_verb string @description("The concrete action to take, e.g. 'Tighten bolt'")
  tooling string[] @description("List of tools required, e.g. ['Wrench', 'Torque'] If missing, empty list.")
  consumables string[] @description("Consumable materials, e.g. ['Sealant MIL-S-81733']. If missing, empty list.")
  hazard_class HazardClass? @description("Explosives Safety Hazard. If none, leave null.")
  required_cert PersonnelRole? @description("Quality/Personnel requirement. If none, leave null.")
  standard_ref string? @description("e.g. 'ISO-9001'. If none, leave null.")
  is_value_added bool @description("True ONLY if the step physically transforms the product (e.g., machining, curing, applying sealant). False if it is an inspection, movement, or waiting.")
  is_safety_critical bool @description("CRITICAL: True if the step involves static grounding, explosive hazard mitigation (Class 1.1, 1.3), environmental safety, or regulatory sign-offs. False otherwise.")
  process_category ProcessCategory @description("The functional category of the manufacturing process.")
  justification string @description("A 1-sentence explanation of why the value-added and safety-critical flags were chosen.")
  estimated_duration_minutes int? @description("Extract any mentioned time constraints, cure times, or labor durations. If none, leave null.")
  
  // Hook 1: Direct link to DLA PUB LOG / Industry Specs
  military_and_industry_standards string[] @description("Extract formal standards: Military (MIL-, MS, AN*, NAS*, AS*), Joint Industry (J-STD-*), Electronics (IPC-*), Testing (ASTM-, SAE-, ANSI-, ISO-), Process (NADCAP*). Normalize to use a single hyphen between prefix and number (e.g., 'J STD 001', 'JSTD001' -> 'J-STD-001', 'MIL PRF 81733' -> 'MIL-PRF-81733'). Return empty array if none.")

  // Hook 2: Direct link to Windchill
  internal_part_numbers string[] @description("Extract internal proprietary part numbers, assembly numbers, or drawing numbers explicitly mentioned (e.g., 'PN 99-812', 'Assy 104-B'). Strip the 'PN' prefix; return the alphanumeric identifier.")

  // Hook 3: The Semantic Fallback (For Weaviate)
  material_and_hardware_slang string[] @description("Extract generic nouns for consumables/hardware lacking a specific part number (e.g., 'RTV Silicone', 'Loctite', 'Hex Nut', 'Epoxy'). Used for downstream vector similarity searches against a materials index.")

  // Hook 4: Figure/Image References for Neo4j Figure Nodes
  figure_references string[] @description("Extract ONLY explicit figure, image, graphic, or drawing identifiers referenced in this step. Valid examples: 'Figure 3', 'Fig. 12A', 'Graphic 7', 'Drawing 101-B'. Extract the identifier only (e.g., '3', '12A', '7', '101-B'). Do NOT extract vague references like 'see the diagram below' or 'as illustrated'. Return empty array if no explicit figure ID is present.")
}

class StrategicAssessment {
  proprietary_score float @description("0.0 (Common) to 1.0 (Secret Sauce). Score based on how specific/complex the process is.")
  outsourceable bool @description("If it requires secret sauce or highly sensitive MAT, true. Default to false if unclear.")
}

class MatAugmentation {
  steps ManufacturingStep[]
  assessment StrategicAssessment
}

function ExtractWorkInstructions(text: string, system_instructions: string) -> MatAugmentation {
  client Ollama
  prompt #"
    {{ system_instructions }}

    ### DOCUMENT TEXT ###
    ---
    {{ text }}
    ---

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}
  "#
}
