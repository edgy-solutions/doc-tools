"""DECLINED: the third bucket, ruled 2026-11-16.

A header field blank in one fire with a **declared** withdrawal, where every other
fire published the **ground-truth** value, is DECLINED -- not unstable and not wrong.
The fires that answered answered correctly, and the fire that did not say so.

Why it is neither of the two buckets that already existed. An EXEMPTION says "this is
a defect, but a human was warned"; it leaves the defect on the books. Declined says the
measurement does not describe a defect at all: there is no disagreement (one fire wrote
nothing) and no wrong value (every value written was the ground-truth one). Reporting it
as instability charges the pipeline with a defect it does not have, and reporting it as
an exemption charges it with one a warning excuses.

THE STRICT VERDICT IS THE WHOLE SAFETY OF THE RULE. `strict_verdict` reads
`written_unsettled` (blank rows included), `identity_half_unstable` and
`header_correctness.failing_notices` directly, granting nothing, so a declined row stays
red there with no wiring at all -- which is why `check_header_correctness` skips only the
blocking/exempted LINE and leaves `failing_notices` intact. Tests below pin that.

No cluster, no S3, no network, no doc_tools import: every input is a plain dict, and
`scripts/` is loaded by path as in test_corpus_gate_written_agreement.py.
"""
import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("pcn_corpus_gate")

FN = "TYC-PCN-24-210412.pdf"
VALUE = "TE Connectivity"

# The withdrawal vocabulary, verbatim from the producer that emits it
# (doc_tools/utils/sustainment_header_trust.py:1282 at pin 58ef369), and the branch at
# :1274 that must NOT count -- it reports a value that WAS published.
MFR_WITHDRAWN = (
    "header.mfr withdrawn: text layer 'TE Connecvity' and region witness 'Vishay' do "
    "not agree; an uncorroborated manufacturer is withdrawn rather than written")
MFR_CORROBORATED = (
    "header.mfr corroborated by the region witness: text layer 'TE Connecvity', "
    "witness 'TE Connectivity'; kept 'TE Connectivity'")
MFR_PARENT_REFUSED = ("header.mfr_parent refused: 'ttelectronics.com' is a web or "
                      "e-mail domain, not a name")
DOC_ID_REASON = ("doc_id taken from the document ('PCN-24-210412', printed at page 1 "
                 "header); header.doc_id refused the pass value")


def _blank_rows(field="mfr", blank_fires=(2,), fn=FN, value=VALUE):
    """`compare_written_headers`'s own shape: (fn, field, {fire: value}, [blank fires])."""
    seen = {n: (None if n in blank_fires else value) for n in (1, 2, 3)}
    return [(fn, field, seen, list(blank_fires))]


def _corpus(declared_in=(2,), reason=MFR_WITHDRAWN, flagged=(1, 2, 3), fn=FN):
    """One notice, three fires. `flagged` sets needs_review; `declared_in` carries the
    reason. A reason without needs_review is not a declaration, and that is pinned."""
    out = {}
    for n in (1, 2, 3):
        out[n] = {fn: {"ok": True, "needs_review": n in flagged,
                       "review_reasons": [reason] if n in declared_in else []}}
    return out


def _totals(**kw):
    """A fire's `header_totals`. `exact` is a COUNT and not a located list, which is why
    "published the ground-truth value" has to be read negatively -- scored, not pending,
    not correctly_absent, in no failure list."""
    t = {"notices_with_gt": 1, "notices_observed": 1, "unobserved": [],
         "fields_scored": 2, "exact": 2, "pending": [], "aliases": [],
         "correctly_absent": [], "distractor": [], "wrong": [], "misformatted": [],
         "unreadable": [], "absent": [], "hallucinated": [], "observed": True,
         "clean": True}
    t.update(kw)
    return t


def _tyc_totals(blank_fire=2, field="mfr", fn=FN):
    """The shape the TYC record actually had: the blank fire scores the field `absent`
    against a ground truth that holds a value, the others score it clean."""
    return {n: (_totals(absent=[f"{fn}:{field}"], exact=1, clean=False)
                if n == blank_fire else _totals())
            for n in (1, 2, 3)}


# --------------------------------------------------------------------------
# classify_declined -- the four conditions
# --------------------------------------------------------------------------

