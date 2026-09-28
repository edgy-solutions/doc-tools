"""Prefer the TEXT LAYER where a stored crop was cut through the glyphs.

Measured on ADI_PDN_23_0120 at corpus pin sha256:0136991e (2026-09-27): the pixel path
emitted `7873ACPZ` where ground truth is `AD7873ACPZ`. That notice reaches vision through
the PURE pixel path -- grid_forwarded: 0 -- so tier 1 never claimed the page and no amount
of grid forwarding can reach it.

The cause is in the prompt the run log preserved, not inferred:

    ### OCR TEXT (AUTHORITATIVE for the exact characters of every MPN) ###
    Pin To Pin Product Family Replacement Part Compatible Comments AD7873 AD7873ARUZ Yes

    ### HTML TABLE (rough hint only - may be sparse or wrong) ###
    <th>del</th> ... <td>7873ACPZ</td><td>AD7873</td><td>| AD7873ARUZ</td>

The authoritative OCR slice holds NEITHER form of the part. The crop is cut on its LEFT
edge -- `del` is what survives of `Model`, `7873ACPZ` of `AD7873ACPZ` -- so the model read
the only place the string appeared at all, the rough HTML hint, which carries the same cut.

Extending the crop geometry to all four edges is the primary cure, but it re-renders crops,
so it can only help documents ingested AFTER it ships. These tests pin the second half:
repairing an already-stored cut crop at READ time from the page text layer, which is not
clipped. `AD7873ACPZ` prints twice in this notice as prose.

The near-miss neighbours are in the fixture ON PURPOSE. `AD7873` and `AD7873ARUZ` are
short, real, and both extended by longer part numbers in the same document -- if the rule
were "lengthen anything that has a longer relative", it would corrupt them, and the tests
below would go red.
"""
from types import SimpleNamespace

import pytest

from doc_tools.baml_client import sync_client as sync_client_module
from doc_tools.plugins import sustainment as sustainment_module
from doc_tools.plugins.sustainment import SustainmentPlugin
from doc_tools.utils.table_text_layer import doc_text_tokens, prefer_text_layer_mpn

# The real ADI_PDN_23_0120 text layer, trimmed to the lines that matter and otherwise
# verbatim from the corpus run log: the clipped table element text, plus the two places
# the full part number prints as prose.
ADI_TEXT = """PDN 23_0120 Rev. A

Obsolescence of AD7873ACPZ

Pin To Pin Product Family Replacement Part Compatible Comments AD7873 AD7873ARUZ Yes

AD7873ACPZ
"""


def test_the_adi_left_cut_is_repaired_from_the_text_layer():
    """The measured 897/898 defect, by its real strings."""
    assert prefer_text_layer_mpn("7873ACPZ", doc_text_tokens(ADI_TEXT)) == "AD7873ACPZ"


@pytest.mark.parametrize("real", ["AD7873", "AD7873ARUZ", "AD7873ACPZ"])
def test_a_part_present_verbatim_is_never_lengthened(real):
    """The guard that keeps this from being normalization.

    `AD7873` is a real product-family value printed in the affected column, and BOTH
    `AD7873ARUZ` and `AD7873ACPZ` extend it. It is present verbatim in the text layer, so
    there is no evidence of a cut, so it is returned untouched.
    """
    assert prefer_text_layer_mpn(real, doc_text_tokens(ADI_TEXT)) == real


def test_verbatim_presence_outranks_a_unique_longer_part():
    """The verbatim guard on its own, with nothing else able to carry the test.

    In ADI_TEXT `AD7873` is protected twice over -- it is verbatim AND ambiguous (two
    longer forms) -- so deleting the verbatim check would leave those cases green. Here
    exactly ONE longer part extends it, which is the shape where the two rules disagree:
    only the verbatim check keeps `AD7873` intact.
    """
    assert prefer_text_layer_mpn("AD7873", doc_text_tokens("AD7873 AD7873ARUZ")) == "AD7873"


def test_a_right_edge_cut_is_repaired_too():
    """Four edges, not one: a cut on the RIGHT leaves a PREFIX behind."""
    assert prefer_text_layer_mpn("AD7873AC", doc_text_tokens(ADI_TEXT)) == "AD7873ACPZ"


def test_two_candidate_longer_parts_means_no_repair():
    """Ambiguity must return the fragment, not a coin flip.

    A fragment matches nothing downstream and reads as a miss. A WRONG part number matches
    the wrong part, and is indistinguishable from a real extraction -- the same reason the
    grid no-parts-column fix emits nothing rather than a guess.
    """
    tokens = doc_text_tokens("AB1234 CD1234 both end the same way")
    assert prefer_text_layer_mpn("1234", tokens) == "1234"


def test_no_candidate_means_no_repair():
    tokens = doc_text_tokens("nothing here extends it AD7873ARUZ")
    assert prefer_text_layer_mpn("XZ99Q", tokens) == "XZ99Q"


def test_middle_containment_is_not_a_cut_and_must_not_repair():
    """endswith/startswith model an EDGE cut. Containment would be a different and
    unjustified claim: a crop cut through the glyphs loses characters from one END."""
    tokens = doc_text_tokens("AD7873ACPZ")
    assert prefer_text_layer_mpn("7873", tokens) == "7873"


