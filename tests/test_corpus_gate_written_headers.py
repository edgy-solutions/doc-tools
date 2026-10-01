"""The release gate's WRITTEN-HEADER source, the cross-fire bytes check, and the
rates block (`scripts/pcn_corpus_gate.py` + `scripts/pcn_corpus_run.py`).

Why these three together: they are the pieces that let the gate reach its verdict
from each fire's own JSON instead of from a probe of the fire's stdout. The log
probe stays as a fallback for pins that predate the recording, so both paths are
pinned here — including, explicitly, that they agree.

No S3, no LLM, no network. `scripts/` is imported by path, following
`tests/test_header_agreement_instrument.py`: `scripts/` is not importable and an
`__init__.py` there would make a measurement harness look like library code.
"""
import importlib.util
import io
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    # pcn_corpus_gate imports its sibling pcn_header_agreement, and pcn_corpus_run
    # imports pcn_score / pcn_crop_seal, by plain module name.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("pcn_corpus_gate")
run = _load("pcn_corpus_run")


def _notice(content_hash="sha256:aaa", **header):
    h = {"mfr": "TE Connectivity", "doc_id": "PCN-24-210412", "revision": None,
         "doc_type": "PCN", "pub_date": "2024-04-12", "doc_level_ltb_date": None}
    h.update(header)
    return {"ok": True, "written_header": h, "content_hash": content_hash}


# ---------------------------------------------------------------------------
# headers_from_corpus — the preferred source
# ---------------------------------------------------------------------------

def test_headers_come_straight_off_the_recorded_written_header():
    out = gate.headers_from_corpus({"A.pdf": _notice()})
    assert out["A.pdf"]["mfr"] == "TE Connectivity"
    # revision is carried, which the log path could not promise: it is in neither of
    # pcn_header_agreement's compared tuples.
    assert "revision" in out["A.pdf"]


def test_a_failed_notice_is_skipped_rather_than_recorded_empty():
    """An errored notice has no header to compare. Recording {} for it would read as
    'measured, and every field was absent', which is a different claim."""
    entry = _notice()
    entry["ok"] = False
    assert gate.headers_from_corpus({"A.pdf": entry}) == {}


def test_an_image_that_records_no_written_header_yields_nothing():
    assert gate.headers_from_corpus({"A.pdf": {"ok": True}}) == {}
    assert gate.headers_from_corpus(None) == {}
    assert gate.headers_from_corpus({}) == {}


def test_a_non_dict_entry_does_not_raise():
    assert gate.headers_from_corpus({"A.pdf": "unexpected"}) == {}


def test_source_selection_is_all_or_nothing_across_the_fire_set():
    """Mixing a recorded header for one fire with a log-recovered one for another
    would compare two different derivations and call the difference instability. The
    selection in `score_fires` is `all(...)`, so one fire without the recording sends
    the whole set to the fallback."""
    per_fire = {1: gate.headers_from_corpus({"A.pdf": _notice()}),
                2: gate.headers_from_corpus({"A.pdf": {"ok": True}}),
                3: gate.headers_from_corpus({"A.pdf": _notice()})}
    assert not all(per_fire.values())


# ---------------------------------------------------------------------------
# check_same_bytes — the assumption the whole instrument rests on
# ---------------------------------------------------------------------------

def test_constant_bytes_across_fires_block_nothing():
    corpus = {n: {"A.pdf": _notice("sha256:aaa")} for n in (1, 2, 3)}
    assert gate.check_same_bytes(corpus) == []


def test_a_fire_that_read_different_bytes_blocks():
    """Three fires over one document is the premise of every cross-fire finding. If
    the underlying PDF changed mid-set, two fires disagreeing is CORRECT behaviour on
    two documents, and reporting it as instability would be wrong."""
    corpus = {1: {"A.pdf": _notice("sha256:aaa")},
              2: {"A.pdf": _notice("sha256:bbb")},
              3: {"A.pdf": _notice("sha256:aaa")}}
    msgs = gate.check_same_bytes(corpus)
    assert len(msgs) == 1
    assert "A.pdf" in msgs[0] and "same source bytes" in msgs[0]


def test_an_unrecordable_bytes_check_is_not_a_pass():
    """No hash recorded => no blocking message, but coverage must not read verified so
    the report says NOT VERIFIABLE rather than implying it was."""
    corpus = {n: {"A.pdf": {"ok": True}} for n in (1, 2, 3)}
    assert gate.check_same_bytes(corpus) == []
    assert gate.content_hashes_by_fire(corpus) == {}
    assert gate.bytes_coverage(corpus)["complete"] is False


