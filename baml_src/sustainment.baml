enum ChangeCategory {
    Material
    Process
    Location
    Discontinuation
    Packaging
    Testing
}

class PartImpact {
    affected_mpn string
    replacement_mpn string?
    ltb_date string? @description("Last Time Buy Date in ISO 8601 (YYYY-MM-DD)")
}

class SustainmentNotice {
    doc_id string @description("The PCN/PDN number, e.g., 23-002")
    doc_type string @description("PCN or PDN")
    pub_date string @description("The notification date")
    mfr string @description("The manufacturer, e.g., Mini-Circuits")
    categories ChangeCategory[]
    summary string @description("High-level impact summary (1-2 sentences)")
    impacted_parts PartImpact[]
}

function ExtractSustainment(doc: string, system_instructions: string) -> SustainmentNotice {
  client LLM
  prompt #"
    {{ system_instructions }}

    ### DOCUMENT TEXT ###
    ---
    {{ doc }}
    ---

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}
  "#
}