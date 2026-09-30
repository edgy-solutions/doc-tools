"""Tests for doc_tools.utils.notice_identity — the Level-2 dedupe identity
(mfr, doc_id, revision) key and classifier.

Pure unit tests: no S3, no Dagster, no BAML. See the module docstring in
doc_tools/utils/notice_identity.py for the judgment calls these tests pin
(corporate-suffix stripping, None-vs-'-' revision, no hash()-derived key,
and revision ordering only where genuinely decidable).
"""
from doc_tools.utils import notice_identity as ni


# ---------------------------------------------------------------------------
# normalize_component: generic equivalences
# ---------------------------------------------------------------------------

def test_normalize_component_casefolds_and_collapses_whitespace():
    assert ni.normalize_component("PCN   2683") == "pcn 2683"
    assert ni.normalize_component("pcn 2683") == "pcn 2683"
    assert ni.normalize_component("  PCN 2683  ") == "pcn 2683"


def test_normalize_component_drops_typesetting_punctuation():
    assert ni.normalize_component("Diodes, Incorporated.") == "diodes incorporated"
    assert ni.normalize_component("O'Brien Semiconductor") == "obrien semiconductor"


def test_normalize_component_none_is_empty_string():
    assert ni.normalize_component(None) == ""


def test_normalize_component_keeps_dash_it_is_not_noise_punctuation():
    # '-' is a real printed revision value (judgment call #2) and can be
    # meaningful inside a doc_id; it must survive normalization.
    assert ni.normalize_component("-") == "-"
    assert ni.normalize_component("BYVB32-200-E3") == "byvb32-200-e3"


# ---------------------------------------------------------------------------
# notice_key: corporate-suffix equivalence (judgment call #1)
# ---------------------------------------------------------------------------

def test_corporate_suffix_variants_collapse_to_one_key():
    k1 = ni.notice_key("Diodes Incorporated", "PCN 2683", "A")
    k2 = ni.notice_key("diodes  incorporated", "PCN 2683", "A")
    k3 = ni.notice_key("Diodes, Incorporated.", "PCN 2683", "A")
    assert k1 == k2 == k3


def test_corporate_suffix_stripping_does_not_collide_different_companies():
    # Guard against over-aggressive stripping: two genuinely different
    # manufacturers must not collapse to the same key just because one of
    # them happens to end in a suffix-like token that survives stripping
    # unrelated to the other's name.
    assert ni.notice_key("Diodes Incorporated", "PCN 1", "A") != ni.notice_key(
        "Acme Incorporated", "PCN 1", "A")


def test_suffix_alone_is_never_stripped_to_empty():
    # A (synthetic) mfr that IS only the suffix word must not normalize away
    # to an empty, key-colliding mfr component.
    assert ni._strip_corporate_suffix("inc") == "inc"


# ---------------------------------------------------------------------------
# notice_key: revision None vs '-' (judgment call #2)
# ---------------------------------------------------------------------------

def test_revision_none_and_dash_are_different_keys():
    k_none = ni.notice_key("Acme Inc", "PCN 1", None)
    k_dash = ni.notice_key("Acme Inc", "PCN 1", "-")
    assert k_none != k_dash


def test_revision_none_is_stable_and_not_confused_with_empty_string():
    k_none = ni.notice_key("Acme Inc", "PCN 1", None)
    k_empty = ni.notice_key("Acme Inc", "PCN 1", "")
    assert k_none != k_empty


# ---------------------------------------------------------------------------
# notice_key: determinism, and NOT derived from Python's hash()
# ---------------------------------------------------------------------------

def test_notice_key_is_deterministic_same_inputs_same_key():
    a = ni.notice_key("Diodes Incorporated", "PCN 2683", "A")
    b = ni.notice_key("Diodes Incorporated", "PCN 2683", "A")
    assert a == b


def test_notice_key_matches_exact_literal_not_a_salted_hash():
    # Built from the SAME literal substrings the algorithm is documented to
    # produce (casefold + corporate-suffix strip on mfr, casefold on
    # doc_id/revision, joined on SEPARATOR) — not by calling notice_key()
    # again and not via hashlib/hash(). Python's hash() is salted per
    # process (PYTHONHASHSEED), so it could never satisfy an exact literal
    # assertion like this one across two separate interpreter runs.
    expected = ni.SEPARATOR.join(("diodes", "pcn 2683", "a"))
    assert ni.notice_key("Diodes Incorporated", "PCN 2683", "A") == expected


