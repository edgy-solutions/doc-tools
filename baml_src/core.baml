class Section {
  title string
  level int
  start_page int @description("The page number where this section begins based on the Table of Contents or page markers")
  end_page int? @description("The page number where this section ends")
  subsections Section[]
}

class Outline {
  sections Section[]
}

function ExtractOutline(document_text: string, system_instructions: string) -> Outline {
  client LLM
  prompt #"
    {{ system_instructions }}

    ### DOCUMENT TEXT ###
    ---
    {{ document_text }}
    ---

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}
  "#
}
