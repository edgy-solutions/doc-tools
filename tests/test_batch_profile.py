"""Arms for doc_tools.batch.profile: one per finding code, plus the shipped profile."""
import copy
import json
from pathlib import Path

import pytest

from doc_tools.batch.profile import Catalogue, load_profile, validate_profile

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "registry" / "batch_profiles" / "pcn-ltb-by-part.yaml"


def profile(*columns, granularity="notice_part"):
    return {"name": "t", "granularity": granularity, "columns": list(columns)}


def col(output, field=None, **kw):
    c = {"output": output, **kw}
    if field:
        c["source"] = {"field": field}
    return c


def hits(findings, code):
    return [f for f in findings if f.code == code]


def test_shipped_profile_has_no_errors():
    found = validate_profile(load_profile(SHIPPED))
    errors = [f for f in found if f.severity == "error"]
    warnings = [f"{f.code}@{f.where}" for f in found if f.severity == "warning"]
    assert not errors, (errors, "warnings:", warnings)


def test_catalogue_as_measured_today():
    """Reads the catalogue; transcribes nothing.

    The contract section 9 says "28 of the 57" and is stale (part.customer_mpn
    landed in #191). The validator reads the catalogue rather than hardcoding a
    count, so a catalogue change moves this test and nothing else.
    """
    cat = Catalogue.load()
    fields = json.loads((ROOT / "registry" / "export_field_catalogue.json").read_text(encoding="utf-8"))["fields"]
    assert len(fields) == 58
    served = [f for f in fields if f["served_by"] is not None]
    assert len(served) == 33
    assert len(fields) - len(served) == 25
    assert {"extracted_value", "field", "evidence_ref", "added", "corrected", "deleted"} <= cat.shared_wire_names


def test_schema_refuses_undecided_transforms():
    """Contract section 11 item 4: upper/trim/fixed are undecided, so REFUSED."""
    for key in ("upper", "trim", "fixed"):
        found = validate_profile(profile(col("A", "notice.notice_id", **{key: True})))
        assert hits(found, "schema"), key
        assert hits(found, "schema")[0].where == "columns[0]"


def test_date_column_with_only_format_is_refused():
    """Contract section 6: a date column needs on_unresolvable AND landing."""
    found = validate_profile(profile(col("D", "notice.notice_id", format="iso8601")))
    s = hits(found, "schema")
    assert s and all(f.where == "columns[0]" for f in s)


def test_field_unknown():
    f = hits(validate_profile(profile(col("A", "notice.notice_id"), col("B", "no.such"))), "field-unknown")
    assert [x.where for x in f] == ["columns[1].source.field"]


def test_field_not_served():
    f = hits(validate_profile(profile(col("A", "notice.notice_id"), col("B", "header.doc_id"))), "field-not-served")
    assert [x.where for x in f] == ["columns[1].source.field"]


def test_field_not_extracted():
    cat = Catalogue.load()
    assert "change_type" in cat.not_extracted
    f = hits(validate_profile(profile(col("A", "notice.notice_id"), col("B", "change_type"))), "field-not-extracted")
    assert [x.where for x in f] == ["columns[1].source.field"]


def test_row_field_required():
    f = hits(validate_profile(profile(col("A", "notice.notice_id"), col("B", "part.affected_mpn"))), "row-field-required")
    assert [x.where for x in f] == ["columns[1].source"]


def test_row_field_refused():
    c = col("B", "notice.notice_id")
    c["source"]["row_field"] = "affected_mpn"
    f = hits(validate_profile(profile(col("A", "notice.notice_id"), c)), "row-field-refused")
    assert [x.where for x in f] == ["columns[1].source.row_field"]


def test_row_field_unrecognised_is_a_warning_and_both_forms_accepted():
    def with_rf(rf):
        c = col("B", "part.affected_mpn")
        c["source"]["row_field"] = rf
        return validate_profile(profile(c))

    bad = hits(with_rf("bogus"), "row-field-unrecognised")
    assert [(x.severity, x.where) for x in bad] == [("warning", "columns[0].source.row_field")]
    assert not hits(with_rf("affected_mpn"), "row-field-unrecognised")
    assert not hits(with_rf("parts[i].affected_mpn"), "row-field-unrecognised")


def test_landing_not_declared():
    c = col("D", "notice.notice_id", on_unresolvable="land", landing="nowhere")
    f = hits(validate_profile(profile(col("A", "notice.notice_id"), c)), "landing-not-declared")
    assert [x.where for x in f] == ["columns[1].landing"]


def test_duplicate_output():
    f = hits(validate_profile(profile(col("A", "notice.notice_id"), col("A", "notice.notice_id"))), "duplicate-output")
    assert [x.where for x in f] == ["columns[1].output"]


def test_mapping_unverified_is_a_warning():
    f = hits(validate_profile(profile(col("A", "notice.notice_date"))), "mapping-unverified")
    assert [(x.severity, x.where) for x in f] == [("warning", "columns[0].source.field")]


def test_granularity_row_field():
    c = col("B", "row.row_index")
    f = hits(validate_profile(profile(col("A", "notice.notice_id"), c, granularity="notice")), "granularity-row-field")
    assert [x.where for x in f] == ["columns[1].source.field"]


def test_all_findings_reported_and_malformed_input_does_not_raise():
    p = profile(col("A", "no.such"), "not-a-dict", {"output": 3, "source": "x"}, col("A", "header.doc_id"))
    found = validate_profile(p)
    assert hits(found, "field-unknown") and hits(found, "field-not-served") and hits(found, "duplicate-output")
    assert validate_profile(None) and validate_profile({"columns": "x"})
