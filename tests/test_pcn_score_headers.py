"""The header half of `scripts/pcn_score.py`.

WHY A HEADER SCORER AT ALL, given that `pcn_corpus_gate.py` already compares
headers across three fires: AGREEMENT IS NOT CORRECTNESS, and on this corpus
that is not hypothetical. The three real pinned f32 fires each wrote
`pub_date = 2024-06-10` for TYC. The agreement check therefore records
`pub_date` as AGREE — it appears nowhere in that report's disagreeing-fields
list — while the page says the notice was published on the 7th and 06-10 is
the portal's print stamp, i.e. the day the PDF was rendered. Three fires
agreed on a wrong value and the only instrument that could say so is ground
truth. `test_real_three_fire_pub_date_is_the_declared_distractor` pins exactly
that case with the values the fires actually produced.

The statuses are tested apart rather than as one "wrong" bucket because they
are different defects: a DECLARED distractor is a value ground truth names and
explains (a field-attribution failure, fixable in the prompt), `wrong` is a
value ground truth does not account for, `misformatted` is the right content in
an unusable shape, and `unreadable` is a date this scorer refuses to guess at.
Collapsing them would discard the reason ground truth was written down.
"""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pcn_score = _load("pcn_score")

TYC = "TYC-PCN-24-210412.pdf"

# A minimal headers block in the shape the shipped ground truth uses.
SPEC = {
    "_note": "ignored: keys starting with _ are prose, not fields",
    "mfr": {
        "value": "TE Connectivity",
        "source": "page-1 heading",
        "not": {
            "TE Connecvity": "the degraded text layer, dropped ti ligature",
            "TE": "the witness reading the logo wordmark",
        },
    },
    "pub_date": {
        "value": "2024-06-07",
        "source": "PCN Date: 07-JUN-24",
        "not": {"2024-06-10": "the portal print stamp, not the publication date"},
    },
    "doc_level_ltb_date": {
        "value": None,
        "status": "PENDING -- not established",
        "candidates": {"2024-06-06": "text layer", "2024-06-08": "witness"},
    },
}


def _headers(**written):
    return pcn_score.score_headers(written, SPEC)["fields"]


# --------------------------------------------------------------------------
# One field at a time.

def test_the_page_value_is_exact():
    assert _headers(mfr="TE Connectivity")["mfr"]["status"] == "exact"


def test_declared_distractor_is_not_merely_wrong():
    f = _headers(pub_date="2024-06-10")["pub_date"]
    assert f["status"] == "distractor"
    assert f["matched"] == "2024-06-10"
    assert "print stamp" in f["why"]


def test_a_distractor_is_recognised_through_its_page_spelling():
    """`10-Jun-2024` is how the stamp is printed; ground truth declares the ISO
    form. The same wrong value in a different spelling is still that value, so
    the declared reason must still be reported."""
    f = _headers(pub_date="10-Jun-2024")["pub_date"]
    assert f["status"] == "distractor"
    assert f["matched"] == "2024-06-10"


def test_a_text_distractor_is_recognised_case_insensitively():
    f = _headers(mfr="te  connecvity")["mfr"]
    assert f["status"] == "distractor"
    assert f["matched"] == "TE Connecvity"


def test_an_undeclared_value_is_wrong_not_a_distractor():
    f = _headers(pub_date="2024-01-01")["pub_date"]
    assert f["status"] == "wrong"
    assert "why" not in f


def test_right_date_wrong_shape_is_misformatted_and_not_credited():
    f = _headers(pub_date="07-JUN-24")["pub_date"]
    assert f["status"] == "misformatted"
    assert pcn_score.score_headers({"pub_date": "07-JUN-24"}, SPEC)["exact"] == 0


def test_right_text_wrong_shape_is_misformatted():
    assert _headers(mfr="TE   CONNECTIVITY")["mfr"]["status"] == "misformatted"


def test_an_ambiguous_slash_date_is_unreadable_not_a_distractor():
    """`6/10/24` is the print stamp's other spelling, but it is ALSO a valid
    spelling of 6 October. Attributing it to the declared 06-10 distractor would
    mean this scorer resolved the ambiguity by assumption and then graded its own
    assumption. It is reported unreadable instead."""
    f = _headers(pub_date="6/10/24")["pub_date"]
    assert f["status"] == "unreadable"
    assert "matched" not in f


