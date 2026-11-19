# ADR-0171 — production must not depend on the live Langfuse path

**Status:** accepted + built
**Date:** no ruling date is recorded; carried in `AGENTS.md` as standing guidance · recorded
2026-11-18
**Deciders:** `AGENTS.md` §Prompt Management 3, this repo's standing guidance — no individual
ruling is on record
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:89` (§Prompt Management 3); the mechanism at
`doc_tools/plugins/base.py:85-95` (the lazily-constructed client) and `:111-132` (the switch)
**Related:** [ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md),
[ADR-0172](ADR-0172-the-drift-check-reads-the-runtimes-own-var.md),
[ADR-0175](ADR-0175-proprietary-prompt-text-is-not-committed.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md),
[ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md)

## Context

There is a second prompt source: `PROMPT_SOURCE=langfuse` fetches the text live from the GUI at
the label named by `LANGFUSE_PROMPT_LABEL` (default `production`), falling back to the canonical
file if the service is unreachable (`base.py:113-126`). It exists because an SME tuning wording
wants a loop measured in seconds, not in image builds.

That path is useful and it is also a trapdoor. In `langfuse` mode the text the model receives
can change **without any commit, any image rebuild and any pin move**. Nothing in a run's own
output records which mode produced it. So a corpus score taken under `langfuse` is a statement
about whatever a label pointed at that afternoon, not about the pinned image — and it is
indistinguishable, in the report, from one that is.

This is not hypothetical. Measured 2026-09-28: a peer's helm revision added `LANGFUSE_HOST`,
`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to the sandbox release about thirty seconds
after a roll. No harm followed, because `PROMPT_SOURCE` was still `file` and the client is never
constructed in that mode — but the same edit one key wider would have voided the gate silently.
(The variables are named here; no value of any of them appears in this record.)

## Decision

**Production depends on the committed file, never on the live Langfuse path. A prompt change
ships engineer-via-PR.**

- The route is: edit in the GUI (dev) → reconcile into `prompts/*.md` via PR → CI drift check
  ([ADR-0172](ADR-0172-the-drift-check-reads-the-runtimes-own-var.md)) → image build → deploy.
  `AGENTS.md:89`.
- `langfuse` is an **opt-in** SME/dev path, never the deployed configuration.
- The dependency is removed structurally, not by convention: the client is a lazy property
  (`base.py:85-95`), so in `file` mode it is never instantiated and the workload carries no
  Langfuse credential requirement and no network call on the extraction path. Pinned by
  `tests/test_prompt_source.py:53`.
- Where the opt-in path *is* used, an outage degrades to the canonical file rather than failing
  (`base.py:120-126`), pinned by `tests/test_prompt_source.py:113`.
- A measurement harness pins the mode itself rather than trusting the environment:
  `scripts/pcn_corpus_run.py:69-71` sets `PROMPT_SOURCE=file` before importing `doc_tools`, with
  the comment *"The prompt must come from the committed file, not from whatever a Langfuse label
  points at today, or the measurement is not reproducible"*, and drops the two Langfuse key
  variables at `:67-68`.

## Consequences

- A score can be attributed to a pin, and a prompt change is reviewable before it can affect
  one.
- **`PROMPT_SOURCE` pointing at Langfuse text voids a corpus measurement.** The measured
  artefact is then not the committed prompt, so the run cannot be cited as evidence for the pin
  under which it was taken — and because the mode is absent from the run's output, a report
  pasted from such a run reads exactly like a valid one. Treat `langfuse` as a **stop
  condition** for any measurement meant to gate a re-ingest or a roll.
- The mode must be read **out of the running pod, not out of the chart**: a peer can add env
  after a roll, as the 2026-09-28 observation shows. `scripts/pcn_gate_prefire.py:17` records
  `PROMPT_SOURCE` as part of the measured environment for exactly this reason.
- The prompt path has **two** distinct silent failures, and they compose: a wrong source (this
  record) and an absent file ([ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md)).
  Neither is visible in a score.
- The cost is iteration speed. An SME wording change cannot reach production without a PR and
  an image build, which is the price of the attribution.
- Keeping the opt-in path at all means the trapdoor stays open; the mitigation is the harness
  pinning the mode and the operator reading it off the pod, not the removal of the mode.

## Alternatives considered

- **Delete the Langfuse source entirely.** Not taken: `AGENTS.md:88` keeps it deliberately as
  the SME/dev iteration path. Deleting it would move hot-tuning into uncommitted local edits,
  which is the same drift with no drift check available at all.
- **Serve the GUI label in production and rely on the drift check to keep it honest.** Rejected
  by `AGENTS.md:89` outright. It also inverts the guarantee: the check would then be the only
  thing standing between a label edit and a changed extraction, and it runs at merge time, not
  at call time.
- **Record the resolved mode and prompt refs in the run output so a `langfuse` run is at least
  identifiable.** Half-present and not recorded as a decision: `prompt_refs`
  (`base.py:168-172`) already carries `lf:<version>` or `sha1:<12 hex>` per prompt for
  telemetry, but no corpus report field at the pin asserts the mode. Not recorded as considered;
  noted here so the gap is visible rather than inferred.