def test_a_hash_recorded_by_only_one_fire_is_not_a_disagreement():
    corpus = {1: {"A.pdf": _notice("sha256:aaa")},
              2: {"A.pdf": {"ok": True}},
              3: {"A.pdf": {"ok": True}}}
    assert gate.check_same_bytes(corpus) == []


# ---------------------------------------------------------------------------
# bytes_coverage — the check must not claim more than it measured
# ---------------------------------------------------------------------------

def test_full_coverage_is_reported_complete():
    corpus = {n: {"A.pdf": _notice("sha256:aaa"), "B.pdf": _notice("sha256:bbb")}
              for n in (1, 2, 3)}
    cov = gate.bytes_coverage(corpus)
    assert cov["complete"] is True
    assert cov["unverified"] == []
    assert cov["notices_scored"] == 2


def test_partial_coverage_is_not_complete_and_names_the_gap():
    """The defect this function exists for. Measured 2026-09-30: 11 of 22 real manifests
    carry `source_key`, so some notices recorded a hash and some did not. A set-wide
    `bool(hashes)` read True and the report claimed "verified" over documents that were
    never hashed."""
    corpus = {n: {"A.pdf": _notice("sha256:aaa"), "B.pdf": {"ok": True}}
              for n in (1, 2, 3)}
    cov = gate.bytes_coverage(corpus)
    assert cov["complete"] is False
    assert cov["verified"] == ["A.pdf"]
    assert cov["unverified"] == ["B.pdf"]


def test_a_notice_hashed_by_only_some_fires_counts_as_unverified():
    """Two fires agreeing says nothing about the third fire's input."""
    corpus = {1: {"A.pdf": _notice("sha256:aaa")},
              2: {"A.pdf": _notice("sha256:aaa")},
              3: {"A.pdf": {"ok": True}}}
    cov = gate.bytes_coverage(corpus)
    assert cov["complete"] is False
    assert cov["unverified"] == ["A.pdf"]


def test_a_failed_notice_is_not_counted_against_coverage():
    """An errored notice was not scored, so it is not a coverage gap — counting it would
    make every run with one failure read as incompletely verified."""
    corpus = {n: {"A.pdf": _notice("sha256:aaa"),
                  "B.pdf": {"ok": False, "error": "boom"}} for n in (1, 2, 3)}
    cov = gate.bytes_coverage(corpus)
    assert cov["notices_scored"] == 1
    assert cov["complete"] is True


# ---------------------------------------------------------------------------
# The rates block
# ---------------------------------------------------------------------------

REAL_RATES = {
    "documents": 9, "errors": 0, "not_applicable": 0,
    "rates": {"needs_review": {"count": 3, "denominator": 9},
              "crops_near_cap": {"count": 1, "denominator": 9},
              "crops_row_short": {"count": 0, "denominator": 9},
              "text_layer_degraded": {"count": 1, "denominator": 9}},
    "chunk_tally": None,
}


def test_absent_rates_are_reported_as_unavailable_never_as_zero():
    out = gate._render_rates_block(False, None)
    assert "not available" in out
    assert "Not printed as a zero." in out


def test_rates_render_through_the_canonical_renderer():
    out = gate._render_rates_block(True, REAL_RATES)
    assert "INGEST RATES" in out
    assert "needs_review" in out and "3 of 9" in out
    # The nested shape must not leak as a Python repr.
    assert "{'count'" not in out and '"count"' not in out


def test_an_absent_chunk_tally_renders_as_not_observed():
    """written_without_vector is per-CHUNK, and this harness writes no chunk. It must
    read as not observed; a 0 would assert that chunks were written and all carried a
    vector."""
    out = gate._render_rates_block(True, REAL_RATES)
    assert "not observed" in out


def test_an_unexpected_rates_shape_is_reported_verbatim_not_reformatted():
    """A report may be scored over score JSONs from an older image. Presence of
    `rates` does not prove the shape, and a silently reformatted unknown payload would
    look authoritative."""
    out = gate._render_rates_block(True, {"needs_review": 0.33})
    assert "not in the shape" in out
    assert "needs_review" in out


# ---------------------------------------------------------------------------
# pcn_corpus_run.written_header — the producer side
# ---------------------------------------------------------------------------

class _Notice:
    def __init__(self, **kw):
        defaults = {"mfr": "TE Connectivity", "doc_id": "PCN-24-210412",
                    "revision": "1", "doc_type": "PCN", "pub_date": "2024-04-12",
                    "doc_level_ltb_date": "2024-06-06"}
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


