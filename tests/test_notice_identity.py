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


def test_normalize_component_still_strips_the_dot():
    # Proves the mfr/doc_id path is unchanged by the normalize_revision split:
    # if this regressed to keeping the dot, "Diodes, Incorporated." would stop
    # equating with "Diodes Incorporated" and corporate-suffix stripping
    # (judgment call #1) would silently stop firing on real notices.
    assert ni.normalize_component("PCN 2.0") == "pcn 20"


# ---------------------------------------------------------------------------
# normalize_revision: like normalize_component, but the dot survives
# ---------------------------------------------------------------------------

def test_normalize_revision_keeps_the_structural_dot():
    # If this regressed to stripping the dot (normalize_revision degenerating
    # back to normalize_component), "2.0" and "1.15" would collide down to
    # concatenated-integer strings and _compare_revisions would misorder them
    # again -- the exact defect this module fixes.
    assert ni.normalize_revision("2.0") == "2.0"
    assert ni.normalize_revision("1.15") == "1.15"


def test_normalize_revision_still_normalizes_everything_else():
    # Case-fold, strip ',' and apostrophe, collapse whitespace -- everything
    # normalize_component does except the dot.
    assert ni.normalize_revision("  Rev 2.0  ") == "rev 2.0"
    assert ni.normalize_revision("Rev,2.0") == "rev2.0"
    assert ni.normalize_revision("O'Brien 2.0") == "obrien 2.0"
    assert ni.normalize_revision(None) == ""


def test_normalize_revision_strips_leading_and_trailing_dot_only():
    # A trailing dot is typesetting (a sentence period after "2"), not a
    # revision segment separator -- this is what keeps "2." and "1." from
    # becoming "2.0"-shaped and gaining segments they were never printed
    # with. Only dots BETWEEN characters are structural.
    assert ni.normalize_revision("2.") == "2"
    assert ni.normalize_revision(".2") == "2"
    assert ni.normalize_revision("2.0.") == "2.0"


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


def test_classify_pair_absent_vs_present_revision_is_not_an_ordering():
    """An absent revision does not make the printed side newer.

    This assertion is INVERTED from the one originally shipped, which called
    the printed side newer on the reasoning that vendors leave a first release
    unmarked. Three corpus fires at pin dd043b6 retired that: over the
    byte-identical Diodes PCN-2683 pair the header pass read revision 'R5',
    None, 'R5' for the SAME bytes. So an absent revision is as likely to be a
    header miss as a document that prints none, and it cannot order anything.
    """
    unrevisioned = _record("Acme Inc", "PCN 1", None, "sha-old")
    revisioned = _record("Acme Inc", "PCN 1", "A", "sha-new")
    both = (ni.classify_pair(revisioned, unrevisioned),
            ni.classify_pair(unrevisioned, revisioned))
    assert [r["relation"] for r in both] == ["revision_order_unknown"] * 2
    # The reason must say WHY it declined, so a reviewer reading a dedupe log
    # is not left guessing whether the extractor or the document is at fault.
    assert "header miss" in both[0]["reason"]


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
# Revision: the filenames disagree ('FULLGREEN' vs 'Rev1_EOL') and — this was
# ASSUMED otherwise here, wrongly — so does the extracted revision, even though
# the bytes are the same. Three fires at pin dd043b6 read, for FULLGREEN,
# revision 'R5' / None / 'R5', with the two copies swapping which one carried
# it fire to fire. `revision` is in neither RAW_FIELDS nor WRITTEN_FIELDS of
# scripts/pcn_header_agreement.py, so that instrument reported both files as
# "agree" throughout. The pair below therefore pins BOTH cases: the stable one,
# and the measured unstable one that used to come back "supersedes".
# The whole point is that the FILENAME must not decide notice identity — but
# nor may a nondeterministic revision, which is why the content hash is
# consulted before the keys are compared at all.
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


def test_diodes_pair_is_identical_even_when_the_header_pass_flips_the_revision():
    """The same bytes must never be reported as superseding themselves.

    This is the exact pair and the exact values measured over three fires at
    pin dd043b6: identical sha256, and a revision the header pass reported as
    'R5' on fires 1 and 3 and as None on fire 2. Before the content hash was
    moved ahead of the key comparison, this returned:

        {'relation': 'supersedes',
         'reason': "same (mfr, doc_id); revision 'R5' is newer than None"}

    i.e. one copy of a document declared to supersede its byte-identical twin,
    which is the false-positive the dedupe exists to avoid. Both orderings are
    asserted because a direction-dependent answer here would be just as wrong.
    """
    as_fire_1 = _record("Diodes Incorporated", "PCN-2683", "R5", _DIODES_2683_SHA256)
    as_fire_2 = _record("Diodes Incorporated", "PCN-2683", None, _DIODES_2683_SHA256)

    # The nondeterminism is real: the keys genuinely differ.
    assert as_fire_1["key"] != as_fire_2["key"]

    for a, b in ((as_fire_1, as_fire_2), (as_fire_2, as_fire_1)):
        result = ni.classify_pair(a, b)
        assert result["relation"] == "identical", result
        # The reason must surface the key disagreement rather than hiding it —
        # it is a reportable fact about the extractor, not a detail to swallow.
        assert "keys differ" in result["reason"]


