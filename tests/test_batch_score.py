"""Arms for doc_tools.batch.score: one per rule of the scorer spec, on synthetic rows."""
import csv
import json
from pathlib import Path

import yaml

from doc_tools.batch.score import DETAIL_BANNER, main

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "registry" / "batch_profiles" / "pcn-ltb-by-part.yaml"
HEADER = ["Notice", "Affected MPN", "Replacement MPN", "LTB Date", "date_ambiguous", "no_parts"]
KEYS = ["--key", "Notice", "--key", "Affected MPN"]
# Everything a scorecard string may be besides a profile column or the profile's own name.
VOCAB = {"scorecard_version", "profile", "granularity", "keys", "rows", "columns", "totals",
         "exported", "truth", "joined", "truth_only", "exported_only", "asserted", "match",
         "mismatch", "expected_empty_got_value", "expected_value_got_empty",
         "not_exported", "rate", "notice_part"}


def rec(notice, mpn, repl="", ltb="", amb="", nop=""):
    return dict(zip(HEADER, [notice, mpn, repl, ltb, amb, nop]))


def put(path, rows, header=HEADER):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, header, restval="")
        w.writeheader()
        w.writerows(rows)
    return path


def run(tmp_path, capsys, rows, truth, *flags, truth_header=HEADER, keys=KEYS):
    r = put(tmp_path / "rows.csv", rows)
    t = put(tmp_path / "truth.csv", truth, truth_header)
    card = tmp_path / "card.json"
    code = main(["--rows", str(r), "--truth", str(t), "--profile", str(SHIPPED), *keys,
                 "--scorecard", str(card), *flags])
    return code, card, capsys.readouterr().err


def load(card):
    return json.loads(card.read_text(encoding="utf-8"))


ROWS = [rec("N-1", "ZZ1", "ZZ1B", "2024-01-05"), rec("N-1", "ZZ2", "", "")]


def test_clean_set_is_100_percent(tmp_path, capsys):
    code, card, _ = run(tmp_path, capsys, ROWS, ROWS)
    c = load(card)
    assert code == 0
    assert c["rows"] == {"exported": 2, "truth": 2, "joined": 2, "truth_only": 0, "exported_only": 0}
    assert c["columns"]["LTB Date"]["rate"] == 1.0
    assert c["totals"]["rate"] == 1.0 and c["totals"]["asserted"] == c["totals"]["match"] > 0


def test_mismatch_is_counted_and_not_normalised(tmp_path, capsys):
    truth = [rec("N-1", "ZZ1", "zz1b", "2024-01-05 ")]  # case and trailing space both differ
    code, card, _ = run(tmp_path, capsys, ROWS, truth)
    c = load(card)["columns"]
    assert code == 0
    assert c["Replacement MPN"]["mismatch"] == 1 and c["LTB Date"]["mismatch"] == 1
    assert c["Replacement MPN"]["rate"] == 0.0


def test_empty_token_satisfied_and_violated(tmp_path, capsys):
    truth = [rec("N-1", "ZZ1", "<empty>", "<empty>"), rec("N-1", "ZZ2", "<empty>", "2024-01-05")]
    _, card, _ = run(tmp_path, capsys, ROWS, truth)
    c = load(card)["columns"]
    assert c["Replacement MPN"]["expected_empty_got_value"] == 1  # ZZ1 has a value
    assert c["Replacement MPN"]["match"] == 1                     # ZZ2 is empty
    assert c["LTB Date"]["expected_empty_got_value"] == 1
    assert c["LTB Date"]["expected_value_got_empty"] == 1
    assert c["LTB Date"]["asserted"] == 2


def test_blank_truth_cell_scores_nothing(tmp_path, capsys):
    truth = [rec("N-1", "ZZ1"), rec("N-1", "ZZ2")]
    _, card, _ = run(tmp_path, capsys, ROWS, truth)
    c = load(card)
    assert all(v["asserted"] == 0 and v["rate"] is None for v in c["columns"].values())
    assert c["totals"]["asserted"] == 0 and c["totals"]["rate"] is None


def test_truth_only_and_exported_only_are_counted(tmp_path, capsys):
    truth = [rec("N-1", "ZZ1", "ZZ1B"), rec("N-9", "ZZ9", "ZZ9B")]  # ZZ2 not in truth; N-9 not exported
    code, card, err = run(tmp_path, capsys, ROWS, truth)
    c = load(card)
    assert code == 0
    assert c["rows"]["truth_only"] == 1 and c["rows"]["exported_only"] == 1 and c["rows"]["joined"] == 1
    # the missing row's assertion is in the denominator: 1 match of 2, not 1 of 1
    assert c["totals"]["asserted"] == 2 and c["totals"]["rate"] == 0.5
    # and it is in the COLUMN's denominator too, or the column reads 1 of 1 = 100%
    repl = c["columns"]["Replacement MPN"]
    assert repl["asserted"] == 2 and repl["match"] == 1 and repl["not_exported"] == 1
    assert repl["rate"] == 0.5
    assert "1 truth row(s) not exported" in err


