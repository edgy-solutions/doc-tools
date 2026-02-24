class ManufacturingStep {
  procedure_id string @description("e.g. 'PROC-04' - The parent procedure this step belongs to")
  step_id string @description("e.g. '3.2.1' - The specific step identifier")
  action_verb string @description("The concrete action to take, e.g. 'Tighten bolt'")
  tooling string[] @description("List of tools required, e.g. ['Wrench', 'Torque'] If missing, empty list.")
  consumables string[] @description("Consumable materials, e.g. ['Sealant MIL-S-81733']. If missing, empty list.")
  hazard_class string? @description("Explosives Safety Hazard, e.g. '1.1D'. If none, leave null.")
  required_cert string? @description("Quality/Personnel requirement, e.g. 'QC Inspector'. If none, leave null.")
  standard_ref string? @description("e.g. 'ISO-9001'. If none, leave null.")
  is_value_added bool @description("True if the step physically transforms the product. False if it is just an inspection, verification, QC check, or movement.")
  process_category string @description("Classify the fundamental physics (e.g., 'Curing', 'Machining', 'Chemical Coating', 'Assembly', 'Non-Destructive Testing').")
  estimated_duration_minutes int? @description("Extract any mentioned time constraints, cure times, or labor durations. If none, leave null.")
}

class StrategicAssessment {
  proprietary_score float @description("0.0 (Common) to 1.0 (Secret Sauce). Score based on how specific/complex the process is.")
  outsourceable bool @description("If it requires secret sauce or highly sensitive MAT, true. Default to false if unclear.")
}

class MatAugmentation {
  steps ManufacturingStep[]
  assessment StrategicAssessment
}

function ExtractWorkInstructions(text: string) -> MatAugmentation {
  client Ollama
  prompt #"
    Analyze the following Munitions Acceleration & Manufacturing (MAT) document text.
    Extract the sequenced manufacturing procedures and steps.
    
    CRITICAL: For every step, identify:
    - The `procedure_id` it belongs to.
    - The `step_id` (e.g. 1.2.4).
    - The `action_verb` (the core task being performed).
    - Any `tooling` and `consumables` (materials like sealants, epoxies).
    - Any safety `hazard_class` designations (e.g., Class 1.1).
    - Any `required_cert` (Personnel authorizations like 'QC Inspector' or 'Journeyman').
    - Compliance `standard_ref` (e.g. ISO-9001, MIL-STD).
    - Whether it `is_value_added` (physical transformation vs verification/movement).
    - The `process_category` of the fundamental physics.
    - Any `estimated_duration_minutes` (e.g., cure times, labor time).

    Also, generate a strategic assessment assigning a proprietary_score (0 to 1.0) and determination of outsourceability.
    
    Document Text:
    {{ text }}

    {{ ctx.output_format }}
  "#
}