@pytest.mark.parametrize("written", [None, ""])
def test_nothing_written_is_absent(written):
    assert _headers(pub_date=written)["pub_date"]["status"] == "absent"


def test_a_pending_field_is_not_scored_in_either_direction():
    h = pcn_score.score_headers(
        {"mfr": "TE Connectivity", "pub_date": "2024-06-07",
         "doc_level_ltb_date": "2024-06-06"}, SPEC)
    f = h["fields"]["doc_level_ltb_date"]
    assert f["status"] == "pending"
    assert f["candidates"] == ["2024-06-06", "2024-06-08"]
    # Excluded from the denominator, and does not stop the notice being clean.
    assert h["scored"] == ["mfr", "pub_date"]
    assert h["exact"] == 2
    assert h["clean"] is True


def test_a_pending_field_cannot_be_failed_by_picking_the_other_candidate():
    """Both candidates are equally unproven, so neither can be graded. Scoring
    one as correct would promote a guess to a fact."""
    for cand in ("2024-06-06", "2024-06-08", "2024-07-01"):
        h = pcn_score.score_headers({"doc_level_ltb_date": cand}, SPEC)
        assert h["fields"]["doc_level_ltb_date"]["status"] == "pending"


def test_prose_keys_are_not_scored_as_fields():
    assert "_note" not in _headers(mfr="TE Connectivity")


# --------------------------------------------------------------------------
# Date normalization.

@pytest.mark.parametrize("raw,iso", [
    ("2024-06-07", "2024-06-07"),
    ("07-JUN-24", "2024-06-07"),
    ("10-Jun-2024", "2024-06-10"),
    ("8 June 2024", "2024-06-08"),
    ("8-June-2024", "2024-06-08"),
    (" 2024-6-7 ", "2024-06-07"),
])
def test_normalize_date_reads_the_spellings_these_notices_print(raw, iso):
    assert pcn_score.normalize_date(raw) == iso


@pytest.mark.parametrize("raw", [
    "6/10/24",      # US or day-first: June 10 or 6 October, two different days
    "2024/06/07",
    "June 2024",
    "",
    None,
    42,
    "2024-13-01",   # not a month
])
def test_normalize_date_refuses_what_it_cannot_read_without_guessing(raw):
    assert pcn_score.normalize_date(raw) is None


# --------------------------------------------------------------------------
# Totals, and the not-observed case.

def _run(written_header, ok=True):
    gt = {TYC: {"count": 1, "mpns": ["X"], "headers": SPEC}}
    entry = {"ok": ok, "mpns": ["X"]}
    if written_header is not None:
        entry["written_header"] = written_header
    return pcn_score.score_run({TYC: entry}, gt)


def test_a_run_without_written_header_is_unobserved_not_zero_failures():
    scored = _run(None)
    t = scored["header_totals"]
    assert t["observed"] is False
    assert t["unobserved"] == [TYC]
    assert t["notices_observed"] == 0
    # No failures were found because nothing was measured. `clean` alone would
    # read as success, which is why `observed` is reported beside it.
    assert t["clean"] is True
    assert "NOT SCORED" in pcn_score.render_headers(scored)


def test_an_absent_notice_still_counts_in_the_header_denominator():
    """A notice that never ran has UNOBSERVED headers. Dropping it from the
    denominator instead would shrink the corpus to whatever happened to run."""
    scored = pcn_score.score_run({}, {TYC: {"count": 1, "mpns": ["X"],
                                            "headers": SPEC}})
    t = scored["header_totals"]
    assert t["notices_with_gt"] == 1
    assert t["unobserved"] == [TYC]


def test_totals_locate_every_failure_as_notice_colon_field():
    t = _run({"mfr": "TE", "pub_date": "2024-01-01"})["header_totals"]
    assert t["distractor"] == [f"{TYC}:mfr"]
    assert t["wrong"] == [f"{TYC}:pub_date"]
    assert t["clean"] is False
    assert t["observed"] is True


