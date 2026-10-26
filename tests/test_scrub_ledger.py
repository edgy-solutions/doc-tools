"""The seal on the scrub ledger contract.

THE ORDER, VERBATIM
-------------------
    "4. Batch fixture: scrubber -> schema PR, continue the chain."

and from the design this implements (``invincible-agent/sessions/
2026-10-22-design-from-7f-batch-fixture-scrubber-for-chris-review.md``):

    "## 4. The ledger -- the part to review first ... One ledger per fixture,
    committed beside it. Two artifacts, not one, and the split is the point."
    "The committed ledger carries NO original value."
    "### 4.3 The verification block, which must be measured and not asserted"

WHAT IS SEALED, AND WHY EACH ONE IS A WAY THE CONTRACT COULD BE GREEN AND INERT
------------------------------------------------------------------------------
1. **A raw original value is REJECTED.** This is the one rule the module exists
   for. A ledger that accepts a part number where a redaction belongs commits
   the value -- and a transcript, as this repo already learned from a drift
   script that printed three live credentials, is not editable.
2. **Every rejection is a rejection and not a warning.** Pydantic validates on
   construction, so a model that merely *documents* an invariant in a docstring
   and never raises would look identical to one that enforces it until a bad
   ledger loaded cleanly. Each guard below asserts ``ValidationError``.
3. **The verification block cannot be silently incomplete.** A missing check is
   the default-pass failure this repo has met repeatedly (a gate that reds out
   on age, a seal green at both ends of a span it did not cover). A ledger with
   five of six checks must not load.
4. **The generated schema is not stale.** The models are the authority and the
   JSON file is their projection; a drifted projection is a consumer validating
   against permissions the loader refuses.
5. **The example fixture is valid BY CONSTRUCTION and carries no original.** The
   strongest available test of rule 1: the committed JSON is scanned for every
   synthetic original and must contain none of them.
6. **Nothing in the ingest path imports this.** Design §7: "No scrubber in the
   ingest path. This is an offline tool that produces committed artifacts."
   A comment cannot enforce that; the source walk at the bottom can.

Two tests read the SOURCE and the generated file deliberately -- an import edge
that does not exist yet and a schema that has drifted are both invisible to a
behavioural test of the models alone.
"""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from doc_tools.scrub.ledger import (LEDGER_VERSION, Check, CheckName,
                                    CheckResult, MappingPolicy, ScrubLedger,
                                    Site, is_redacted, redact, shape_of,
                                    shapes_equal)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "scrub")
EXAMPLE = os.path.join(FIXTURE_DIR, "ledger_example.json")
SCHEMA = os.path.join(ROOT, "registry", "scrub_ledger.schema.json")
# The interpreter ALREADY RUNNING the suite, never a constructed venv path.
# This was `.venv/Scripts/python.exe` and CI red-lit both staleness tests with
# a FileNotFoundError: that layout is Windows-only, and the Linux runner has
# `.venv/bin/python`. CLAUDE.md's "this repo's venv only" rule is about which
# interpreter a HUMAN invokes; inside the suite the venv is already the one
# running, so sys.executable satisfies the rule on both platforms and cannot
# drift from it.
VENV_PYTHON = sys.executable


def _read(path: str) -> str:
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def _example_dict() -> dict:
    """The committed example, as a mutable dict a test can spoil one field of."""
    return json.loads(_read(EXAMPLE))


def _spoiled(**changes):
    """The example with top-level keys replaced. Returns the ValidationError."""
    data = _example_dict()
    data.update(copy.deepcopy(changes))
    with pytest.raises(ValidationError) as caught:
        ScrubLedger.model_validate(data)
    return caught.value


# ----------------------------------------------------------------- redaction
def test_redact_is_byte_length_and_eight_hex():
    """``len=N sha256:XXXXXXXX`` and nothing else -- the repo-wide convention."""
    out = redact("ACME-77-X")
    assert out == "len=9 sha256:" + out.split(":")[1]
    assert is_redacted(out)
    assert len(out.split(":")[1]) == 8
    # len is in BYTES, so a multi-byte original is not quietly shorter than it
    # really is: this character is two bytes in utf-8 and one character.
    assert redact("µ").startswith("len=2 ")


def test_redact_agrees_between_two_ledgers_without_naming_the_value():
    """Two ledgers can agree on an original -- that is the point of a digest --
    and ``covers`` is how a reviewer holding the mapping checks one."""
    ledger = ScrubLedger.model_validate(_example_dict())
    sub = ledger.substitution_for("ACME-77-X")
    assert sub is not None
    assert sub.covers("ACME-77-X")
    assert not sub.covers("ACME-77-Y")
    assert ledger.substitution_for("never scrubbed") is None


