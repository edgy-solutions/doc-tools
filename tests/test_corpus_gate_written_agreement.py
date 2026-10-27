"""The corpus gate's blocking header arm measures the WRITTEN value.

Ruling 2026-10-26: the blocking arm compares `written_header` across the fires; the raw
plain-mode comparison stays as an advisory `unstable_raw` report row; a header field that
is blank in one fire and populated in another is needs_review on the BLANK fire, always.

No cluster, no S3, no network, no doc_tools import: every input is a plain dict. The
scripts are loaded by path, as in test_corpus_gate_written_headers.py.
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
hdr = _load("pcn_header_agreement")

FN = "TYC-PCN-24-210412.pdf"


def _wh(**kw):
    h = {"mfr": "TE Connectivity", "doc_id": "PCN-24-210412", "revision": None,
         "doc_type": "PCN", "pub_date": "2024-04-12", "doc_level_ltb_date": None}
    h.update(kw)
    return h


def _fires(*headers, fn=FN):
    """{fire_n: {filename: written_header}} from one header per fire."""
    return {i + 1: {fn: h} for i, h in enumerate(headers)}


# Reasons in the product's own words (see the vocabulary in pcn_corpus_gate.py).
DOC_ID_REASON = ("doc_id taken from the document ('PCN-24-210412', printed at "
                 "page 1 header)")
MFR_REFUSED = "header.mfr refused: 'TE' is not cited by anything in this document"
PUB_REFUSED = "header.pub_date refused: '2024-04-12' is not cited"
PASS_FAILED = "header pass failed: TimeoutError"
WITNESS_DISABLED = "region witness DISABLED for this document: no raster"
LTB_LOST = ("region witness LOST the ltb region on page 1 (unreadable); header fields "
            "doc_level_ltb_date were neither supplied nor corroborated")


def _reviews(reasons=None, **by_fire):
    """corpus_by_fire: _reviews(f1=False, f2=True, ...). `reasons` is one list for every
    fire, or {fire_n: list}; omitted, no reasons are carried (the old shape)."""
    out = {}
    for k, v in by_fire.items():
        n = int(k[1:])
        rs = reasons.get(n, []) if isinstance(reasons, dict) else (reasons or [])
        out[n] = {FN: {"needs_review": v, "review_reasons": list(rs)}}
    return out


# 1 ------------------------------------------------------------------------
def test_identical_written_headers_agree_and_block_nothing():
    res = gate.compare_written_headers(_fires(_wh(), _wh(), _wh()))
    assert res["verdicts"] == {FN: "agree"}
    assert not (res["disagreements"] or res["blank_rows"] or res["absent"]
                or res["no_written"])
    blocking, exempted = gate.apply_written_arm(res, _reviews(f1=False, f2=False, f3=False))
    assert blocking == [] and exempted == []


# 2 ------------------------------------------------------------------------
def test_a_populated_value_difference_without_needs_review_blocks():
    res = gate.compare_written_headers(
        _fires(_wh(mfr="TE Connecvity"), _wh(mfr="TE"), _wh(mfr="TE")))
    assert res["verdicts"][FN] == "DISAGREE"
    assert res["disagreements"] == [(FN, "mfr", ["TE Connecvity", "TE", "TE"])]
    blocking, exempted = gate.apply_written_arm(
        res, _reviews(f1=False, f2=False, f3=False))
    assert len(blocking) == 1 and "WRITTEN header fields disagree" in blocking[0]
    assert exempted == []


# 3 ------------------------------------------------------------------------
def test_the_same_difference_declared_in_all_three_fires_is_exempted():
    res = gate.compare_written_headers(
        _fires(_wh(mfr="TE Connecvity"), _wh(mfr="TE"), _wh(mfr="TE")))
    blocking, exempted = gate.apply_written_arm(
        res, _reviews([MFR_REFUSED], f1=True, f2=True, f3=True))
    assert blocking == []
    assert len(exempted) == 1 and "all three fires" in exempted[0]


# 4 ------------------------------------------------------------------------
def test_revision_and_doc_id_are_not_in_the_written_arm():
    assert "revision" not in gate.WRITTEN_ARM_FIELDS
    assert "doc_id" not in gate.WRITTEN_ARM_FIELDS
    # imported from the instrument (gate.hdr_agreement), not a second literal
    assert gate.WRITTEN_ARM_FIELDS == hdr.WRITTEN_FIELDS

    # the 2683 shape: revision rotates and doc_id differs, everything compared agrees
    res = gate.compare_written_headers(_fires(
        _wh(revision="A", doc_id="PCN-2683"),
        _wh(revision="B", doc_id="PCN #: 2683"),
        _wh(revision=None, doc_id="PCN-2683")))
    assert res["verdicts"] == {FN: "agree"}
    blocking, exempted = gate.apply_written_arm(res, _reviews(f1=False, f2=False, f3=False))
    assert blocking == [] and exempted == []


# 5 ------------------------------------------------------------------------
def test_a_blank_fire_without_needs_review_blocks_and_names_fire_and_value():
    res = gate.compare_written_headers(
        _fires(_wh(), _wh(pub_date=None), _wh()))
    assert res["verdicts"][FN] == "BLANK"
    assert res["disagreements"] == []          # a blank is not a value difference
    assert [(r[0], r[1], r[3]) for r in res["blank_rows"]] == [(FN, "pub_date", [2])]
    # the populated fires' own needs_review is irrelevant to the blank fire
    blocking, exempted = gate.apply_written_arm(res, _reviews(f1=True, f2=False, f3=True))
    assert len(blocking) == 1 and exempted == []
    assert "fire 2" in blocking[0]
    assert "pub_date" in blocking[0]
    assert "2024-04-12" in blocking[0]


# 6 ------------------------------------------------------------------------
def test_needs_review_on_the_blank_fire_alone_exempts():
    res = gate.compare_written_headers(_fires(_wh(), _wh(pub_date=""), _wh()))
    # fires 1 and 3 say nothing: requiring all three would make the correct fires block
    blocking, exempted = gate.apply_written_arm(
        res, _reviews({2: [PUB_REFUSED]}, f1=False, f2=True, f3=False))
    assert blocking == []
    assert len(exempted) == 1 and "fire 2" in exempted[0]


# 7 ------------------------------------------------------------------------
def test_every_fire_blank_is_agreement_on_an_absence():
    res = gate.compare_written_headers(
        _fires(_wh(pub_date=None), _wh(pub_date=""), _wh(pub_date=None)))
    assert res["verdicts"] == {FN: "agree"}
    assert res["blank_rows"] == [] and res["disagreements"] == []
    blocking, exempted = gate.apply_written_arm(res, _reviews(f1=False, f2=False, f3=False))
    assert blocking == [] and exempted == []


# 8 ------------------------------------------------------------------------
def test_a_notice_missing_from_one_fire_is_absent_and_blocks_without_exemption():
    from_corpus = {1: {FN: _wh()}, 2: {FN: _wh()}, 3: {"OTHER.pdf": _wh()}}
    res = gate.compare_written_headers(from_corpus)
    assert res["verdicts"][FN] == "ABSENT"
    assert (FN, [3]) in res["absent"]
    # even with every fire declaring, an instrument gap is not exempted
    blocking, exempted = gate.apply_written_arm(res, _reviews(f1=True, f2=True, f3=True))
    assert any(FN in b and "not recorded by fire(s) [3]" in b for b in blocking)
    assert not any(FN in e for e in exempted)


def test_a_notice_no_fire_recorded_is_reported_not_blocked():
    res = gate.compare_written_headers(_fires(_wh(), _wh(), _wh()),
                                       expected={FN, "NEVER.pdf"})
    assert res["unrecorded"] == ["NEVER.pdf"]
    blocking, _ = gate.apply_written_arm(res, _reviews(f1=False, f2=False, f3=False))
    assert blocking == []


# 9 ------------------------------------------------------------------------
def test_a_fire_with_no_written_header_blocks_under_its_own_message():
    res = gate.compare_written_headers({1: {FN: _wh()}, 2: {FN: _wh()}, 3: {}})
    assert (3, None) in res["no_written"]
    assert res["absent"] == [] and res["disagreements"] == []
    blocking, _ = gate.apply_written_arm(res, _reviews(f1=True, f2=True, f3=True))
    assert len(blocking) == 1
    assert "fire 3 recorded no `written_header`" in blocking[0]
    assert "WRITTEN header fields disagree" not in blocking[0]

    # and one notice's entry that is not a header at all
    res = gate.compare_written_headers({1: {FN: _wh()}, 2: {FN: None}, 3: {FN: _wh()}})
    assert (2, FN) in res["no_written"]
    assert res["verdicts"][FN] == "ABSENT"


# 10 -----------------------------------------------------------------------
def _compare(fires, fields, capsys):
    out = hdr.compare(fires, fields)
    return out, capsys.readouterr().out


def test_compare_classifies_blank_vs_populated_apart_from_disagree(capsys):
    fires = [("f1", {"T.pdf": {"mfr": "TE", "pub_date": "2024-04-12"}}),
             ("f2", {"T.pdf": {"mfr": None, "pub_date": "2024-04-12"}}),
             ("f3", {"T.pdf": {"mfr": "TE", "pub_date": "2024-04-12"}})]
    (notices, disagreements, unmeasured, blank_rows), out = _compare(
        fires, ("mfr", "pub_date"), capsys)
    assert disagreements == [] and unmeasured == []
    assert blank_rows == [("T.pdf", "mfr", ["TE", None, "TE"], ["f2"])]
    assert "BLANK" in out and "DISAGREE" not in out
    assert "BLANK vs POPULATED, blank in: ['f2']" in out


def test_compare_not_measured_wins_over_blank(capsys):
    fires = [("f1", {"T.pdf": {"mfr": "TE"}}),
             ("f2", {"T.pdf": {"mfr": None}}),
             ("f3", {"T.pdf": {"other": 1}})]          # f3 never yielded `mfr`
    (_n, disagreements, unmeasured, blank_rows), out = _compare(fires, ("mfr",), capsys)
    assert unmeasured == [("T.pdf", "mfr")]
    assert blank_rows == [] and disagreements == []
    assert "NOT MEASURED" in out


def test_compare_all_blank_is_agreement_and_main_still_fails_on_a_blank_row(
        capsys, tmp_path):
    fires = [("f1", {"T.pdf": {"mfr": None}}), ("f2", {"T.pdf": {"mfr": ""}})]
    (_n, d, u, b), out = _compare(fires, ("mfr",), capsys)
    assert (d, u, b) == ([], [], []) and "agree" in out

    def log(path, mfr):
        block = json.dumps({"mfr": mfr, "doc_id": "X"}, indent=2)
        path.write_text(f"--- T.pdf\n{hdr.MARKER}\n{block}\n", encoding="utf-8")
        return str(path)

    rc = hdr.main([log(tmp_path / "a.log", "TE"), log(tmp_path / "b.log", None)])
    out = capsys.readouterr().out
    assert rc == 1, "a blank-vs-populated field must still fail the script's exit"
    assert "BLANK vs POPULATED" in out


# 11 -----------------------------------------------------------------------
def test_the_plain_parse_keeps_a_blank_row_and_its_forms():
    stdout = (f"{'T.pdf':44s} BLANK\n"
              f"      {'mfr':22s} 'TE' | None | 'TE'   <- BLANK vs POPULATED, blank in: ['f2']\n")
    notices, absent, nm = gate.parse_header_agreement(stdout)
    assert notices["T.pdf"]["verdict"] == "BLANK"
    rows = gate.unstable_raw_rows(notices)
    assert rows == [{"notice": "T.pdf", "field": "mfr", "forms": ["'TE'", "None", "'TE'"]}]


def test_forms_containing_a_bar_are_not_torn():
    forms = gate.split_forms("'a | b' | 'c' | 'a | b'")
    assert forms == ["'a | b'", "'c'", "'a | b'"]


def _write_fire(tmp_path, n, written):
    corpus = {FN: {"ok": True, "needs_review": False, "written_header": written,
                   "content_hash": "sha256:aaa"}}
    cp, sp = tmp_path / f"corpus_f{n}.json", tmp_path / f"score_f{n}.json"
    cp.write_text(json.dumps(corpus), encoding="utf-8")
    sp.write_text(json.dumps({"totals": {"exact": 1, "gt": 1, "spurious": 0,
                                         "missing": 0, "malformed": 0}}), encoding="utf-8")
    return {"n": n, "exit": 0, "started_at": "t", "ended_at": "t", "elapsed_s": 1,
            "log": f"f{n}.log", "log_path": str(tmp_path / f"f{n}.log"),
            "corpus_path": str(cp), "score_path": str(sp), "seal_path": None}


def _score(tmp_path, monkeypatch, plain_exit, plain_stdout, writtens):
    # Isolate the header arms: the parts/seal/bytes terms are other instruments' business
    # and have their own tests. Everything NOT stubbed here is the code under test.
    monkeypatch.setattr(gate, "run_header_agreement",
                        lambda base_dir, logs: (plain_exit, plain_stdout))
    monkeypatch.setattr(gate, "check_header_correctness",
                        lambda totals, corpus: ({}, [], []))
    monkeypatch.setattr(gate, "check_declared_bytes", lambda a, b: [])
    fires = [_write_fire(tmp_path, n, w) for n, w in enumerate(writtens, start=1)]
    report, _ = gate.score_fires(str(tmp_path), fires)
    return report


RAW_2683 = (f"{'PCN-2683.pdf':44s} DISAGREE\n"
            f"      {'doc_id':22s} 'PCN-2683' | 'PCN #: 2683' | 'PCN-2683'\n")


def test_a_raw_disagreement_alone_does_not_block_and_is_kept_as_unstable_raw(
        tmp_path, monkeypatch):
    report = _score(tmp_path, monkeypatch, 1, RAW_2683, [_wh(), _wh(), _wh()])
    assert report["header_agreement"]["exit"] == 1
    assert report["header_agreement"]["blocks"] is False
    assert report["blocking"] == []
    assert report["verdict"] == "pass"
    assert report["strict_verdict"] == "pass"
    assert report["unstable_raw"] == [
        {"notice": "PCN-2683.pdf", "field": "doc_id",
         "forms": ["'PCN-2683'", "'PCN #: 2683'", "'PCN-2683'"]}]
    assert report["written_agreement"]["verdicts"] == {FN: "agree"}
    md = gate.render_markdown(report, str(tmp_path), "cmd", ["f1.log"])
    assert "## Raw reader instability (advisory, never blocks)" in md


def test_a_written_disagreement_still_blocks_whatever_the_raw_exit(tmp_path, monkeypatch):
    report = _score(tmp_path, monkeypatch, 0, "", [_wh(), _wh(mfr="Other"), _wh()])
    assert report["verdict"] == "fail"
    assert any("WRITTEN header fields disagree" in b for b in report["blocking"])
    assert report["strict_verdict"] == "fail"


# --------------------------------------------------------------------------
# Ruling 2026-10-27: the exemption is keyed to the FIELD UNDER TEST.

def _mfr_disagree():
    return gate.compare_written_headers(
        _fires(_wh(mfr="TE Connecvity"), _wh(mfr="TE"), _wh(mfr="TE")))


def _all(reasons):
    return _reviews(reasons, f1=True, f2=True, f3=True)


def test_a_doc_id_reason_does_not_exempt_an_mfr_disagreement():
    """The 10-of-10 case: the doc_id precedence ruling narrates a doc_id reason and sets
    needs_review on every notice, which used to buy every field an exemption."""
    blocking, exempted = gate.apply_written_arm(_mfr_disagree(), _all([DOC_ID_REASON]))
    assert exempted == []
    assert len(blocking) == 1 and "`mfr`" in blocking[0]
    assert "no reason names `mfr`" in blocking[0]
    assert "another field" in blocking[0]


def test_a_refusal_names_one_field_and_exempts_only_that_field():
    res = gate.compare_written_headers(_fires(
        _wh(mfr="TE Connecvity", pub_date="2024-04-12"),
        _wh(mfr="TE", pub_date="2024-04-13"),
        _wh(mfr="TE", pub_date="2024-04-14")))
    blocking, exempted = gate.apply_written_arm(res, _all([MFR_REFUSED]))
    # one notice, two failing fields: one exempted line, one blocking, each naming its field
    assert len(exempted) == 1 and "`mfr`" in exempted[0]
    assert "header.mfr refused" in exempted[0]
    assert len(blocking) == 1 and "`pub_date`" in blocking[0]
    assert "no reason names `pub_date`" in blocking[0]


def test_a_failed_header_pass_exempts_every_field():
    cases = (("mfr", ("A", "B", "B")),
             ("pub_date", ("2024-01-01", "2024-01-02", "2024-01-03")))
    for field, vals in cases:
        res = gate.compare_written_headers(_fires(*[_wh(**{field: v}) for v in vals]))
        blocking, exempted = gate.apply_written_arm(res, _all([PASS_FAILED]))
        assert blocking == [] and len(exempted) == 1 and field in exempted[0]
        assert "header pass failed" in exempted[0]


def test_a_disabled_witness_exempts_every_field():
    blocking, exempted = gate.apply_written_arm(_mfr_disagree(), _all([WITNESS_DISABLED]))
    assert blocking == [] and len(exempted) == 1
    assert "region witness DISABLED" in exempted[0]


def test_a_lost_region_naming_the_field_exempts_it_and_its_source_companion():
    for field in ("doc_level_ltb_date", "doc_level_ltb_date_source"):
        corpus = _all([LTB_LOST])
        assert gate.header_declaration_for_field_in_all_fires(corpus, FN, field)
        res = {"disagreements": [(FN, field, ["a", "b", "b"])], "blank_rows": [],
               "absent": [], "no_written": []}
        blocking, exempted = gate.apply_written_arm(res, corpus)
        assert blocking == [] and len(exempted) == 1
    # and says nothing about a field it does not name
    assert not gate.header_declaration_for_field_in_all_fires(_all([LTB_LOST]), FN, "mfr")


def test_the_source_base_strips_one_suffix_only():
    assert gate._declaration_field_base("doc_level_ltb_date_source") == "doc_level_ltb_date"
    assert gate._declaration_field_base("mfr") == "mfr"
    assert gate._declaration_field_base("x_source_source") == "x_source"


def test_a_declaration_in_two_fires_of_three_exempts_nothing():
    corpus = _reviews({1: [MFR_REFUSED], 2: [MFR_REFUSED], 3: [DOC_ID_REASON]},
                      f1=True, f2=True, f3=True)
    blocking, exempted = gate.apply_written_arm(_mfr_disagree(), corpus)
    assert exempted == [] and len(blocking) == 1


def test_a_perfect_reason_without_the_flag_exempts_nothing():
    corpus = _reviews([MFR_REFUSED], f1=False, f2=False, f3=False)
    assert not gate.header_declaration_for_field_in_all_fires(corpus, FN, "mfr")
    blocking, exempted = gate.apply_written_arm(_mfr_disagree(), corpus)
    assert exempted == [] and len(blocking) == 1
    assert "needs_review is not True" in blocking[0]


def test_a_blank_fire_is_exempted_only_by_a_declaration_naming_its_field():
    res = gate.compare_written_headers(_fires(_wh(), _wh(pub_date=None), _wh()))
    named = _reviews({2: [PUB_REFUSED]}, f1=False, f2=True, f3=False)
    blocking, exempted = gate.apply_written_arm(res, named)
    assert blocking == [] and len(exempted) == 1 and "header.pub_date refused" in exempted[0]
    other = _reviews({2: [DOC_ID_REASON]}, f1=False, f2=True, f3=False)
    blocking, exempted = gate.apply_written_arm(res, other)
    assert exempted == [] and len(blocking) == 1
    assert "no reason names `pub_date`" in blocking[0] and "fire 2" in blocking[0]


# the doc_id NARRATION is not a declaration, so it is absent from these lists
DOC_ID_REFUSED = "header.doc_id refused: x is not cited"


def test_the_identity_half_is_keyed_to_the_field_that_actually_moved():
    """Ruling 2026-10-27, applied to the last arm that was keyed to the PAIR: a
    declaration about `doc_id` must not exempt an `mfr` that moved."""
    moving_mfr = {FN: ("mfr",)}
    blocking, exempted = gate.apply_declaration_rule(
        [], [FN], _all([MFR_REFUSED]), moving_mfr)
    assert blocking == [] and len(exempted) == 1 and "`mfr` differs" in exempted[0]

    blocking, exempted = gate.apply_declaration_rule(
        [], [FN], _all([DOC_ID_REFUSED]), moving_mfr)
    assert exempted == [] and len(blocking) == 1
    assert "no reason names `mfr`" in blocking[0] and "undeclared: mfr" in blocking[0]

    # a header-WIDE reason still covers whichever field moved
    blocking, exempted = gate.apply_declaration_rule(
        [], [FN], _all([PASS_FAILED]), moving_mfr)
    assert blocking == [] and len(exempted) == 1


def test_both_halves_moving_need_both_declared():
    both = {FN: ("mfr", "doc_id")}
    blocking, exempted = gate.apply_declaration_rule(
        [], [FN], _all([MFR_REFUSED]), both)
    assert exempted == [] and len(blocking) == 1
    assert "undeclared: doc_id" in blocking[0]
    blocking, exempted = gate.apply_declaration_rule(
        [], [FN], _all([MFR_REFUSED, DOC_ID_REFUSED]), both)
    assert blocking == [] and len(exempted) == 1


def test_an_unsupplied_moving_half_requires_every_identity_field():
    """No moving-field map (the pre-2026-10-27 call shape, and the case where identity
    could not be FORMED in some fire): one field declared exempts nothing."""
    blocking, exempted = gate.apply_declaration_rule([], [FN], _all([MFR_REFUSED]))
    assert exempted == [] and len(blocking) == 1 and "undeclared: doc_id" in blocking[0]


def test_compute_stability_reports_which_half_moved():
    def recs(*keys):
        return {n: {FN: {"key": k}} for n, k in enumerate(keys, start=1)}

    sep = gate.notice_identity.SEPARATOR
    mfr_moved = recs(*[sep.join([m, "PCN-1", "A"]) for m in ("TE", "TE Conn", "TE")])
    unstable, revision, moving = gate.compute_stability(mfr_moved, [FN])
    assert unstable == [FN] and revision == [] and moving == {FN: ("mfr",)}

    doc_moved = recs(*[sep.join(["TE", d, "A"]) for d in ("PCN-1", "PCN-2", "PCN-1")])
    _u, _r, moving = gate.compute_stability(doc_moved, [FN])
    assert moving == {FN: ("doc_id",)}

    # identity could not be FORMED in one fire: no moving half is named, so both
    # fields are required rather than neither
    missing = recs(sep.join(["TE", "PCN-1", "A"]), None, sep.join(["TE", "PCN-1", "A"]))
    unstable, _r, moving = gate.compute_stability(missing, [FN])
    assert unstable == [FN] and moving == {FN: ("mfr", "doc_id")}

    rev_only = recs(*[sep.join(["TE", "PCN-1", r]) for r in ("A", "B", "A")])
    unstable, revision, moving = gate.compute_stability(rev_only, [FN])
    assert unstable == [] and revision == [FN] and moving == {}
