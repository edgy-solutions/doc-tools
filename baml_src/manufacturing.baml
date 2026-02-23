class ManufacturingStep {
  action string @description("The concrete action to take, e.g. 'Tighten bolt'")
  tooling string[] @description("List of tools required, e.g. ['Wrench', 'Torque'] If missing, empty list.")
  standard_ref string? @description("e.g. 'ISO-9001'. If none, leave null.")
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
    Extract the sequenced manufacturing steps (actions, required tooling, and compliance standard references).
    Also, generate a strategic assessment assigning a proprietary_score (0 to 1.0) and determination of outsourceability.
    
    Document Text:
    {{ text }}

    {{ ctx.output_format }}
  "#
}