def test_a_notice_with_no_headers_block_is_not_counted():
    scored = pcn_score.score_run(
        {TYC: {"ok": True, "mpns": ["X"], "written_header": {"mfr": "whatever"}}},
        {TYC: {"count": 1, "mpns": ["X"]}})
    assert scored["header_totals"]["notices_with_gt"] == 0
    assert "nothing scored" in pcn_score.render_headers(scored)


# --------------------------------------------------------------------------
# Exit status.

def _main(tmp_path, results, gt):
    res = tmp_path / "corpus.json"
    res.write_text(json.dumps(results), encoding="utf-8")
    gtf = tmp_path / "gt.json"
    gtf.write_text(json.dumps({"notices": gt}), encoding="utf-8")
    import sys
    argv = sys.argv
    sys.argv = ["pcn_score.py", str(res), "--ground-truth", str(gtf)]
    try:
        return pcn_score.main()
    finally:
        sys.argv = argv


def test_a_distractor_header_fails_a_run_whose_parts_are_perfect(tmp_path):
    gt = {TYC: {"count": 1, "mpns": ["X"], "headers": SPEC}}
    results = {TYC: {"ok": True, "mpns": ["X"],
                     "written_header": {"mfr": "TE Connectivity",
                                        "pub_date": "2024-06-10"}}}
    assert _main(tmp_path, results, gt) == 1


def test_exact_headers_and_perfect_parts_pass(tmp_path):
    gt = {TYC: {"count": 1, "mpns": ["X"], "headers": SPEC}}
    results = {TYC: {"ok": True, "mpns": ["X"],
                     "written_header": {"mfr": "TE Connectivity",
                                        "pub_date": "2024-06-07",
                                        "doc_level_ltb_date": "2024-06-06"}}}
    assert _main(tmp_path, results, gt) == 0


def test_an_unmeasured_header_block_does_not_fail_a_parts_run(tmp_path):
    """A pre-written_header image measured parts and nothing else. Failing it on
    headers would report a defect in the extractor where there is only a gap in
    the instrument; the report says NOT SCORED instead."""
    gt = {TYC: {"count": 1, "mpns": ["X"], "headers": SPEC}}
    assert _main(tmp_path, {TYC: {"ok": True, "mpns": ["X"]}}, gt) == 0


# --------------------------------------------------------------------------
# The shipped ground truth, and the real fires.

def test_shipped_header_ground_truth_is_internally_consistent():
    gt = pcn_score.load_ground_truth()
    blocks = {fn: e["headers"] for fn, e in gt.items() if e.get("headers")}
    assert blocks, "no notice carries a headers block — this test is then vacuous"
    for fn, block in blocks.items():
        for name, spec in block.items():
            if name.startswith("_"):
                continue
            where = f"{fn}:{name}"
            if spec.get("expect_absent"):
                # Carries no `value` like a pending field, and means the
                # opposite: established as having nothing to establish.
                assert spec.get("_why"), (
                    f"{where}: expect_absent with no _why -- a claim that the "
                    f"document states no value has to say how that was read")
                assert spec.get("value") is None, f"{where}: expect_absent with a value"
                assert spec.get("accepted") is None, (
                    f"{where}: expect_absent with an accepted set")
                assert not spec.get("candidates"), (
                    f"{where}: expect_absent with candidates -- candidates belong to "
                    f"a pending field, where the value is unknown rather than absent")
                for bad, why in (spec.get("not") or {}).items():
                    assert why, f"{where}: declares {bad!r} wrong without saying why"
                continue
            if spec.get("value") is None:
                assert spec.get("status"), f"{where}: pending with no status"
                assert spec.get("candidates"), f"{where}: pending with no candidates"
                continue
            assert spec.get("source"), f"{where}: a value with no page source"
            for bad, why in (spec.get("not") or {}).items():
                assert bad != spec["value"], f"{where}: declares its own value wrong"
                assert why, f"{where}: declares {bad!r} wrong without saying why"
            if pcn_score.is_date_field(name):
                assert pcn_score.normalize_date(spec["value"]) == spec["value"], (
                    f"{where}: date ground truth is not ISO")


