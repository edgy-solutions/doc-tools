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


# 2a -----------------------------------------------------------------------
def test_a_case_only_difference_is_agreement_not_a_disagreement():
    """THE 2026-11-02 RULING. Three fires wrote TI's `mfr` as
    `['TEXAS INSTRUMENTS', 'TEXAS INSTRUMENTS', 'Texas Instruments']` on
    identical bytes. The SCORER credits that pair -- comparison is
    canonical-after-alias and `pcn_score._fold_text` folds case -- while this
    arm blocked on it, so one report held two standards for one string."""
    res = gate.compare_written_headers(
        _fires(_wh(mfr="TEXAS INSTRUMENTS"), _wh(mfr="TEXAS INSTRUMENTS"),
               _wh(mfr="Texas Instruments")))
    assert res["verdicts"][FN] == "agree"
    assert res["disagreements"] == []
    blocking, exempted = gate.apply_written_arm(
        res, _reviews(f1=False, f2=False, f3=False))
    assert blocking == [] and exempted == []


# 2b -----------------------------------------------------------------------
def test_a_difference_beyond_case_still_blocks_and_prints_what_was_written():
    """The arm keeps its teeth. The shape this same field took on 2026-10-29 --
    the full legal name against a shouted short one -- is not a case variant and
    still blocks, and the evidence prints what each fire WROTE, never the key it
    was compared by.

    THIS NOW PINS THE FALLBACK, NOT THE GATE'S VERDICT ON TI. It passes no
    specs, which is the no-ground-truth comparison; under TI's real
    declarations these same three reads unify, because the `accepted` set names
    the shouted form verbatim-correct for that notice (2e, ruled 2026-11-08).
    The two live together on purpose: a notice ground truth says nothing about
    is still held to the stricter reading."""
    res = gate.compare_written_headers(
        _fires(_wh(mfr="Texas Instruments Incorporated"),
               _wh(mfr="Texas Instruments Incorporated"),
               _wh(mfr="TEXAS INSTRUMENTS")))
    assert res["verdicts"][FN] == "DISAGREE"
    assert res["disagreements"] == [
        (FN, "mfr", ["Texas Instruments Incorporated",
                     "Texas Instruments Incorporated", "TEXAS INSTRUMENTS"])]
    blocking, _ = gate.apply_written_arm(
        res, _reviews(f1=False, f2=False, f3=False))
    assert len(blocking) == 1 and "TEXAS INSTRUMENTS" in blocking[0]


# 2c -----------------------------------------------------------------------
def test_case_is_folded_but_whitespace_is_not():
    """`_fold_text` collapses whitespace as well as case; this equality key
    deliberately stops at case. Two fires that wrote differently-spaced values
    read the field differently, and that stays a disagreement."""
    res = gate.compare_written_headers(
        _fires(_wh(mfr="TE Connectivity"), _wh(mfr="TE  Connectivity"),
               _wh(mfr="TE Connectivity")))
    assert res["verdicts"][FN] == "DISAGREE"


# --------------------------------------------------------------------------
# THE 2026-11-08 RULING: the arm compares CANONICAL FORMS, not strings.
#
# These pass the REAL declarations out of scripts/pcn_ground_truth.json rather
# than a hand-made stand-in, which is deliberate: the gate must agree with the
# scorer, the scorer reads that file, and a form added or withdrawn there has to
# move both. 2a-2c above pass no specs and keep measuring the FALLBACK, which is
# still what runs for a notice ground truth does not declare.

SPECS = gate.written_header_specs()
TI = "TI_PCN_20210316000.pdf"
ONSEMI = "onsemi_Generic_IPCN25300X.pdf"


def _as(fn, under=FN):
    """One notice's real declarations, keyed to the filename these fires use."""
    return {under: SPECS[fn]}


# 2d -----------------------------------------------------------------------
def test_the_spec_loader_drops_prose_keys_and_covers_the_corpus():
    assert len(SPECS) == 10                       # all ten notices declare headers
    assert "_note" not in SPECS[TI]               # prose for a reader, not a field
    assert SPECS[TI]["mfr"]["value"] == "Texas Instruments Incorporated"
    assert all("mfr" in s for s in SPECS.values())


