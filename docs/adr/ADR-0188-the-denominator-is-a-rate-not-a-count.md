# ADR-0188 — The corpus denominator is a rate over ten notices, not a count

**Status:** measured
**Date:** the current denominator was set 2026-10-29 (PR #191); the reading rule is
standing · recorded 2026-11-18
**Deciders:** a property of the measurement, recorded by this lane after a count was quoted
as if it were comparable
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** agent memory `pcn-corpus-denominator-is-898-not-896`; the published reports under
`docs/corpus-gate/` (`latest.json` carries `denominator` on every rate and the `corpus` block
on every score); the denominator is owned by `score_run` in `scripts/pcn_score.py`, summing
ground truth, and declared in `scripts/pcn_ground_truth.json` — agent memory, which was the
**only** written statement of this rule before this record
**Related:** [ADR-0190](ADR-0190-ground-truth-ti-page-two-is-devices-only.md) (the ruling
that produced the current figure), [ADR-0129](ADR-0129-a-customer-part-number-is-never-an-affected-part.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md),
[ADR-0222](ADR-0222-the-corpus-validation-is-the-authority.md)

## Context

The parts figure in a corpus-gate report is a fraction, and its denominator has moved five
times: **924, 898, 896, 522, 512**. Every one of those moves was legitimate, and a score
measured against one is **not comparable** to a score measured against another.

Quoted as a bare count — "893 parts" — a figure therefore says nothing, and it has already
inverted a conclusion here: a count that fell because the denominator fell reads as a
regression, and a count that rose because the denominator rose reads as an improvement.

The current figure is **512 over ten documents / ten scored entries**, re-labelled from 522
on 2026-10-29 (PR #191). Ten notices is also the denominator of every *rate* the report
carries: `latest.json` prints `"denominator": 10` on `needs_review`, `crops_failed`,
`crops_truncated`, `crops_near_cap`, `crops_row_short` and `text_layer_degraded`, per fire
and aggregated.

## Decision

**Cite the denominator with every figure, and compare rates — never counts.**

- The corpus is **ten notices**. A parts score is `n / 512` at this pin; a run-level rate is
  `n / 10`.
- A **rate compares across a denominator move and a count does not.** The 522 → 512 move is
  the clean case: ten entries were re-labelled from affected parts to customer aliases, so
  numerator and denominator fell together by the same ten. A rate at 512 is comparable to one
  at 522; a count is not.
- Reports dated before a move **keep their own denominator and are not restated**. The
  erratum lives in the report.
- **Four kinds of move are permitted, and they look different.** Anything else is a tune:
  1. a **correction** — a count in ground truth was wrong (896 → 898, which *lowered* the
     score);
  2. a **widening** — documents added, which raises the denominator by exactly the new
     entries' counts and says nothing about the numerator (898 → 924);
  3. a **dedup** — the same bytes were scored twice (924 → 522: two filenames are
     byte-identical, so one document's parts were counted twice);
  4. a **re-label** — the same cells counted as something else (522 → 512).
- **A ground-truth edit that raises the score is the suspicious direction.** The correction
  and the dedup both pass that test; the dedup because it removes a duplicate numerator as
  well as a duplicate denominator.
- The load-bearing edit in a dedup is the `notices{}` deletion, not the targets row, because
  `score_run` owns the denominator by summing ground truth (`scripts/pcn_score.py:629`).
  `check_corpus_enumeration` (`scripts/pcn_corpus_run.py:522`, run at startup) asserts
  `gt_parts == distinct_parts` so that a report cannot disagree with itself.

## Consequences

- A denominator move has a **live CI consequence**, measured 2026-11-01: the guard refuses a
  committed report measured against the old denominator, with a message naming both figures,
  and `corpus-gate` is the single required check on `main`. A non-chart PR still merges, but
  the next pin bump or `charts/` change is blocked until a fresh in-cluster report measuring
  the new figure is committed.
- **A fresh fire of the current pin cannot lift that red.** The gate scores against the
  ground truth baked into the **image**, not the tree, so an image predating the re-label
  re-emits the old figure. Only an image containing the ground-truth change can measure the
  new one, which makes the **pin bump the fix and not its beneficiary** — and the pre-roll
  report must land in the same PR as the pin
  ([ADR-0185](ADR-0185-pre-roll-checked-false-is-by-design.md)).
- A figure quoted without its denominator is not reusable, and the `corpus` block in
  `latest.json` exists so that nobody has to reconstruct it.
- The customer aliases score on their own denominator of **21** (the `customer_aliases` block
  in `latest.json`, two notices) and are **advisory** — never
  part of the parts verdict, contributing to neither `blocking` nor `exempted`, so a red
  there cannot earn an exemption.
- Scored entries equalled distinct documents for the first time at the dedup. A corpus where
  scored entries exceed documents is a corpus where some bytes are counted twice.

## Alternatives considered

- **Restate historical reports against the current denominator.** Rejected: a report is the
  artefact a merge decision was taken on, and rewriting its numbers loses what was decided.
  The erratum goes in the report instead.
- **Freeze the denominator so figures stay comparable.** Rejected by the four kinds of move:
  a frozen denominator would mean refusing a correction, a widening, a dedup or a re-label —
  each of which makes the measurement *more* truthful. A conflated ground truth is worse than
  a wrong one: at 522 it scored a ten-part fabrication as perfect, because the instrument had
  been taught the fabrication.
- **Quote counts and let the reader infer the denominator.** This is the behaviour the rule
  exists to stop; it is not an alternative so much as the failure.
