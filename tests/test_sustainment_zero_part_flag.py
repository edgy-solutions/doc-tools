"""THE ADI_PCN_24_0003 SHAPE: a parts pass that ran, emitted nothing, and flagged nothing.

ADI_PCN_24_0003 lists ~1,577 affected parts as plain `Family / Model` text and its ONLY
`Table` element is the page-1 contact block ("Americas: Europe: Japan: ..."). Because a
table exists the router takes the table branch, vision correctly reports no parts column
and returns 0 rows, and `_apply_vision_stats` flags only crops_failed / crops_near_cap /
crops_row_short -- so zero rows with no parts column flagged NOTHING. `needs_review`
stayed false with no reasons, and the whole notice was lost silently. Measured by
invincible-agent/lane/01 at doc-tools@809963cb.

WHY THESE TESTS GO THROUGH `_extract_fulltext` AND NOT THROUGH `parts_text_list` ALONE.
The salvage's parsing is unit-tested in tests/test_parts_text_list.py. What those tests
CANNOT see is the half that actually failed on ADI: the router reaching the salvage at
all, and the flag being set. A pure-module test of a parser would have been green on the
day the notice was lost. So these drive the real dispatch, with the BAML client faked,
following the harness in tests/test_sustainment_grid_forwarding_mixed.py.

The fake is a fake of the MODEL, not of the thing under test. Vision returning [] is the
measured truth for this document -- vision read the contact block correctly and there
were no parts in it -- so the stub states a fact rather than standing in for one. Every
assertion below is on the ROUTER'S OWN OUTPUT (which rows, which reasons, which banner),
never on a value the fake supplied.
"""
import pytest

from doc_tools.baml_client import sync_client as sync_client_module
from doc_tools.plugins import sustainment as sustainment_module
from doc_tools.plugins.sustainment import SustainmentPlugin

# Six Family / Model pairs, flattened onto two lines the way a multi-column list arrives
# out of unstructured's UncategorizedText / NarrativeText / Title elements.
PAIRS = [
    ("AD8601", "AD8601ARTZ-REEL7"),
    ("LTC1326", "LTC1326CMS8#TRPBF"),
    ("ADG704", "ADG704BRMZ-REEL"),
    ("AD5693R", "AD5693RBRMZ-RL7"),
    ("LT3045", "LT3045EDD#TRPBF"),
    ("ADA4051", "ADA4051-2AUJZ-R7"),
]
MODELS = [m for _, m in PAIRS]

# The exact Title string that the old eight-label tuple missed: ADI puts a vendor word
# INSIDE the label, so "affected models" never appears as a substring.
ADI_HEADING = "Appendix A - Affected ADI Models:"


def _pairs_text(caption_count=6):
    """The ADI page-2 shape: the heading, the self-counting caption, then the pairs."""
    half = len(PAIRS) // 2
    lines = [
        ADI_HEADING,
        f"Added Parts On This Revision - Product Family / Model Number ({caption_count})",
        "  ".join(f"{f} / {m}" for f, m in PAIRS[:half]),
        "  ".join(f"{f} / {m}" for f, m in PAIRS[half:]),
    ]
    return "\n".join(lines)


# Names an affected-parts section and carries an MPN-shaped token, but prints no pair:
# the salvage must decline and the ZERO-PART FLAG must fire instead.
NO_PAIRS_TEXT = "MODELS AFFECTED\nThe device XYZ1234ABC is affected by this change.\n"

# The page-1 ADI contact block: a real Table element carrying no parts column. This is
# what makes `tables` non-empty and sends the document down the table branch.
CONTACT_TABLE = {"type": "Table",
                 "text": "Americas: Europe: Japan: Korea: Rest of Asia:",
                 "metadata": {}}


class _FakeB:
    """ExtractParts returns [] -- the measured outcome on the contact block."""

    def __init__(self):
        self.extract_parts_calls = 0

    def ExtractParts(self, **kwargs):
        self.extract_parts_calls += 1
        return []

    def LabelGridColumns(self, **kwargs):  # pragma: no cover - no declines in these tests
        raise AssertionError("no declined grid in these tests")


