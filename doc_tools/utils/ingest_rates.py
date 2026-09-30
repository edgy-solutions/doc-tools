"""Aggregate per-document review signals into run-level RATES.

Per-notice logs answer "what happened to THIS document." Nobody reads those logs in
production — the thing that actually gets watched is a rate, and the thing that
actually indicates a regression is that rate RISING run over run. This module turns a
run's per-document records into exactly that: one count/denominator/percentage per
signal, in a form small enough to paste into a dated report or a nightly gate.

PURE ON PURPOSE. No dagster, no boto3, no filesystem, no network — `summarize_rates`
and `render_rates` take plain dicts/lists in and return plain dicts/strings out, so
both producers (the corpus harness in scripts/pcn_corpus_run.py, and the real ingest
asset in doc_tools/assets/semantic_assets.py) can call the SAME aggregation and unit
tests never need either producer's machinery to exercise it.
"""
from typing import Any, Dict, Iterable, List, Optional

# The per-DOCUMENT rate flags this module knows how to aggregate. `needs_review` lives
# on the record itself (the plugin's doc-level verdict); the other three live under
# `stats` (counters `SustainmentPlugin._extract_fulltext` already produces — see
# doc_tools/plugins/sustainment.py). Order here is the order they render in.
RATE_FLAGS = ("needs_review", "crops_near_cap", "crops_row_short", "text_layer_degraded")


def summarize_rates(records: Iterable[Dict[str, Any]],
                     chunk_tally: Optional[Dict[str, Any]] = None) -> dict:
    """Reduce one run's per-document records to counts, denominators and a chunk line.

    `records`: one dict per document attempted this run. A HEALTHY record carries
    `needs_review` (bool) and `stats` (dict, carrying at least `crops_near_cap`,
    `crops_row_short`, `text_layer_degraded`).

    THREE dispositions, not two, and the difference is load-bearing:

    * FAILED — `ok: False`, or a truthy `error`. Counted under `errors` and EXCLUDED from
      every rate's denominator: a document that never extracted is not evidence that its
      text layer was healthy, and folding it into the "not degraded" side would understate
      the failure it actually is.
    * NOT APPLICABLE — no `stats`, but nothing says it failed. `stats` is a
      sustainment-only field today, so EVERY manufacturing/maintenance/training/compliance
      document reaches this function with `stats=None` while having extracted perfectly.
      Counted under `not_applicable`, also excluded from the denominators.
    * SCORED — everything else, and the only thing in a rate's denominator.

    Why the third bucket instead of inferring failure from a missing `stats`: this module
    exists so a RISING rate is the production signal. Folding not-applicable into `errors`
    would make a manufacturing ingest log "0 documents scored, 1 error" on every single
    run — a permanently nonzero failure count, which is the one reading that trains people
    to stop watching the number. Failure is therefore asserted by the caller (`ok`/`error`)
    and never guessed from the absence of a domain-specific field.

    `chunk_tally`: optional, the ingest-only chunk-write counters (`written`,
    `written_without_vector`) from doc_tools/assets/semantic_assets.py's chunk tally.
    Omitted (None) whenever the caller never wrote a chunk — this is the corpus harness's
    normal case, since it drives the plugin directly and stops before ingest. See the
    NOT-OBSERVED note on `render_rates` below: it is why this function keeps that
    distinction as `None` rather than defaulting the counters to 0.

    Returns:
        {
          "documents": int,          # records that reached `stats` (the rate denominator)
          "errors": int,             # records the caller declared failed, see above
          "not_applicable": int,     # records with no `stats` and no declared failure
          "rates": {flag: {"count": int, "denominator": int} for flag in RATE_FLAGS},
          "chunk_tally": {"written": int, "written_without_vector": int} or None,
        }
    """
    counts = {flag: 0 for flag in RATE_FLAGS}
    documents = 0
    errors = 0
    not_applicable = 0
    for rec in records:
        # Failure is what the CALLER declares, never what this function infers from a
        # missing field — see the three dispositions in the docstring.
        if rec.get("ok") is False or rec.get("error"):
            errors += 1
            continue
        stats = rec.get("stats")
        if not stats:
            not_applicable += 1
            continue
        documents += 1
        if rec.get("needs_review"):
            counts["needs_review"] += 1
        for flag in ("crops_near_cap", "crops_row_short", "text_layer_degraded"):
            if stats.get(flag):
                counts[flag] += 1

    rates = {flag: {"count": counts[flag], "denominator": documents} for flag in RATE_FLAGS}

    # NOT OBSERVED vs ZERO — do not collapse these. `written_without_vector` is only ever
    # incremented by the real chunk-write path in semantic_assets.py; the corpus harness
    # calls the plugin directly and never writes a chunk, so for a harness run this
    # counter was never touched, not touched-and-found-zero. Defaulting it to 0 here
    # would tell a reader "no chunk lost its vector," a claim about chunk writes that did
    # not happen. Keep it None end to end — `render_rates` is what turns None into an
    # explicit "not observed" line. DO NOT "simplify" this to `chunk_tally or {}` with a
    # 0 default; that reintroduces exactly the false zero this comment exists to prevent.
    chunk_summary = None
    if chunk_tally is not None:
        chunk_summary = {
            "written": chunk_tally.get("written") or 0,
            "written_without_vector": chunk_tally.get("written_without_vector") or 0,
        }

    return {
        "documents": documents,
        "errors": errors,
        "not_applicable": not_applicable,
        "rates": rates,
        "chunk_tally": chunk_summary,
    }


def _pct(count: int, denominator: int) -> str:
    if denominator <= 0:
        return " n/a "
    return f"{100.0 * count / denominator:5.1f}%"


def render_rates(summary: dict) -> str:
    """Render a `summarize_rates` result as an aligned, <=80-column plain-text block —
    suitable for a run log and for pasting straight into a dated report.
    """
    documents = summary.get("documents", 0)
    errors = summary.get("errors", 0)
    not_applicable = summary.get("not_applicable", 0)
    rates = summary.get("rates", {})
    chunk_tally = summary.get("chunk_tally")

    # `not applicable` is shown even at 0, so that a reader who sees a domain reporting
    # "0 scored" can tell WHICH exclusion put it there without going to the source.
    lines = [f"INGEST RATES  ({documents} scored, {errors} error(s), "
             f"{not_applicable} not applicable)"]
    for flag in RATE_FLAGS:
        r = rates.get(flag, {"count": 0, "denominator": documents})
        count, denom = r["count"], r["denominator"]
        lines.append(f"  {flag:<22} {count:>4} of {denom:<4} documents  ({_pct(count, denom)})")

    # PER-CHUNK, NOT PER-DOCUMENT — deliberately its own line with its own denominator
    # (`written`, a chunk count), never folded into the RATE_FLAGS loop above, which
    # would imply the two are measured against the same population. They are not: the
    # four flags above are one-per-document, this is one-per-chunk.
    if chunk_tally is None:
        lines.append("  written_without_vector: not observed (no chunk write in this run)")
    else:
        written = chunk_tally.get("written", 0)
        wwv = chunk_tally.get("written_without_vector", 0)
        lines.append(f"  written_without_vector {wwv:>4} of {written:<4} chunks written  "
                     f"({_pct(wwv, written)})")

    return "\n".join(lines)
