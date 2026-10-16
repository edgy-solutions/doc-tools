"""The witness line the corpus gate's fire log must carry.

ORDERED REQUIREMENT, 2026-10-09: "run the gate three fires; witness line must be
in the fire log." These tests pin the line's existence, its content, and the one
property that makes it useful -- that it is printed on EVERY path, including the
paths where corroboration does not run.

Why it did not exist: the header trust reasons reached `review_reasons` in
review.json only. The gate reads two artifacts per fire, `fire{N}.log` (the
fire's stdout, captured by `pcn_corpus_gate.run_fires` with `stdout=logf`) and
`corpus_f{N}.json` (post-trust WRITTEN values). Measured at pin `6dc19712`:
`grep -a` for `region witness` and for `header.mfr` across all three fire logs
returned nothing, so whether fire 1's `mfr` had been corroborated or merely left
unchallenged was not in evidence in anything that run produced.
"""

import ast
import pathlib

from doc_tools.utils import sustainment_header_trust as trust

# A witness record shaped as `witness_regions.regions_for_document` emits them:
# the element_id ends with the REGION_SPECS name, and the text is the model's
# verbatim `Label: value` answer block.
WITNESS = [{
    "element_id": "witness_p1_header_block",
    "text": ("Manufacturer: TE Connectivity\n"
             "Document Number: PCN-24-210412\n"
             "Notice Date: 07-JUN-2024"),
}]

# The token a human or a grep looks for. Changing it is a breaking change to the
# gate's readability, so it is asserted by name rather than implied.
TOKEN = "header trust witness: "


def test_the_line_names_what_the_witness_read_and_what_was_written():
    line = trust.header_witness_summary(
        {"mfr": "TE", "mfr_source": "TE"}, WITNESS, text_layer_degraded=True)
    assert line.startswith(TOKEN)
    assert "witness_mfr='TE Connectivity'" in line
    assert "written_mfr='TE'" in line
    assert "degraded=True" in line
    assert "witness_regions=1" in line
    # The citation's presence, never the citation itself: a region answer can be a
    # whole paragraph and this line is read in a log.
    assert "witness_mfr_cited=True" in line


def test_a_degraded_document_with_no_witness_reading_says_so_rather_than_being_silent():
    """The absence of a reading is the finding, so it has to be printed.

    This is the fire-1 case that could not be settled from the artifacts: an
    `mfr` the witness did not corroborate and an `mfr` the witness agreed with
    were indistinguishable, because neither produced any output at all.
    """
    line = trust.header_witness_summary(
        {"mfr": "TE Connecvity", "mfr_source": "TE Connecvity"},
        [{"element_id": "witness_p1_header_block", "text": "Manufacturer: not shown"}],
        text_layer_degraded=True)
    assert "witness_mfr=None" in line
    assert "degraded=True" in line
    assert "written_mfr='TE Connecvity'" in line


def test_the_line_is_printed_on_a_healthy_document_too():
    """`degraded=False` is a fact about the document, not a missing measurement.

    `require_mfr_witness_agreement` deliberately returns [] on a healthy text
    layer. If the line were conditional on that check having run, a healthy
    document would produce no witness line and a reader could not tell it apart
    from an instrumentation failure.
    """
    line = trust.header_witness_summary({"mfr": "SEMELAB"}, None,
                                        text_layer_degraded=False)
    assert line.startswith(TOKEN)
    assert "degraded=False" in line
    assert "witness_regions=0" in line
    assert "written_mfr='SEMELAB'" in line


def test_it_decides_nothing_and_mutates_nothing():
    header = {"mfr": "TE", "mfr_source": "TE"}
    before = dict(header)
    trust.header_witness_summary(header, WITNESS, text_layer_degraded=True)
    assert header == before


def test_a_witness_that_cannot_be_parsed_still_yields_a_line():
    """A log line must never be the thing that loses a document."""

    class Exploding:
        def __iter__(self):
            raise RuntimeError("boom")

        def __len__(self):
            return 1

    line = trust.header_witness_summary({"mfr": "TE"}, Exploding(),
                                        text_layer_degraded=True)
    assert line.startswith(TOKEN)
    assert "parse_error=" in line


def test_an_absent_mfr_prints_none_not_an_empty_string():
    """`''` and None are different outcomes: the refusal writes `''`."""
    line = trust.header_witness_summary({"mfr": ""}, WITNESS,
                                        text_layer_degraded=True)
    assert "written_mfr=None" in line


def test_the_plugin_prints_the_summary_and_every_trust_reason():
    """Wiring, read off the source: the helper is useless if nothing calls it.

    Asserted structurally rather than by driving a full extraction, because the
    header pass needs a live model. The companion behavioural coverage of the
    three trust calls is in tests/test_second_witness_wiring.py.
    """
    src = pathlib.Path("doc_tools/plugins/sustainment.py").read_text(encoding="utf-8")
    ast.parse(src)  # a print statement in a file that does not import is no line
    assert "header_trust.header_witness_summary(" in src
    # Printed, not appended to `reasons`: stdout is what the gate captures.
    assert 'print("[SustainmentPlugin] " + header_trust.header_witness_summary(' in src
    assert 'print(f"[SustainmentPlugin] header trust: {_r}")' in src
    # And the reasons still reach review.json, which was never the problem.
    assert "reasons += trust_reasons" in src


def test_the_summary_runs_after_all_three_trust_calls():
    """Order matters: a summary printed before the corroboration check would name
    the value the check is about to withdraw, which is the opposite of useful."""
    src = pathlib.Path("doc_tools/plugins/sustainment.py").read_text(encoding="utf-8")
    i_supply = src.index("trust_reasons += header_trust.supply_header_from_regions(")
    i_refuse = src.index("trust_reasons += header_trust.refuse_unsourced_header_values(")
    i_corrob = src.index("trust_reasons += header_trust.require_mfr_witness_agreement(")
    i_print = src.index('print("[SustainmentPlugin] " + header_trust.header_witness_summary(')
    assert i_supply < i_refuse < i_corrob < i_print