# 2e -----------------------------------------------------------------------
def test_an_accepted_spelling_unifies_and_reverses_the_2026_10_29_block():
    """THE REVERSAL, as a test. 2b holds these same three reads apart and is
    still right about the fallback; here TI's own `accepted` set declares
    `TEXAS INSTRUMENTS` a verbatim-correct reading OF THIS NOTICE, so all three
    resolve to one canonical form and the arm has nothing to block."""
    res = gate.compare_written_headers(
        _fires(_wh(mfr="Texas Instruments Incorporated"),
               _wh(mfr="Texas Instruments Incorporated"),
               _wh(mfr="TEXAS INSTRUMENTS")),
        specs=_as(TI))
    assert res["disagreements"] == []
    assert res["verdicts"][FN] == "agree"
    # `pub_date` is declared too and was compared -- as strings, since these
    # reads resolve to no canonical form. Listed here means ground truth was
    # AVAILABLE for the field, not that every read resolved.
    assert res["canonical"][FN] == ["mfr", "pub_date"]
    blocking, exempted = gate.apply_written_arm(
        res, _reviews(f1=False, f2=False, f3=False))
    assert blocking == [] and exempted == []


# 2f -----------------------------------------------------------------------
def test_a_declared_distractor_never_unifies():
    """onsemi's `ONSEM.` sits in the spec's `not` block: a named trap, not a
    spelling. It resolves to no canonical form, falls back to the string key and
    keeps the arm's teeth -- which is why the gate stays red on onsemi, and
    correctly so."""
    res = gate.compare_written_headers(
        _fires(_wh(mfr="onsemi"), _wh(mfr="ONSEM."), _wh(mfr="onsemi")),
        specs=_as(ONSEMI))
    assert res["verdicts"][FN] == "DISAGREE"
    assert res["disagreements"] == [(FN, "mfr", ["onsemi", "ONSEM.", "onsemi"])]
    blocking, _ = gate.apply_written_arm(res, _reviews(f1=False, f2=False, f3=False))
    assert len(blocking) == 1 and "ONSEM." in blocking[0]


# 2g -----------------------------------------------------------------------
def test_the_same_failing_read_in_every_fire_is_still_agreement():
    """Three fires that wrote one declared distractor read the field the SAME
    way. Whether that reading is right is the correctness arm's question; this
    arm asks whether the fires differ, and they do not."""
    res = gate.compare_written_headers(
        _fires(_wh(mfr="ONSEM."), _wh(mfr="ONSEM."), _wh(mfr="ONSEM.")),
        specs=_as(ONSEMI))
    assert res["verdicts"][FN] == "agree" and res["disagreements"] == []


# 2h -----------------------------------------------------------------------
def test_a_misformatted_read_unifies_although_it_fails_correctness():
    """Why `_WRITTEN_UNIFYING` is written out longhand rather than derived as
    HEADER_FAILURES' complement: `misformatted` is IN that tuple -- it fails the
    correctness arm -- and it unifies HERE, because a mangled spelling of an
    accepted form still carries the content the page printed."""
    assert "misformatted" in gate.pcn_score.HEADER_FAILURES
    scored = gate.pcn_score.score_header_field("mfr", "te  connectivity",
                                               SPECS[FN]["mfr"])
    assert scored["status"] == "misformatted"
    res = gate.compare_written_headers(
        _fires(_wh(mfr="TE Connectivity"), _wh(mfr="te  connectivity"),
               _wh(mfr="TE")),
        specs=_as(FN))
    assert res["verdicts"][FN] == "agree"


# 2i -----------------------------------------------------------------------
def test_one_day_written_two_ways_unifies_and_a_different_day_does_not():
    """Dates resolve through `normalize_date`, so one day spelled two ways is one
    reading -- and the day itself still has to match."""
    same = gate.compare_written_headers(
        _fires(_wh(doc_level_ltb_date="2024-06-06"),
               _wh(doc_level_ltb_date="06-Jun-2024"),
               _wh(doc_level_ltb_date="2024-06-06")),
        specs=_as(FN))
    assert same["verdicts"][FN] == "agree"
    other = gate.compare_written_headers(
        _fires(_wh(doc_level_ltb_date="2024-06-06"),
               _wh(doc_level_ltb_date="2024-06-07"),
               _wh(doc_level_ltb_date="2024-06-06")),
        specs=_as(FN))
    assert other["verdicts"][FN] == "DISAGREE"