def test_a_raw_original_value_is_rejected():
    """THE rule. A ledger field that takes a value where a redaction belongs
    commits the value, and the commit is not editable afterwards."""
    data = _example_dict()
    data["substitutions"][0]["original"] = "SYN033R60J104KE19D"
    with pytest.raises(ValidationError):
        ScrubLedger.model_validate(data)
    # ... and so are the near misses: a full digest, a bare length, upper-case
    # hex, nine hex digits, a leading zero. Each is a plausible hand-edit.
    for bad in ("len=18 sha256:" + "a" * 64, "len=18", "len=18 sha256:ABCDEF12",
                "len=18 sha256:abcdef123", "sha256:abcdef12",
                "len=018 sha256:abcdef12"):
        data["substitutions"][0]["original"] = bad
        with pytest.raises(ValidationError):
            ScrubLedger.model_validate(data)


def test_the_committed_example_contains_no_original_value():
    """The strongest form of the rule available to a test: scan the bytes.

    Every synthetic original is known to this test because the builder declares
    them; none may appear anywhere in the committed JSON -- not in a
    substitution, not in the allowlist, not in a check's detail string.
    """
    sys.path.insert(0, FIXTURE_DIR)
    try:
        import make_ledger_example
    finally:
        sys.path.pop(0)
    text = _read(EXAMPLE)
    for original, replacement in make_ledger_example.SYNTHETIC.values():
        assert original not in text, f"{original!r} leaked into the ledger"
        # The replacement, by contrast, is PUBLISHED: it is in the fixture PDF.
        assert replacement in text


# --------------------------------------------------------------------- shapes
def test_shape_keeps_punctuation_literally():
    """Design §2.1. ``SOT-23`` and ``PCN24-029`` are told apart by where the
    hyphen sits, and the extractor's shape tests read exactly that."""
    assert shape_of("SOT-23") == "AAA-99"
    assert shape_of("PCN24-029") == "AAA99-999"
    assert shape_of("ACME-77-X") == "AAAA-99-A"
    assert shape_of("Northwind Components") == "Aaaaaaaaa Aaaaaaaaaa"
    assert shape_of("") == ""


def test_shape_equality_is_not_length_equality():
    """Design §2.2b. The failure this rules out is a replacement that is the
    right LENGTH and the wrong shape -- which an extractor reading shapes sees
    as a different part number entirely."""
    assert shapes_equal("AAA999", "XQB712")
    assert not shapes_equal("AAA999", "XQBX12")  # same length, wrong shape
    assert not shapes_equal("AAA999", "XQB71")


def test_character_level_repeats_are_deliberately_not_preserved():
    """Design §2.3, recorded as a test so a later "improvement" has to argue
    with it: ``AA00AA`` -> ``XQ71BF`` is acceptable; preserving the repeat would
    leak structure of the original."""
    assert shapes_equal(shape_of("AA00AA"), "XQ71BF")


def test_a_shape_unequal_replacement_is_rejected():
    data = _example_dict()
    data["substitutions"][0]["replacement"] = "XQB712T40M558BF23"  # one short
    with pytest.raises(ValidationError, match="declared shape"):
        ScrubLedger.model_validate(data)


# ------------------------------------------------------------------ the sites
def test_an_uncounted_occurrence_is_rejected():
    """An occurrence not listed is one nobody checked was scrubbed."""
    data = _example_dict()
    data["substitutions"][0]["occurrences"] = 3  # two sites are listed
    with pytest.raises(ValidationError, match="uncounted occurrence"):
        ScrubLedger.model_validate(data)


def test_a_table_cell_site_must_be_addressed():
    """The pair-table case is a cell case; an unaddressed cell cannot be
    re-checked against the source table."""
    Site(page=1, kind="body_text")  # no address needed, and that is fine
    with pytest.raises(ValidationError, match="row and col"):
        Site(page=2, kind="table_cell", row=4)


def test_the_example_records_the_same_original_in_a_cell_and_in_a_paragraph():
    """Design §6.1 -- the case a naive per-occurrence scrub gets wrong. If the
    example stopped carrying it, the ledger would stop documenting it."""
    ledger = ScrubLedger.model_validate(_example_dict())
    affected = ledger.substitution_for("SYN033R60J104KE19D")
    assert affected is not None
    kinds = sorted(site.kind for site in affected.sites)
    assert kinds == ["body_text", "table_cell"]


