"""Arms for doc_tools.batch.cli: one per rule of the link-3 spec, on synthetic extractions."""
import csv
import json
from pathlib import Path

import pytest
import yaml

from doc_tools.batch.cli import main, normalise_date

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "registry" / "batch_profiles" / "pcn-ltb-by-part.yaml"
HEADER = ["Notice", "Affected MPN", "Replacement MPN", "LTB Date", "date_ambiguous", "no_parts"]


def row(part, field, value, **kw):
    r = {"row_index": 0, "part_index": part, "mpn": f"AAA{part}", "field": f"parts[i].{field}",
         "extracted_value": value, "obtained_via": "direct", "match_confidence": 1.0,
         "needs_review": False, "review_reason": None, "source_snippet": value, "evidence_ref": None}
    return {**r, **kw}


def extraction(rows, notice_id="TESTNOTICE-1", part_count=None, **kw):
    """A hand-written Extraction carrying every required key (cortex-bff pin)."""
    n = len({r["part_index"] for r in rows}) if part_count is None else part_count
    doc = {"ingest_id": "i-1", "notice_id": notice_id, "content_kind": "pcn", "attempt": 1,
           "leaf": "pcn", "leaf_source": "x", "corrected_by": None,
           "notice": {"mfr": "Acme Semiconductor", "mfr_source": "header",
                      "mfr_parent": None, "notice_date": "2023-11-01"},
           "part_count": n, "rows": rows,
           "rows_without_evidence": 0, "review_ref": None, "relocated_to": None}
    return {**doc, **kw}


def run(tmp_path, capsys, docs, profile=SHIPPED, *flags):
    ex = []
    for i, d in enumerate(docs):
        p = tmp_path / f"ex{i}.json"
        p.write_text(json.dumps(d), encoding="utf-8")
        ex += ["--extraction", str(p)]
    out = tmp_path / "out.csv"
    code = main(["--profile", str(profile), *ex, "--out", str(out), *flags])
    return code, out, capsys.readouterr().err


def read(out):
    with open(out, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def test_shipped_profile_exact_rows(tmp_path, capsys):
    doc = extraction([
        row(0, "affected_mpn", "XQ100"), row(0, "replacement_mpn", "XQ100B"),
        row(0, "ltb_date", "2023-12-05"),
        row(1, "affected_mpn", "XQ200"),  # no replacement, no date: two rows absent, not three
    ])
    code, out, _ = run(tmp_path, capsys, [doc])
    assert code == 0
    assert read(out) == [HEADER,
                         ["TESTNOTICE-1", "XQ100", "XQ100B", "2023-12-05", "", ""],
                         ["TESTNOTICE-1", "XQ200", "", "", "", ""]]


def test_zero_parts_emits_one_no_parts_row(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, [extraction([])])
    assert code == 0
    assert read(out) == [HEADER, ["TESTNOTICE-1", "", "", "", "", "true"]]


def test_block_leaves_no_output_file(tmp_path, capsys):
    prof = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))
    prof["columns"][2]["source"]["absent_row"] = "block"
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(prof), encoding="utf-8")
    # The first notice would export fine; the second has no replacement row.
    docs = [extraction([row(0, "affected_mpn", "XQ1"), row(0, "replacement_mpn", "XQ1B")], "N-1"),
            extraction([row(0, "affected_mpn", "XQ2")], "N-2")]
    code, out, err = run(tmp_path, capsys, docs, p)
    assert code == 1
    assert not out.exists()
    assert not list(tmp_path.glob("out.csv*"))  # nor a temp file beside it
    assert "N-2" in err and "Replacement MPN" in err and "0" in err  # notice, column, part named


def test_ambiguous_date_lands_verbatim(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, [extraction([row(0, "affected_mpn", "XQ1"),
                                                      row(0, "ltb_date", "05/12/2023")])])
    assert code == 0
    r = read(out)[1]
    assert r[3] == "" and r[4] == "05/12/2023"
    assert out.read_bytes().count(b"05/12/2023") == 1


def test_refused_profile_exit_2_prints_every_finding(tmp_path, capsys):
    bad = {"name": "t", "granularity": "notice_part", "columns": [
        {"output": "A", "source": {"field": "no.such"}},
        {"output": "B", "source": {"field": "header.doc_id"}}]}
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    code, out, err = run(tmp_path, capsys, [extraction([])], p)
    assert code == 2 and not out.exists()
    assert "field-unknown" in err and "field-not-served" in err


def test_part_count_disagreement_warns_and_exports(tmp_path, capsys):
    doc = extraction([row(0, "affected_mpn", "XQ1")], part_count=3)
    code, out, err = run(tmp_path, capsys, [doc])
    assert code == 0 and len(read(out)) == 2
    assert "part_count=3" in err and "1 distinct" in err


