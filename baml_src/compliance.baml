class ComplianceRule {
  manual_reference string @description("e.g. 'DAFMAN 21-201 Section 4.2' - The source manual or regulatory document reference.")
  rule_type string @description("e.g. 'Safety', 'Throughput', 'Storage', 'Certification' - The category of the compliance rule.")
  applicable_hazard_class string? @description("e.g. '1.1D', '1.3' - The explosives hazard class this rule targets. If none, leave null.")
  target_metric string? @description("e.g. 'Max 5 Units', '< 15 mins' - The quantitative or qualitative metric mandated by the rule.")
  rule_description string @description("A concise summary of what the rule requires.")
}

class ComplianceAugmentation {
  rules ComplianceRule[]
}

function ExtractComplianceRules(text: string, system_instructions: string) -> ComplianceAugmentation {
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
