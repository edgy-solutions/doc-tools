"""Pure-logic tests for doc_tools.utils.ingest_rates.

Covers: empty input, a mixed set where some rate flags fire, the
errors-excluded-from-denominator rule (a failed document is not evidence its text layer
was healthy), and the written_without_vector NOT-OBSERVED-vs-ZERO distinction — the
point of the module. See the module docstring for why `chunk_tally=None` must never
render as a 0.
"""
from doc_tools.utils.ingest_rates import (
    RATE_FLAGS, aggregate_rates_across_fires, render_rates,
    render_rates_across_fires, summarize_rates,
)


def _ok(needs_review, crops_near_cap=0, crops_row_short=0, text_layer_degraded=0):
    return {
        "ok": True,
        "needs_review": needs_review,
        "stats": {
            "crops_near_cap": crops_near_cap,
            "crops_row_short": crops_row_short,
            "text_layer_degraded": text_layer_degraded,
        },
    }


def _failed(error="boom"):
    return {"ok": False, "error": error}


# --------------------------------------------------------------------------- #
# summarize_rates
# --------------------------------------------------------------------------- #
def test_empty_input_yields_zero_documents_and_zero_everything():
    summary = summarize_rates([])
    assert summary["documents"] == 0
    assert summary["errors"] == 0
    assert set(summary["rates"]) == set(RATE_FLAGS)
    for flag in RATE_FLAGS:
        assert summary["rates"][flag] == {"count": 0, "denominator": 0}
    assert summary["chunk_tally"] is None


def test_mixed_set_counts_each_flag_independently():
    records = [
        _ok(needs_review=True, crops_near_cap=1),
        _ok(needs_review=True, crops_row_short=1, text_layer_degraded=1),
        _ok(needs_review=False),
    ]
    summary = summarize_rates(records)
    assert summary["documents"] == 3
    assert summary["errors"] == 0
    assert summary["rates"]["needs_review"] == {"count": 2, "denominator": 3}
    assert summary["rates"]["crops_near_cap"] == {"count": 1, "denominator": 3}
    assert summary["rates"]["crops_row_short"] == {"count": 1, "denominator": 3}
    assert summary["rates"]["text_layer_degraded"] == {"count": 1, "denominator": 3}


def test_failed_documents_are_counted_as_errors_and_excluded_from_denominators():
    """A DECLARED failure (`ok: False`, or a truthy `error`) never reached the point where
    crops_near_cap/crops_row_short/text_layer_degraded exist. It must land in `errors`,
    NOT count as a healthy (non-degraded) document — a failed extraction is not evidence
    the text layer was fine."""
    records = [
        _ok(needs_review=True, text_layer_degraded=1),
        _failed("timeout"),
        {"ok": False},                       # declared failure, no stats at all
    ]
    summary = summarize_rates(records)
    assert summary["documents"] == 1, "only the one record with stats counts toward the rate"
    assert summary["errors"] == 2
    assert summary["not_applicable"] == 0
    assert summary["rates"]["text_layer_degraded"] == {"count": 1, "denominator": 1}
    assert summary["rates"]["needs_review"] == {"count": 1, "denominator": 1}


def test_missing_stats_without_a_declared_failure_is_not_applicable_not_an_error():
    """`stats` is a SUSTAINMENT-ONLY field. Every manufacturing/maintenance/training/
    compliance document reaches summarize_rates with stats=None having extracted
    perfectly, so inferring failure from a missing `stats` would log a permanent
    "1 error" on every non-sustainment ingest — the one reading that teaches people to
    stop watching the number this module exists to make watchable.

    Failure is therefore something the CALLER declares, never something inferred."""
    records = [
        {"ok": True, "needs_review": False},              # e.g. a manufacturing doc
        {"needs_review": False},                          # no ok, no error, no stats
        _failed("timeout"),                               # the only real failure here
    ]
    summary = summarize_rates(records)
    assert summary["errors"] == 1, "only the declared failure is an error"
    assert summary["not_applicable"] == 2
    assert summary["documents"] == 0
    # And the distinction has to survive into the rendered block, or a reader seeing
    # "0 scored" cannot tell which exclusion put it there.
    out = render_rates(summary)
    assert "1 error" in out
    assert "2 not applicable" in out


def test_chunk_tally_passthrough():
    summary = summarize_rates([_ok(True)], chunk_tally={"written": 10, "written_without_vector": 3})
    assert summary["chunk_tally"] == {"written": 10, "written_without_vector": 3}


