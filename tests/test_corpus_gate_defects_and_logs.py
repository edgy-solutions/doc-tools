"""A red corpus-gate run has to be diagnosable AFTER the pod is gone.

Both halves of this file exist because of one event, 2026-10-01. Three fires of
the 9-notice corpus ran against one pinned image on verified-identical source
bytes. Fires 1 and 2 scored 898/898. Fire 3 scored 890/898 -- the first time
PARTS nondeterminism had been observed in this corpus at all. Neither of the two
questions that matter could be answered:

  WHICH NOTICE lost the 8 parts? The gate kept each fire's `totals` and threw
  away the `per_notice` block that `pcn_score.py` had already computed, naming
  the exact MPNs. So the report said 8 and could not say where.

  WHAT DID THE FIRE PRINT? `fire3.log` was written inside the pod. By the time
  anyone looked, the Job had reached `Failed`, and a completed pod refuses
  `kubectl exec` ("cannot exec into a container in a completed pod") -- the file
  was unreachable while the pod object that held it still existed. `kubectl
  logs` worked the entire time.

So: carry the per-notice lists into the report (which is committed to git by the
publisher and outlives everything), and echo the logs a reader will need into
the gate's own stdout (which `kubectl logs` keeps serving after `exec` closes).

WHY THESE ASSERTIONS AND NOT A SNAPSHOT OF THE MARKDOWN. The invariants are
about what survives, not about layout: a defect must be attributable to a
notice, an unmeasured fire must not read as a clean one, and the retrieval
command the report prints must match the delimiter the dump actually emits. A
golden-file test would fail on wording and pass on all three of those breaking.
"""

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    # pcn_corpus_gate imports its sibling pcn_header_agreement by plain module
    # name, so scripts/ has to be importable.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("pcn_corpus_gate")


# --------------------------------------------------------------------------
# Fixtures shaped like the real instruments' output. The per-notice record
# shape is pcn_score.py's `score_notice` return value (count/emitted/distinct/
# exact/spurious/missing/malformed/clean), and the absent/failed shape is the
# `error` variant score_run builds for a notice that never ran.

def _clean_notice(count):
    return {"count": count, "emitted": count, "distinct": count, "exact": count,
            "spurious": [], "missing": [], "malformed": [], "clean": True}


def _score_with_a_missing_notice():
    """Fire 3 of 2026-10-01, in miniature: one notice short by 8 parts."""
    lost = ["MPN-%03d" % i for i in range(8)]
    per = {
        "clean_notice.pdf": _clean_notice(100),
        "the_notice_that_lost_them.pdf": {
            "count": 108, "emitted": 100, "distinct": 100, "exact": 100,
            "spurious": [], "missing": lost, "malformed": [], "clean": False,
        },
    }
    totals = {"gt": 208, "exact": 200, "spurious": 0, "missing": 8,
              "malformed": 0, "emitted": 200}
    return {"per_notice": per, "totals": totals}, lost


# --------------------------------------------------------------------------
# Item 1: the per-notice lists.

def test_a_missing_part_is_attributable_to_a_notice():
    """The 2026-10-01 regression: 8 parts gone, no way to say from where."""
    score, lost = _score_with_a_missing_notice()
    defects = gate.notice_defects(score)
    assert "the_notice_that_lost_them.pdf" in defects, (
        "the notice that lost parts is not named in the carried defects, which "
        "is exactly the hole that made fire 3's 890/898 unattributable"
    )
    assert defects["the_notice_that_lost_them.pdf"]["missing"] == lost, (
        "the missing MPNs are not carried whole -- a count would have been no "
        "better than the totals the report already had"
    )


def test_a_clean_notice_is_not_carried():
    score, _ = _score_with_a_missing_notice()
    defects = gate.notice_defects(score)
    assert "clean_notice.pdf" not in defects, (
        "clean notices are being carried, which buries the defective one in a "
        "report that is read by a human under time pressure"
    )


def test_no_per_notice_data_is_None_and_an_all_clean_set_is_empty():
    """"Nothing wrong" and "nothing measured" must not render the same.

    This is the distinction the old report could not express: a fire whose score
    JSON could not be read showed up as a row with no detail, indistinguishable
    at a glance from a fire that had nothing to report.
    """
    assert gate.notice_defects(None) is None
    assert gate.notice_defects({"totals": {"missing": 8}}) is None, (
        "a score JSON with no per_notice block must read as UNMEASURED, not as "
        "a clean set"
    )
    assert gate.notice_defects({"per_notice": {"a.pdf": _clean_notice(5)}}) == {}, (
        "an all-clean fire must be {} -- falsy, but distinguishable from None"
    )