def test_notice_key_is_unambiguously_parseable():
    key = ni.notice_key("Diodes Incorporated", "PCN 2683", "A")
    assert ni.parse_notice_key(key) == ("diodes", "pcn 2683", "a")


# ---------------------------------------------------------------------------
# build_identity: missing mfr/doc_id -> no key, no collision, never raises
# ---------------------------------------------------------------------------

def test_build_identity_missing_mfr_gives_no_key_and_does_not_raise():
    identity = ni.build_identity(None, "PCN 2683", "A")
    assert identity["key"] is None
    assert identity["complete"] is False
    assert "mfr" in identity["note"]


def test_build_identity_missing_doc_id_gives_no_key_and_does_not_raise():
    identity = ni.build_identity("Diodes Incorporated", None, "A")
    assert identity["key"] is None
    assert identity["complete"] is False
    assert "doc_id" in identity["note"]


def test_build_identity_empty_header_fields_do_not_raise():
    # doc_tools.utils.sustainment_merge.empty_header's shape on a totally
    # failed header pass: mfr="" (not None). Must behave the same as mfr
    # being None — no key, no raise.
    identity = ni.build_identity("", "", None)
    assert identity["key"] is None
    assert identity["complete"] is False


def test_build_identity_missing_component_never_collides_two_failed_documents():
    # Two DIFFERENT documents whose headers both failed must not be treated
    # as the same notice merely because both produced empty/missing fields.
    a = ni.build_identity(None, "PCN 1", None)
    b = ni.build_identity(None, "PCN 2", None)
    assert a["key"] is None and b["key"] is None
    record_a = {"key": a["key"], "content_hash": "hash-a"}
    record_b = {"key": b["key"], "content_hash": "hash-b"}
    result = ni.classify_pair(record_a, record_b)
    assert result["relation"] == "distinct"


def test_build_identity_success_exposes_readable_triple_alongside_key():
    identity = ni.build_identity("Diodes Incorporated", "PCN 2683", "A")
    assert identity["key"] is not None
    assert identity["normalized_mfr"] == "diodes"
    assert identity["normalized_doc_id"] == "pcn 2683"
    assert identity["normalized_revision"] == "a"
    # Raw values preserved verbatim for display.
    assert identity["mfr"] == "Diodes Incorporated"
    assert identity["doc_id"] == "PCN 2683"
    assert identity["revision"] == "A"


# ---------------------------------------------------------------------------
# classify_pair: every relation
# ---------------------------------------------------------------------------

def _record(mfr, doc_id, revision, content_hash):
    key = ni.notice_key(mfr, doc_id, revision)
    return {"key": key, "content_hash": content_hash, "revision": revision,
            "doc_id": doc_id, "mfr": mfr}


def test_classify_pair_identical_same_key_same_hash():
    a = _record("Acme Inc", "PCN 1", "A", "sha-xyz")
    b = _record("Acme Inc", "PCN 1", "A", "sha-xyz")
    assert ni.classify_pair(a, b)["relation"] == "identical"


def test_classify_pair_duplicate_copy_same_key_different_hash():
    a = _record("Acme Inc", "PCN 1", "A", "sha-one")
    b = _record("Acme Inc", "PCN 1", "A", "sha-two")
    assert ni.classify_pair(a, b)["relation"] == "duplicate_copy"


def test_classify_pair_supersedes_numeric_revisions():
    newer = _record("Acme Inc", "PCN 1", "2", "sha-new")
    older = _record("Acme Inc", "PCN 1", "1", "sha-old")
    assert ni.classify_pair(newer, older)["relation"] == "supersedes"
    assert ni.classify_pair(older, newer)["relation"] == "superseded_by"


def test_classify_pair_supersedes_single_alpha_revisions():
    newer = _record("Acme Inc", "PCN 1", "B", "sha-new")
    older = _record("Acme Inc", "PCN 1", "A", "sha-old")
    assert ni.classify_pair(newer, older)["relation"] == "supersedes"
    assert ni.classify_pair(older, newer)["relation"] == "superseded_by"


