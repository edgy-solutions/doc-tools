enum InspectionType {
  @@dynamic
}

enum MaintenanceLevel {
  @@dynamic
}

class MaintenanceStep {
  procedure_id string @description("The parent maintenance procedure this step belongs to")
  step_id string @description("The specific step identifier")
  instruction_text string @description("The full, verbatim raw text of the step from the document.")
  action_verb string @description("The concrete maintenance action, e.g. 'Remove', 'Install', 'Inspect', 'Lubricate', 'Torque'")
  tooling string[] @description("List of tools required, e.g. ['Torque Wrench', 'Multimeter']. If missing, empty list.")
  consumables string[] @description("Consumable materials, e.g. ['MIL-PRF-81322 Grease', 'Loctite 242']. If missing, empty list.")
  hazard_class string? @description("Safety hazard classification. If none, leave null.")
  required_cert string? @description("Personnel certification requirement. If none, leave null.")
  standard_ref string? @description("e.g. 'TM 9-1005-317-23'. If none, leave null.")
  inspection_type InspectionType? @description("Type of inspection if this is an inspection step. If not an inspection, leave null.")
  maintenance_level MaintenanceLevel? @description("Organizational, Direct Support, or Depot level. If unclear, leave null.")
  is_safety_critical bool @description("True if the step involves high-voltage, explosive ordnance, load-bearing components, or flight-critical systems.")
  torque_spec string? @description("Extract any torque specifications mentioned (e.g., '15 ft-lbs', '20 Nm'). If none, leave null.")
  justification string @description("A 1-sentence explanation of why the safety-critical flag was chosen.")
  estimated_duration_minutes int? @description("Extract any mentioned time constraints or labor durations. If none, leave null.")

  // Hook 1: Military & Industry Standards
  military_and_industry_standards string[] @description("Extract formal standards: Military (MIL-, TM-, TM 9-*, FM-), Industry (SAE-, ANSI-, ISO-). Normalize to use a single hyphen between prefix and number. Return empty array if none.")

  // Hook 2: Part Numbers
  internal_part_numbers string[] @description("Extract internal part numbers, NSNs, or drawing numbers explicitly mentioned. Strip prefixes; return the alphanumeric identifier.")

  // Hook 3: Figure/Image References
  figure_references string[] @description("Extract ONLY explicit figure, image, graphic, or drawing identifiers referenced in this step. Valid examples: 'Figure 3', 'Fig. 12A', 'Graphic 7'. Extract the identifier only (e.g., '3', '12A', '7'). Do NOT extract vague references. Return empty array if no explicit figure ID is present.")
}

class MroAugmentation {
  steps MaintenanceStep[]
}

function ExtractMaintenanceProcedures(text: string) -> MroAugmentation {
  client Ollama
  prompt #"
    Analyze the following maintenance technical manual text and extract each discrete maintenance step.

    You are a military maintenance data extraction agent. Your primary objective is to identify procedural steps for equipment repair, inspection, and servicing. Scan the text for removal/installation procedures, inspection intervals, torque specifications, required tools, consumable lubricants/sealants, and safety-critical operations.

    CRITICAL RULES:
    1. Standard Normalization: Standardize all standard references using hyphens (e.g., 'TM 9 1005 317 23' -> 'TM-9-1005-317-23', 'MIL PRF 81322' -> 'MIL-PRF-81322').
    2. Proximity Awareness: Standards are often near phrases like 'per', 'IAW', 'in accordance with', or 'ref'.
    3. Safety Critical: True ONLY for steps involving high-voltage, explosive ordnance, load-bearing structural components, or flight-critical systems.
    4. Figure References: Extract ONLY explicit, resolvable identifiers (e.g., 'Figure 3', 'Fig. 12A'). Never extract vague references like 'see diagram below'.

    For every step, identify:
    - The `procedure_id` it belongs to.
    - The `step_id`.
    - The `instruction_text` (full verbatim text).
    - The `action_verb` (the core maintenance action).
    - Any `tooling` and `consumables`.
    - Any `hazard_class` designation. If none, leave null.
    - Any `required_cert`. If none, leave null.
    - Any `standard_ref` (e.g., TM, MIL-STD).
    - The `inspection_type` if applicable.
    - The `maintenance_level` if determinable.
    - Whether it `is_safety_critical`.
    - Any `torque_spec` mentioned.
    - The `justification` for the safety classification.
    - Any `estimated_duration_minutes`.
    - Any `military_and_industry_standards`.
    - Any `internal_part_numbers` or NSNs.
    - Any explicit `figure_references`.

    Document Text:
    {{ text }}

    {{ ctx.output_format }}
  "#
}
