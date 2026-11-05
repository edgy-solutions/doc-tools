"""The scrub allowlist: vocabulary named in config, matched by mechanism.

Config names the case, code implements the mechanism. These tests seal both
halves: the YAML covers the extractor's header vocabulary (so the vocabulary
under test and the allowlist cannot drift apart), and the loader and matcher
refuse the ways an allowlist can be quietly wrong.
"""
from __future__ import annotations

import os

import pytest

from doc_tools.scrub.allowlist import Allowlist
from doc_tools.scrub.ledger import AllowlistRule

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML_PATH = os.path.join(ROOT, "registry", "scrub_allowlist.yaml")


@pytest.fixture(scope="module")
def allowlist() -> Allowlist:
    return Allowlist.load(YAML_PATH)


def _write(tmp_path, body: str):
    p = tmp_path / "al.yaml"
    p.write_bytes(body.encode("utf-8"))
    return p


# ------------------------------------------------------------------ the seal
def test_the_allowlist_covers_the_extractor_header_vocabulary(allowlist):
    """The vocabulary UNDER TEST and the allowlist must not drift apart: an
    addition to the extractor's header tuples that the allowlist lacks would be
    scrubbed out of the fixture it is meant to be tested by."""
    from doc_tools.utils import table_text_layer as ttl
    from doc_tools.utils.sustainment_header_trust import _GAZETTEER_NAMES

    by_rule = {}
    for phrase, rule in allowlist.phrases():
        by_rule.setdefault(rule, set()).add(phrase)
    headers = by_rule[AllowlistRule.HEADER_VOCABULARY]
    for tuple_name in ("AFFECTED_HEADERS", "REPLACEMENT_HEADERS", "ALIAS_HEADERS",
                       "CUSTOMER_HEADERS", "_CUSTOMER_PART_CUES"):
        missing = [h for h in getattr(ttl, tuple_name) if h not in headers]
        assert missing == [], f"{tuple_name} not in the allowlist: {missing}"
    for printed in ("Part Number", "Alternative Part Number", "Affected Part",
                    "Replacement", "Customer Part Number", "Last Time Buy"):
        assert printed in headers
    missing = [n for n in _GAZETTEER_NAMES
               if n not in by_rule[AllowlistRule.MANUFACTURER_NAME]]
    assert missing == [], f"gazetteer names not allowlisted: {missing}"
    for short in ("Diodes", "TI", "ADI", "IDT"):
        assert short in by_rule[AllowlistRule.MANUFACTURER_NAME]


def test_allowlist_py_carries_no_literal_vocabulary():
    """Config names the case; the module implements the mechanism."""
    src = open(os.path.join(ROOT, "doc_tools", "scrub", "allowlist.py"),
               encoding="utf-8").read()
    for literal in ("Part Number", "Diodes", "AEC-Q200", "Last Time Buy"):
        assert literal not in src


# ------------------------------------------------------------------ the ref
def test_ref_is_path_at_eight_hex_of_the_file_bytes(allowlist):
    path, _, digest = allowlist.ref.rpartition("@")
    assert path.endswith("registry/scrub_allowlist.yaml")
    assert len(digest) == 8 and all(c in "0123456789abcdef" for c in digest)


def test_a_crlf_rewrite_changes_the_ref(tmp_path):
    """The digest is over BYTES: a text-mode rewrite must not be invisible."""
    lf = tmp_path / "lf.yaml"
    crlf = tmp_path / "crlf.yaml"
    raw = open(YAML_PATH, "rb").read()
    lf.write_bytes(raw)
    crlf.write_bytes(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert Allowlist.load(lf).ref.rpartition("@")[2] != \
        Allowlist.load(crlf).ref.rpartition("@")[2]


# ------------------------------------------------------------------ loader
def test_load_rejects_an_unknown_top_level_key(tmp_path):
    with pytest.raises(ValueError, match="unknown top-level"):
        Allowlist.load(_write(tmp_path, "allowlist_version: 1\nrules: {}\nextra: 1\n"))


def test_load_rejects_an_unknown_rule_name(tmp_path):
    with pytest.raises(ValueError, match="unknown rule"):
        Allowlist.load(_write(
            tmp_path, "allowlist_version: 1\nrules:\n  nonsense:\n    phrases: [a]\n"))


def test_load_rejects_a_version_other_than_one(tmp_path):
    with pytest.raises(ValueError, match="allowlist_version"):
        Allowlist.load(_write(tmp_path, "allowlist_version: 2\nrules: {}\n"))


def test_load_rejects_a_date_detector_other_than_is_entirely_a_date(tmp_path):
    with pytest.raises(ValueError, match="is_entirely_a_date"):
        Allowlist.load(_write(
            tmp_path,
            "allowlist_version: 1\nrules:\n  date:\n    detector: my_own_parser\n"))


# ------------------------------------------------------------------ spans
def test_longest_match_wins_at_the_same_offset(allowlist):
    spans = allowlist.spans("Customer Part Number")
    assert [(s.text, s.rule) for s in spans] == [
        ("Customer Part Number", AllowlistRule.HEADER_VOCABULARY)]


def test_matching_is_case_insensitive_and_spans_carry_the_source_text(allowlist):
    spans = allowlist.spans("AFFECTED PART")
    assert [s.text for s in spans] == ["AFFECTED PART"]


def test_a_phrase_does_not_match_inside_a_part_number(allowlist):
    """`device` and `opn` are headers; as substrings they would exempt the middle
    of a part number and leave a fragment unscrubbed."""
    assert allowlist.spans("XYdeviceAB12 TOPN123") == ()


def test_spans_never_overlap(allowlist):
    text = "Last Time Buy PCN-2683 Table 3 - EOL Devices and No Replacement Parts"
    spans = allowlist.spans(text)
    for a, b in zip(spans, spans[1:]):
        assert a.end <= b.start


def test_a_caption_span_stops_before_the_part_numbers_that_follow_it(allowlist):
    """A whole-line caption pattern would swallow every part number the extractor
    concatenates after the caption in one table element, and leak all of them."""
    text = "Table 4 - EOL Devices and No Replacement Parts WT21120001 WC3110001Q"
    caps = [s for s in allowlist.spans(text) if s.rule is AllowlistRule.CAPTION]
    assert [c.text for c in caps] == [
        "Table 4 - EOL Devices and No Replacement Parts"]


def test_dates_are_found_by_the_detector_not_a_pattern(allowlist):
    text = "DATE: 06/25/2024 last order 22 Dec, 2024 and 6/16/2021."
    dates = [s.text for s in allowlist.spans(text) if s.rule is AllowlistRule.DATE]
    assert dates == ["06/25/2024", "22 Dec, 2024", "6/16/2021"]


def test_rules_argument_drops_a_rule(allowlist):
    text = "Diodes Incorporated 06/25/2024"
    all_rules = frozenset(AllowlistRule)
    assert {s.rule for s in allowlist.spans(text, rules=all_rules)} == {
        AllowlistRule.MANUFACTURER_NAME, AllowlistRule.DATE}
    no_mfr = all_rules - {AllowlistRule.MANUFACTURER_NAME}
    assert {s.rule for s in allowlist.spans(text, rules=no_mfr)} == {
        AllowlistRule.DATE}


def test_unit_package_and_standard_strings_are_allowlisted(allowlist):
    spans = allowlist.spans("SOT-23 X7R AEC-Q200 0402")
    assert [s.text for s in spans] == ["SOT-23", "X7R", "AEC-Q200", "0402"]
