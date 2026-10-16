"""The corpus is keyed by source content hash: one document, one score.

`Diodes_PCN_2683_Rev1_EOL.pdf` and `Diodes_PCN_2683_FULLGREEN.pdf` are byte-identical
(sha256 af5bfad3..., measured 2026-10-12 inside the sandbox doc-tools pod), so scoring
both counted one document twice at 402 parts: 924 harness parts over 522 distinct ones.
After the re-key `gt_parts == distinct_parts == 522` holds by assertion.

Claims about the corpus are asserted against the REAL ground-truth file. The mutation
checks deep-copy it and monkeypatch the loaders; they never write to the real file.

No S3, no LLM, no network. `scripts/` is loaded by path, as the sibling corpus-gate tests
do.
"""
import copy
import importlib.util
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("pcn_corpus_gate")
run = _load("pcn_corpus_run")
score = run.pcn_score

ALIAS = "Diodes_PCN_2683_FULLGREEN.pdf"
REP = "Diodes_PCN_2683_Rev1_EOL.pdf"
DIODES_SHA = "af5bfad3f9344eb1dc942230a33cb61b58fb911b977da2063fffbecb5788074c"


def _targets():
    return {t["file"] for t in run.TARGETS}


def _diodes(corpus):
    return [d for d in corpus["documents"] if REP in d["filenames"]][0]


@pytest.fixture
def mutate(monkeypatch):
    """Return (gt, corpus) deep copies, with the loaders pointed at them."""
    gt = copy.deepcopy(score.load_ground_truth())
    corpus = copy.deepcopy(score.load_corpus())
    monkeypatch.setattr(score, "load_corpus", lambda *a, **k: corpus)
    return gt, corpus


# --------------------------------------------------------------------------- #
# The real tree.

def test_check_ground_truth_passes_on_the_real_tree():
    run.check_ground_truth()


def test_the_four_corpus_numbers_after_the_rekey():
    c = score.load_corpus()
    assert c["scored_entries"] == c["distinct_documents"] == 10
    assert c["gt_parts"] == c["distinct_parts"] == 522
    assert run.GT_TOTAL == 522


def test_scored_notices_are_exactly_targets_and_the_alias_is_not_scored():
    gt = score.load_ground_truth()
    assert set(gt) == _targets()
    assert ALIAS not in gt
    assert ALIAS not in _targets()


def test_the_diodes_document_is_two_filenames_one_sha256_representative_first():
    d = _diodes(score.load_corpus())
    assert d["filenames"] == [REP, ALIAS]
    assert d["sha256"] == DIODES_SHA
    assert d["inbound_copies"] == 4
    assert [x for x in score.load_corpus()["documents"] if x["sha256"] == DIODES_SHA] == [d]


def test_every_document_declares_a_well_formed_distinct_sha256():
    docs = score.load_corpus()["documents"]
    hashes = [d["sha256"] for d in docs]
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)
    assert len(set(hashes)) == len(hashes) == 10
    # bare hex in the declaration; the prefix belongs to content_hash only
    assert not any(h.startswith("sha256:") for h in hashes)


# --------------------------------------------------------------------------- #
# TI: the logo wordmark is an accepted form, and the set stays closed.

def _ti_mfr_spec():
    return score.load_ground_truth()["TI_PCN_20210316000.pdf"]["headers"]["mfr"]


def test_ti_logo_wordmark_scores_alias_and_the_canonical_stays_exact():
    spec = _ti_mfr_spec()
    r = score.score_header_field("mfr", "TEXAS INSTRUMENTS", spec)
    assert r["status"] == "alias"
    assert r["canonical"] == "Texas Instruments Incorporated"
    assert score.score_header_field(
        "mfr", "Texas Instruments Incorporated", spec)["status"] == "exact"


def test_alias_is_a_pass_and_not_a_failure():
    assert "alias" in score.HEADER_PASSES
    assert "alias" not in score.HEADER_FAILURES


def test_ti_accepted_set_is_closed():
    r = score.score_header_field("mfr", "Texas Instrument Inc", _ti_mfr_spec())
    assert r["status"] in score.HEADER_FAILURES
    assert r["status"] != "alias"


# --------------------------------------------------------------------------- #
# Mutations: each must abort the run at startup.

def test_mutation_alias_readded_to_notices_aborts(mutate):
    gt, _ = mutate
    gt[ALIAS] = copy.deepcopy(gt[REP])
    with pytest.raises(SystemExit, match="exactly TARGETS|re-inflate"):
        run.check_corpus_enumeration(gt)


def test_mutation_document_with_zero_scored_filenames_aborts(mutate):
    gt, corpus = mutate
    _diodes(corpus)["filenames"] = ["Diodes_not_scored_a.pdf", "Diodes_not_scored_b.pdf"]
    with pytest.raises(SystemExit):
        run.check_corpus_enumeration(gt)


