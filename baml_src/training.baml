class Concept {
  name string
  description string
  related_terms string[]
  salience float  // 0.0-1.0: How central is this concept? 1.0 = main topic, 0.3 = mentioned briefly
}

class LearningObjective {
  description string
}

class SlideAugmentation {
  concepts Concept[]
  objectives LearningObjective[]
  summary string
  figure_references string[] @description("Extract explicit figure, diagram, or graphic identifiers referenced in the slide text (e.g., 'Figure 4', 'ICN-12345', 'Diagram 2A'). Do NOT extract vague references like 'see the image below'. Return empty array if none.")
}

function ExtractConcepts(slide_text: string, system_instructions: string) -> SlideAugmentation {
  client Ollama
  prompt #"
    {{ system_instructions }}

    ### DOCUMENT TEXT ###
    ---
    {{ slide_text }}
    ---

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}
  "#
}
