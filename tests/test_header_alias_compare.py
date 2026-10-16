"""Canonical-after-alias header comparison, and the TYC mfr flip as a test case.

WHY THIS FILE EXISTS. On 2026-10-09 a three-fire corpus-gate run produced three
written headers for TYC-PCN-24-210412.pdf that were identical in every field but
one: fire 1 wrote mfr `TE`, fires 2 and 3 wrote `TE Connectivity`. The gate
called fire 1 a declared distractor and the run FAILED on that one field, so the
verdict was decided by which member of one set of correct readings came up. The
previous day's PASS was the same coin landing the other way.

The ruling was not to exempt the field. It was that the COMPARATOR was wrong for
a verbatim field: `TE Connectivity` is the heading, `TE Connecvity` is what this
notice's damaged text layer hands an extractor, and `TE` is what the logo
renders as. All three are faithful readings of the page, so comparison resolves
a written value to its canonical form FIRST and compares canonical forms --
never raw string against `value`.

The three fire outputs are therefore a fixture, and the flip is a test case
rather than a coin. The fixture is verbatim from the pod that ran them; see its
`_provenance` block.

A deliberate non-goal: this must not become a way to make a wrong answer pass.
The tests below pin both directions -- an accepted spelling passes, and an
undeclared value, a real distractor, and a MANGLED spelling of an accepted
spelling all still fail with their own diagnosis.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pcn" / \
    "tyc-mfr-three-fires-2026-10-09.json"

NOTICE = "TYC-PCN-24-210412.pdf"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pcn_score = _load("pcn_score")


@pytest.fixture(scope="module")
def observed():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mfr_spec():
    gt = json.loads((SCRIPTS / "pcn_ground_truth.json").read_text(encoding="utf-8"))
    return gt["notices"][NOTICE]["headers"]["mfr"]


@pytest.fixture(scope="module")
def headers_spec():
    gt = json.loads((SCRIPTS / "pcn_ground_truth.json").read_text(encoding="utf-8"))
    return gt["notices"][NOTICE]["headers"]


# --------------------------------------------------------------------------
# Ground truth: the accepted set itself
# --------------------------------------------------------------------------

def test_tyc_mfr_accepts_the_three_ruled_spellings(mfr_spec):
    """The set is the ruled one, exactly -- not a superset someone widened to
    make a run go green, and not a subset that would red one again."""
    assert pcn_score.accepted_forms(mfr_spec) == (
        "TE Connectivity", "TE Connecvity", "TE")


def test_the_canonical_form_is_first_and_is_the_heading(mfr_spec):
    """Order is load-bearing: callers take forms[0] as the canonical form, and
    `TE Connectivity` is what the page prints, whatever a fire wrote."""
    assert mfr_spec["value"] == "TE Connectivity"
    assert pcn_score.accepted_forms(mfr_spec)[0] == mfr_spec["value"]


def test_the_two_former_distractors_are_no_longer_declared_as_traps(mfr_spec):
    """They were in `not` until 2026-10-09. If either comes back, this field is
    a coin flip again and this assert is the thing that says so."""
    live = [k for k in (mfr_spec.get("not") or {}) if not k.startswith("_")]
    assert live == []
    assert pcn_score.declared_distractors("mfr", mfr_spec) == {}


def test_every_accepted_spelling_carries_its_justification(mfr_spec):
    """An accepted set is a claim about the page. Each member has to say which
    part of the page it is a reading of, or the set cannot be audited."""
    for form, why in mfr_spec["accepted"].items():
        assert isinstance(why, str) and why.strip(), form


# --------------------------------------------------------------------------
# Ruling (c): the three observed fire outputs
# --------------------------------------------------------------------------

def test_the_fixture_is_the_run_that_was_observed(observed):
    """Guard on the fixture, so a later edit cannot quietly change what is being
    replayed. Three fires, the mfr flip present, every other field identical."""
    assert observed["notice"] == NOTICE
    fires = observed["fires"]
    assert [f["fire"] for f in fires] == [1, 2, 3]
    assert [f["written_header"]["mfr"] for f in fires] == [
        "TE", "TE Connectivity", "TE Connectivity"]
    others = [{k: v for k, v in f["written_header"].items() if k != "mfr"}
              for f in fires]
    assert others[0] == others[1] == others[2]


@pytest.mark.parametrize("fire,expected_status", [(1, "alias"), (2, "exact"), (3, "exact")])
def test_each_observed_fire_passes_mfr(observed, mfr_spec, fire, expected_status):
    """THE REGRESSION PIN. Fire 1 is the one the gate blocked on; it now reads
    `alias`, which is a pass. Fires 2 and 3 still read `exact` -- the fix does
    not work by loosening everything into one bucket."""
    written = observed["fires"][fire - 1]["written_header"]["mfr"]
    f = pcn_score.score_header_field("mfr", written, mfr_spec)
    assert f["status"] == expected_status
    assert f["status"] not in pcn_score.HEADER_FAILURES
    assert f["status"] in pcn_score.HEADER_PASSES


def test_no_observed_fire_has_any_header_failure(observed, headers_spec):
    """Scored over the WHOLE header block, not just mfr: the run's other fields
    each had a declared distractor one row or one print stamp away, and this
    asserts no fire took one. Had it, exempting mfr would have left the run red
    anyway, which is the thing a per-field fix can hide."""
    for fire in observed["fires"]:
        h = pcn_score.score_headers(fire["written_header"], headers_spec)
        assert h["observed"] is True
        assert h["clean"] is True, (fire["fire"], h["by_status"])
        assert not [s for s in pcn_score.HEADER_FAILURES if h["by_status"].get(s)]


def test_the_flip_is_unanimous_after_canonicalization(observed, mfr_spec):
    """The point of the ruling, stated as one assert: three different written
    strings, one canonical answer. Before it, these same three fires produced
    two verdicts."""
    forms = pcn_score.accepted_forms(mfr_spec)
    canonical = {forms[0] if f["written_header"]["mfr"] in forms else
                 f["written_header"]["mfr"] for f in observed["fires"]}
    assert canonical == {"TE Connectivity"}


def test_the_run_fails_under_a_raw_string_comparator(observed, mfr_spec):
    """What actually changed, pinned from the other side. A raw compare against
    `value` fails exactly one of the three fires -- a 1-in-3 red on a field no
    fire got wrong. If this assert ever goes green, the comparator has gone back
    to raw string and the fixture above would stop being able to tell."""
    raw_failures = [f["fire"] for f in observed["fires"]
                    if f["written_header"]["mfr"] != mfr_spec["value"]]
    assert raw_failures == [1]


def test_the_text_layer_spelling_passes_although_no_fire_wrote_it(mfr_spec):
    """`TE Connecvity` is the third member and did not appear in this run. It is
    what earlier runs produced, so it is asserted here rather than waiting for a
    fourth red on the same field."""
    f = pcn_score.score_header_field("mfr", "TE Connecvity", mfr_spec)
    assert f["status"] == "alias"
    assert f["canonical"] == "TE Connectivity"
    assert "ligature" in (f.get("why") or "")


# --------------------------------------------------------------------------
# The other direction: what must still fail
# --------------------------------------------------------------------------

def test_an_unaccounted_manufacturer_is_still_wrong(mfr_spec):
    """The accepted set is CLOSED. A manufacturer named nowhere on the page is
    not an alias of anything."""
    f = pcn_score.score_header_field("mfr", "Vishay", mfr_spec)
    assert f["status"] == "wrong"


def test_a_mangled_accepted_spelling_is_misformatted_not_laundered(mfr_spec):
    """The alias match is exact-string, so a case- or whitespace-mangled form of
    an accepted spelling falls through to the shape check and is reported
    `misformatted` -- a failure. Folding at the alias step would have made this
    a pass and turned the accepted set into a wildcard."""
    for mangled in ("te connectivity", "TE  Connectivity", " TE connecvity "):
        f = pcn_score.score_header_field("mfr", mangled, mfr_spec)
        assert f["status"] == "misformatted", mangled
        assert f["status"] in pcn_score.HEADER_FAILURES


def test_a_real_declared_distractor_still_reads_as_one(headers_spec):
    """pub_date's print stamp is the control: a field that kept its `not` block
    is unaffected by any of this, and still reports the declared trap with its
    reason rather than a bare `wrong`."""
    f = pcn_score.score_header_field("pub_date", "2024-06-10", headers_spec["pub_date"])
    assert f["status"] == "distractor"
    assert f["matched"] == "2024-06-10"
    assert "print stamp" in f["why"]


def test_absent_is_not_an_alias(mfr_spec):
    """Writing nothing is not writing an accepted spelling. `absent` is a
    failure and must not be absorbed by the alias step."""
    for empty in (None, ""):
        assert pcn_score.score_header_field("mfr", empty, mfr_spec)["status"] == "absent"


# --------------------------------------------------------------------------
# The comparator's own guards
# --------------------------------------------------------------------------

def test_a_field_with_no_accepted_block_has_exactly_one_accepted_form():
    """Every other header field in ground truth is untouched by this change and
    goes through the same comparator, so the no-alias case has to be the
    one-element case rather than a separate code path."""
    assert pcn_score.accepted_forms({"value": "PCN"}) == ("PCN",)
    assert pcn_score.accepted_forms({"value": None}) == ()


def test_a_canonical_form_outside_its_own_accepted_set_raises():
    """A ground-truth defect that would otherwise show up as a mysteriously
    failing field. Inserting the value quietly would hide it behind a pass."""
    with pytest.raises(ValueError, match="not in its own `accepted` set"):
        pcn_score.accepted_forms({"value": "TE Connectivity",
                                  "accepted": ["TE", "TE Connecvity"]})


def test_a_spelling_in_both_accepted_and_not_raises():
    """Ground truth saying a value is both verbatim-correct and a declared trap
    has no right answer: crediting it would credit a trap, failing it would fail
    a correct reading. It raises and names the field instead."""
    spec = {"value": "TE Connectivity",
            "accepted": ["TE Connectivity", "TE"],
            "not": {"TE": "was a trap"}}
    with pytest.raises(ValueError, match="BOTH"):
        pcn_score.declared_distractors("mfr", spec)


def test_the_overlap_guard_folds_before_comparing():
    """`TE` in one block and `te` in the other is the same contradiction, and a
    raw compare would miss it -- the exact class of bug this whole file is
    about."""
    spec = {"value": "TE Connectivity",
            "accepted": ["TE Connectivity", "TE"],
            "not": {" te ": "was a trap in a different shape"}}
    with pytest.raises(ValueError, match="BOTH"):
        pcn_score.declared_distractors("mfr", spec)


def test_prose_keys_are_not_read_as_values(mfr_spec):
    """Underscore keys are documentation everywhere in pcn_ground_truth.json.
    `accepted._rule` must not become an accepted spelling and `not._was` must
    not become a distractor -- the second would make the literal string `_was`
    a declared trap."""
    assert "_rule" not in pcn_score.accepted_forms(mfr_spec)
    assert "_was" not in pcn_score.declared_distractors("mfr", mfr_spec)
    assert pcn_score.score_header_field("mfr", "_was", mfr_spec)["status"] == "wrong"


# --------------------------------------------------------------------------
# Totals and reporting: a pass that is not `exact` must still be visible
# --------------------------------------------------------------------------

def test_an_alias_is_counted_apart_from_exact(observed, headers_spec):
    """`exact` stays strict. An alias is a pass but not an exact hit, so a
    reader never has to explain an `exact` short of `fields_scored` with no
    failure beside it -- and a fire answering by logo rather than by heading
    stays visible instead of being rounded up."""
    h1 = pcn_score.score_headers(observed["fires"][0]["written_header"], headers_spec)
    h2 = pcn_score.score_headers(observed["fires"][1]["written_header"], headers_spec)
    assert h1["alias"] == 1 and h1["exact"] == h2["exact"] - 1
    assert h2["alias"] == 0

    t = pcn_score.header_totals({NOTICE: {"headers": h1}})
    assert t["aliases"] == [f"{NOTICE}:mfr"]
    assert t["clean"] is True
    assert t["observed"] is True


def test_the_alias_is_named_in_the_rendered_report(observed, headers_spec):
    """A pass that is not exact has to appear in the text a human reads, or the
    accepted set becomes a silent widening of ground truth."""
    h1 = pcn_score.score_headers(observed["fires"][0]["written_header"], headers_spec)
    per = {NOTICE: {"headers": h1}}
    text = pcn_score.render_headers({"per_notice": per,
                                     "header_totals": pcn_score.header_totals(per)})
    assert "accepted alias" in text
    assert f"{NOTICE}:mfr" in text
    assert "'TE'" in text


def test_the_gate_reads_its_failure_statuses_from_the_scorer():
    """The gate used to carry its own hardcoded copy of the five failure
    statuses. A status added to the scorer would have been silently ignored by
    the gate, which is how a new failure class ends up not blocking anything."""
    gate_src = (SCRIPTS / "pcn_corpus_gate.py").read_text(encoding="utf-8")
    assert "pcn_score.HEADER_FAILURES" in gate_src
    assert '("distractor", "wrong", "misformatted", "unreadable", "absent")' \
        not in gate_src