def test_classify_pair_supersedes_absent_vs_present_revision():
    unrevisioned = _record("Acme Inc", "PCN 1", None, "sha-old")
    revisioned = _record("Acme Inc", "PCN 1", "A", "sha-new")
    assert ni.classify_pair(revisioned, unrevisioned)["relation"] == "supersedes"
    assert ni.classify_pair(unrevisioned, revisioned)["relation"] == "superseded_by"


def test_classify_pair_revision_order_unknown_alpha_vs_numeric():
    # THE CRITICAL CASE: 'A' vs '1' is same (mfr, doc_id), different
    # revision, but mixed alpha/numeric — never a decidable order.
    a = _record("Acme Inc", "PCN 1", "A", "sha-a")
    b = _record("Acme Inc", "PCN 1", "1", "sha-b")
    result = ni.classify_pair(a, b)
    assert result["relation"] == "revision_order_unknown"
    result_rev = ni.classify_pair(b, a)
    assert result_rev["relation"] == "revision_order_unknown"


def test_classify_pair_revision_order_unknown_multitoken_revision():
    a = _record("Acme Inc", "PCN 1", "Rev1", "sha-a")
    b = _record("Acme Inc", "PCN 1", "A", "sha-b")
    assert ni.classify_pair(a, b)["relation"] == "revision_order_unknown"


def test_classify_pair_revision_order_unknown_dash_vs_anything():
    a = _record("Acme Inc", "PCN 1", "-", "sha-a")
    b = _record("Acme Inc", "PCN 1", "A", "sha-b")
    assert ni.classify_pair(a, b)["relation"] == "revision_order_unknown"


def test_classify_pair_distinct_different_doc_id():
    a = _record("Acme Inc", "PCN 1", "A", "sha-a")
    b = _record("Acme Inc", "PCN 2", "A", "sha-b")
    assert ni.classify_pair(a, b)["relation"] == "distinct"


def test_classify_pair_distinct_different_mfr():
    a = _record("Acme Inc", "PCN 1", "A", "sha-a")
    b = _record("Globex Inc", "PCN 1", "A", "sha-b")
    assert ni.classify_pair(a, b)["relation"] == "distinct"


# ---------------------------------------------------------------------------
# THE REAL CORPUS CASE this task exists for.
#
# Diodes_PCN_2683_FULLGREEN.pdf and Diodes_PCN_2683_Rev1_EOL.pdf are
# byte-identical (len=181899, sha256=af5bfad3f9344eb1dc942230a33cb61b58fb
# 911b977da2063fffbecb5788074c per docs/pcn-corpus-validation-2026-09-21.md)
# and both scored at gt=402 — one document counted twice in the 898-part
# corpus denominator. Both files extract the SAME header (mfr='Diodes
# Incorporated', doc_id='PCN-2683', pub_date='2024-06-25'). The doc_id used
# below is the REAL extracted value, read out of the three corpus fires at
# pin 025be04a (grep '"doc_id"' on the fire log -> "PCN-2683"), not a
# stand-in. Note the HYPHEN: it survives normalization, because `-` is a real
# printed revision value and is deliberately excluded from the punctuation
# stripping that drops `.`, `,` and `'`.
# Revision: the filenames disagree ('FULLGREEN' vs 'Rev1_EOL') but the
# extracted header comes from byte-identical PDF bytes, so it is identical
# too — the whole point is that the FILENAME must not decide notice
# identity, only the header content does.
# ---------------------------------------------------------------------------

_DIODES_2683_SHA256 = "af5bfad3f9344eb1dc942230a33cb61b58fb911b977da2063fffbecb5788074c"


def test_diodes_pcn_2683_fullgreen_and_rev1_eol_are_identical():
    fullgreen = _record("Diodes Incorporated", "PCN-2683", None, _DIODES_2683_SHA256)
    rev1_eol = _record("Diodes Incorporated", "PCN-2683", None, _DIODES_2683_SHA256)

    assert fullgreen["key"] == rev1_eol["key"]
    # The hyphen is preserved, so the key is the real printed identity.
    assert ni.parse_notice_key(fullgreen["key"])[1] == "pcn-2683"

    result = ni.classify_pair(fullgreen, rev1_eol)
    assert result["relation"] == "identical"