def test_the_tyc_shape_classifies_declined_one_of_three():
    """THE CASE THE RULE WAS WRITTEN FOR, as the 2026-11-11 fire recorded it: `mfr`
    blank in fire 2 with a withdrawal that names the field, published correctly in
    fires 1 and 3."""
    declined = gate.classify_declined(_blank_rows(), _corpus(), _tyc_totals())
    assert list(declined) == [(FN, "mfr")]
    r = declined[(FN, "mfr")]
    assert r["declined_fires"] == [2] and r["published_fires"] == [1, 3]
    assert (r["declined_in"], r["of"]) == (1, 3)
    assert "`mfr`" in r["basis"] and "withdrawn" in r["basis"]


def test_an_undeclared_blank_is_not_declined_and_still_blocks():
    """A blank nobody flagged is a silent write of nothing. The classification must not
    reach it, and the blank-fire rule must still block it."""
    corpus = _corpus(declared_in=(), flagged=(1, 3))
    declined = gate.classify_declined(_blank_rows(), corpus, _tyc_totals())
    assert declined == {}
    blocking, exempted = gate.apply_blank_fire_rule(_blank_rows(), corpus,
                                                    declined=declined)
    assert len(blocking) == 1 and "undeclared silent blank" in blocking[0]
    assert exempted == []


def test_a_reason_naming_another_field_does_not_decline():
    """`header.mfr_parent refused` is a different field. The identifier boundary in
    `_reason_names_field` is what keeps it from reading as a declaration about `mfr`."""
    assert gate.classify_declined(_blank_rows(),
                                  _corpus(reason=MFR_PARENT_REFUSED),
                                  _tyc_totals()) == {}


def test_a_reason_reporting_a_publication_is_not_a_declaration():
    """The corroboration branch names `mfr` and carries no declaring verb: it says the
    value WAS written. A value that was published cannot have been declined."""
    assert gate.classify_declined(_blank_rows(),
                                  _corpus(reason=MFR_CORROBORATED),
                                  _tyc_totals()) == {}


def test_a_reason_without_needs_review_is_not_a_declaration():
    """A narration on a document nobody is told to review is not a withdrawal."""
    assert gate.classify_declined(_blank_rows(),
                                  _corpus(flagged=(1, 3)),
                                  _tyc_totals()) == {}


def test_a_wrong_value_in_another_fire_is_not_declined():
    """"Every other fire published the ground-truth value" is a condition, not a
    description. A fire that wrote the field WRONG means the field really is in
    dispute, and the row stays where the blank-fire rule put it."""
    totals = _tyc_totals()
    totals[3] = _totals(wrong=[f"{FN}:mfr"], exact=1, clean=False)
    declined = gate.classify_declined(_blank_rows(), _corpus(), totals)
    assert declined == {}
    blocking, exempted = gate.apply_blank_fire_rule(_blank_rows(), _corpus(),
                                                    declined=declined)
    assert blocking == [] and len(exempted) == 1   # declared, so exempted as before


def test_a_pending_field_in_another_fire_is_not_a_publication():
    """`pending` means ground truth has not ruled on it. Nothing was published."""
    totals = _tyc_totals()
    totals[1] = _totals(pending=[f"{FN}:mfr"])
    assert gate.classify_declined(_blank_rows(), _corpus(), totals) == {}


def test_an_unobserved_notice_in_another_fire_is_not_a_publication():
    totals = _tyc_totals()
    totals[3] = _totals(unobserved=[FN])
    assert gate.classify_declined(_blank_rows(), _corpus(), totals) == {}


def test_a_fire_with_no_header_totals_at_all_is_not_a_publication():
    totals = _tyc_totals()
    totals[3] = None
    assert gate.classify_declined(_blank_rows(), _corpus(), totals) == {}


def test_correctly_absent_ground_truth_is_not_declined():
    """Ground truth holds NO value for the field, so there is no ground-truth value for
    another fire to have declined. The rule is inapplicable, not silently true."""
    totals = {n: _totals(correctly_absent=[f"{FN}:mfr"]) for n in (1, 2, 3)}
    assert gate.classify_declined(_blank_rows(), _corpus(), totals) == {}


