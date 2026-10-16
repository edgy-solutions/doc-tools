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
# on the record itself (the plugin's doc-level verdict); the rest live under `stats`
# (counters `SustainmentPlugin._extract_fulltext` already produces — see
# doc_tools/plugins/sustainment.py). Order here is the order they render in.
#
# A RATE IS PER DOCUMENT, EVEN WHERE THE UNDERLYING FIELD IS A COUNT. `crops_failed`
# and `crops_truncated` are crop COUNTS in `stats` (a notice with 3 failed crops stores
# 3), and they are aggregated here by TRUTHINESS, exactly like the boolean flags: the
# rate reads "documents with at least one failed crop", never "crops failed". Two
# consequences a reader of the rendered block must not get wrong:
#   * 2 of 10 does not mean 2 crops. The crop-level denominator is `n_tables`, which
#     this module never sees; telemetry.py carries that ratio separately.
#   * `crops_truncated` is a SUBSET of `crops_failed` (sustainment.py:919), so the two
#     rates NEST — a truncation is also a failure, and adding them double-counts.
# They are added because the crop seal, not the parts score, is what has been holding
# exit 0 (three fires on pin sha256:85ad4c9d failed on the crop term alone while fire 1
# scored 522/522), and a failed crop was visible per notice but in no run-level rate.
RATE_FLAGS = ("needs_review", "crops_failed", "crops_truncated",
              "crops_near_cap", "crops_row_short", "text_layer_degraded")

# Which flags are read off the record and which off its `stats`. DERIVED, not a second
# hand-written list: when the aggregation loop below carried its own literal tuple of
# stats flags, a name added to RATE_FLAGS alone would have rendered "0 of N documents"
# for ever — a clean-looking zero for a signal nothing was counting.
_RECORD_FLAGS = ("needs_review",)
_STATS_FLAGS = tuple(f for f in RATE_FLAGS if f not in _RECORD_FLAGS)


def summarize_rates(records: Iterable[Dict[str, Any]],
                     chunk_tally: Optional[Dict[str, Any]] = None) -> dict:
    """Reduce one run's per-document records to counts, denominators and a chunk line.

    `records`: one dict per document attempted this run. A HEALTHY record carries
    `needs_review` (bool) and `stats` (dict, carrying at least every name in
    `_STATS_FLAGS`). A missing name counts as not-flagged for that document, which is
    why a producer that stops emitting one looks clean rather than erroring — the names
    are listed in RATE_FLAGS so that producer and consumer have one place to agree.

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
        for flag in _RECORD_FLAGS:
            if rec.get(flag):
                counts[flag] += 1
        # Truthiness, not value: `crops_failed`/`crops_truncated` are counts, and one
        # document with three failed crops is ONE document with a failed crop. See the
        # note on RATE_FLAGS.
        for flag in _STATS_FLAGS:
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


def aggregate_rates_across_fires(rates_by_fire: Dict[Any, Optional[dict]]) -> dict:
    """Worst case per flag across several fires of one gate invocation.

    `rates_by_fire`: fire key -> that fire's `summarize_rates`-shaped dict, or None for
    a fire that emitted no `rates` at all.

    * MAX per flag, independently per flag (different flags may max on different fires).
    * The denominator travels with the count: it is the denominator of the fire that
      produced the max, and that fire is recorded in `"fire"`. A max count is never
      paired with another fire's population.
    * A None fire contributes NOTHING (not zeros, not a denominator); it is listed in
      `fires_missing`.
    * `chunk_tally` stays None unless some contributing fire observed one (NOT-OBSERVED
      is not ZERO; see `summarize_rates`).
    * Ties on count keep the earliest fire in sorted order.
    """
    def _key(k):
        return (str(type(k).__name__), k)

    keys = sorted(rates_by_fire, key=_key)
    contributing = [k for k in keys if rates_by_fire[k] is not None]
    missing = [k for k in keys if rates_by_fire[k] is None]

    agg: Dict[str, Any] = {
        "fires": contributing,
        "fires_missing": missing,
        "agreement": True,
        "documents": 0,
        "errors": 0,
        "not_applicable": 0,
        "rates": {},
        "chunk_tally": None,
    }
    if not contributing:
        return agg

    summaries = {k: rates_by_fire[k] for k in contributing}
    for field in ("documents", "errors", "not_applicable"):
        agg[field] = max((s.get(field) or 0) for s in summaries.values())

    agreement = True
    for flag in RATE_FLAGS:
        per = {}
        for k, s in summaries.items():
            r = (s.get("rates") or {}).get(flag, {"count": 0, "denominator": s.get("documents", 0)})
            per[k] = (r["count"], r["denominator"])
        best = contributing[0]
        for k in contributing:
            if per[k][0] > per[best][0]:
                best = k
        if len(set(per.values())) > 1:
            agreement = False
        agg["rates"][flag] = {
            "count": per[best][0],
            "denominator": per[best][1],
            "fire": best,
            "by_fire": {k: per[k][0] for k in contributing},
        }
    agg["agreement"] = agreement

    tallies = [s["chunk_tally"] for s in summaries.values() if s.get("chunk_tally") is not None]
    if tallies:
        agg["chunk_tally"] = {
            "written": max(t.get("written") or 0 for t in tallies),
            "written_without_vector": max(t.get("written_without_vector") or 0
                                          for t in tallies),
        }
    return agg


def render_rates_across_fires(agg: dict) -> str:
    """Render an `aggregate_rates_across_fires` result as aligned plain text (<=80 cols)."""
    fires = agg.get("fires", [])
    missing = agg.get("fires_missing", [])
    rates = agg.get("rates", {})
    chunk_tally = agg.get("chunk_tally")
    names = ", ".join(f"f{k}" for k in fires) or "none"

    lines = [f"INGEST RATES  (MAXIMA across {len(fires)} fire(s): {names})",
             f"  {agg.get('documents', 0)} scored, {agg.get('errors', 0)} error(s), "
             f"{agg.get('not_applicable', 0)} not applicable (max across fires)"]
    for flag in RATE_FLAGS:
        r = rates.get(flag)
        if r is None:
            lines.append(f"  {flag:<22} not observed")
            continue
        count, denom = r["count"], r["denominator"]
        lines.append(f"  {flag:<22} {count:>4} of {denom:<4} documents  "
                     f"({_pct(count, denom)})  from f{r.get('fire')}")

    if not agg.get("agreement", True):
        lines.append("")
        lines.append("  !! FIRES DISAGREED on the same image in the same invocation.")
        lines.append("  !! These rates are NOT a property of the image; read the worst case.")
        for flag in RATE_FLAGS:
            r = rates.get(flag)
            if not r:
                continue
            by_fire = r.get("by_fire", {})
            # Flag differs if counts differ (denominator-only differences are shown too).
            if len(set(by_fire.values())) > 1 or r["denominator"] != agg.get("documents"):
                detail = " ".join(f"f{k}={v}" for k, v in by_fire.items())
                lines.append(f"    {flag:<22} {detail}")

    if missing:
        lines.append("  fires that emitted no rates (not observed, NOT zero): "
                     + ", ".join(f"f{k}" for k in missing))

    if chunk_tally is None:
        lines.append("  written_without_vector: not observed (no chunk write in this run)")
    else:
        written = chunk_tally.get("written", 0)
        wwv = chunk_tally.get("written_without_vector", 0)
        lines.append(f"  written_without_vector {wwv:>4} of {written:<4} chunks written  "
                     f"({_pct(wwv, written)})")
    return "\n".join(lines)
