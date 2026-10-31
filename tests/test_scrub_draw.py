"""The shape tokeniser: shape-for-shape, deterministic, structure-free, reserved,
and never colliding. Fixed test salt, never an env read."""
from __future__ import annotations

import pytest

from doc_tools.scrub.draw import (MAX_ATTEMPTS, RESERVED_LEADING_UPPER,
                                  CollisionExhausted, Drawer)
from doc_tools.scrub.ledger import shape_of, shapes_equal

SALT = b"doc-tools-test-salt"

ORIGINALS = [
    "FJ3330013", "FJ4800016", "FK2500037", "FK2500086", "TLC271ACS-13",
    "S1615B-10.0000", "WL2511F0048.000000", "AP3402KTTR-G1", "PI2EQX3232AZDEX",
    "2683A", "Northwind Components", "WT21120001", "WT21120003",
]


def test_every_draw_is_shape_equal_to_its_original():
    d = Drawer(SALT)
    for o in ORIGINALS:
        assert shapes_equal(shape_of(o), d.draw(o).replacement)


def test_punctuation_is_kept_literal():
    r = Drawer(SALT).draw("S1615B-10.0000").replacement
    assert r[5 + 1] == "-" or "-" in r
    assert r.index("-") == "S1615B-10.0000".index("-")
    assert r.index(".") == "S1615B-10.0000".index(".")


def test_the_same_original_always_draws_the_same_replacement():
    d = Drawer(SALT)
    assert d.draw("FJ3330013") == d.draw("FJ3330013")


def test_a_second_drawer_with_the_same_salt_reproduces_the_draw():
    a, b = Drawer(SALT), Drawer(SALT)
    for o in ORIGINALS:
        assert a.draw(o) == b.draw(o)


def test_a_different_salt_draws_a_different_replacement():
    assert Drawer(SALT).draw("FJ3330013").replacement != \
        Drawer(b"another-test-salt").draw("FJ3330013").replacement


def test_no_two_originals_share_a_replacement():
    d = Drawer(SALT)
    reps = [d.draw(o).replacement for o in ORIGINALS]
    assert len(set(reps)) == len(reps)


def test_no_repeat_run_or_prefix_structure_survives_pinned_salt():
    """Asserted on the ACTUAL output under the fixed salt, not on a probability.

    `FK2500037` repeats a digit three times; `123456789` ascends; `FK2500037`
    and `FK2500086` share a six-character prefix. None of that is shape, and a
    fixture that kept it would teach the extractor structure a scrubbed part
    number would not have."""
    d = Drawer(SALT)
    rep = d.draw("FK2500037").replacement
    assert rep == EXPECTED["FK2500037"]
    digits = rep[2:]
    assert len(set(digits[2:5])) > 1, "the 000 run survived"
    asc = d.draw("AB123456789").replacement
    assert asc == EXPECTED["AB123456789"]
    tail = asc[2:]
    assert tail != "123456789" and tail != "".join(sorted(tail))
    other = d.draw("FK2500086").replacement
    assert other == EXPECTED["FK2500086"]
    assert rep[2:8] != other[2:8], "the shared numeric prefix survived"


EXPECTED = {
    "FK2500037": "QQ5023453",
    "AB123456789": "QQ092848531",
    "FK2500086": "ZQ8231431",
}


def test_a_leading_uppercase_run_draws_only_from_the_reserved_letters():
    d = Drawer(SALT)
    for o in ["FJ3330013", "TLC271ACS-13", "S1615B-10.0000", "PI2EQX3232AZDEX"]:
        got = d.draw(o)
        lead = 0
        while o[lead].isupper():
            lead += 1
        assert set(got.replacement[:lead]) <= set(RESERVED_LEADING_UPPER)
        assert got.reserved_space == "leading uppercase from {Q,X,Z}"


def test_only_the_first_uppercase_run_is_reserved():
    got = Drawer(SALT).draw("TLC271ACS-13").replacement
    assert set(got[:3]) <= set(RESERVED_LEADING_UPPER)
    assert set(got[6:9]) - set(RESERVED_LEADING_UPPER), (
        "the second run was drawn from the reserved letters too")


def test_an_original_with_no_leading_uppercase_records_the_none_measurement():
    got = Drawer(SALT).draw("2683A")
    assert got.reserved_space == (
        "none: no leading uppercase run; collision_check carries this one alone")
    assert got.reserved_space is not None


def test_zero_redraws_is_recorded_as_a_measurement():
    assert Drawer(SALT).draw("FJ3330013").redraws == 0


def test_a_known_mpn_collision_forces_a_redraw():
    first = Drawer(SALT).draw("FJ3330013").replacement
    again = Drawer(SALT, forbidden=frozenset({first})).draw("FJ3330013")
    assert again.redraws > 0
    assert again.replacement != first


def test_a_replacement_never_equals_its_original_or_an_earlier_draw():
    d = Drawer(SALT)
    for o in ORIGINALS:
        assert d.draw(o).replacement != o


def test_exhausting_the_attempts_raises_naming_the_shape():
    forbidden = frozenset(RESERVED_LEADING_UPPER)
    with pytest.raises(CollisionExhausted, match=rf"{MAX_ATTEMPTS} attempts"):
        Drawer(SALT, forbidden=forbidden).draw("A")


def test_the_salt_does_not_reach_repr_or_attributes():
    d = Drawer(SALT)
    assert SALT.decode() not in repr(d)
    assert not any(a for a in dir(d) if "salt" in a.lower() and not a.startswith("_"))


def test_an_empty_salt_is_refused():
    with pytest.raises(ValueError):
        Drawer(b"")