def test_a_field_with_no_located_evidence_at_all_is_not_declined():
    """THE ONE HOLE THE RULE WOULD OTHERWISE HAVE. `_gt_published_in_fire` reads a pass
    as "named in no failure list", so a field ground truth never scores would read as
    published-correctly in EVERY fire and a real instability would classify as declined
    on the strength of never having been measured. `_gt_scores_field` requires positive
    evidence: some fire must LOCATE the field."""
    totals = {n: _totals() for n in (1, 2, 3)}   # clean, and `mfr` nowhere named
    declined = gate.classify_declined(_blank_rows(), _corpus(), totals)
    assert declined == {}
    blocking, exempted = gate.apply_blank_fire_rule(_blank_rows(), _corpus(),
                                                    declined=declined)
    assert len(exempted) == 1 and blocking == []


def test_an_alias_counts_as_located_and_as_a_publication():
    """An alias is a pass: the spelling ground truth accepts as verbatim-correct. It is
    both the positive evidence `_gt_scores_field` wants and a publication."""
    totals = _tyc_totals()
    totals[1] = _totals(aliases=[f"{FN}:mfr"])
    assert list(gate.classify_declined(_blank_rows(), _corpus(), totals)) == [(FN, "mfr")]


def test_a_row_blank_in_every_fire_is_not_declined():
    """Nothing published it, so nothing says the value was right."""
    rows = _blank_rows(blank_fires=(1, 2, 3))
    assert gate.classify_declined(rows, _corpus(declared_in=(1, 2, 3)),
                                  _tyc_totals()) == {}


def test_two_blank_fires_report_declined_in_two_of_three():
    """The report says N of 3, not "one fire"."""
    rows = _blank_rows(blank_fires=(2, 3))
    totals = {n: (_totals(absent=[f"{FN}:mfr"], exact=1, clean=False)
                  if n in (2, 3) else _totals()) for n in (1, 2, 3)}
    declined = gate.classify_declined(rows, _corpus(declared_in=(2, 3)), totals)
    r = declined[(FN, "mfr")]
    assert r["declined_fires"] == [2, 3] and r["published_fires"] == [1]
    assert (r["declined_in"], r["of"]) == (2, 3)


def test_every_blank_fire_must_have_declared():
    """Two blanks, one declared: the undeclared one is still a silent write."""
    rows = _blank_rows(blank_fires=(2, 3))
    totals = {n: (_totals(absent=[f"{FN}:mfr"], exact=1, clean=False)
                  if n in (2, 3) else _totals()) for n in (1, 2, 3)}
    assert gate.classify_declined(rows, _corpus(declared_in=(2,)), totals) == {}


# --------------------------------------------------------------------------
# What the classification removes, and what it must leave
# --------------------------------------------------------------------------

def test_a_declined_row_leaves_both_lists_on_the_blank_fire_rule():
    declined = gate.classify_declined(_blank_rows(), _corpus(), _tyc_totals())
    blocking, exempted = gate.apply_blank_fire_rule(_blank_rows(), _corpus(),
                                                    declined=declined)
    assert blocking == [] and exempted == []


def test_header_correctness_drops_the_line_and_keeps_failing_notices():
    """THE SAFETY. `failing_notices` is what `strict_verdict` reads, so it stays intact
    while the blocking/exempted line goes. The strict view grants nothing."""
    totals = _tyc_totals()
    declined = gate.classify_declined(_blank_rows(), _corpus(), totals)
    block, blocking, exempted = gate.check_header_correctness(
        totals, _corpus(), declined=declined)
    assert blocking == [] and exempted == []
    assert block["failing_notices"] == [FN]


def test_header_correctness_still_reports_an_undeclined_failure():
    """The skip is keyed to (notice, field), not to the notice."""
    totals = {n: _totals(wrong=[f"{FN}:pub_date"],
                         absent=([f"{FN}:mfr"] if n == 2 else []),
                         exact=1, clean=False) for n in (1, 2, 3)}
    declined = gate.classify_declined(_blank_rows(), _corpus(), totals)
    assert list(declined) == [(FN, "mfr")]
    _, blocking, exempted = gate.check_header_correctness(totals, _corpus(),
                                                          declined=declined)
    assert len(blocking) == 1 and "`pub_date`" in blocking[0]
    assert exempted == []