# The values the three real f32 fires wrote for TYC, recovered from their logs
# by pcn_header_agreement and transcribed from docs/corpus-gate/report-2026-10-01
# -rereduced.md. Order is fire 1 | 2 | 3.
_REAL_FIRES = (
    {"mfr": "TE Connecvity", "pub_date": "2024-06-10",
     "doc_level_ltb_date": None},
    {"mfr": "TE", "pub_date": "2024-06-10",
     "doc_level_ltb_date": "2024-06-06"},
    {"mfr": "TE Connecvity", "pub_date": "2024-06-10",
     "doc_level_ltb_date": "2024-06-06"},
)


def test_real_three_fire_pub_date_is_the_declared_distractor():
    """All three fires agree on `2024-06-10`, so the cross-fire agreement check
    reports pub_date as AGREE; ground truth reports it as the portal print
    stamp. This is the case the header scorer exists for — a stable wrong value
    is invisible to a check that only compares fires to each other.

    These three fires also wrote `TE Connecvity`, `TE` and `TE Connecvity` for
    `mfr`, and this test asserted all three were distractors until 2026-10-09.
    Ruled that day: they are the damaged text layer's reading and the logo
    wordmark, both verbatim-correct readings of the same printed name, so they
    are ACCEPTED and `mfr` is a pass here. The assertion is kept rather than
    deleted, inverted to the ruling, because `pub_date` and `mfr` differ in
    exactly the way that matters: one is a value printed somewhere else on the
    page (a real trap), the other is the same value spelled differently."""
    gt = pcn_score.load_ground_truth()
    spec = gt[TYC]["headers"]
    for fire in _REAL_FIRES:
        h = pcn_score.score_headers(fire, spec)
        assert h["clean"] is False
        assert h["fields"]["pub_date"]["status"] == "distractor"
        assert h["fields"]["mfr"]["status"] in pcn_score.HEADER_PASSES


def test_real_fires_got_the_ltb_date_right_where_they_wrote_it_at_all():
    """`doc_level_ltb_date` was PENDING until 2026-09-30, when the page was
    rendered and read: the Estimated Dates table says `Last Order Date (Obsolete
    Parts Only): 06-JUN-2024`. So the two fires that wrote a value wrote the
    right one, and the scorer must now say so rather than abstain.

    Fire 1 wrote nothing, which is `absent` — a different finding from `wrong`,
    and the reason the field is a recall gap in exactly one of three runs rather
    than a precision defect in all of them."""
    gt = pcn_score.load_ground_truth()
    spec = gt[TYC]["headers"]
    got = [pcn_score.score_headers(f, spec)["fields"]["doc_level_ltb_date"]
           for f in _REAL_FIRES]
    assert [f["status"] for f in got] == ["absent", "exact", "exact"]
    assert all(f["expected"] == "2024-06-06" for f in got)


def test_the_adjacent_row_and_the_witness_reading_are_both_declared():
    """The two ways to get this field wrong are not the same kind of wrong, and
    the scorer has to keep them apart.

    `2024-06-07` is the NEXT ROW of the same table (Last Ship Date of Changed
    Items) and is also the correct pub_date — a run returning it has read the
    page and taken the wrong line. `2024-06-08` is the second witness's reading
    and appears nowhere on the page at all: a digit substitution, the standing
    failure mode of that witness. Both must score `distractor` with ground
    truth's reason attached, not as anonymous near-misses."""
    gt = pcn_score.load_ground_truth()
    spec = gt[TYC]["headers"]
    for bad in ("2024-06-07", "2024-06-08"):
        f = pcn_score.score_headers({"doc_level_ltb_date": bad},
                                    spec)["fields"]["doc_level_ltb_date"]
        assert f["status"] == "distractor", bad
        assert f["matched"] == bad
        assert f["why"]


def test_tyc_is_scored_on_all_three_header_fields():
    """The shipped TYC block must leave nothing pending. A pending field is
    scored in neither direction, so a block that still carries one is reporting
    on two fields while looking like it reports on three."""
    spec = pcn_score.load_ground_truth()[TYC]["headers"]
    named = {k for k in spec if not k.startswith("_")}
    assert named == {"mfr", "pub_date", "doc_level_ltb_date"}
    assert all(spec[k].get("value") for k in named), (
        "a TYC header field is still pending")
    h = pcn_score.score_headers(
        {"mfr": "TE Connectivity", "pub_date": "2024-06-07",
         "doc_level_ltb_date": "2024-06-06"}, spec)
    assert h["scored"] == ["doc_level_ltb_date", "mfr", "pub_date"]
    assert h["clean"] is True