# ---------------------------------------------------------------------------
# DOTTED REVISIONS NOW ORDER CORRECTLY. Found 2026-09-30 while writing the 7f
# contract (docs/notice-identity-contract.md); latent, not observed in the
# corpus at the time. Fixed by introducing `normalize_revision` (keeps the
# structural dot that `normalize_component` strips) and making
# `_compare_revisions` split dotted-numeric revisions on `.`, map each
# segment to `int`, zero-pad the shorter tuple, and compare segment-wise.
#
# WHAT IT USED TO DO. `normalize_component` stripped '.', so the dot in a
# printed revision was gone before `_compare_revisions` ever saw it:
#
#     "2.0"  -> "20"       "1.15" -> "115"
#     "3.0"  -> "30"       "2.99" -> "299"
#     "1.0"  -> "10"       "1.00" -> "100"
#
# Both sides then matched the old `_NUMERIC_RE` and were compared as
# concatenated integers, so the pair was DECIDED — in the wrong direction,
# and silently:
#
#     2.0 vs 1.15  ->  superseded_by   (2.0 is the NEWER revision)
#     3.0 vs 2.99  ->  superseded_by   (3.0 is the NEWER revision)
#     1.0 vs 1.00  ->  superseded_by   (they are the SAME revision)
#
# That was exactly the outcome judgment call #4 exists to prevent: "guessing
# would risk hiding the newer notice behind the older one". A sensor acting
# on `superseded_by` would have declined to let revision 2.0 displace
# 1.15 — the newer notice dropped.
#
# WHAT IT DOES NOW. Segment-wise, zero-padded tuple comparison: 2.0 vs 1.15
# is (2, 0) vs (1, 15) -> 2.0 is newer, reported as `supersedes`. Equivalent
# spellings of the same revision (1.0 vs 1.00, 01 vs 1) zero-pad to equal
# tuples and come back `duplicate_copy`, not an ordering and not
# `revision_order_unknown` -- `classify_pair` has an explicit `order == 0`
# branch for this. See docs/notice-identity-contract.md section 6.5 and the
# module docstring's judgment call #4 for the full writeup.
def test_a_dotted_revision_is_not_ordered_backwards():
    """2.0 supersedes 1.15. Pinned to the exact relation, not just "not
    backwards": if the fix regressed to only avoiding `superseded_by` (e.g.
    falling back to `revision_order_unknown`) this would catch it."""
    a = _record("Acme Inc", "PCN 1", "2.0", "sha-a")
    b = _record("Acme Inc", "PCN 1", "1.15", "sha-b")
    result = ni.classify_pair(a, b)["relation"]
    assert result != "superseded_by"
    assert result == "supersedes"


def test_equivalent_dotted_revisions_are_not_ordered_against_each_other():
    """1.0 and 1.00 are the same revision spelled two ways. If
    `_compare_revisions` stopped zero-padding, this would misclassify the
    pair as `supersedes`/`superseded_by` instead of recognizing the
    equivalence."""
    a = _record("Acme Inc", "PCN 1", "1.0", "sha-a")
    b = _record("Acme Inc", "PCN 1", "1.00", "sha-b")
    result = ni.classify_pair(a, b)["relation"]
    assert result in ("duplicate_copy", "revision_order_unknown")
    assert result == "duplicate_copy"


def test_three_part_dotted_revision_supersedes_three_vs_two_ninety_nine():
    """3.0 vs 2.99 -- a case where naive string/concatenated-integer compare
    gets it backwards (30 < 299) but segment-wise tuple compare gets it
    right ((3, 0) > (2, 99)). If segment-wise comparison regressed to a
    whole-string compare, this would silently flip back to superseded_by."""
    a = _record("Acme Inc", "PCN 1", "3.0", "sha-a")
    b = _record("Acme Inc", "PCN 1", "2.99", "sha-b")
    assert ni.classify_pair(a, b)["relation"] == "supersedes"


def test_longer_dotted_revision_with_extra_segment_supersedes_shorter():
    """2.0.1 vs 2.0 -- three segments against two. If zero-padding were
    missing or wrong, the shorter tuple could compare unequal-length tuples
    directly (a Python TypeError) or the extra segment could be dropped,
    silently losing the information that 2.0.1 is a point release after 2.0."""
    a = _record("Acme Inc", "PCN 1", "2.0.1", "sha-a")
    b = _record("Acme Inc", "PCN 1", "2.0", "sha-b")
    assert ni.classify_pair(a, b)["relation"] == "supersedes"


def test_leading_zero_revision_is_duplicate_copy_not_an_ordering():
    """01 vs 1 -- the leading-zero route into the `order == 0` branch,
    distinct from the explicit-decimal route covered above. If segments
    were compared as strings instead of ints, "01" vs "1" would wrongly
    compare unequal; if int-conversion were dropped, this would misfire as
    an ordering instead of recognizing the same revision."""
    a = _record("Acme Inc", "PCN 1", "01", "sha-a")
    b = _record("Acme Inc", "PCN 1", "1", "sha-b")
    assert ni.classify_pair(a, b)["relation"] == "duplicate_copy"


def test_dotted_revision_against_non_numeric_is_order_unknown():
    """2.0 vs R5 -- one side dotted-numeric, the other not. If the
    dotted-numeric branch regressed to matching on a looser pattern (e.g.
    "starts with a digit"), this could wrongly decide an order against a
    revision scheme the module has never characterized."""
    a = _record("Acme Inc", "PCN 1", "2.0", "sha-a")
    b = _record("Acme Inc", "PCN 1", "R5", "sha-b")
    assert ni.classify_pair(a, b)["relation"] == "revision_order_unknown"


def test_dotted_revision_with_non_numeric_segment_is_order_unknown():
    """1.A vs 1.B -- a dot present but a non-numeric segment. Proves the
    dotted-numeric regex requires EVERY segment to be digits; if it only
    checked for the presence of a dot, this would wrongly fall into the
    segment-wise compare and decide an order from non-numeric segments."""
    a = _record("Acme Inc", "PCN 1", "1.A", "sha-a")
    b = _record("Acme Inc", "PCN 1", "1.B", "sha-b")
    assert ni.classify_pair(a, b)["relation"] == "revision_order_unknown"