def test_an_absent_notice_is_carried_with_its_error():
    """score_run's error variant: every GT part missing, and a reason."""
    score = {"per_notice": {"never_ran.pdf": {
        "count": 3, "error": "notice absent from run", "exact": 0,
        "spurious": [], "missing": ["A", "B", "C"], "malformed": [],
        "emitted": 0, "distinct": 0, "clean": False}},
        "totals": {"gt": 3, "exact": 0, "spurious": 0, "missing": 3,
                   "malformed": 0, "emitted": 0}}
    rec = gate.notice_defects(score)["never_ran.pdf"]
    assert rec["error"] == "notice absent from run"
    assert rec["missing"] == ["A", "B", "C"]


def test_a_not_clean_notice_with_empty_lists_is_still_carried():
    """The counts-do-not-add-up case.

    `score_notice` sets `clean` False when `exact != count` even with all three
    defect lists empty -- a notice that emitted a duplicate, say. Selecting on
    the lists alone would drop it, and the report would call a not-clean notice
    clean.
    """
    score = {"per_notice": {"odd.pdf": {
        "count": 10, "emitted": 11, "distinct": 9, "exact": 9,
        "spurious": [], "missing": [], "malformed": [], "clean": False}}}
    assert "odd.pdf" in gate.notice_defects(score)


def test_the_report_names_the_notice_and_the_parts():
    """End-to-end through the renderer, because the report is what survives."""
    score, lost = _score_with_a_missing_notice()
    report = {
        "fires": [{"n": 3, "exit": 1, "elapsed_s": 1320, "log": "fire3.log",
                   "totals": score["totals"], "defects": gate.notice_defects(score)}],
    }
    block = gate._render_defects_block(report)
    assert "the_notice_that_lost_them.pdf" in block
    for mpn in lost:
        assert mpn in block, f"{mpn} is missing from the rendered report"


def test_the_report_says_so_when_a_fire_was_not_measured():
    report = {"fires": [{"n": 2, "exit": 0, "elapsed_s": 1300, "log": "fire2.log",
                         "totals": None, "defects": None}]}
    block = gate._render_defects_block(report)
    assert "no per-notice data" in block, (
        "an unmeasured fire renders as if it had nothing to report"
    )


def test_a_disagreement_between_the_lists_and_the_totals_is_shouted():
    """The lists and the totals come from one scorer over one dataset.

    `score_run` computes `totals["missing"]` as the sum of the per-notice
    `missing` lengths, so they cannot legitimately differ. If they do, the
    carrying is broken (truncation, a stale totals block, two scorer versions)
    and the report must not present both numbers as if either were reliable.
    """
    score, _ = _score_with_a_missing_notice()
    score["totals"]["missing"] = 99
    report = {"fires": [{"n": 3, "exit": 1, "elapsed_s": 1320, "log": "fire3.log",
                         "totals": score["totals"],
                         "defects": gate.notice_defects(score)}]}
    block = gate._render_defects_block(report)
    assert "DISAGREES WITH ITSELF" in block
    assert "99" in block and "8" in block


# --------------------------------------------------------------------------
# Item 2: the fire logs.

def _fires(tmp_path, names):
    out = []
    for n, text in names:
        p = tmp_path / f"fire{n}.log"
        p.write_text(text, encoding="utf-8")
        out.append({"n": n, "log": p.name, "log_path": str(p)})
    return out


def test_a_failing_verdict_preserves_EVERY_fire_log_even_the_clean_ones(tmp_path):
    """The 2026-10-01 shape exactly, and the trap a per-fire selector falls into.

    All three fires exited 0. The Job failed because the GATE's verdict was
    `fail`, and fire 3's log is the one that was lost. Selecting on `exit != 0`
    -- the obvious reading of "preserve logs on a failed Job" -- would have
    preserved nothing at all in the one case this feature exists for.

    Clean fires are preserved too, deliberately: a header-caused red can leave
    every fire clean on parts, and the corpus JSON carries no header fields, so
    the compared header values exist in the logs and nowhere else.
    """
    fires = _fires(tmp_path, [(1, "ok"), (2, "ok"), (3, "lost 8")])
    report = {"verdict": "fail", "fires": [
        {"n": 1, "exit": 0, "totals": {"missing": 0}, "defects": {}},
        {"n": 2, "exit": 0, "totals": {"missing": 0}, "defects": {}},
        {"n": 3, "exit": 0, "totals": {"missing": 8}, "defects": {"x.pdf": {}}},
    ]}
    selected = [e["n"] for e, _ in gate.fires_needing_preservation(report, fires)]
    assert selected == [1, 2, 3], (
        "a failing Job did not preserve every fire log; on 2026-10-01 every "
        "fire exited 0 and the log that was wanted was fire 3's"
    )


def test_a_fire_with_no_per_notice_data_is_preserved_even_on_a_PASS(tmp_path):
    """The case the report can say LEAST about is the one that most needs its log.

    A clean exit whose own score JSON could not be read leaves the report with
    nothing but a row of dashes. It should not be able to pass quietly.
    """
    fires = _fires(tmp_path, [(2, "something happened")])
    report = {"verdict": "pass",
              "fires": [{"n": 2, "exit": 0, "totals": None, "defects": None}]}
    selected = [e["n"] for e, _ in gate.fires_needing_preservation(report, fires)]
    assert selected == [2]


