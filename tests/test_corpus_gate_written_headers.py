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
    """No hash recorded => no blocking message, but `bytes_checked` must be False so
    the report says NOT VERIFIABLE rather than implying it was verified."""
    corpus = {n: {"A.pdf": {"ok": True}} for n in (1, 2, 3)}
    assert gate.check_same_bytes(corpus) == []
    assert gate.content_hashes_by_fire(corpus) == {}


def test_a_hash_recorded_by_only_one_fire_is_not_a_disagreement():
    corpus = {1: {"A.pdf": _notice("sha256:aaa")},
              2: {"A.pdf": {"ok": True}},
              3: {"A.pdf": {"ok": True}}}
    assert gate.check_same_bytes(corpus) == []


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
    def __init__(self, body=None, raises=False):
        self.body, self.raises, self.asked = body, raises, []

    def get_object(self, Bucket, Key):  # noqa: N803 (boto3's own signature)
        self.asked.append(Key)
        if self.raises:
            raise RuntimeError("no such key")
        return {"Body": io.BytesIO(self.body)}


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


def test_a_missing_source_key_yields_none_rather_than_raising():
    """A missing hash must not fail a scoring run: the consequence is recorded where
    it is consumed (`bytes_checked: false`), not raised here."""
    assert run.source_content_hash(_FakeS3(b"x"), {}) is None


def test_an_unreadable_source_object_yields_none_rather_than_raising():
    assert run.source_content_hash(_FakeS3(raises=True), {"source_key": "k"}) is None