# ------------------------------------------------------------- the salt's name
def test_a_salt_pasted_where_its_name_belongs_is_rejected():
    """The accident the whole redaction convention exists for, in the one field
    whose value would be a live secret."""
    for bad in (redact("a batch salt"), "a" * 32, "9f8e7d6c5b4a3f2e",
                "c2VjcmV0LXNhbHQtdmFsdWUtaGVyZQ=="):
        data = _example_dict()
        data["scrub"]["salt_ref"] = bad
        with pytest.raises(ValidationError):
            ScrubLedger.model_validate(data)


def test_run_at_must_be_a_utc_instant():
    for bad in ("2026-10-25", "2026-10-25T06:10:00",
                "2026-10-25T06:10:00+00:00", "yesterday"):
        data = _example_dict()
        data["scrub"]["run_at"] = bad
        with pytest.raises(ValidationError, match="UTC instant"):
            ScrubLedger.model_validate(data)


# ---------------------------------------------------------------- the mapping
def test_the_mapping_policy_and_the_mapping_reference_must_agree_both_ways():
    """A one-way scrub that names a mapping either kept one or is lying about
    which -- and either way the ledger's own claim cannot be trusted."""
    data = _example_dict()
    assert data["policy"]["mapping"] == MappingPolicy.ONE_WAY.value
    data["scrub"]["mapping_ref"] = "sandbox/scrub-mapping#example"
    with pytest.raises(ValidationError, match="keeps no re-identification key"):
        ScrubLedger.model_validate(data)

    data = _example_dict()
    data["policy"]["mapping"] = MappingPolicy.RETAINED.value
    with pytest.raises(ValidationError, match="mapping_ref is empty"):
        ScrubLedger.model_validate(data)


def test_the_mapping_must_be_injective_in_both_directions():
    data = _example_dict()
    data["substitutions"][1]["replacement"] = \
        data["substitutions"][0]["replacement"]
    with pytest.raises(ValidationError, match="injective"):
        ScrubLedger.model_validate(data)

    data = _example_dict()
    data["substitutions"][1]["original"] = data["substitutions"][0]["original"]
    data["substitutions"][1]["shape"] = data["substitutions"][0]["shape"]
    with pytest.raises(ValidationError, match="merge the sites"):
        ScrubLedger.model_validate(data)


def test_a_replacement_may_not_land_on_an_allowlisted_string():
    """Design §3.3: "Allowlist by VOCABULARY, scrub by SHAPE, and let the
    allowlist win." A replacement equal to an allowlisted header inverts that."""
    data = _example_dict()
    data["allowlisted"].append({"text": data["substitutions"][0]["replacement"],
                                "rule": "header_vocabulary", "count": 1})
    with pytest.raises(ValidationError, match="allowlisted strings"):
        ScrubLedger.model_validate(data)


# -------------------------------------------------------------- verification
def test_every_check_must_be_present():
    """A missing check is not a default pass. This repo has been bitten by the
    opposite reading more than once."""
    data = _example_dict()
    del data["verification"]["checks"][CheckName.LEAK_TEST.value]
    error = str(_spoiled(verification=data["verification"]))
    assert "missing" in error
    assert CheckName.LEAK_TEST.value in error
    assert "not a default pass" in error


def test_a_not_run_check_must_say_why():
    """Recording a check as not-run is the honest option; recording it as
    not-run with no reason records nothing."""
    with pytest.raises(ValidationError, match="must say why"):
        Check(result=CheckResult.NOT_RUN, detail="skipped")
    Check(result=CheckResult.NOT_RUN,
          detail="no mapping retained, so the equivalence seal cannot run")


def test_an_empty_detail_is_rejected_on_every_result():
    """"Measured and not asserted" (§4.3): a PASS with nothing measured is an
    assertion wearing a measurement's clothes."""
    for result in CheckResult:
        with pytest.raises(ValidationError):
            Check(result=result, detail="")


def test_committable_is_false_unless_every_check_passed():
    """A REFUSED leak test -- the text-layer-below-threshold case -- fails
    CLOSED. Image-borne text is the known hole, and a PDF whose parts live in an
    image is exactly the document this must say no to."""
    ledger = ScrubLedger.model_validate(_example_dict())
    assert ledger.committable
    assert ledger.why_not_committable() == ""

    for bad in (CheckResult.FAIL, CheckResult.REFUSED, CheckResult.NOT_RUN):
        data = _example_dict()
        data["verification"]["checks"][CheckName.LEAK_TEST.value] = {
            "result": bad.value,
            "detail": "page 2's text layer retained 11% of the source's "
                      "characters; the parts table is an image",
            "measurements": {"min_page_text_retention": 0.11},
        }
        spoiled = ScrubLedger.model_validate(data)
        assert not spoiled.committable
        assert CheckName.LEAK_TEST.value in spoiled.why_not_committable()
        assert spoiled.verification.failed == [CheckName.LEAK_TEST.value]