# 2j -----------------------------------------------------------------------
def test_a_value_where_ground_truth_expects_none_unifies_nothing():
    """TI declares `doc_level_ltb_date` EXPECT-ABSENT -- the page establishes no
    day -- so a fire that wrote one scores `hallucinated`, which resolves to no
    canonical form. Two spellings of ONE day disagree here where 2i agrees, and
    the difference is the declaration rather than the strings."""
    spec = SPECS[TI]["doc_level_ltb_date"]
    assert spec.get("value") is None and spec.get("expect_absent") is True
    assert gate.pcn_score.score_header_field(
        "doc_level_ltb_date", "2021-03-16", spec)["status"] == "hallucinated"
    res = gate.compare_written_headers(
        _fires(_wh(doc_level_ltb_date="2021-03-16"),
               _wh(doc_level_ltb_date="16-Mar-2021"),
               _wh(doc_level_ltb_date="2021-03-16")),
        specs=_as(TI))
    assert res["verdicts"][FN] == "DISAGREE"


# 2j' ----------------------------------------------------------------------
def test_a_pending_field_unifies_nothing():
    """`pending` -- ground truth declares the field and records no established
    value for it -- resolves to no canonical form either, so the comparison
    stays the case-folded one.

    HAND-MADE, and the only spec here that is: no notice carries this shape
    today. TI's one value-less field is expect-absent (above), which the scorer
    diagnoses differently and which would hide this status if it were the only
    thing covering it."""
    spec = {"status": "not yet established from the page"}
    assert gate.pcn_score.score_header_field("mfr", "TE", spec)["status"] == "pending"
    res = gate.compare_written_headers(
        _fires(_wh(mfr="TE Connectivity"), _wh(mfr="TE"), _wh(mfr="TE")),
        specs={FN: {"mfr": spec}})
    assert res["verdicts"][FN] == "DISAGREE"
    # the same three reads, against the REAL spec, are one name read three ways
    assert gate.compare_written_headers(
        _fires(_wh(mfr="TE Connectivity"), _wh(mfr="TE"), _wh(mfr="TE")),
        specs=_as(FN))["verdicts"][FN] == "agree"


# 2k -----------------------------------------------------------------------
def test_the_fallback_is_stricter_than_the_canonical_comparison():
    """The no-ground-truth path separates more, never less. Stated as a test so
    that a caller passing no specs can never be read as a weakening."""
    reads = _fires(_wh(mfr="Texas Instruments Incorporated"),
                   _wh(mfr="TEXAS INSTRUMENTS"),
                   _wh(mfr="Texas Instruments"))
    assert gate.compare_written_headers(reads)["verdicts"][FN] == "DISAGREE"
    assert gate.compare_written_headers(reads, specs={})["verdicts"][FN] == "DISAGREE"
    assert gate.compare_written_headers(
        reads, specs=_as(TI))["verdicts"][FN] == "agree"
    assert gate.compare_written_headers(reads)["canonical"] == {}


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


# --------------------------------------------------------------------------
# End to end: the gate loads the specs itself, and the report says which
# comparison produced its verdicts.

def test_the_report_names_which_fields_were_compared_canonically(
        tmp_path, monkeypatch):
    """`score_fires` calls `written_header_specs()` -- the arm is not given its
    ground truth by a caller, so an operator cannot run the gate without it.
    `doc_level_ltb_date` is absent from the list because `_wh()` leaves it blank
    in every fire: all-blank is agreement on an absence and nothing is compared.
    `doc_type` is absent because ground truth does not declare it."""
    report = _score(tmp_path, monkeypatch, 0, "", [_wh(), _wh(), _wh()])
    assert report["written_agreement"]["canonical"] == {FN: ["mfr", "pub_date"]}
    assert report["written_agreement"]["verdicts"] == {FN: "agree"}
    md = gate.render_markdown(report, str(tmp_path), "cmd", ["f1.log"])
    assert "Compared by CANONICAL FORM" in md
    assert "2 field(s) across 1 notice(s)" in md


def test_a_real_declared_spelling_no_longer_blocks_the_whole_report(
        tmp_path, monkeypatch):
    """The TI pair that produced two standards in one report: the scorer credited
    it and this gate blocked on it. One report, one standard -- and the parts of
    the verdict that are not this arm's are untouched."""
    report = _score(tmp_path, monkeypatch, 0, "",
                    [_wh(mfr="TE Connectivity"), _wh(mfr="TE CONNECTIVITY"),
                     _wh(mfr="TE")])
    assert report["written_agreement"]["verdicts"] == {FN: "agree"}
    assert not any("WRITTEN header fields disagree" in b
                   for b in report["blocking"])