# --------------------------------------------------------------------------
# The identity half -- compute_stability's conservative widening, undone
# --------------------------------------------------------------------------

DECLINED_MFR = {(FN, "mfr"): {"notice": FN, "field": "mfr", "declined_fires": [2],
                              "published_fires": [1, 3], "declined_in": 1, "of": 3,
                              "basis": "a review reason names `mfr`"}}


def test_the_identity_line_is_declined_when_the_other_moving_field_is_settled():
    """`compute_stability` names BOTH identity fields whenever the identity could not be
    FORMED in some fire, which is exactly what a declined blank produces: the blank
    nulls one component, so no key exists, so no moving half can be named. `doc_id` was
    never moving, and charging it with a difference it does not have is the widening
    this undoes."""
    assert gate.identity_instability_declined(
        FN, ("mfr", "doc_id"), DECLINED_MFR, set()) is True
    blocking, exempted = gate.apply_declaration_rule(
        [], [FN], _corpus(), {FN: ("mfr", "doc_id")}, declined=DECLINED_MFR,
        unsettled_fields=set())
    assert blocking == [] and exempted == []


def test_the_identity_line_still_blocks_when_the_other_field_really_moved():
    """`unsettled_fields` is the written comparison's own rows, so the two readings
    cannot drift apart. A `doc_id` that genuinely disagrees is not explained by the
    `mfr` withdrawal."""
    unsettled = {(FN, "doc_id")}
    assert gate.identity_instability_declined(
        FN, ("mfr", "doc_id"), DECLINED_MFR, unsettled) is False
    blocking, _ = gate.apply_declaration_rule(
        [], [FN], _corpus(declared_in=()), {FN: ("mfr", "doc_id")},
        declined=DECLINED_MFR, unsettled_fields=unsettled)
    assert len(blocking) == 1 and "identity half is unstable" in blocking[0]


def test_an_identity_instability_with_nothing_declined_is_untouched():
    """At least one field must actually be declined, or this is an ordinary instability
    with nothing to classify -- not a line to drop because no field objected."""
    assert gate.identity_instability_declined(FN, ("mfr", "doc_id"), {}, set()) is False
    blocking, _ = gate.apply_declaration_rule(
        [], [FN], _corpus(declared_in=()), {FN: ("mfr", "doc_id")}, declined={},
        unsettled_fields=set())
    assert len(blocking) == 1


# --------------------------------------------------------------------------
# _why_not_declared -- which fires declared (ruled 2026-11-16)
# --------------------------------------------------------------------------

def test_why_not_declared_names_the_fires_that_did_declare():
    """The 2026-11-11 report printed "no reason names `mfr`" on a notice where fire 2
    named it exactly as asked; fires 1 and 3 did not, because they PUBLISHED the value
    and so had nothing to declare. "No fire named it" and "only the fire with the defect
    named it" are different states with different fixes."""
    msg = gate._why_not_declared(_corpus(), FN, "mfr")
    assert "IS declared in fire(s) [2]" in msg
    assert "NOT in fire(s) [1, 3]" in msg
    assert "not only the one that withdrew" in msg


def test_why_not_declared_says_so_when_no_fire_named_the_field():
    msg = gate._why_not_declared(_corpus(declared_in=(1, 2, 3), reason=DOC_ID_REASON),
                                 FN, "mfr")
    assert "NO fire's reasons name `mfr`" in msg
    assert "IS declared" not in msg


def test_why_not_declared_reports_a_missing_flag_before_anything_else():
    """A MISSING flag and a flag about the WRONG field are different defects with
    different fixes, and the flag comes first: there is nothing to read."""
    msg = gate._why_not_declared(_corpus(flagged=(2, 3)), FN, "mfr")
    assert "needs_review is not True in fire(s) [1]" in msg


def test_why_not_declared_on_one_fire_names_that_fire():
    """The blank-fire rule asks about one fire only."""
    msg = gate._why_not_declared(_corpus(declared_in=(2,)), FN, "mfr", fires=(3,))
    assert "needs_review=True in fire 3" in msg
    assert "NO fire's reasons name `mfr`" in msg


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------