# --------------------------------------------------------------------------
# expect_absent: the field the document does not answer.
#
# WHY THIS EXISTS. Three statuses could describe a field with no page value and
# none of them scored it. `absent` means ground truth says there IS a value and
# none was written -- a miss. `pending` means ground truth has not established
# the value, and is excluded from the score in both directions. Declaring such
# a field `value: null` was the only option available, so it reported `pending`
# -- which means a run that INVENTED a last-time-buy date for a notice that has
# none scored exactly as well as a run that correctly wrote nothing.
#
# TI's PCN#20210316000 is the real case: a die-coat qualification change with no
# last-time-buy at all, printing `Proposed 1st Ship Date: Jun 22, 2021` in the
# same block as the dates it DOES state. The bait is adjacent to where the
# answer would go, which is the shape that produces a confident wrong date.

ABSENT_SPEC = {
    "doc_level_ltb_date": {
        "expect_absent": True,
        "_why": ("a die-coat qualification change: the notice announces no "
                 "discontinuation and states no last-time-buy date anywhere"),
        "not": {
            "2021-06-22": ("Proposed 1st Ship Date -- the date the CHANGED part "
                           "starts shipping, not a last-time-buy for the old one"),
        },
    },
}


def _absent(**written):
    return pcn_score.score_headers(written, ABSENT_SPEC)["fields"]


def test_writing_nothing_is_the_pass_when_the_document_states_nothing():
    f = _absent(doc_level_ltb_date=None)["doc_level_ltb_date"]
    assert f["status"] == "correctly_absent"
    assert f["status"] in pcn_score.HEADER_PASSES
    assert "die-coat" in f["why"]


def test_an_empty_string_is_also_correctly_absent():
    assert (_absent(doc_level_ltb_date="")["doc_level_ltb_date"]["status"]
            == "correctly_absent")


def test_a_missing_key_is_correctly_absent_not_unscored():
    """`written.get(name)` yields None for a key the run never wrote, and that
    is the same answer as writing null: the field was not answered."""
    assert (_absent()["doc_level_ltb_date"]["status"] == "correctly_absent")


def test_any_value_at_all_is_hallucinated():
    f = _absent(doc_level_ltb_date="2020-01-15")["doc_level_ltb_date"]
    assert f["status"] == "hallucinated"
    assert f["status"] in pcn_score.HEADER_FAILURES


def test_the_adjacent_ship_date_is_reported_as_the_distractor_it_matched():
    """The failure is `hallucinated` either way -- the document states no value,
    so there was nothing to mis-pick. But WHICH value was picked up is the whole
    diagnostic: `Proposed 1st Ship Date` two lines from where an LTB would go
    names the fix as a field-attribution one."""
    f = _absent(doc_level_ltb_date="2021-06-22")["doc_level_ltb_date"]
    assert f["status"] == "hallucinated"
    assert f["matched"] == "2021-06-22"
    assert "1st Ship Date" in f["why"]


def test_the_distractor_is_matched_through_its_page_spelling():
    f = _absent(doc_level_ltb_date="22-Jun-2021")["doc_level_ltb_date"]
    assert f["status"] == "hallucinated"
    assert f["matched"] == "2021-06-22"


# --------------------------------------------------------------------------
# The regression this status exists for.

def test_a_fabricated_date_is_SCORED_here_where_value_null_excluded_it():
    """THE POINT OF THE WHOLE STATUS. The same written value against the two
    specs that both carry no `value`: pending leaves it out of the score, and
    expect_absent fails it. Before this existed only the first was expressible,
    so an invented date could not be failed by this instrument at all."""
    pending_spec = {"doc_level_ltb_date": {
        "value": None,
        "status": "PENDING -- not established",
        "candidates": {"2024-06-06": "text layer"},
    }}
    invented = {"doc_level_ltb_date": "2021-06-22"}

    as_pending = pcn_score.score_headers(invented, pending_spec)
    assert as_pending["fields"]["doc_level_ltb_date"]["status"] == "pending"
    assert as_pending["scored"] == [], "a pending field must stay out of the score"
    assert as_pending["clean"] is True, "and cannot be failed"

    as_absent = pcn_score.score_headers(invented, ABSENT_SPEC)
    assert as_absent["fields"]["doc_level_ltb_date"]["status"] == "hallucinated"
    assert as_absent["scored"] == ["doc_level_ltb_date"]
    assert as_absent["clean"] is False