@pytest.fixture(autouse=True)
def _prompt_from_file(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    monkeypatch.setattr(sustainment_module, "_vision_output_tokens", lambda collector: 10)


@pytest.fixture
def plugin():
    return SustainmentPlugin(domain_type="sustainment")


def _run(plugin, monkeypatch, full_text, elements, vision=True):
    """Drive the real router. Tier 1 emits nothing (no grid in this document at all)."""
    fake = _FakeB()
    monkeypatch.setattr(sync_client_module, "b", fake)
    monkeypatch.setattr(
        plugin, "_extract_parts_text_layer",
        lambda manifest, s3, bucket: ([], {
            "text_layer_pages": 1, "text_layer_parts": 0,
            "text_layer_used": False, "text_layer_declines": []}))
    monkeypatch.setattr(plugin, "_extract_header", lambda full_text: None)
    if vision:
        monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision")
    else:
        monkeypatch.delenv("VISION_LLM_BASE_URL", raising=False)
    nodes = plugin._extract_fulltext(
        full_text, "DOC1", metadata=None, elements=elements,
        manifest={"source_key": "notice.pdf"}, s3_client=object(), bucket="bucket")
    return nodes[0].domain_augmentation, fake


def _mpns(aug):
    return [p.affected_mpn for p in aug.notice.impacted_parts]


def _reasons(aug):
    return aug.review_reasons


def _banners(aug):
    return aug.review["doc_review_reasons"]


def test_the_adi_shape_salvages_the_text_list_and_forces_review(plugin, monkeypatch):
    """The defect, end to end: a contact table takes the table branch and the parts
    still come out -- deterministically, from the text, with no second vision call."""
    aug, fake = _run(plugin, monkeypatch, _pairs_text(), [CONTACT_TABLE])

    # The rows are the MODEL side of each pair, verbatim, in document order.
    assert _mpns(aug) == MODELS
    for p in aug.notice.impacted_parts:
        assert p.affected_mpn == p.affected_mpn_source, "the token IS the source"
    assert aug.stats["router_text_list_used"] is True
    assert aug.stats["text_list_parts"] == len(MODELS)
    assert aug.stats["text_list_caption_count"] == 6
    # The pass DID run and DID return nothing -- that is what made the salvage necessary.
    assert fake.extract_parts_calls == 1
    assert aug.stats["vision_used"] is True
    # No grid, no column header, no cell provenance: a human confirms the list.
    assert aug.needs_review is True
    assert any("salvaged" in r for r in _reasons(aug))
    # Nothing is claimed MISSING here: the parts were recovered.
    assert not any("PARTS MAY BE MISSING" in b for b in _banners(aug))


def test_a_caption_shortfall_is_reported(plugin, monkeypatch):
    """The document's own count is the oracle. 6 parsed against a caption of 20 is a
    shortfall and says so; it never silently reports 6 as the whole list."""
    aug, _ = _run(plugin, monkeypatch, _pairs_text(caption_count=20), [CONTACT_TABLE])

    assert _mpns(aug) == MODELS
    assert aug.stats["text_list_shortfall"] is True
    assert "caption of 20" in aug.stats["text_list_shortfall_detail"]
    assert any("shortfall" in r for r in _reasons(aug))
    assert aug.needs_review is True


def test_a_pass_that_ran_and_emitted_nothing_is_flagged_and_bannered(plugin, monkeypatch):
    """The cheap fix that stops the silence. No pair to salvage, so the parts stay lost --
    but the notice is no longer lost QUIETLY, which is the whole defect."""
    aug, fake = _run(plugin, monkeypatch, NO_PAIRS_TEXT, [CONTACT_TABLE])

    assert _mpns(aug) == []
    assert fake.extract_parts_calls == 1
    assert aug.needs_review is True
    assert any("emitted 0 parts" in r for r in _reasons(aug))
    # The text advertises a parts list, so the banner is earned.
    assert any("PARTS MAY BE MISSING" in b for b in _banners(aug))
    assert "router_text_list_used" not in aug.stats


def test_a_header_only_notice_that_ran_no_pass_is_NOT_flagged(plugin, monkeypatch):
    """THE FALSE-POSITIVE CONTROL, and the reason the flag reads `stats` and not the
    branch. A process-change notice with no table and no parts list is the COMMON case;
    flagging it would make a banner -- a hard refusal downstream -- the default outcome
    for every ordinary notice. The `elif not tables` branch deliberately sets no flag and
    must keep setting none.
    """
    aug, fake = _run(plugin, monkeypatch,
                     "This notice announces a process change. No devices are affected.",
                     [], vision=False)

    assert _mpns(aug) == []
    assert fake.extract_parts_calls == 0
    assert not any("emitted 0 parts" in r for r in _reasons(aug))
    assert not any("PARTS MAY BE MISSING" in b for b in _banners(aug))
    assert "router_text_list_used" not in aug.stats