def test_declined_lines_say_n_of_three_and_which_fires():
    line = gate.declined_lines(
        gate.classify_declined(_blank_rows(), _corpus(), _tyc_totals()))[0]
    assert "DECLINED in 1 of 3 fires" in line
    assert "fire(s) [2] withdrew it and said so" in line
    assert "fire(s) [1, 3] published the ground-truth value" in line
    assert "Not unstable and not wrong" in line


def test_declined_lines_carry_no_document_value():
    """The basis is the field name and the verb. The withdrawn value stays out."""
    line = gate.declined_lines(
        gate.classify_declined(_blank_rows(), _corpus(), _tyc_totals()))[0]
    assert "TE Conne" not in line and "Vishay" not in line


def _wh(**kw):
    h = {"mfr": VALUE, "doc_id": "PCN-24-210412", "revision": None, "doc_type": "PCN",
         "pub_date": "2024-04-12", "doc_level_ltb_date": None}
    h.update(kw)
    return h


def _write_fire(tmp_path, n, written, needs_review, reasons, header_totals):
    corpus = {FN: {"ok": True, "needs_review": needs_review,
                   "review_reasons": list(reasons), "written_header": written,
                   "content_hash": "sha256:aaa"}}
    cp, sp = tmp_path / f"corpus_f{n}.json", tmp_path / f"score_f{n}.json"
    cp.write_text(json.dumps(corpus), encoding="utf-8")
    sp.write_text(json.dumps({"totals": {"exact": 1, "gt": 1, "spurious": 0,
                                         "missing": 0, "malformed": 0},
                              "header_totals": header_totals}), encoding="utf-8")
    return {"n": n, "exit": 0, "started_at": "t", "ended_at": "t", "elapsed_s": 1,
            "log": f"f{n}.log", "log_path": str(tmp_path / f"f{n}.log"),
            "corpus_path": str(cp), "score_path": str(sp), "seal_path": None}


def test_the_report_carries_a_declined_section_with_the_strict_verdict_beside_it(
        tmp_path, monkeypatch):
    """End to end through `score_fires`: the fire set that produced the 11-11 red,
    classified, reported in its own section, and still red in the strict view."""
    monkeypatch.setattr(gate, "run_header_agreement", lambda base_dir, logs: (0, ""))
    monkeypatch.setattr(gate, "check_declared_bytes", lambda a, b: [])
    totals = _tyc_totals()
    fires = [_write_fire(tmp_path, n, _wh(mfr=None) if n == 2 else _wh(),
                         True, [MFR_WITHDRAWN] if n == 2 else [], totals[n])
             for n in (1, 2, 3)]
    report, _ = gate.score_fires(str(tmp_path), fires)

    assert report["written_agreement"]["verdicts"][FN] == "BLANK"
    assert [(r["notice"], r["field"], r["declined_in"]) for r in report["declined"]] \
        == [(FN, "mfr", 1)]
    assert report["blocking"] == []
    assert report["exempted"] == []
    assert report["verdict"] == "pass"
    # THE SAFETY, measured: the blank row and the ground-truth failure both still count.
    assert report["strict_verdict"] == "fail"
    assert report["header_correctness"]["failing_notices"] == [FN]

    md = gate.render_markdown(report, str(tmp_path), "cmd", ["f1.log"])
    assert "## Declined" in md
    assert "DECLINED in 1 of 3 fires" in md
    assert ("Strict verdict, which grants no exemptions and classifies nothing: "
            "**FAIL** — every row above still counts there." ) in md


def test_the_declined_section_renders_none_on_a_clean_fire_set(tmp_path, monkeypatch):
    """A section that only appears when it fires is a section a reader cannot trust the
    absence of."""
    monkeypatch.setattr(gate, "run_header_agreement", lambda base_dir, logs: (0, ""))
    monkeypatch.setattr(gate, "check_declared_bytes", lambda a, b: [])
    fires = [_write_fire(tmp_path, n, _wh(), False, [], _totals()) for n in (1, 2, 3)]
    report, _ = gate.score_fires(str(tmp_path), fires)
    assert report["declined"] == [] and report["declined_lines"] == []
    md = gate.render_markdown(report, str(tmp_path), "cmd", ["f1.log"])
    assert "## Declined" in md
    assert "Strict verdict, which grants no exemptions and classifies nothing: **PASS**" in md
