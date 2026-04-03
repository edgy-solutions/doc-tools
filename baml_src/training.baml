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

function ExtractConcepts(slide_text: string) -> SlideAugmentation {
  client Ollama
  prompt #"
    Analyze the following text from a training slide.
    Extract key technical concepts taught, define them briefly, and identify learning objectives.
    Also provide a brief summary of the slide.
    
    IMPORTANT: For each concept, assign a "salience" score (0.0 to 1.0) indicating how central it is to this slide:
    - 1.0 = The primary topic or main concept being taught
    - 0.7 = Important supporting concept, explained in detail
    - 0.5 = Related concept mentioned substantively
    - 0.3 = Briefly mentioned or referenced
    - 0.1 = Appears in footer, header, sidebar, or not directly relevant to the content
    
    Focus on the actual slide content, not headers/footers. Generic terms like "Safety" in a footer should get low salience.
    Also extract any explicit figure, diagram, or graphic references (e.g., 'Figure 4', 'Diagram 2A'). Only extract resolvable identifiers, never vague references.

    Slide Text:
    {{ slide_text }}

    {{ ctx.output_format }}
  "#
}