def test_written_header_carries_the_identity_triple_and_the_written_tuple():
    h = run.written_header(_Notice())
    assert set(h) == {"mfr", "doc_id", "revision", "doc_type", "pub_date",
                      "doc_level_ltb_date"}
    assert h["revision"] == "1"


def test_blank_strings_are_normalized_to_none():
    """`SustainmentNotice` stores mfr/pub_date as non-Optional str, so the plugin
    coerces a missing or refused value to "". The log-derived path spells the same
    absence None. Left unnormalized, the gate would report a DISAGREEMENT between two
    sources that both observed absence."""
    h = run.written_header(_Notice(mfr="", pub_date="", doc_level_ltb_date=None))
    assert h["mfr"] is None
    assert h["pub_date"] is None
    assert h["doc_level_ltb_date"] is None


def test_doc_type_is_not_normalized_away():
    """doc_type's "PCN" default is a real written value — it selects the disposition
    ruleset downstream — so it is recorded as written, not blanked."""
    assert run.written_header(_Notice(doc_type="PCN"))["doc_type"] == "PCN"


def test_a_refused_mfr_gives_a_header_that_forms_no_identity_key():
    """The consequence of the normalization above, stated as a test: a refused mfr
    reaches build_identity as falsy and no key is formed, which is the deliberate
    direction (a missed duplicate, not a false match)."""
    from doc_tools.utils import notice_identity as ni
    h = run.written_header(_Notice(mfr=""))
    ident = ni.build_identity(h["mfr"], h["doc_id"], h["revision"])
    assert ident["complete"] is False
    assert ident["key"] is None
    assert "mfr" in ident["note"]


# ---------------------------------------------------------------------------
# The two sources must agree
# ---------------------------------------------------------------------------

def test_the_two_header_sources_produce_the_same_identity_records():
    """Given the same values, the recorded path and the log path must reach the same
    identity. This is what makes the fallback a fallback rather than a second answer.
    """
    values = {"mfr": "TE Connectivity", "doc_id": "PCN-24-210412", "revision": "1"}
    from_corpus = gate.build_identity_records(
        {1: gate.headers_from_corpus({"A.pdf": _notice(**values)})})
    from_log_shape = gate.build_identity_records({1: {"A.pdf": dict(values)}})
    assert from_corpus[1]["A.pdf"]["key"] == from_log_shape[1]["A.pdf"]["key"]
    assert from_corpus[1]["A.pdf"]["key"] is not None


# ---------------------------------------------------------------------------
# source_content_hash — hashed from the SOURCE object, never from text.json
# ---------------------------------------------------------------------------

class _FakeS3:
    def __init__(self, body=None, raises=False, listing=None):
        self.body, self.raises, self.asked = body, raises, []
        self.listing, self.listed = listing or [], []

    def get_object(self, Bucket, Key):  # noqa: N803 (boto3's own signature)
        self.asked.append(Key)
        if self.raises:
            raise RuntimeError("no such key")
        return {"Body": io.BytesIO(self.body)}

    def list_objects_v2(self, Bucket, Prefix):  # noqa: N803
        self.listed.append(Prefix)
        return {"Contents": [{"Key": k} for k in self.listing if k.startswith(Prefix)]}


def test_the_hash_is_taken_over_the_declared_source_key():
    """`source_key` is declared by the producer. Deriving it from `text_location`
    instead would be a path guess that breaks the first time the layout changes."""
    c = _FakeS3(b"%PDF-1.4 ...")
    h = run.source_content_hash(c, {"source_key": "sustainment/inbound/x.pdf",
                                    "text_location": "a/generated/x_pdf/text.json"})
    assert c.asked == ["sustainment/inbound/x.pdf"]
    assert h.startswith("sha256:") and len(h) == len("sha256:") + 64


def test_the_same_bytes_hash_the_same_and_different_bytes_do_not():
    a = run.source_content_hash(_FakeS3(b"same"), {"source_key": "k"})
    b = run.source_content_hash(_FakeS3(b"same"), {"source_key": "k"})
    c = run.source_content_hash(_FakeS3(b"other"), {"source_key": "k"})
    assert a == b != c


def test_a_declared_source_key_wins_over_the_sibling_search():
    """The fallback must not fire when the producer named a key — listing would be work
    done to reach the same answer, and could reach a different one."""
    c = _FakeS3(b"x", listing=["sustainment/inbound/adi/OTHER.pdf"])
    run.source_content_hash(c, {"source_key": "declared/x.pdf"},
                            "sustainment/inbound/adi/generated/x/manifest.json", "x.pdf")
    assert c.asked == ["declared/x.pdf"]
    assert c.listed == []