def test_a_non_mpn_fragment_is_left_alone():
    """`del`, the clipped header cell from the same ADI crop, is not a part number and must
    not acquire one. Both guards cover it: under the length floor, and no digit."""
    # `Model7Number` is MPN-shaped and UNIQUELY extends `Model`, so this reds if the
    # looks_like_mpn check on the emitted value is ever dropped -- with a digit-free
    # neighbour it would not, and the guard would be untested.
    tokens = doc_text_tokens("del Model Model7Number")
    assert prefer_text_layer_mpn("del", tokens) == "del"
    assert prefer_text_layer_mpn("Model", tokens) == "Model"
    # And `Mode` -- a clipped non-part, ABSENT verbatim, so the verbatim guard cannot
    # cover it and only the MPN-shape check on the emitted value can. Without this
    # assertion, removing that check leaves the whole module green.
    assert prefer_text_layer_mpn("Mode", tokens) == "Mode"


def test_short_fragments_are_below_the_repair_floor():
    """Matching 3 characters of a part number is not evidence of anything -- the same
    threshold `looks_like_mpn` uses for a bare token."""
    assert prefer_text_layer_mpn("731", doc_text_tokens("AD731 AD7873ACPZ")) == "731"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_values_pass_through(value):
    assert prefer_text_layer_mpn(value, doc_text_tokens(ADI_TEXT)) == value


def test_tokenizer_keeps_mpn_punctuation_and_splits_table_separators():
    """`SYTX9-122HP-1+` is a REAL corpus part: `-`, `+`, `.`, `/` and `#` are characters of
    part numbers, never separators. A flattened table leaves `|` behind, which is."""
    tokens = doc_text_tokens("| SYTX9-122HP-1+ | 090-44310-31, AD7873ARUZ; done.")
    assert "SYTX9-122HP-1+" in tokens
    assert "090-44310-31" in tokens
    assert "AD7873ARUZ" in tokens
    assert "|" not in tokens


# --------------------------------------------------------------------------- #
# Wiring: the repair has to be REACHED from the pixel path, and counted.
# --------------------------------------------------------------------------- #
class _FakeB:
    def __init__(self, parts):
        self._parts = parts
        self.extract_parts_calls = 0

    def ExtractParts(self, **kwargs):
        self.extract_parts_calls += 1
        return self._parts


def _part(affected, replacement=None, affected_source=None, replacement_source=None):
    return SimpleNamespace(affected_mpn=affected, affected_mpn_source=affected_source,
                           replacement_mpn=replacement,
                           replacement_mpn_source=replacement_source,
                           ltb_date=None, ltb_date_source=None)


@pytest.fixture(autouse=True)
def _prompt_from_file(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")


@pytest.fixture
def plugin():
    return SustainmentPlugin(domain_type="sustainment")


def _run(monkeypatch, plugin, parts, full_text):
    fake = _FakeB(parts)
    monkeypatch.setattr(sync_client_module, "b", fake)
    monkeypatch.setattr(sustainment_module, "_vision_output_tokens", lambda c: 100)
    el = {"type": "Table", "text": "clipped ocr",
          "metadata": {"page_number": 1, "text_as_html": ""}}
    return plugin._extract_parts([el], None, None, full_text)


def test_the_pixel_path_repairs_the_clipped_mpn_and_counts_it(plugin, monkeypatch):
    parts, stats = _run(monkeypatch, plugin, [_part("7873ACPZ", "AD7873ARUZ")], ADI_TEXT)

    assert [p["affected_mpn"] for p in parts] == ["AD7873ACPZ"]
    assert [p["replacement_mpn"] for p in parts] == ["AD7873ARUZ"], \
        "the replacement was never cut and must survive the pass untouched"
    assert stats["text_layer_repairs"] == 1
    assert stats["text_layer_repair_detail"] == [
        {"page_number": 1, "field": "affected_mpn", "from": "7873ACPZ", "to": "AD7873ACPZ"}]


def test_the_provenance_join_key_is_repaired_too(plugin, monkeypatch):
    """`affected_mpn_source` is what places the reviewer's highlight box.

    build_review_items feeds it to resolve_value, which string-matches it against the
    positioned OCR index. Leaving the clipped fragment there resolves to the wrong span or
    to nothing, so the repair would be invisible on the review card even with the MPN
    right. Both fields are held to the SAME evidence, and both changes are recorded.
    """
    parts, stats = _run(monkeypatch, plugin,
                        [_part("7873ACPZ", "AD7873ARUZ", affected_source="7873ACPZ")],
                        ADI_TEXT)

    assert parts[0]["affected_mpn"] == "AD7873ACPZ"
    assert parts[0]["affected_mpn_source"] == "AD7873ACPZ", \
        "a clipped join key resolves to the wrong span, or to nothing"
    assert stats["text_layer_repairs"] == 2, \
        "the counter counts FIELDS repaired, and the source is a field"
    assert [r["field"] for r in stats["text_layer_repair_detail"]] == \
        ["affected_mpn", "affected_mpn_source"]


def test_a_clean_pixel_read_is_not_touched_and_counts_zero(plugin, monkeypatch):
    """Over-firing is the risk this wiring carries, so it is pinned at the wiring level
    too: a vision pass that read the table correctly must come through byte-identical."""
    parts, stats = _run(monkeypatch, plugin, [_part("AD7873ACPZ", "AD7873ARUZ")], ADI_TEXT)

    assert [(p["affected_mpn"], p["replacement_mpn"]) for p in parts] == \
        [("AD7873ACPZ", "AD7873ARUZ")]
    assert stats["text_layer_repairs"] == 0
    assert stats["text_layer_repair_detail"] == []
