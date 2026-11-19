# ADR-0172 — the drift check reads the same env var the runtime serves

**Status:** built
**Date:** no ruling date is recorded; carried in `AGENTS.md` as standing guidance · recorded
2026-11-18
**Deciders:** `AGENTS.md` §Prompt Management 4, this repo's standing guidance — no individual
ruling is on record
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:90` (§Prompt Management 4); `scripts/check_drift.py:7-10` — a code
comment, which is the **only** statement of the *why* in the tree
**Related:** [ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md),
[ADR-0171](ADR-0171-production-does-not-depend-on-langfuse.md),
[ADR-0202](ADR-0202-expect-image-is-read-off-the-pods.md) (the same read-it-back pattern, for
images)

## Context

[ADR-0171](ADR-0171-production-does-not-depend-on-langfuse.md) says prompt changes made in the
GUI must be reconciled back into `prompts/*.md` before they can ship. Something has to notice
when they have not been. That is `scripts/check_drift.py`: it walks `prompts/*.md`, fetches each
name from Langfuse, compares the stripped text, and exits non-zero on any divergence
(`:21-34`, `:42-44`).

The failure this record is about is subtler than "nobody checked". It is **checking the wrong
version**. The runtime, on the opt-in path, serves whatever sits at the label in
`LANGFUSE_PROMPT_LABEL` (`doc_tools/plugins/base.py:114`, default `production`). If the drift
script read its own constant, or a differently-named variable, then CI would compare the
committed file against version A while the live path could serve version B — and the check
would be green over exactly the drift it exists to catch. The guard would have the appearance
of coverage and none of the substance.

## Decision

**The drift check reads the same environment variable the runtime reads, so CI guards exactly
what the live path can serve.**

- `scripts/check_drift.py:10` reads `LANGFUSE_PROMPT_LABEL` with the same `production` default
  as `base.py:114`. The comment at `:7-9` states the requirement — *"The label checked here MUST
  match the label the runtime serves on the opt-in Langfuse path … otherwise CI would validate a
  different version than prod could serve"* — and the standing instruction is to keep them
  aligned and not reintroduce a mismatch.
- Divergence **fails the merge**: `sys.exit(1)` with the message to sync the GUI change back to
  git before merging (`:42-44`).
- An **unfetchable** prompt counts as drift, not as a pass (`:38-40`). A prompt that exists in
  the repo but not yet under the label is therefore reported, rather than skipped.
- A missing `prompts/` directory is itself a failure (`:17-19`).

## Consequences

- The check cannot be green on a label the runtime does not use. The alignment is one line in
  each file, and both lines are cited here so a future edit to either can be checked against the
  other.
- **The ruling and the wiring disagree, and the disagreement is about where it runs.** The
  script is implemented and would fail a merge — but measured at the pin,
  `.github/workflows/build-container.yml` is this repository's only workflow
  ([ADR-0200](ADR-0200-a-stacked-pr-runs-no-ci-gate.md)) and **no step in it invokes
  `check_drift.py`**. `AGENTS.md:90` and `README.md:362` both describe it as running in CI and
  failing the merge; nothing fails a merge today. Recorded on 2026-09-29 in the same terms. The
  row belongs in [DEBT.md](DEBT.md).
- The practical consequence of that gap: a pod on `PROMPT_SOURCE=langfuse` could serve an older
  prompt than the repo's, and the merge that should have caught it passes. The default of `file`
  ([ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md)) is what keeps this
  from being an active production hazard — the structural protection is the default, not the
  check.
- Because an unfetchable prompt is drift, adding a new prompt file makes the script red until
  that prompt exists in Langfuse under the label. Observed 2026-09-26 when a grid-columns prompt
  was added. With the script unwired this is currently a local inconvenience rather than a
  blocked merge, which is precisely why the gap is easy to leave open.
- The script talks to Langfuse, so it needs credentials to run at all. Any wiring of it into a
  workflow inherits that requirement, and the credential is referenced by variable name only
  ([ADR-0205](ADR-0205-a-length-and-a-hash-prefix-never-a-value.md)).

## Alternatives considered

- **Hard-code the label in the script.** Rejected by the comment at `:7-9`: that is the
  mismatch the decision exists to prevent.
- **Compare against every label rather than the served one.** Not recorded as considered. It
  would turn the check from "can production serve something we have not committed?" into a
  broader inventory question, and the first is the one the GitOps route needs.
- **Treat an unfetchable prompt as a pass rather than as drift.** Not recorded as considered,
  and it would reopen the gap for the commonest case — a prompt that exists in the repo and
  nowhere else.
- No alternative is recorded for the wiring gap itself; `AGENTS.md` and `README.md` both assume
  the step exists.
