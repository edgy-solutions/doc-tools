"""doc_type must come from the document's own TITLE TEXT, not from the header model.

`ExtractHeader`'s `doc_type` field flipped PCN/PDN/PCN across repeated fires on
byte-identical input (see `doc_tools/plugins/sustainment.py::HEADER_TEMPERATURE`'s
comment). A vendor's title is printed once, on the page, and does not sample — so
`doc_type_from_titles` (doc_tools/utils/sustainment_header_trust.py) replaces the
model's label as the routing source of truth.

Every case here is a MUTATION CHECK in spirit: each assertion pins a specific branch
of the ordered decision (explicit code > ambiguity check > keyword fallback), and a
failure message says which branch broke, not just that a tuple mismatched.
"""
from doc_tools.utils.sustainment_header_trust import doc_type_from_titles, titles_from_elements


def test_explicit_pcn_code_title():
    assert doc_type_from_titles(["Product Change Notice PCN-24-001"]) == ("PCN", "title"), \
        "an explicit PCN code with no conflicting keyword must resolve to PCN/title"


def test_explicit_pdn_code_title():
    assert doc_type_from_titles(["PDN Notice 2024-17"]) == ("PDN", "title"), \
        "an explicit PDN code with no conflicting keyword must resolve to PDN/title"


def test_keyword_only_pdn_title():
    assert doc_type_from_titles(["Product Obsolescence Notification"]) == ("PDN", "title"), \
        "no explicit code, but PDN keyword evidence, must still classify as PDN"


def test_keyword_only_pcn_title():
    assert doc_type_from_titles(["Product Change Notification"]) == ("PCN", "title"), \
        "no explicit code, but PCN keyword evidence, must still classify as PCN"


def test_pcn_code_plus_eol_keyword_in_the_SAME_title_is_ambiguous():
    """One title that carries the vendor's PCN code AND the vendor's own EOL wording:
    form and words disagree inside the document's single label for itself, and silently
    picking one would select a different disposition ruleset without saying so.

    NOTE this is a constructed title, not a corpus one. An earlier version of this test
    claimed EOL-36 and Diodes_PCN_2683_Rev1_EOL had this shape; measured, they do not —
    see `test_a_later_table_caption_does_not_overturn_the_headline`."""
    result = doc_type_from_titles(["PCN-2683 Rev1 End of Life Notification"])
    assert result == (None, "title-ambiguous"), \
        "a PCN code alongside PDN (EOL) keyword evidence must refuse to guess, not silently pick PCN"


def test_both_codes_present_is_ambiguous():
    assert doc_type_from_titles(["PCN/PDN combined notice"]) == (None, "title-ambiguous"), \
        "both an explicit PCN and PDN code in the same title must refuse to guess"


def test_empty_and_whitespace_titles_have_no_evidence():
    assert doc_type_from_titles([]) == (None, "no-title-evidence")
    assert doc_type_from_titles(["", "   ", None]) == (None, "no-title-evidence"), \
        "blank/whitespace-only titles must not be mistaken for evidence"


def test_no_code_no_keyword_has_no_evidence():
    assert doc_type_from_titles(["Quarterly Newsletter"]) == (None, "no-title-evidence")


def test_code_embedded_in_a_longer_token_does_not_count():
    """'PCNX' contains the substring 'PCN' but is not the code 'PCN' — a naive substring
    search would misfire here. The check must be TOKEN-BOUNDARY, not substring."""
    assert doc_type_from_titles(["PCNX Series Datasheet Update"]) == (None, "no-title-evidence"), \
        "'PCNX' must not be read as the PCN code (token-boundary check failed)"


def test_both_keyword_classes_in_one_title_and_no_code_is_ambiguous():
    """`norm.normalize_doc_type` resolves this shape by preferring PDN ("a discontinuance
    stated as a 'change' is still a discontinuance for routing"). This function does NOT
    reuse that, on purpose: the branch directly above refuses a code that its own title
    contradicts, and preferring a class here would mean the same disagreement is fatal
    when a code is present and silently resolved when it is not. A router that wants the
    discontinuance reading owns making it — and can see `doc_type` was left unstated."""
    result = doc_type_from_titles(["Product Change and End of Life Notification"])
    assert result == (None, "title-ambiguous"), \
        ("a single title asserting BOTH classes must be refused, not resolved by "
         "preference — the code branch refuses the identical disagreement")


