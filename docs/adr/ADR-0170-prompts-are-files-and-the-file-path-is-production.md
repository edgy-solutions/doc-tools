# ADR-0170 — prompts are files in the repo, and the file path is production

**Status:** built
**Date:** no ruling date is recorded; carried in `AGENTS.md` as standing guidance · recorded
2026-11-18
**Deciders:** `AGENTS.md` §Prompt Management, this repo's standing guidance — no individual
ruling is on record
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:84-88` (§Prompt Management 1–2); implemented at
`doc_tools/plugins/base.py:97-132` (`_get_dynamic_prompt`) and `:134-166`
(`_load_prompt_from_file`)
**Related:** [ADR-0171](ADR-0171-production-does-not-depend-on-langfuse.md) (the half of this
that says production must not *drift* off the file),
[ADR-0172](ADR-0172-the-drift-check-reads-the-runtimes-own-var.md),
[ADR-0175](ADR-0175-proprietary-prompt-text-is-not-committed.md),
[`docs/arch/components/extraction-pipeline.md`](../arch/components/extraction-pipeline.md)

## Context

Extraction behaviour in this repo is mostly prompt behaviour. A BAML function supplies the
schema and the layout; the text that decides what the model looks for arrives as
`system_instructions`. If that text lives inside the BAML source, or inside a GUI, then two
things stop being true at once: a code review can no longer see what changed, and a score can
no longer be attributed to a commit.

The concrete failure is a measurement that cannot be defended. A corpus run is cited as
evidence for a pin. If the prompt text came from somewhere other than the pinned image, the run
measured something the pin does not contain, and the citation is void — with nothing in the
run's own output to say so.

Measured at the pin: twelve canonical prompt files exist under `prompts/`, one per BAML entry
point plus the two vision prompts, and `PROMPT_SOURCE` defaults to `file`
(`doc_tools/plugins/base.py:111`).

## Decision

**A prompt is a git-committed Markdown file under `prompts/`, and the file path is the
production path.**

- Prompts are decoupled from BAML code. `baml_src/*.baml` declares the schema and the layout
  ([ADR-0173](ADR-0173-the-baml-prompt-layout-is-fixed.md)); the instruction text is loaded at
  call time from `prompts/{prompt_name}.md`.
- `PROMPT_SOURCE=file` is the **default** (`base.py:111`) and the intended production
  configuration. An unknown value also resolves to `file`, with a warning (`base.py:128-131`).
- In `file` mode Langfuse is never contacted. The client is a lazily-constructed property
  (`base.py:85-95`), so the default path needs no Langfuse credentials and no network.
- The canonical template is hashed **before** variable substitution and stamped as a prompt ref
  (`base.py:157-160`), so a trace names which reviewed prompt version produced an extraction
  rather than which rendered string did.
- Pinned by `tests/test_prompt_source.py:53` (default is file and never builds the client),
  `:73` (unknown value falls back to file) and `:125` (a missing canonical file raises).

## Consequences

- What runs is exactly what was merged. A prompt change is a reviewable diff and lands by the
  ordinary PR route; a score is attributable to a commit.
- **A missing prompt file is a configuration failure that can still read as a successful run
  with nothing extracted.** This is the sharpest cost of making the file path production:
  prompts resolve by *relative* path, so the process working directory decides whether they
  exist. Measured 2026-09-24 — the corpus harness launched from the wrong directory: three
  notices returned 0 parts while a fourth printed 402/402 (its tier-1 text-layer path needs no
  prompt), nothing raised, nothing exited non-zero, and the only reliable tell was wall time,
  0.7s against 33.5s for a real vision call.
- The repair is partial at the pin, and this is **live, not fixed**. The loader raises a
  distinct `PromptUnavailableError` (`base.py:10-22`, `:152`), and the sustainment path declares
  `REQUIRED_PROMPT_FILES` (`doc_tools/plugins/sustainment.py:706-712`), validates them once up
  front (`:1699`), and re-raises ahead of each broad handler (`:764-772`, and at `:2236`,
  `:2255`, `:2296`) — pinned by `tests/test_prompt_unavailable_hard_fail.py`. **The other
  plugins have no such carve-out.** On the compliance path the error is caught by the broad
  `except Exception` at `doc_tools/plugins/compliance.py:66-78`, which substitutes a mock
  `ERROR-FALLBACK` rule and returns normally; the manufacturing and maintenance global passes
  catch it at `manufacturing.py:168-172` and `maintenance.py:117-122` and fall back to a legacy
  loop that re-reads the same file, so it surfaces there only incidentally. The row belongs in
  [DEBT.md](DEBT.md).
- The failure is recorded in `review_reasons` / `doc_flags`, but it is invisible in the
  harness's per-notice flag columns, which are vision statistics and print as zeros when the
  failure happened before any vision call.
- A prompt file is a deployment artefact. It must be present in the image at the path the
  plugin asks for, relative to the process working directory — `/app` in the pod.

## Alternatives considered

- **Keep the prompt text inside the BAML source.** Rejected by `AGENTS.md` §Prompt Management 1:
  the text then changes only through a `baml-cli generate` cycle, and the schema diff and the
  wording diff become one diff.
- **Serve the prompt from the GUI as the production source.** That is the opt-in path, not the
  default, and it is refused for production by
  [ADR-0171](ADR-0171-production-does-not-depend-on-langfuse.md).
- **Resolve prompts by absolute path, or package them as module data, so the working directory
  cannot break them.** Not recorded as considered. The recorded repair was a distinct exception
  plus up-front validation, which names the failure rather than removing it.