def test_a_manifest_without_source_key_falls_back_to_the_sibling_pdf():
    """Only 11 of the 22 real manifests carry `source_key` (measured 2026-09-30) — all
    three ADI manifests and six of seven onsemi IPCN ones predate the field. Without this
    the bytes check would be permanently inert on exactly those notices."""
    c = _FakeS3(b"%PDF-1.4", listing=[
        "sustainment/inbound/adi_run3/ADI_PDN_23_0120.pdf",
        "sustainment/inbound/adi_run3/generated/ADI_PDN_23_0120_pdf/text.json",
    ])
    h = run.source_content_hash(
        c, {}, "sustainment/inbound/adi_run3/generated/ADI_PDN_23_0120_pdf/manifest.json",
        "ADI_PDN_23_0120.pdf")
    assert c.listed == ["sustainment/inbound/adi_run3/"]
    assert c.asked == ["sustainment/inbound/adi_run3/ADI_PDN_23_0120.pdf"]
    assert h.startswith("sha256:")


def test_the_fallback_resolves_within_the_manifests_own_inbound_copy():
    """Three copies of the Diodes notice sit in sibling directories. The search is
    scoped to everything before `/generated/`, so it cannot return another copy's PDF —
    which would silently hash a different object than the one scored."""
    c = _FakeS3(b"%PDF", listing=[
        "sustainment/inbound/diodes_2683/Diodes_PCN_2683_Rev1_EOL.pdf",
        "sustainment/inbound/diodes_bbox/Diodes_PCN_2683_Rev1_EOL.pdf",
    ])
    run.source_content_hash(
        c, {},
        "sustainment/inbound/diodes_bbox/generated/D_pdf/manifest.json",
        "Diodes_PCN_2683_Rev1_EOL.pdf")
    assert c.asked == ["sustainment/inbound/diodes_bbox/Diodes_PCN_2683_Rev1_EOL.pdf"]


def test_a_missing_source_key_with_nothing_to_fall_back_on_yields_none():
    """A missing hash must not fail a scoring run: the consequence is recorded where it
    is consumed (`bytes_coverage.unverified`), not raised here."""
    assert run.source_content_hash(_FakeS3(b"x"), {}) is None
    assert run.source_content_hash(_FakeS3(b"x", listing=[]), {},
                                   "a/generated/b/manifest.json", "x.pdf") is None


def test_an_unreadable_source_object_yields_none_rather_than_raising():
    assert run.source_content_hash(_FakeS3(raises=True), {"source_key": "k"}) is None


# --------------------------------------------------------------------------
# (e) Header correctness — the condition cross-fire agreement cannot reach.

def _totals(**kw):
    t = {"notices_with_gt": 1, "notices_observed": 1, "unobserved": [],
         "fields_scored": 2, "exact": 2, "pending": [], "distractor": [],
         "wrong": [], "misformatted": [], "unreadable": [], "absent": [],
         "observed": True, "clean": True}
    t.update(kw)
    return t


def _corpus(needs_review):
    entry = {"ok": True, "needs_review": needs_review}
    return {n: {"TYC.pdf": dict(entry)} for n in (1, 2, 3)}


def test_a_fire_set_with_no_header_totals_is_unscored_not_passed():
    """Score JSONs from an image predating header scoring. The report must say so
    and must NOT block: nothing was measured, which is neither a pass nor a fail.
    `observed` is what a reader checks before believing a clean result."""
    block, blocking, exempted = gate.check_header_correctness(
        {1: None, 2: None, 3: None}, _corpus(False))
    assert block["observed"] is False
    assert "NOT a pass" in block["reason"]
    assert (blocking, exempted) == ([], [])


def test_a_declared_distractor_blocks_and_names_the_field():
    block, blocking, exempted = gate.check_header_correctness(
        {n: _totals(distractor=["TYC.pdf:pub_date"], exact=1, clean=False)
         for n in (1, 2, 3)},
        _corpus(False))
    assert block["failing_notices"] == ["TYC.pdf"]
    assert len(blocking) == 1
    assert "pub_date (distractor)" in blocking[0]
    assert "fire 1" in blocking[0] and "fire 3" in blocking[0]
    assert exempted == []


def test_three_fires_agreeing_on_a_wrong_value_still_blocks():
    """THE WHOLE POINT. Identical header_totals in all three fires means perfect
    agreement; agreement check (b) reports nothing. Ground truth reports the
    value as the declared print stamp, so this condition blocks where (b)
    structurally cannot."""
    totals = _totals(distractor=["TYC.pdf:pub_date"], exact=1, clean=False)
    _, blocking, _ = gate.check_header_correctness(
        {1: totals, 2: dict(totals), 3: dict(totals)}, _corpus(False))
    assert blocking, "a value all three fires agree on must still be checkable"