def test_a_later_table_caption_does_not_overturn_the_headline():
    """THE MEASURED CORPUS CASE. `Diodes_PCN_2683_Rev1_EOL` is headed "PRODUCT CHANGE
    NOTICE" / "PCN-2683" and, five titles later, captions a table "Table 2 - EOL Devices
    with Life-time Buy Opportunity and No Replacement Parts".

    Read as one flat blob, that caption's "EOL" is a PDN keyword contradicting the form's
    own PCN code, and BOTH Diodes notices came back unstated — a document that labels
    itself in capitals on page 1, refused because of a table caption. A caption is
    subject matter; the headline is the document's label for itself."""
    titles = [
        "PRODUCT CHANGE NOTICE",
        "PCN-2683",
        "DESCRIPTION OF CHANGE",
        "IMPACT",
        "PRODUCTS AFFECTED",
        "Table 2 - EOL Devices with Life-time Buy Opportunity and No Replacement Parts",
    ]
    assert doc_type_from_titles(titles) == ("PCN", "title"), \
        ("the headline decides; an EOL table CAPTION must not make a self-labelled PCN "
         "unstated (measured: this is Diodes_PCN_2683_Rev1_EOL's real title list)")


def test_a_title_with_no_signal_is_skipped_rather_than_deciding():
    """TYC-PCN-24-210412's first title is "Product Change Noﬁcaon" — ligature loss has
    eaten the letters that would match a keyword — and its code lives in the THIRD title.
    So "the first title decides" must mean the first title that carries any signal, not
    the first title."""
    titles = ["Product Change Noﬁcaon", "TE Connecvity",
              "Product Change Noﬁcaon: PCN-24-210412"]
    assert doc_type_from_titles(titles) == ("PCN", "title"), \
        ("a title with neither code nor keyword must be skipped, not treated as "
         "no-title-evidence for the whole document")


def test_the_headline_wins_over_a_later_title_of_the_opposite_type():
    """MUTATION CHECK on precedence, in the direction the corpus does not exercise: a
    PDN-headed notice that later prints a PCN-ish section heading must stay PDN. If this
    fails while the Diodes test passes, the implementation is preferring PCN rather than
    preferring the headline."""
    titles = ["Product Discontinuance Notice - PDN 23_0120 Rev. -",
              "Product Change Notification history"]
    assert doc_type_from_titles(titles) == ("PDN", "title"), \
        "precedence must be positional (first signal wins), not a preference for a class"


# --------------------------------------------------------------------------- #
# titles_from_elements
# --------------------------------------------------------------------------- #
def _el(etype, text):
    return {"type": etype, "text": text}


def test_titles_from_elements_ignores_non_title_types():
    elements = [
        _el("NarrativeText", "This is body text, not a title"),
        _el("Title", "Product Change Notice"),
        _el("Table", "AD7873ACPZ AD7873ARUZ"),
    ]
    assert titles_from_elements(elements) == ["Product Change Notice"]


def test_titles_from_elements_preserves_order_across_pages():
    """Page 1 is NOT sufficient: two Diodes notices in the corpus carry their classifying
    title on a LATER page. Order must be preserved so the later, classifying title is not
    lost or reordered ahead of an earlier, non-classifying one."""
    elements = [
        _el("Title", "Cover Page"),
        _el("NarrativeText", "ignored"),
        _el("Title", "  "),                       # blank after strip -> dropped
        _el("Title", "PCN-2683 Rev1 End of Life"),
    ]
    assert titles_from_elements(elements) == ["Cover Page", "PCN-2683 Rev1 End of Life"]


def test_titles_from_elements_handles_missing_or_non_dict_elements():
    assert titles_from_elements(None) == []
    assert titles_from_elements([_el("Title", ""), "not-a-dict", {"type": "Title"}]) == []