# --------------------------------------------------------------------------- #
# render_rates
# --------------------------------------------------------------------------- #
def test_render_rates_stays_under_80_columns():
    summary = summarize_rates(
        [_ok(True, crops_near_cap=1, crops_row_short=1, text_layer_degraded=1)],
        chunk_tally={"written": 150, "written_without_vector": 2},
    )
    text = render_rates(summary)
    assert all(len(line) <= 80 for line in text.splitlines())


def test_render_rates_shows_written_without_vector_share_of_written():
    summary = summarize_rates([_ok(False)], chunk_tally={"written": 150, "written_without_vector": 2})
    text = render_rates(summary)
    assert "150" in text and "2" in text
    assert "1.3%" in text  # 2/150


def test_chunk_tally_none_never_renders_written_without_vector_as_zero():
    """THE point of this module. A harness run that never writes a chunk must not print
    a 0 next to written_without_vector — that would read as "measured, and it was zero"
    when the truth is "never measured." Assert the not-observed line carries no digit at
    all, so a 0 cannot hide in it, and that the block states plainly it was not observed.
    """
    summary = summarize_rates([_ok(True), _ok(False)], chunk_tally=None)
    assert summary["chunk_tally"] is None
    text = render_rates(summary)

    lines = text.splitlines()
    wwv_lines = [l for l in lines if "written_without_vector" in l]
    assert len(wwv_lines) == 1
    wwv_line = wwv_lines[0]

    assert "not observed" in wwv_line
    assert "no chunk write in this run" in wwv_line
    assert not any(ch.isdigit() for ch in wwv_line), (
        f"written_without_vector line must carry no digit when not observed: {wwv_line!r}")


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))


# --------------------------------------------------------------------------- #
# aggregate_rates_across_fires / render_rates_across_fires
# --------------------------------------------------------------------------- #
def _summary(docs=10, chunk_tally=None, **counts):
    rates = {f: {"count": counts.get(f, 0), "denominator": docs} for f in RATE_FLAGS}
    return {"documents": docs, "errors": 0, "not_applicable": 0,
            "rates": rates, "chunk_tally": chunk_tally}


def test_disagreeing_fires_report_the_worst_case_from_the_right_fire():
    # Measured on pin a72a4a26: same image, same invocation.
    agg = aggregate_rates_across_fires({
        1: _summary(crops_row_short=0, needs_review=3),
        2: _summary(crops_row_short=1, needs_review=4),
    })
    assert agg["agreement"] is False
    assert agg["rates"]["crops_row_short"]["count"] == 1
    assert agg["rates"]["crops_row_short"]["fire"] == 2
    assert agg["rates"]["needs_review"]["count"] == 4
    assert agg["rates"]["needs_review"]["fire"] == 2
    assert agg["rates"]["needs_review"]["by_fire"] == {1: 3, 2: 4}
    assert list(agg["rates"]) == list(RATE_FLAGS)


def test_different_flags_max_on_different_fires():
    agg = aggregate_rates_across_fires({
        1: _summary(needs_review=5),
        2: _summary(crops_near_cap=2),
    })
    assert agg["rates"]["needs_review"]["fire"] == 1
    assert agg["rates"]["crops_near_cap"]["fire"] == 2


def test_missing_fire_is_excluded_and_never_a_zero():
    agg = aggregate_rates_across_fires({
        1: None,
        2: _summary(docs=8, needs_review=2),
    })
    assert agg["fires"] == [2]
    assert agg["fires_missing"] == [1]
    assert agg["documents"] == 8
    assert agg["rates"]["needs_review"]["by_fire"] == {2: 2}
    out = render_rates_across_fires(agg)
    assert "not observed" in out and "f1" in out


def test_denominator_travels_with_the_max_count():
    agg = aggregate_rates_across_fires({
        1: _summary(docs=10, needs_review=3),
        2: _summary(docs=7, needs_review=4),
    })
    r = agg["rates"]["needs_review"]
    assert (r["count"], r["denominator"], r["fire"]) == (4, 7, 2)
    assert agg["agreement"] is False


def test_identical_fires_agree_and_render_no_disagreement():
    agg = aggregate_rates_across_fires({
        1: _summary(needs_review=3), 2: _summary(needs_review=3), 3: _summary(needs_review=3),
    })
    assert agg["agreement"] is True
    out = render_rates_across_fires(agg)
    assert "DISAGREED" not in out
    assert "MAXIMA across 3 fire(s): f1, f2, f3" in out
    assert all(len(line) <= 80 for line in out.splitlines())


