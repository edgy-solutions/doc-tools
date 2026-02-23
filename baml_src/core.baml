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

function ExtractOutline(document_text: string) -> Outline {
  client Ollama
  prompt #"
    Analyze the following document text and extract the hierarchical outline (Table of Contents).
    Identify sections, their levels, and titles.
    
    CRITICAL: You must identify the 'start_page' for every section. 
    Look for page numbers listed in the Table of Contents or infer them from page markers in the text (e.g. 'Page 5').
    If the end page is implicit (the start of the next section), you may leave end_page null or estimate it.

    Document Text:
    {{ document_text }}

    {{ ctx.output_format }}
  "#
}
