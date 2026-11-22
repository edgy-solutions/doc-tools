# ADR-0189 — The published report is the authority; a fire log is raw

**Status:** measured
**Date:** standing; the leak that fixes the reading rule was measured 2026-11-11 · recorded
2026-11-18
**Deciders:** this lane, after reading a fire log the wrong way and having to disclose it
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** agent memory `corpus-json-is-written-values-fire-logs-are-raw` and
`a-broad-grep-over-the-gate-fire-log-leaks-document-text`; the published artefacts
themselves — `docs/corpus-gate/latest.json` plus 42 dated reports, and **no README** in that
directory — agent memory, which was the **only** written statement of this rule before this
record
**Related:** [ADR-0180](ADR-0180-raw-verdicts-are-advisory.md) (raw versus written),
[ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md),
[ADR-0184](ADR-0184-a-red-line-says-which-fires-declared.md),
[ADR-0205](ADR-0205-a-length-and-a-hash-prefix-never-a-value.md),
[`docs/arch/components/corpus-gate.md`](../arch/components/corpus-gate.md)

## Context

A fire writes two very different things.

The **published report** — `docs/corpus-gate/latest.json`, committed by the gate run itself
through `scripts/pcn_gate_publish.py` onto a branch with a standing pull request, plus the
dated reports beside it — carries `verdict`, `strict_verdict`, `blocking`, `exempted`,
`declined`, the per-fire totals, the rates with their denominators and `measured_image`.
Those are **written values**.

The **fire log** is not a log of results. The gate echoes all three fires' logs to stdout
whenever the verdict is not `pass`, on the assumption that a human wants the detail on a red
— so the log carries prompts and **raw page text**, around 810 KB and ~9,600 lines.

On **2026-11-11 this lane ran a broad `Select-String` over a 9,627-line fire log to find the
verdict, and it printed raw document text into the transcript, including a contact address
and part identifiers.** A transcript is not editable. That is why this record exists and why
it is stated as a disclosure rather than as advice.

There is a second, quieter failure. A claim about **model behaviour** read from the corpus
JSON can be exactly backwards: `written_header` is what survived the trust logic — witness
supply, document-wins, refusal — and what the model returned is in the fire log only. This
lane stated the inverse of the truth in a report before checking.

## Decision

**The published `latest.json` and the dated reports are the authority for any rate or verdict
claim. A fire log is raw, and it is the last resort.**

- Quote the **published report** for a verdict, a rate, a blocking list or a measured digest.
  It is the artefact a merge decision is taken on, and it holds written values only.
- When the log genuinely is needed — per-call timings, crop counters, resample detail, things
  the report does not carry — grep it with **anchored, instrument-owned key names**, never a
  bare word that can match inside a value. The same trap as filtering a pod's environment
  with a case-insensitive word match, which matches inside a **value** and not only a key.
- **Never a broad grep, and never an unfiltered read.** A bare term that happens to appear in
  document text prints document text.
- Keep the log **out of the repo**: the scratchpad only. It is the one copy of the raw fires
  and it must not be committed.
- **Say which instrument a claim comes from.** Raw and written are cited separately and by
  name; a header behaviour attributed to the model is parsed from the fire logs, not inferred
  from the corpus JSON.
- A **Failed** gate Job is a red **verdict**, not a broken run. Reading it as an outage and
  re-firing costs three fires ([ADR-0186](ADR-0186-the-gate-clock-is-off.md)) and answers
  nothing.

## Consequences

- A newcomer's first read is a JSON file, not a cluster and not a log — which is the only
  reading that is both cheap and safe.
- Some questions are simply **not answerable** from the published report, and the cost of
  answering them is a careful, anchored grep of a log in the scratchpad. That cost is
  accepted; a broad grep is not an alternative to it.
- `docs/corpus-gate/` holds 42 published artefacts and no README, so the reading rules live
  here and in [`docs/arch/components/corpus-gate.md`](../arch/components/corpus-gate.md)
  rather than beside the artefacts.
- The publishing branch is **force-rewritten**, so it is fetched with a `+refs/heads/…`
  refspec; a plain fetch can fail or serve a stale tip.
- A **diagnostic run overwrites the authority report**. A fire taken to answer a side
  question can destroy the artefact a merge decision rests on, which is one more reason the
  published report is read before anything is fired.
- A recompute against a stored verdict is evidence **only while it reproduces that verdict**:
  a replay that cannot reproduce the published verdict is void, and a recompute is never a
  fire ([ADR-0183](ADR-0183-declined-is-the-third-bucket.md)).

## Alternatives considered

- **Stop echoing the fire logs on a red.** Not taken, and not this lane's to take alone: the
  echo is what makes a red diagnosable at all, because the per-fire artefacts live inside a
  pod that dies with the Job. The mitigation chosen instead is a better blocking line
  ([ADR-0184](ADR-0184-a-red-line-says-which-fires-declared.md)), so that the common
  questions are answered from the report.
- **Redact the echo at the producer**, the way `tools/drift_check.py` redacts on a name match.
  **Not** recorded as considered for the gate, and it is the obvious shape of a real fix: the
  present rule is a discipline, and a discipline is what failed on 2026-11-11.
- **Commit the fire log beside the report so it can be read without a cluster.** Rejected: it
  would put raw document text in the repository permanently.