def test_no_fire_contributed():
    agg = aggregate_rates_across_fires({1: None, 2: None})
    assert agg["fires"] == []
    assert agg["fires_missing"] == [1, 2]
    assert agg["rates"] == {}
    assert agg["agreement"] is True
    assert aggregate_rates_across_fires({})["fires"] == []


def test_chunk_tally_all_none_stays_none_not_zero():
    agg = aggregate_rates_across_fires({1: _summary(), 2: _summary()})
    assert agg["chunk_tally"] is None
    assert "not observed" in render_rates_across_fires(agg)


def test_chunk_tally_maxes_over_fires_that_have_one():
    agg = aggregate_rates_across_fires({
        1: _summary(),
        2: _summary(chunk_tally={"written": 10, "written_without_vector": 1}),
        3: _summary(chunk_tally={"written": 12, "written_without_vector": 0}),
    })
    assert agg["chunk_tally"] == {"written": 12, "written_without_vector": 1}


def test_disagreement_line_and_per_fire_counts_are_rendered():
    agg = aggregate_rates_across_fires({
        1: _summary(crops_row_short=0, needs_review=3),
        2: _summary(crops_row_short=1, needs_review=4),
        3: _summary(crops_row_short=0, needs_review=3),
    })
    out = render_rates_across_fires(agg)
    assert "FIRES DISAGREED" in out
    assert "f1=0 f2=1 f3=0" in out
    assert "from f2" in out
    assert all(len(line) <= 80 for line in out.splitlines())


# --------------------------------------------------------------------------- #
# crops_failed / crops_truncated: COUNTS in `stats`, a PER-DOCUMENT rate here
# --------------------------------------------------------------------------- #
def test_a_crop_count_is_aggregated_per_document_not_per_crop():
    """Three failed crops in one notice is ONE document with a failed crop.

    `crops_failed` is a crop count in `stats`, unlike the booleans beside it. If it
    were summed, the rate's own denominator (documents) would stop bounding its
    numerator and "4 of 2 documents" would be renderable.
    """
    summary = summarize_rates([
        {"ok": True, "needs_review": False,
         "stats": {"crops_failed": 3, "crops_truncated": 0}},
        {"ok": True, "needs_review": False,
         "stats": {"crops_failed": 0, "crops_truncated": 0}},
    ])
    assert summary["documents"] == 2
    assert summary["rates"]["crops_failed"] == {"count": 1, "denominator": 2}
    assert summary["rates"]["crops_failed"]["count"] <= summary["documents"]


def test_truncated_is_a_subset_of_failed_so_the_two_rates_nest():
    """sustainment.py:919 — a truncated crop is also a failed one.

    Pinned because the two rates render as adjacent lines, which invites adding them.
    A document counted under `crops_truncated` MUST also be counted under
    `crops_failed`; a producer that ever emitted truncated-without-failed would be the
    defect, and this asserts the shape the consumer relies on.
    """
    summary = summarize_rates([
        {"ok": True, "needs_review": False,
         "stats": {"crops_failed": 1, "crops_truncated": 1}},
        {"ok": True, "needs_review": False,
         "stats": {"crops_failed": 2, "crops_truncated": 0}},
    ])
    failed = summary["rates"]["crops_failed"]["count"]
    truncated = summary["rates"]["crops_truncated"]["count"]
    assert (failed, truncated) == (2, 1)
    assert truncated <= failed, "the two rates nest; they are not disjoint"


def test_both_crop_counters_render_and_stay_within_80_columns():
    out = render_rates(summarize_rates([
        {"ok": True, "needs_review": True,
         "stats": {"crops_failed": 1, "crops_truncated": 1,
                   "crops_near_cap": 0, "crops_row_short": 0,
                   "text_layer_degraded": 0}},
    ]))
    assert "crops_failed" in out
    assert "crops_truncated" in out
    assert all(len(line) <= 80 for line in out.splitlines())


def test_a_stats_flag_missing_from_the_record_counts_as_not_flagged():
    """Pre-existing producers (and every fixture) omit the new keys.

    They must read as not-flagged, never raise — a rate that crashes the aggregation
    on an older record would take down the run log that carries every other rate.
    """
    summary = summarize_rates([_ok(needs_review=False)])
    assert summary["documents"] == 1
    assert summary["rates"]["crops_failed"] == {"count": 0, "denominator": 1}