def test_the_examples_checks_carry_measurements_not_just_a_result():
    """§4.3 again, now against the committed example: a check with a bare PASS
    and no counts would make the whole block decorative."""
    ledger = ScrubLedger.model_validate(_example_dict())
    for name, check in ledger.verification.checks.items():
        assert check.result is CheckResult.PASS
        assert len(check.detail) > 20, name
        assert check.measurements, name
    leak = ledger.verification.checks[CheckName.LEAK_TEST]
    # The threshold the leak test fails closed below is a MEASUREMENT.
    assert "min_page_text_retention" in leak.measurements
    collision = ledger.verification.checks[CheckName.COLLISION_CHECK]
    assert collision.measurements["reserved_space"] == "XQB"


# -------------------------------------------------------------------- policy
def test_the_policy_block_records_an_answer_and_defaults_to_nothing():
    """Why the schema could land with four rulings open: every policy field is
    REQUIRED, so a fixture states its assumptions instead of inheriting them."""
    data = _example_dict()
    for field in ("manufacturer_name", "dates", "mapping",
                  "enters_scored_corpus", "authority"):
        spoiled = _example_dict()
        del spoiled["policy"][field]
        with pytest.raises(ValidationError):
            ScrubLedger.model_validate(spoiled)
    # And the example says in its own authority string that it is not ruled.
    assert "RECOMMENDATION ONLY" in data["policy"]["authority"]
    assert data["policy"]["enters_scored_corpus"] is False


def test_an_unknown_ledger_version_is_rejected():
    """A reader that guesses at an unknown version is how a schema change
    becomes a silent misread."""
    with pytest.raises(ValidationError, match="is not"):
        ScrubLedger.model_validate(dict(_example_dict(),
                                        ledger_version=LEDGER_VERSION + 1))


def test_an_unknown_field_is_rejected_and_a_ledger_is_frozen():
    """``extra="forbid"``: a typo'd key is a field nobody reads, and on this
    schema a field nobody reads could be one holding an original."""
    with pytest.raises(ValidationError):
        ScrubLedger.model_validate(dict(_example_dict(), orignal_value="x"))
    ledger = ScrubLedger.model_validate(_example_dict())
    with pytest.raises(ValidationError):
        ledger.fixture_id = "something else"


# ------------------------------------------------- the generated projection
def test_the_schema_projection_is_not_stale():
    """The models are the authority; the JSON file is their projection. A
    drifted projection lets a non-Python consumer validate against permissions
    the loader refuses -- including, in the worst case, an original in clear."""
    assert os.path.exists(SCHEMA), "run scripts/generate_scrub_ledger_schema.py"
    completed = subprocess.run(
        [VENV_PYTHON, os.path.join("scripts", "generate_scrub_ledger_schema.py"),
         "--check"], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_example_fixture_is_not_stale():
    completed = subprocess.run(
        [VENV_PYTHON,
         os.path.join("tests", "fixtures", "scrub", "make_ledger_example.py"),
         "--check"], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_schema_carries_the_redaction_pattern_and_its_own_caveat():
    """The pattern is the one rule a non-Python consumer MUST get; the caveat is
    the honest statement that the rest of the rules are not in this file."""
    schema = json.loads(_read(SCHEMA))
    text = json.dumps(schema)
    assert "len=(0|[1-9][0-9]*) sha256:[0-9a-f]{8}" in text
    assert "shape, not its truth" in schema["$comment"]
    assert "do not edit" in schema["$comment"]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


# ---------------------------------------------------- design §7, as a guard
def test_nothing_in_the_ingest_path_imports_the_scrubber():
    """Design §7: "No scrubber in the ingest path. This is an offline tool that
    produces committed artifacts; nothing in ``doc_tools/`` imports it."

    A comment cannot enforce that. One import edge from an asset or a pass would
    put a tool whose whole job is to touch original values into the pipeline
    that runs against live documents.
    """
    offenders = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "doc_tools")):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "scrub")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            for line in _read(path).splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ")
                        or stripped.startswith("from ")):
                    continue
                if "scrub" in stripped:
                    offenders.append(f"{path}: {stripped}")
    assert offenders == [], (
        "design §7 says the scrubber is offline and nothing in doc_tools "
        f"imports it: {offenders}")
