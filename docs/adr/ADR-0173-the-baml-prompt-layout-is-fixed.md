# ADR-0173 — the BAML prompt layout is fixed

**Status:** accepted
**Date:** no ruling date is recorded; carried in `AGENTS.md` as standing guidance · recorded
2026-11-18
**Deciders:** `AGENTS.md` §Extension Patterns 2, this repo's standing guidance — no individual
ruling is on record
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:73-77` (§Extension Patterns, "Adding a New Domain", step 2); the measured
departures from it at `baml_src/sustainment.baml:139-144` and `:214-222` — long code comments,
which are the **only** written statement of those two rulings before this record
**Related:** [ADR-0104](ADR-0104-a-new-domain-is-a-schema-and-a-plugin.md) (the schema-and-plugin
route this layout is step 2 of),
[ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md) (where the
instructions text itself comes from),
[ADR-0176](ADR-0176-tables-become-markdown-grids.md)

## Context

A BAML function assembles one request out of four things: who the model is and what it is for,
the document text, the dynamic instructions loaded from `prompts/`, and the output schema. The
order they appear in is not cosmetic. A long document in the middle of a prompt pushes whatever
precedes it far from the generation point, and the model weights the end of its context more
heavily — so instructions placed before a few thousand lines of extracted text are instructions
the model has largely stopped attending to by the time it answers.

Without a house order, each new domain picks one, and a recall regression in domain four looks
like a prompt-wording problem when it is a prompt-*position* problem. Nothing about the
extracted values says which it was.

A second, sharper failure lives on the multimodal functions, and it is not about attention at
all: BAML splits a prompt into content blocks at image boundaries, so text placed after an image
yields `[text, image, text]`. Measured — vLLM's gemma multimodal template fails to place the
image token in that shape (`Failed to apply prompt replacement for mm_items['image']`, a litellm
500), while Ollama tolerates it. Layout there is a hard compatibility constraint.

## Decision

**Every BAML extraction prompt follows one fixed section layout, and a departure from it is
justified in a comment at the function.**

The house layout, `AGENTS.md:74-77`:

1. Role / task definition
2. `### DOCUMENT TEXT ###` — the content
3. `### INSTRUCTIONS ###` — the dynamic `system_instructions`
4. `### OUTPUT FORMAT ###` — `{{ ctx.output_format }}`

Two measured departures are ruled in, not drifted into:

- **The image block is last.** `baml_src/sustainment.baml:139-144`: image-last yields a clean
  `[text, image]` that both backends accept — *"Do NOT move `ctx.output_format` below the
  image."* The same comment records that an image in a **system** turn fails on vLLM and is
  tolerated by Ollama, so the image rides a user turn.
- **A function returning a bare `string` omits `### OUTPUT FORMAT ###` entirely.**
  `baml_src/sustainment.baml:214-222`, for `TranscribePage` (`:224`) and, by the same reasoning,
  `ReadRegion` (`:258-260`, `:262`). `ctx.output_format` renders the schema of the return type;
  a bare string has no fields, so it renders to the **empty string**. Rendering the actual
  request showed the user turn carrying a `### OUTPUT FORMAT ###` heading over nothing,
  immediately before the image — *"a dangling section at best, and at worst an invitation for
  the model to try to satisfy an empty format spec, directly against this prompt's own 'plain
  text only' rule."* Measured, not assumed.

## Consequences

- A new domain's prompt is assembled the same way as the existing ones, so a recall change
  between domains is a wording question rather than a layout question.
- **The ruling and the code disagree on where the instructions go, and the status line is the
  code's.** Measured at the pin, all nine typed-return functions
  (`baml_src/core.baml:13`, `compliance.baml:13`, `maintenance.baml:40`, `manufacturing.baml:61`,
  `sustainment.baml:74`, `:108`, `:172`, `:284`, `training.baml:28`) place
  `{{ system_instructions }}` **first**, with no `### INSTRUCTIONS ###` heading, then — where
  they carry one — `### DOCUMENT TEXT ###`, then `### OUTPUT FORMAT ###`. That is
  role-and-instructions → document → format, not the documented role → document → instructions →
  format. (`sustainment.baml:108` and `:172` take a grid and images rather than document text and
  carry no `### DOCUMENT TEXT ###` heading at all.) Only the two
  vision string functions use the `### INSTRUCTIONS ###` heading at all (`sustainment.baml:228`,
  `:266`). The row belongs in [DEBT.md](DEBT.md).
- So the recency-bias mitigation the rule asks for — instructions *after* the document text — is
  **not what any extraction prompt in this tree does today**. The status is `accepted`: ruled and
  in force as guidance, with the implementation absent. A reader comparing `AGENTS.md` against
  `baml_src/` will find the mismatch; this record is where it is named rather than discovered.
- No measurement is recorded for the recency-bias claim itself. The two departures above *are*
  measured; the base ordering is reasoned.
- The vision exceptions cost uniformity: two functions in `sustainment.baml` look wrong against
  the house rule and are not, which is why their comments are long and why they are cited here.

## Alternatives considered

- **Let each domain choose its own layout.** Rejected by `AGENTS.md:73` — the rule exists to make
  prompts comparable across domains.
- **Keep `### OUTPUT FORMAT ###` on the string-returning vision functions for uniformity.**
  Rejected at `baml_src/sustainment.baml:214-222` on a rendered-request measurement: the heading
  stood over an empty string.
- **Put the image first, or interleave text after it.** Rejected at `:139-144` on backend
  behaviour, not preference: vLLM's gemma template fails on `[text, image, text]`.
- **Bring the seven extraction prompts into line with the documented order.** Not recorded as
  considered or declined anywhere in the tree. It would be a change to every prompt's effective
  wording position at once, which is a measurement-bearing change for the corpus gate
  ([ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md)), not a tidy-up.
