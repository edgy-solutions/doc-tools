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

function ExtractSustainment(doc: string) -> SustainmentNotice {
  client Ollama
  prompt #"
    Analyze the following manufacturer notice.
    Extract the information strictly into the requested JSON format.
    
    {{ ctx.output_format }}

    DATA HANDLING INSTRUCTIONS:
    - Tables have been converted to Markdown format.
    - Use the column headers to map 'Affected Parts' to their 'Replacements'.
    - Pay close attention to empty cells (e.g., `| |`). If a cell next to a part is empty, there is no replacement or note for that specific part.
    - If part numbers are listed in a dense grid without headers, treat all items in the grid as Affected Parts.

    DOCUMENT TEXT:
    {{ doc }}
  "#
}