def test_two_rows_same_row_field_is_row_ambiguous(tmp_path, capsys):
    doc = extraction([row(0, "affected_mpn", "XQ1"), row(0, "affected_mpn", "XQ2")])
    code, out, err = run(tmp_path, capsys, [doc])
    assert code == 1 and not out.exists()
    assert "row_ambiguous" in err and "TESTNOTICE-1" in err and "Affected MPN" in err


def test_corrected_by_refuses_the_whole_export(tmp_path, capsys):
    docs = [extraction([row(0, "affected_mpn", "XQ1")], "N-1"),
            extraction([row(0, "affected_mpn", "XQ2")], "N-2", corrected_by="steward-x")]
    code, out, err = run(tmp_path, capsys, docs)
    assert code == 1 and not out.exists()
    assert "export_corrections_not_applied" in err


@pytest.mark.parametrize("raw,iso", [
    ("2023-12-05", "2023-12-05"),
    ("2023-12-05T10:30:00Z", "2023-12-05"),
    ("5 Dec 2023", "2023-12-05"),
    ("December 5, 2023", "2023-12-05"),
    ("13/05/2023", "2023-05-13"),
    ("05/13/2023", "2023-05-13"),
    ("05/05/2023", "2023-05-05"),  # both <= 12 but EQUAL: nothing is chosen
    ("05/12/2023", None),   # both <= 12: the case section 6 is written about
    ("13/14/2023", None),   # both > 12
    ("31 Feb 2023", None),  # a named month does not make an impossible day valid
    (" 5 Dec 2023", None),  # no strip
    ("5 Foo 2023", None),
])
def test_date_table(raw, iso):
    assert normalise_date(raw) == iso


def test_date_table_through_the_cli(tmp_path, capsys):
    cases = {"2023-12-05": ("2023-12-05", ""), "5 Dec 2023": ("2023-12-05", ""),
             "13/05/2023": ("2023-05-13", ""), "05/12/2023": ("", "05/12/2023")}
    docs = [extraction([row(0, "affected_mpn", f"XQ{i}"), row(0, "ltb_date", raw)], f"N-{i}")
            for i, raw in enumerate(cases)]
    code, out, _ = run(tmp_path, capsys, docs)
    assert code == 0
    assert [(r[3], r[4]) for r in read(out)[1:]] == list(cases.values())


def test_inherited_ltb_is_reported_not_hidden(tmp_path, capsys):
    doc = extraction([row(0, "affected_mpn", "XQ1"),
                      row(0, "ltb_date", "2023-12-05", obtained_via="inherited_doc_level")])
    code, out, err = run(tmp_path, capsys, [doc])
    assert code == 0 and read(out)[1][3] == "2023-12-05"
    assert "1 selected row(s) are inherited_doc_level" in err and "LTB Date" in err


def test_dry_run_writes_nothing(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, [extraction([row(0, "affected_mpn", "XQ1")])], SHIPPED, "--dry-run")
    assert code == 0 and not out.exists()


def test_no_selector_disagreement_is_reported(tmp_path, capsys):
    """A row-scope field whose wire name is NOT shared refuses a row_field, so no
    selector is possible and the first row is taken. Where the part rows disagree
    that pick is positional, so it is reported -- the silence is the defect."""
    prof = tmp_path / "p.yaml"
    prof.write_text(yaml.safe_dump(
        {"name": "p", "granularity": "notice_part",
         "columns": [{"output": "Snippet", "source": {"field": "row.source_snippet"}}]}),
        encoding="utf-8")
    rows = [row(0, "affected_mpn", "XQ100", source_snippet="from the table"),
            row(0, "ltb_date", "2023-12-05", source_snippet="from the prose")]
    code, out, err = run(tmp_path, capsys, [extraction(rows)], prof)
    assert code == 0
    assert read(out)[1] == ["from the table"]
    assert "2 different" in err and "no selector is possible" in err


def test_no_selector_agreement_is_silent(tmp_path, capsys):
    """row.mpn is the part identity repeated on every row: the same pick, no warning."""
    prof = tmp_path / "p.yaml"
    prof.write_text(yaml.safe_dump(
        {"name": "p", "granularity": "notice_part",
         "columns": [{"output": "MPN", "source": {"field": "row.mpn"}}]}), encoding="utf-8")
    rows = [row(0, "affected_mpn", "XQ100"), row(0, "ltb_date", "2023-12-05")]
    code, out, err = run(tmp_path, capsys, [extraction(rows)], prof)
    assert code == 0 and read(out)[1] == ["AAA0"]
    assert "no selector is possible" not in err
