"""A form LABEL written into a header field is refused (`refuse_field_label_echoes`).

Fixture: `doc_id == "PCN #: 2683"` on the Diodes notice (byte-identical files
`Diodes_PCN_2683_Rev1_EOL.pdf` / `Diodes_PCN_2683_FULLGREEN.pdf`). A sourcing check cannot
see it because the label+value is printed as one text run.

Scope: this makes a silent write a declared refusal for the fields with no recovery
path. `doc_id`, the field the fixture was found in, is NOT refused — `normalize_doc_id`
maps the echo to the correct `PCN-2683`, so the pipeline re-asserts that normalization
after the last writer instead of discarding a recoverable value.
"""
import pathlib
import re

import pytest

from doc_tools.utils import provenance
from doc_tools.utils import sustainment_header_trust as T
from doc_tools.utils.sustainment_normalize import normalize_doc_id
from doc_tools.utils.sustainment_header_trust import (
    is_field_label_echo,
    refuse_field_label_echoes,
    refuse_unsourced_header_values,
)


def test_fixture_pcn_hash_colon_2683_has_the_echo_shape():
    """The fixture is the shape the predicate exists to detect."""
    assert is_field_label_echo("PCN #: 2683")


def test_the_fixture_field_doc_id_is_recovered_not_refused():
    """`doc_id` is the field the echo was found in and the one field a refusal
    would make worse: the value is fully recoverable, so blanking it would discard a
    correct answer. The pipeline re-asserts the normalization invariant instead."""
    h = {"doc_id": "PCN #: 2683", "doc_id_source": "PCN #: 2683"}
    assert refuse_field_label_echoes(h) == []
    assert h["doc_id"] == "PCN #: 2683"
    assert normalize_doc_id(h["doc_id"]) == "PCN-2683"


@pytest.mark.parametrize("value", [
    "PCN Number: 2683", "Document No.: ABC", "Revision:", "PCN #:", "Eff Date: 2024-06-06",
    "Widget Ref: 77x",  # unlisted label, same structure
])
def test_variants_are_label_echoes(value):
    assert is_field_label_echo(value)


@pytest.mark.parametrize("value", [
    "PCN-2683",
    "Semelab: a TT Electronics company and part of a larger group",  # long right side
    "2683: foo",  # digits in the pre-colon part
    "http://www.diodes.com",
    "12:30 UTC",
    "This notice informs customers that the following change applies: see the attached",
    "", None, 5, ["PCN #: 1"], ":", "a",
])
def test_conservative_guards_survive(value):
    assert not is_field_label_echo(value)


def test_clean_values_are_untouched():
    h = {"doc_id": "PCN-2683", "mfr": "Diodes Incorporated", "revision": "R1"}
    before = dict(h)
    assert refuse_field_label_echoes(h) == []
    assert h == before


def test_per_field_blank_convention():
    h = {"mfr": "Manufacturer: Diodes", "mfr_parent": "Parent Co: X",
         "pub_date": "Date: 2024", "doc_level_ltb_date": "LTB Date: 2025",
         "revision": "Revision:"}
    reasons = refuse_field_label_echoes(h)
    assert len(reasons) == 5
    blanks = {f: s for f, _, s, _ in ((a, b, c, d) for a, b, c, d in T.HEADER_SOURCED_FIELDS)}
    assert h["mfr"] == blanks["mfr"] == ""
    assert h["pub_date"] == blanks["pub_date"] == ""
    assert h["mfr_parent"] is None and blanks["mfr_parent"] is None
    assert h["doc_level_ltb_date"] is None and blanks["doc_level_ltb_date"] is None
    assert h["revision"] is None


@pytest.mark.parametrize("bad", [
    {}, {"doc_id": None}, {"doc_id": 5, "mfr": ["PCN #: 1"]}, {"revision": {"a": 1}},
    {"doc_id": b"PCN #: 1"}, None, "not a dict",
])
def test_never_raises_on_malformed_header(bad):
    assert isinstance(refuse_field_label_echoes(bad), list)


def _index(*texts):
    els = [{"type": "NarrativeText", "text": t,
            "metadata": {"page_number": 1,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792}}}
           for t in texts]
    return provenance.build_positioned_index(els)


def test_a_verbatim_label_echo_is_reported_as_a_label_echo_in_pipeline_order():
    """The case that inverts if the order is wrong: the echo IS printed on the page."""
    idx = _index("Manufacturer: Diodes", "Some other text on the notice.")
    h = {"mfr": "Manufacturer: Diodes", "mfr_source": "Manufacturer: Diodes"}
    reasons = refuse_field_label_echoes(h)
    reasons += refuse_unsourced_header_values(h, idx)
    assert any("form LABEL" in r and "header.mfr" in r for r in reasons), reasons
    assert h["mfr"] != "Manufacturer: Diodes"

    # Reverse order: the sourcing check passes the verbatim echo through.
    h2 = {"mfr": "Manufacturer: Diodes", "mfr_source": "Manufacturer: Diodes"}
    refuse_unsourced_header_values(h2, idx)
    assert h2["mfr"] == "Manufacturer: Diodes"


def test_plugin_calls_label_refusal_between_supply_and_unsourced_refusal():
    src = (pathlib.Path(T.__file__).parents[1] / "plugins" / "sustainment.py").read_text(
        encoding="utf-8")
    pos = {n: [m.start() for m in re.finditer(r"header_trust\." + n + r"\(", src)]
           for n in ("supply_header_from_regions", "refuse_field_label_echoes",
                     "refuse_unsourced_header_values", "require_mfr_witness_agreement")}
    assert all(len(v) == 1 for v in pos.values()), pos
    a, b, c, d = (pos[n][0] for n in ("supply_header_from_regions",
                                      "refuse_field_label_echoes",
                                      "refuse_unsourced_header_values",
                                      "require_mfr_witness_agreement"))
    assert a < b < c < d