def test_correctly_absent_is_scored_and_is_not_counted_as_exact():
    """A pass, but there was no value to match, so crediting it as `exact` would
    overstate what the run got right. Same treatment as `alias`."""
    h = pcn_score.score_headers({"doc_level_ltb_date": None}, ABSENT_SPEC)
    assert h["scored"] == ["doc_level_ltb_date"]
    assert h["clean"] is True
    assert h["exact"] == 0
    assert h["correctly_absent"] == 1


def test_a_hallucinated_field_reaches_the_totals_located_by_notice_and_field():
    per = {TYC: {"headers": pcn_score.score_headers(
        {"doc_level_ltb_date": "2021-06-22"}, ABSENT_SPEC)}}
    t = pcn_score.header_totals(per)
    assert t["hallucinated"] == [f"{TYC}:doc_level_ltb_date"]
    assert t["clean"] is False
    assert t["fields_scored"] == 1


def test_a_correctly_absent_field_is_located_in_the_totals_too():
    """Not a failure, so it needs its own list for the same reason `aliases`
    does: `exact` short of `fields_scored` with no failure beside it is a report
    a reader cannot account for."""
    per = {TYC: {"headers": pcn_score.score_headers(
        {"doc_level_ltb_date": None}, ABSENT_SPEC)}}
    t = pcn_score.header_totals(per)
    assert t["correctly_absent"] == [f"{TYC}:doc_level_ltb_date"]
    assert t["clean"] is True
    assert t["fields_scored"] == 1
    assert t["exact"] == 0


def test_the_gate_blocks_on_hallucinated_without_naming_it():
    """The gate iterates pcn_score.HEADER_FAILURES rather than its own copy, so
    adding a status to the scorer must make the gate block on it with no edit
    there. That is the property; this asserts the membership it rests on."""
    assert "hallucinated" in pcn_score.HEADER_FAILURES
    assert "correctly_absent" not in pcn_score.HEADER_FAILURES
    assert "correctly_absent" in pcn_score.HEADER_PASSES


# --------------------------------------------------------------------------
# Incoherent ground truth raises rather than scoring.

def test_expect_absent_beside_a_value_raises():
    spec = {"doc_level_ltb_date": {"expect_absent": True, "_why": "x",
                                   "value": "2021-06-22", "source": "p1"}}
    with pytest.raises(ValueError, match="cannot both carry"):
        pcn_score.score_headers({"doc_level_ltb_date": None}, spec)


def test_expect_absent_beside_an_accepted_set_raises():
    spec = {"doc_level_ltb_date": {"expect_absent": True, "_why": "x",
                                   "accepted": ["2021-06-22"]}}
    with pytest.raises(ValueError, match="no accepted spelling"):
        pcn_score.score_headers({"doc_level_ltb_date": None}, spec)


# --------------------------------------------------------------------------
# The report says which of the two it is.

def test_the_report_names_a_hallucination_as_invention_not_as_wrong():
    per = {TYC: {"headers": pcn_score.score_headers(
        {"doc_level_ltb_date": "2021-06-22"}, ABSENT_SPEC)}}
    text = pcn_score.render_headers({"per_notice": per,
                                     "header_totals": pcn_score.header_totals(per)})
    assert "HALLUCINATED" in text
    assert "states NO value" in text
    assert "1st Ship Date" in text


def test_the_report_distinguishes_correctly_absent_from_a_miss():
    per = {TYC: {"headers": pcn_score.score_headers(
        {"doc_level_ltb_date": None}, ABSENT_SPEC)}}
    text = pcn_score.render_headers({"per_notice": per,
                                     "header_totals": pcn_score.header_totals(per)})
    assert "correctly absent" in text
    assert "A PASS" in text
    assert "absent — nothing written" not in text
