// One call per group of at most 8 slides, aligned to the course outline
// (contract v4 section 4.6). The reply is per slide, so TEACHES stays slide-level,
// plus one note per section in the group.

class Concept {
  name string @description("A noun phrase of at most 4 words naming what is taught. Never a sentence.")
  salience float @description("0.0-1.0: how central the concept is to THIS slide.")
  related_terms string[] @description("Other names for this SAME concept: abbreviations, acronyms, synonyms, spelled-out forms. Each a noun phrase of at most 4 words. Not broader or narrower topics. Empty if none.")
}

class SlideConcepts {
  slide int @description("The N of this slide's '=== Slide N ===' marker.")
  concepts Concept[]
  figure_references string[] @description("Explicit figure, diagram, or graphic identifiers referenced in the slide text (e.g., 'Figure 4', 'ICN-12345', 'Diagram 2A'). Do NOT extract vague references like 'see the image below'. Empty if none.")
}

class SectionNotes {
  section string @description("The section title exactly as written in its '=== Section: ... ===' marker.")
  summary string? @description("2-3 sentences: what this section of the course teaches.")
  objectives string[] @description("What a learner can do after this section, each starting with a verb. Empty if the section teaches nothing.")
}

class SectionAugmentation {
  slides SlideConcepts[] @description("Exactly one entry per '=== Slide N ===' marker, in order, including slides that teach nothing.")
  sections SectionNotes[] @description("Exactly one entry per '=== Section: ... ===' marker, in order.")
}

function ExtractSectionConcepts(section_text: string, system_instructions: string) -> SectionAugmentation {
  client LLM
  prompt #"
    {{ system_instructions }}

    ### HOW THE TEXT IS LAID OUT ###
    The text below is consecutive slides of one course. A line "=== Section: <title> ===" opens a
    section of the course outline; a line "=== Slide N ===" opens slide N. Extract concepts and
    figure references for EACH slide on its own, and write notes for EACH section.

    ### CONCEPT NAMES ###
    A concept name is a noun phrase of at most 4 words that names the thing taught:
    "Centrifugal Pump", "Phase Angle Separation", "Lockout/Tagout".
    It is never a sentence, a claim, a definition or an instruction:
    "Phases are 120 degrees apart" is wrong; "Phase Angle Separation" is right.
    The same rule applies to every related term.

    ### DOCUMENT TEXT ###
    ---
    {{ section_text }}
    ---

    ### OUTPUT FORMAT ###
    {{ ctx.output_format }}
  "#
}