def test_the_buckets_sum_to_asserted_at_both_levels(tmp_path, capsys):
    """One rate definition: the five buckets sum to `asserted`, per column and in totals."""
    buckets = ("match", "mismatch", "expected_empty_got_value",
               "expected_value_got_empty", "not_exported")
    truth = [rec("N-1", "ZZ1", "ZZ1X", "<empty>"),      # mismatch + expected_empty_got_value
             rec("N-1", "ZZ2", "ZZ2B", ""),             # expected_value_got_empty
             rec("N-7", "ZZ7", "ZZ7B", "2024-02-02")]   # not exported at all
    _, card, _ = run(tmp_path, capsys, ROWS, truth)
    c = load(card)
    for name, a in c["columns"].items():
        assert sum(a[b] for b in buckets) == a["asserted"], name
        assert a["rate"] == (a["match"] / a["asserted"] if a["asserted"] else None), name
    t = c["totals"]
    assert sum(t[b] for b in buckets) == t["asserted"]
    for b in ("asserted", *buckets):
        assert t[b] == sum(a[b] for a in c["columns"].values()), b


def test_duplicated_key_fails_with_the_right_code(tmp_path, capsys):
    code, card, err = run(tmp_path, capsys, ROWS, ROWS + [ROWS[0]])
    assert code == 1 and "truth_key_duplicated" in err and not card.exists()
    code, card, err = run(tmp_path, capsys, ROWS + [ROWS[0]], ROWS)
    assert code == 1 and "rows_key_duplicated" in err and not card.exists()
    assert "ZZ1" not in err  # the diagnostic names lines, never values


def test_undeclared_truth_column_fails(tmp_path, capsys):
    truth = [{**rec("N-1", "ZZ1"), "Colour": "red"}]
    code, card, err = run(tmp_path, capsys, ROWS, truth, truth_header=HEADER + ["Colour"])
    assert code == 1 and "truth_column_undeclared" in err and not card.exists()


def test_undeclared_key_fails(tmp_path, capsys):
    code, card, err = run(tmp_path, capsys, ROWS, ROWS, keys=["--key", "Nope"])
    assert code == 1 and "key_undeclared" in err and not card.exists()


def test_fail_under_above_and_below(tmp_path, capsys):
    truth = [rec("N-1", "ZZ1", "ZZ1B", "2024-01-06")]  # 1 of 2 asserted cells match
    assert run(tmp_path, capsys, ROWS, truth, "--fail-under", "0.4")[0] == 0
    assert run(tmp_path, capsys, ROWS, truth, "--fail-under", "0.9")[0] == 2
    assert load(tmp_path / "card.json")["totals"]["rate"] == 0.5  # still written on exit 2
    assert run(tmp_path, capsys, ROWS, truth)[0] == 0  # opt-in: a bad score alone exits 0


def test_detail_has_values_and_the_banner(tmp_path, capsys):
    truth = [rec("N-1", "ZZ1", "ZZ1X")]
    detail = tmp_path / "detail.csv"
    code, _, _ = run(tmp_path, capsys, ROWS, truth, "--detail", str(detail))
    lines = detail.read_text(encoding="utf-8").splitlines()
    assert code == 0 and lines[0] == DETAIL_BANNER
    assert "ZZ1X" in lines[2] and "ZZ1B" in lines[2] and "mismatch" in lines[2]


def test_scorecard_holds_no_value(tmp_path, capsys):
    """Every string in the scorecard is a profile column, the profile name, or closed vocabulary."""
    profile = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))
    allowed = VOCAB | {c["output"] for c in profile["columns"]} | {profile["name"]}
    truth = [rec("N-1", "ZZ1", "WRONG", "<empty>"), rec("N-8", "SECRETMPN", "X")]
    _, card, _ = run(tmp_path, capsys, ROWS, truth)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert k in allowed, k
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            assert o in allowed, o
        else:
            assert o is None or isinstance(o, (int, float))

    walk(load(card))
    text = card.read_text(encoding="utf-8")
    assert all(v not in text for v in ("ZZ1", "SECRETMPN", "WRONG", "N-8", "2024"))