def test_mutation_document_with_zero_scored_filenames_is_named(mutate):
    gt, corpus = mutate
    # A declared document nothing scores, with TARGETS still fully declared.
    corpus["documents"].append({"sha256": "0" * 64, "bytes": 1, "md5": "x",
                                "filenames": ["Never_scored.pdf"], "inbound_copies": 1})
    corpus["distinct_documents"] = 11
    with pytest.raises(SystemExit, match="nothing scores"):
        run.check_corpus_enumeration(gt)


def test_mutation_document_with_two_scored_filenames_aborts(mutate, monkeypatch):
    gt, corpus = mutate
    # Re-score the alias: TARGETS row + notices entry + gt_parts all move together,
    # so ONLY the one-scored-filename rule can catch it.
    monkeypatch.setattr(run, "TARGETS", run.TARGETS + [{"file": ALIAS, "gt": 402}])
    gt[ALIAS] = copy.deepcopy(gt[REP])
    corpus["scored_entries"] = 11
    corpus["gt_parts"] = 924
    with pytest.raises(SystemExit, match="double-scoring"):
        run.check_corpus_enumeration(gt)


def test_mutation_representative_not_first_aborts(mutate):
    gt, corpus = mutate
    _diodes(corpus)["filenames"] = [ALIAS, REP]
    with pytest.raises(SystemExit, match="filenames\\[0\\]"):
        run.check_corpus_enumeration(gt)


def test_mutation_corrupt_sha256_shape_aborts(mutate):
    gt, corpus = mutate
    corpus["documents"][0]["sha256"] = "sha256:" + corpus["documents"][0]["sha256"]
    with pytest.raises(SystemExit, match="64 lowercase hex"):
        run.check_corpus_enumeration(gt)


def test_mutation_duplicate_sha256_across_two_entries_aborts(mutate):
    gt, corpus = mutate
    corpus["documents"][1]["sha256"] = corpus["documents"][0]["sha256"]
    with pytest.raises(SystemExit, match="repeats a sha256"):
        run.check_corpus_enumeration(gt)


def test_mutation_gt_parts_differs_from_distinct_parts_aborts(mutate, monkeypatch):
    gt, corpus = mutate
    # Move TARGETS and gt_parts together so every other arithmetic check passes and
    # ONLY the new invariant is left to catch the divergence.
    targets = copy.deepcopy(run.TARGETS)
    targets[0]["gt"] += 1
    monkeypatch.setattr(run, "TARGETS", targets)
    monkeypatch.setattr(run, "GT_TOTAL", sum(t["gt"] for t in targets))
    corpus["gt_parts"] = run.GT_TOTAL
    with pytest.raises(SystemExit, match="gt_parts=523 != distinct_parts=522"):
        run.check_corpus_enumeration(gt)


# --------------------------------------------------------------------------- #
# check_declared_bytes: the declared anchor beside check_same_bytes.

def _fires(fn, *hashes):
    return {i + 1: {fn: {"ok": True, "content_hash": h}} for i, h in enumerate(hashes)}


def test_declared_bytes_passes_on_a_match():
    corpus = score.load_corpus()
    by_fire = _fires(REP, *["sha256:" + DIODES_SHA] * 3)
    assert gate.check_declared_bytes(by_fire, corpus) == []


def test_declared_bytes_anchors_the_alias_name_too():
    corpus = score.load_corpus()
    assert gate.check_declared_bytes(_fires(ALIAS, "sha256:" + DIODES_SHA), corpus) == []


def test_declared_bytes_blocks_on_a_mismatched_hash():
    corpus = score.load_corpus()
    # Three fires that AGREE with each other on the wrong bytes: check_same_bytes
    # passes this; the declared anchor must not.
    by_fire = _fires(REP, *["sha256:" + "1" * 64] * 3)
    assert gate.check_same_bytes(by_fire) == []
    msgs = gate.check_declared_bytes(by_fire, corpus)
    assert len(msgs) == 3 and all(REP in m for m in msgs)


def test_declared_bytes_does_not_block_on_a_missing_hash():
    corpus = score.load_corpus()
    by_fire = {1: {REP: {"ok": True}}, 2: {REP: {"ok": True, "content_hash": None}}}
    assert gate.check_declared_bytes(by_fire, corpus) == []


def test_declared_bytes_blocks_on_a_scored_but_undeclared_filename():
    corpus = score.load_corpus()
    msgs = gate.check_declared_bytes(
        _fires("Surprise_Notice.pdf", "sha256:" + "2" * 64), corpus)
    assert len(msgs) == 1 and "Surprise_Notice.pdf" in msgs[0]
    assert "does not declare" in msgs[0]


def test_declared_bytes_never_raises_on_an_empty_declaration():
    assert gate.check_declared_bytes({}, {}) == []
    assert gate.check_declared_bytes({1: None}, None) == []
