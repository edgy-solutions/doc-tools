"""The onsemi IPCN25300X parts loss is STOCHASTIC, and its signature is contiguity.

Measured 2026-10-15 on pin a72a4a26: three fires of ONE gate invocation against ONE
image scored this notice 19, 10 and 19 of 19. Fire 2 lost nine MPNs and raised
`crops_row_short`; fires 1 and 3 lost nothing and did not. So the loss is not a
property of the image, and its appearance implicates no code change.

WHY THIS FILE EXISTS. A stochastic loss with no written record gets rediscovered as a
new regression on every recurrence, and the cheapest way to make a red go away is to
declare the missing parts not-required. Both failure modes are asserted against here.

WHAT MAKES IT A PAGE-BREAK ORPHAN RATHER THAN NINE MISREADS. The nine lost MPNs are
positions 9-17 of the 19 in `scripts/pcn_ground_truth.json`, an unbroken run, with
1-8 and 18-19 kept. Independent misreads do not land in a contiguous block; an
orphaned table segment does.

These tests assert the RECORD and the MECHANISM, never the outcome. A test that
asserted the loss happens would fail on a good fire, and one that asserted all 19
extract would fail on a bad one — flaky either way, which is the trap a stochastic
defect sets. Nothing here runs the extractor, so nothing here is stochastic.

No S3, no LLM, no network. `scripts/` is loaded by path, as the sibling corpus tests do.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
NOTICE = "onsemi_Generic_IPCN25300X.pdf"


def _load(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


score = _load("pcn_score")


@pytest.fixture(scope="module")
def entry():
    with open(SCRIPTS / "pcn_ground_truth.json", encoding="utf-8") as fh:
        return json.load(fh)["notices"][NOTICE]


@pytest.fixture(scope="module")
def record(entry):
    return entry["_stochastic_loss"]


def test_the_record_cannot_drift_from_the_required_list(entry, record):
    """Positions are stored, so recompute them. A hand-written index that no longer
    matches `mpns` would make the contiguity claim below meaningless."""
    recomputed = [entry["mpns"].index(m) + 1 for m in record["mpns"]]
    assert recomputed == record["positions_in_mpns"]


def test_the_lost_block_is_contiguous(record):
    """THE SIGNATURE. This is the evidence that the cause is a page break and not nine
    independent row misreads, so it is asserted rather than left in prose."""
    positions = record["positions_in_mpns"]
    assert positions == list(range(positions[0], positions[0] + len(positions)))
    assert len(positions) == 9


def test_the_kept_parts_are_the_block_either_side(entry, record):
    """1-8 and 18-19 survived. If a future loss keeps a different set, the diagnosis
    has changed and this record no longer describes it."""
    lost = set(record["positions_in_mpns"])
    kept = [i + 1 for i in range(len(entry["mpns"])) if i + 1 not in lost]
    assert kept == [1, 2, 3, 4, 5, 6, 7, 8, 18, 19]


def test_all_nine_are_still_required(entry, record):
    """The point of the record is that these parts are owed, not excused."""
    assert entry["count"] == 19
    assert len(entry["mpns"]) == 19
    for mpn in record["mpns"]:
        assert mpn in entry["mpns"]


def test_none_of_them_is_exempted(entry, record):
    ruled = set(entry.get("expect_absent_mpns") or ())
    assert not (ruled & set(record["mpns"]))


def test_exempting_them_is_refused_by_the_scorer(entry, record):
    """The escape route is proven CLOSED, not merely unused. Moving the nine to
    `expect_absent_mpns` is the cheapest way to turn this red green, and it would
    assert a false fact: all 19 are verbatim in the text layer per `source`."""
    mutated = copy.deepcopy(entry)
    mutated["expect_absent_mpns"] = list(record["mpns"])
    with pytest.raises(ValueError) as exc:
        score.score_notice(list(entry["mpns"]), mutated)
    assert "required and ruled out" in str(exc.value)


def test_the_scorer_does_not_read_the_record(entry, record):
    """`_stochastic_loss` is a RECORD, NOT A RULE. A fire that loses the nine must
    still score 9 missing and must not be clean — otherwise writing the loss down
    would have exempted it, which is the opposite of the intent."""
    kept = [m for m in entry["mpns"] if m not in set(record["mpns"])]
    result = score.score_notice(kept, entry)
    assert result["exact"] == 10
    assert sorted(result["missing"]) == sorted(record["mpns"])
    assert result["spurious"] == []
    assert result["clean"] is False


def test_a_clean_fire_is_unaffected_by_the_record(entry):
    """Adding the key must not perturb normal scoring: fires 1 and 3 scored 19 of 19."""
    result = score.score_notice(list(entry["mpns"]), entry)
    assert result["exact"] == 19
    assert result["missing"] == []
    assert result["clean"] is True


def test_the_record_declares_the_loss_stochastic(record):
    """It must carry BOTH a short fire and a full one, on the same pin. A record
    showing only the failure reads as deterministic and would justify a code hunt
    that has nothing to find."""
    observed = record["observed"]
    pins = {o["pin"] for o in observed}
    assert len(pins) == 1, "a single-image comparison is what makes it stochastic"
    full = [o for o in observed if o["exact"] == 19]
    short = [o for o in observed if o["exact"] < 19]
    assert full and short
    assert len({o["fire"] for o in observed}) == len(observed)
    assert record["signature"] == "page-break orphan"


def test_the_substitution_defect_is_not_folded_in(record):
    """A one-character substitution (NSR02F30NXT5G -> NSR02E30NXT5G) was seen on this
    same notice on 10-13 fire 3. It is a DIFFERENT defect: it yields a spurious string
    rather than a contiguous block of absences, and conflating the two would hide
    whichever one is fixed second."""
    assert "NSR02E30NXT5G" not in record["mpns"]
    for o in record["observed"]:
        assert o.get("spurious") is None