def test_a_clean_pass_echoes_nothing(tmp_path):
    """Echoing a log costs room in the kubelet's rotation window.

    Three clean fires would push ~750 KiB through `kubectl logs` for nothing,
    and the thing evicted at the far end is the report.
    """
    fires = _fires(tmp_path, [(1, "ok")])
    report = {"verdict": "pass",
              "fires": [{"n": 1, "exit": 0, "totals": {"missing": 0}, "defects": {}}]}
    assert gate.fires_needing_preservation(report, fires) == []


def test_the_log_tail_is_the_TAIL(tmp_path):
    """`pcn_corpus_run.py` prints its per-notice breakdown LAST.

    A head-truncated log would preserve the banner and drop the diagnosis,
    which is the opposite of the point.
    """
    p = tmp_path / "fire3.log"
    p.write_text("A" * 1000 + "THE-DIAGNOSIS", encoding="utf-8")
    text, total, omitted = gate.fire_log_tail(str(p), 100)
    assert text.endswith("THE-DIAGNOSIS")
    assert total == 1013 and omitted == 913
    assert len(text) == 100


def test_a_whole_small_log_is_kept_with_nothing_omitted(tmp_path):
    p = tmp_path / "fire1.log"
    p.write_text("short", encoding="utf-8")
    text, total, omitted = gate.fire_log_tail(str(p), 1024)
    assert (text, total, omitted) == ("short", 5, 0)


def test_an_unreadable_log_does_not_take_the_report_down(tmp_path):
    """By the time this runs the fires are over and the report is assembled.

    Raising here would destroy ~70 minutes of GPU-bound measurement over a
    missing file, when the missing file is itself just a finding to report.
    """
    text, total, omitted = gate.fire_log_tail(str(tmp_path / "nope.log"), 1024)
    assert "could not stat" in text
    assert total is None and omitted is None


def test_the_dump_delimiters_are_what_the_report_tells_a_reader_to_grep(tmp_path):
    """The retrieval command in the report and the emitted delimiter are one fact.

    They are written in two different functions, so they can drift -- and a
    drifted `sed` range silently prints nothing, which reads as "the log was
    not preserved" rather than as a documentation bug.
    """
    fires = _fires(tmp_path, [(3, "the fire 3 output")])
    report = {"verdict": "fail",
              "fires": [{"n": 3, "exit": 0, "totals": {"missing": 8},
                         "defects": {"x.pdf": {}}, "log": "fire3.log"}]}
    gate.annotate_log_preservation(report, fires, 1024)
    dump = "\n".join(gate.preserved_log_dumps(report, fires, 1024))
    assert "the fire 3 output" in dump

    instructions = gate._render_log_preservation_block(report)
    # The command in the report is `sed -n '/BEGIN fire 3 log/,/END fire 3 log/p'`;
    # both ends of that range have to occur in the dump for it to print anything.
    assert "BEGIN fire 3 log" in dump and "BEGIN fire 3 log" in instructions
    assert "END fire 3 log" in dump and "END fire 3 log" in instructions


def test_the_report_records_which_logs_were_echoed(tmp_path):
    """Without this the report cannot tell a reader WHERE the log they want is."""
    fires = _fires(tmp_path, [(1, "clean"), (3, "boom")])
    report = {"verdict": "pass", "fires": [
        {"n": 1, "exit": 0, "totals": {"missing": 0}, "defects": {}, "log": "fire1.log"},
        {"n": 3, "exit": 1, "totals": None, "defects": None, "log": "fire3.log"},
    ]}
    gate.annotate_log_preservation(report, fires, 1024)
    by_n = {e["n"]: e for e in report["fires"]}
    assert by_n[1]["log_echoed"] is False and by_n[1]["log_bytes"] == 5
    assert by_n[3]["log_echoed"] is True and by_n[3]["log_bytes"] == 4
    assert by_n[3]["log_echo_cap_bytes"] == 1024
    block = gate._render_log_preservation_block(report)
    assert "fire3.log" in block and "fire1.log" in block


def test_the_echo_cap_is_overridable_and_survives_a_garbage_value(monkeypatch):
    """An operator chasing a long log can raise it; a typo must not disable it."""
    monkeypatch.delenv("PCN_GATE_LOG_TAIL_BYTES", raising=False)
    assert gate.log_tail_bytes() == gate.LOG_TAIL_BYTES_DEFAULT
    monkeypatch.setenv("PCN_GATE_LOG_TAIL_BYTES", "4096")
    assert gate.log_tail_bytes() == 4096
    for bad in ("", "lots", "0", "-1"):
        monkeypatch.setenv("PCN_GATE_LOG_TAIL_BYTES", bad)
        assert gate.log_tail_bytes() == gate.LOG_TAIL_BYTES_DEFAULT, (
            f"PCN_GATE_LOG_TAIL_BYTES={bad!r} disabled log preservation instead "
            f"of falling back"
        )