def test_a_declared_notice_is_exempted_and_not_blocking():
    """Same exemption as the declaration rule in (d): a notice flagged
    needs_review in all three fires has not been written silently."""
    _, blocking, exempted = gate.check_header_correctness(
        {n: _totals(wrong=["TYC.pdf:pub_date"], exact=1, clean=False)
         for n in (1, 2, 3)},
        _corpus(True))
    assert blocking == []
    assert len(exempted) == 1
    assert "needs_review=True in all three fires" in exempted[0]


def test_an_exempted_failure_is_still_a_failing_notice_for_the_strict_view():
    block, blocking, _ = gate.check_header_correctness(
        {n: _totals(absent=["TYC.pdf:mfr"], exact=1, clean=False)
         for n in (1, 2, 3)},
        _corpus(True))
    assert blocking == []
    # strict_verdict reads this key, and grants no exemptions.
    assert block["failing_notices"] == ["TYC.pdf"]


def test_a_pending_field_alone_is_not_a_failure():
    block, blocking, exempted = gate.check_header_correctness(
        {n: _totals(pending=["TYC.pdf:doc_level_ltb_date"]) for n in (1, 2, 3)},
        _corpus(False))
    assert (blocking, exempted) == ([], [])
    assert block.get("failing_notices") == []
    assert block["fires"][1]["pending"] == ["TYC.pdf:doc_level_ltb_date"]


def test_a_failure_in_one_fire_only_is_reported_as_that_one_fire():
    _, blocking, _ = gate.check_header_correctness(
        {1: _totals(), 2: _totals(misformatted=["TYC.pdf:pub_date"], clean=False),
         3: _totals()},
        _corpus(False))
    assert len(blocking) == 1
    assert "fire 2: pub_date (misformatted)" in blocking[0]
    assert "fire 1" not in blocking[0]


def test_the_renderer_states_not_scored_rather_than_zero_failures():
    block, _, _ = gate.check_header_correctness({1: None}, _corpus(False))
    assert "NOT SCORED" in gate._render_header_correctness_block(block)
    assert "NOT PRESENT" in gate._render_header_correctness_block(None)


# --------------------------------------------------------------------------
# The corpus enumeration, where the gate reads it.

def test_the_gate_copies_the_corpus_enumeration_into_its_report():
    corpus = gate.pcn_score.load_corpus()
    assert corpus["distinct_documents"] == 8
    assert corpus["scored_entries"] == 9
    assert corpus["gt_parts"] == 898
    assert corpus["distinct_parts"] == 496
    rendered = gate._render_corpus_block(corpus)
    assert "distinct documents: **8**" in rendered
    assert "until production traffic adds to it" in rendered


def test_a_report_with_no_corpus_block_says_so_instead_of_printing_a_number():
    assert "NOT STATED" in gate._render_corpus_block({})


def test_targets_and_the_enumeration_must_agree_or_the_run_aborts():
    """`check_corpus_enumeration` is the assertion that makes the enumeration an
    INPUT rather than prose. It must pass on the shipped files, and it must fail
    when the denominator is edited without the corpus being re-enumerated."""
    gt = run.pcn_score.load_ground_truth()
    run.check_corpus_enumeration(gt)  # shipped state: no raise

    real = run.pcn_score.load_corpus
    try:
        for bad in ({"documents": [], "distinct_documents": 0,
                     "scored_entries": 9, "gt_parts": 898, "distinct_parts": 496},
                    dict(real(), gt_parts=899),
                    dict(real(), distinct_parts=898),
                    dict(real(), scored_entries=8),
                    {}):
            run.pcn_score.load_corpus = lambda *a, _b=bad, **k: _b
            try:
                run.check_corpus_enumeration(gt)
            except SystemExit:
                continue
            raise AssertionError(f"check_corpus_enumeration accepted {bad!r}")
    finally:
        run.pcn_score.load_corpus = real


def test_the_distinct_parts_arithmetic_is_recomputed_not_restated():
    """496 is 898 minus the Diodes document's 402, because that one content is
    scored under two filenames. The check must be that arithmetic over the
    notices block, not a second copy of the number."""
    gt = run.pcn_score.load_ground_truth()
    corpus = run.pcn_score.load_corpus()
    reps = [d["filenames"][0] for d in corpus["documents"]]
    assert sum(gt[fn]["count"] for fn in reps) == corpus["distinct_parts"]
    assert corpus["gt_parts"] - corpus["distinct_parts"] == 402
