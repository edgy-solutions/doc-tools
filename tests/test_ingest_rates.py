"""Pure-logic tests for doc_tools.utils.ingest_rates.

Covers: empty input, a mixed set where some rate flags fire, the
errors-excluded-from-denominator rule (a failed document is not evidence its text layer
was healthy), and the written_without_vector NOT-OBSERVED-vs-ZERO distinction — the
point of the module. See the module docstring for why `chunk_tally=None` must never
render as a 0.
"""
from doc_tools.utils.ingest_rates import RATE_FLAGS, render_rates, summarize_rates


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
