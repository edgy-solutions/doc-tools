#!/usr/bin/env python
"""pcn_corpus_gate.py — the PCN/PDN corpus harness as a release gate.

Wraps the two existing instruments, `pcn_corpus_run.py` (the parts extraction
and scoring driver) and `pcn_header_agreement.py` (the header stability
check), and turns three sequential fires of the 9-notice corpus into one
pass/fail verdict plus a dated, human-readable report.

Two modes:

  --run (default)     Run three fires now (~70 minutes of sequential,
                       GPU/vision-bound work; see the sequencing note below),
                       then score them.
  --from-logs <dir>    Score a fire set that already ran. No fires, no GPU
                       time — reads the same three artifacts per fire
                       (log, corpus_f{N}.json, score_f{N}.json) that --run
                       would have produced, from <dir>.

Both modes feed the identical scoring path (see `score_fires` below), so a
verdict never depends on which mode produced its inputs.

Pure stdlib + the two instruments this wraps. `doc_tools.utils.notice_identity`
is imported because the spec for this gate requires it directly (identity-key
comparison, see (c) below) — it is itself pure stdlib, no boto3/dagster calls
at import time. Nothing else at module scope reaches into doc_tools.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

# `pcn_header_agreement.py` lives beside this script under scripts/, not as an
# installed package — this mirrors how pcn_header_agreement.py itself imports
# its own sibling, pcn_corpus_run.py, inside build_index_by_file().
sys.path.insert(0, "scripts")
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import pcn_header_agreement as hdr_agreement  # noqa: E402
# For `load_corpus` only — the corpus enumeration the report is measured against.
# Absolute path above, because the relative "scripts" entry resolves against the
# CWD and this module is also imported by tests from elsewhere.
import pcn_score  # noqa: E402

from doc_tools.utils import notice_identity  # noqa: E402
from doc_tools.utils.ingest_rates import (  # noqa: E402
    aggregate_rates_across_fires, render_rates, render_rates_across_fires,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE_COUNT = 3

# --------------------------------------------------------------------------
# Per-notice verdict / field lines, as printed by pcn_header_agreement.compare()
# in PLAIN mode (no --written): this gate never runs --written (see (b) below).
# That plain run measures the RAW model output and is ADVISORY since the
# 2026-10-26 ruling; what blocks is `compare_written_headers` over the recorded
# written values.
#   "<notice>                                   agree"
#   "<notice>                                   DISAGREE"
#   "<notice>                                   BLANK"   (blank in one fire,
#                                               populated in another; the
#                                               field line names the blank fires)
#   "<notice>                                   NOT MEASURED"
#   "<notice>                                   ABSENT"
#   "      <field>                 'v1' | 'v2' | 'v3'[   <- not in evidence...]"
# The spec's own regex is used verbatim for the notice/DISAGREE parse that
# feeds the report and the declaration rule. ABSENT and NOT MEASURED are
# parsed too (separately, below) purely so this gate can tell "the fires
# disagree" (a value conflict) apart from "the instrument could not measure
# this" (a gap) — compare()'s own docstring draws exactly that line, and
# conflating them would let a damaged log be reported as extractor
# instability. Both still block; there is just no declaration exemption for
# the latter (see (d)).
NOTICE_VERDICT_RE = re.compile(r"^(?P<notice>\S.*?)\s{2,}(?P<verdict>agree|DISAGREE|BLANK)\s*$")
NOTICE_ABSENT_RE = re.compile(r"^(?P<notice>\S.*?)\s{2,}ABSENT\s*$")
NOTICE_NOT_MEASURED_RE = re.compile(r"^(?P<notice>\S.*?)\s{2,}NOT MEASURED\s*$")
FIELD_LINE_RE = re.compile(r"^ {6}(?P<field>\S+) +(?P<vals>.+)$")

# A literal backslash-pipe, for escaping a value into a markdown table cell.
# Spelled as a concatenation because the raw two-character sequence is an invalid
# escape in a string literal: it works today but warns on every run of a gate
# whose log people read.
BAR_ESCAPE = "\\" + "|"


def _utcnow_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_json_soft(path):
    """Like _load_json, but for --run mode: a fire that crashed before writing
    its output (e.g. check_ground_truth() or the S3 client raising before the
    first `json.dump`) legitimately leaves no corpus_f{N}.json / score_f{N}.json
    behind. That is a real, reportable failure, not a reason for this gate to
    crash uninformatively instead of reporting red. Returns (data, error)."""
    try:
        return _load_json(path), None
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return None, f"{path}: {type(e).__name__}: {e}"


# --------------------------------------------------------------------------
# Mode A — run three fires.

def run_fires(base_dir):
    os.makedirs(base_dir, exist_ok=True)
    fires = []
    for n in range(1, FIRE_COUNT + 1):
        corpus_out = os.path.join(base_dir, f"corpus_f{n}.json")
        score_out = os.path.join(base_dir, f"score_f{n}.json")
        seal_out = os.path.join(base_dir, f"seal_f{n}.json")
        log_path = os.path.join(base_dir, f"fire{n}.log")

        # DISTINCT PATHS PER FIRE ARE LOAD-BEARING. Two fire drivers once shared
        # one set of output paths (PCN_OUT/PCN_SCORE_OUT/PCN_SEAL_OUT all pointed
        # at the same file across what were meant to be three fires); six fires
        # ran and were mistaken for three, and the resulting logs could not be
        # paired back to their JSON (see two-fire-scripts-clobbered-the-same-logs
        # in project memory). Every path here is suffixed with the fire number
        # for exactly this reason. Never let two fires share a path.
        env = dict(os.environ)
        env["PCN_OUT"] = corpus_out
        env["PCN_SCORE_OUT"] = score_out
        env["PCN_SEAL_OUT"] = seal_out

        started_at = _utcnow_iso()
        t0 = time.time()
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.run(
                [sys.executable, "scripts/pcn_corpus_run.py"],
                cwd=REPO_ROOT, env=env,
                stdout=logf, stderr=subprocess.STDOUT,
            )
        elapsed_s = round(time.time() - t0, 1)
        ended_at = _utcnow_iso()

        fires.append({
            "n": n, "exit": proc.returncode,
            "started_at": started_at, "ended_at": ended_at, "elapsed_s": elapsed_s,
            "log": os.path.basename(log_path), "log_path": log_path,
            "corpus_path": corpus_out, "score_path": score_out, "seal_path": seal_out,
        })
        # Fires run SEQUENTIALLY, never in parallel: the vision endpoint serves
        # one model at a time, and concurrent fires contend (observed 32-37 min
        # runtimes under contention vs ~22 min clean). This loop is the only
        # thing that decides that — do not thread or subprocess.Popen() these.
    return fires


# --------------------------------------------------------------------------
# Mode B — score an already-completed fire set.

def collect_from_logs(base_dir, log_prefix, corpus_prefix, score_prefix,
                      seal_prefix=None):
    fires = []
    # Preflight: validate every required path up front and fail on the first
    # missing one, naming it exactly. This is a caller-error case (wrong
    # directory, wrong prefixes, an incomplete fire set) and is checked before
    # any scoring starts, not discovered partway through — "do not substitute".
    required = []
    for n in range(1, FIRE_COUNT + 1):
        log_path = os.path.join(base_dir, f"{log_prefix}{n}.log")
        corpus_path = os.path.join(base_dir, f"{corpus_prefix}{n}.json")
        score_path = os.path.join(base_dir, f"{score_prefix}{n}.json")
        seal_path = (os.path.join(base_dir, f"{seal_prefix}{n}.json")
                     if seal_prefix else None)
        required.append((n, log_path, corpus_path, score_path, seal_path))
    for n, log_path, corpus_path, score_path, seal_path in required:
        for p in (log_path, corpus_path, score_path):
            if not os.path.isfile(p):
                raise SystemExit(f"--from-logs: required file not found: {p}")
        # A seal prefix that was ASKED FOR and is missing is a caller error, not
        # a silent downgrade to the seal-less reconstruction: the whole point of
        # passing --seal-prefix is to close that gap, so failing to find the file
        # must be loud.
        if seal_path is not None and not os.path.isfile(seal_path):
            raise SystemExit(f"--from-logs: --seal-prefix given but file not found: {seal_path}")

    for n, log_path, corpus_path, score_path, seal_path in required:
        corpus = _load_json(corpus_path)
        score = _load_json(score_path)
        totals = score.get("totals")
        sealed = _load_json(seal_path) if seal_path else None
        exit_code = _reconstruct_exit(corpus, totals, sealed)
        fires.append({
            "n": n, "exit": exit_code,
            "started_at": None, "ended_at": None,
            # No subprocess ran, so there is no wall-clock to record. Best-effort
            # proxy: the sum of each notice's own elapsed_s from corpus_f{N}.json
            # (notices run sequentially within a fire), not a real wall time.
            "elapsed_s": round(sum(
                r.get("elapsed_s", 0) for r in corpus.values() if r.get("ok")
            ), 1),
            "log": os.path.basename(log_path), "log_path": log_path,
            "corpus_path": corpus_path, "score_path": score_path,
            "seal_path": seal_path,
            # Whether the crop-seal term of the exit criterion was actually
            # evaluated, rather than assumed. Surfaced per fire in the report so
            # a reader can tell a reconstructed exit code that checked the seal
            # from one that could not.
            "seal_checked": sealed is not None,
        })
    return fires


def _reconstruct_exit(results, totals, sealed=None):
    """Recompute pcn_corpus_run.py's own exit-code criterion for --from-logs
    mode, where no subprocess ran and there is no real exit code to read.

    Mirrors pcn_corpus_run.py:main()'s return statement, INCLUDING the crop-seal
    term when a seal JSON is supplied via --seal-prefix. The seal file is the
    same artifact the live run wrote to PCN_SEAL_OUT, so reading it reproduces
    the real criterion rather than approximating it.

    Without a seal JSON the seal term is skipped and this is a WEAKER criterion
    than Mode A's real exit code: a from-logs score can then read fires_ok=True
    on a fire set whose live run actually exited 1 on the crop-seal term alone.
    That is why `seal_checked` is reported per fire — an unchecked seal is
    recorded as unproven, never as passed. Pass --seal-prefix whenever the seal
    files exist.
    """
    if totals is None:
        return 1
    if not all(r.get("ok") for r in results.values()):
        return 1
    # Same shape as pcn_corpus_run.py's own seal term: no seal JSON means the
    # term is not evaluated (seal_ok stays True and seal_checked records that),
    # a seal JSON means both its totals must be clean.
    seal_ok = sealed is None or (
        sealed.get("totals", {}).get("repaired_cut_tables") == 0
        and sealed.get("totals", {}).get("errors") == 0
    )
    return 0 if (
        totals["exact"] == totals["gt"]
        and not totals["spurious"]
        and not totals["missing"]
        and not totals["malformed"]
        and seal_ok
    ) else 1


# --------------------------------------------------------------------------
# (b) Header agreement — subprocess over the three logs, plain mode.

def run_header_agreement(base_dir, log_paths):
    # PLAIN MODE ONLY, never --written, and since the 2026-10-26 ruling this run is
    # ADVISORY: its exit code no longer contributes to the verdict (see score_fires).
    # What blocks is `compare_written_headers`, which compares the `written_header`
    # each fire recorded in its own corpus JSON. The ruling was "the blocking arm
    # measures the WRITTEN value", and the way to get it is NOT `--written`: the
    # --written replay cannot build the vision witness the product consults and
    # declines for the degraded notice (WITNESS_DECLINED), so it would report TYC's
    # written fields NOT MEASURED, which fails the gate -- a --written comparison would
    # measure the pre-witness trust logic, not what the product does, and would newly
    # block TYC on an instrument gap. The recorded values need no replay, no S3 and no
    # log parsing. The plain run is kept because the RAW disagreement is still worth
    # seeing: it is the report's `unstable_raw` block, an unsteady reader kept visible
    # without blocking a pin.
    cmd = [sys.executable, "scripts/pcn_header_agreement.py"] + list(log_paths)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    stdout = proc.stdout or ""
    log_path = os.path.join(base_dir, "header_agreement.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(stdout)
        if proc.stderr:
            f.write("\n--- stderr ---\n")
            f.write(proc.stderr)
    return proc.returncode, stdout


def parse_header_agreement(stdout_text):
    """Parse pcn_header_agreement.py's stdout into a {notice: {verdict, fields}}
    dict for the report, plus the ABSENT/NOT MEASURED notice lists used to
    detect an instrument gap (see (d): there is no declaration exemption for
    those, only for a DISAGREE). The exit code, not this parse, is the truth
    for whether the check passed — this is for readability only."""
    lines = stdout_text.splitlines()
    notices = {}
    current = None
    for line in lines:
        m = NOTICE_VERDICT_RE.match(line)
        if m:
            current = m.group("notice")
            notices[current] = {"verdict": m.group("verdict"), "fields": {}}
            continue
        if current is not None:
            fm = FIELD_LINE_RE.match(line)
            if fm:
                notices[current]["fields"][fm.group("field")] = fm.group("vals").strip()
                continue
        # A non-matching, non-indented line ends the current notice's field block.
        if line and not line.startswith(" "):
            current = None

    absent_notices = sorted({m.group("notice") for m in
                              (NOTICE_ABSENT_RE.match(l) for l in lines) if m})
    not_measured_notices = sorted({m.group("notice") for m in
                                    (NOTICE_NOT_MEASURED_RE.match(l) for l in lines) if m})
    return notices, absent_notices, not_measured_notices


_BLANK_SUFFIX = "   <- "


def split_forms(vals):
    """The printed forms of one field line: `'a' | 'b' | 'c'` -> ["'a'", "'b'", "'c'"].

    The instrument joins repr()s with " | ", and a value may itself contain " | ", so a
    plain split would tear one form in two (the 2026-10-09 line held two bars inside a
    value). Each candidate form is therefore grown until it is a valid python literal.
    A trailing annotation ("   <- BLANK vs POPULATED ...") is not a form and is cut
    first. If a piece never parses (a value this cannot read back), fall back to the
    plain split rather than dropping the evidence."""
    import ast
    vals = vals.split(_BLANK_SUFFIX, 1)[0].strip()
    pieces = vals.split(" | ")
    forms, cur = [], None
    for piece in pieces:
        cur = piece if cur is None else cur + " | " + piece
        try:
            ast.literal_eval(cur)
        except (ValueError, SyntaxError):
            continue
        forms.append(cur)
        cur = None
    return forms if cur is None else pieces


def unstable_raw_rows(parsed_notices):
    """[{notice, field, forms}] for every field the plain-mode run printed under a
    DISAGREE or BLANK notice: the RAW model output rotating between forms. ADVISORY --
    nothing derived from this blocks; see `run_header_agreement`."""
    rows = []
    for notice, info in sorted(parsed_notices.items()):
        if info["verdict"] not in ("DISAGREE", "BLANK"):
            continue
        for field, vals in info["fields"].items():
            rows.append({"notice": notice, "field": field, "forms": split_forms(vals)})
    return rows


# THE BLOCKING HEADER ARM: the WRITTEN value, from the recorded corpus JSON.
#
# Compared tuple: `hdr_agreement.WRITTEN_FIELDS` (doc_type, mfr, pub_date,
# doc_level_ltb_date), imported rather than copied so the two instruments cannot drift.
# DELIBERATELY EXCLUDED, and the exclusions are rulings, not omissions:
#   * `revision` -- unstable on PCN-2683 today, and the standing ruling is that the
#     revision half NEVER blocks (section (c); the report prints it under "Revision-half
#     unstable across fires (never blocks)"). Comparing it here would re-block 2683
#     through a second door and silently reverse that ruling.
#   * `doc_id` -- an identity field, already blocked on by (c)'s identity_half_unstable
#     arm. One fact, one gate.
WRITTEN_ARM_FIELDS = hdr_agreement.WRITTEN_FIELDS


def compare_written_headers(from_corpus, expected=None):
    """Compare each notice's `written_header` across the fires.

    `from_corpus` is `{fire_n: {filename: written_header_dict}}`, i.e. what
    `headers_from_corpus` returns per fire. Returns a dict:

      verdicts      {filename: "agree" | "DISAGREE" | "BLANK" | "ABSENT"}
      disagreements [(filename, field, [v_fire1, v_fire2, ...])] -- every fire populated
      blank_rows    [(filename, field, {fire_n: value_or_None}, [blank_fire_ns])]
      absent        [(filename, [fire_ns that did not record it])]
      no_written    [(fire_n, filename_or_None)] -- a fire (None) or one notice's entry
                    that carries no `written_header` (an image older than the recording).
                    NOT a disagreement and reported under its own message.
      unrecorded    filenames in `expected` that NO fire recorded. Reported, never
                    blocked on here: the parts arm and `bytes_coverage` own that case.

    WHY THIS EXISTS INSTEAD OF `--written`: see `run_header_agreement`. In short, the gate
    already holds the written values and the replay cannot measure the degraded notice.

    ABSENT IS A BLOCK, NOT A SKIP. A notice one fire recorded and another did not cannot
    be said to agree. This arm is now the only place that is caught: the plain-mode check
    used to be the one that noticed, and it no longer decides the verdict.

    BLANK vs POPULATED is classified apart from a value difference (see
    `pcn_header_agreement.compare`): None and "" are both blank, every fire blank is
    agreement on an absence, and the fire that wrote nothing is held to a needs_review
    (`apply_blank_fire_rule`).
    """
    fires = sorted(from_corpus)
    out = {"verdicts": {}, "disagreements": [], "blank_rows": [], "absent": [],
           "no_written": [], "unrecorded": []}
    # A fire with nothing at all is an older image (or a dead fire), not N absent
    # notices. Say it once, and compare the fires that do have values.
    empty = [n for n in fires if not from_corpus[n]]
    out["no_written"].extend((n, None) for n in empty)
    live = [n for n in fires if n not in empty]
    names = sorted(set().union(*[set(from_corpus[n]) for n in live]) if live else set())
    for fn in names:
        missing = [n for n in live if fn not in from_corpus[n]]
        unshaped = [n for n in live
                    if fn in from_corpus[n] and not isinstance(from_corpus[n][fn], dict)]
        if missing:
            out["absent"].append((fn, missing))
        if unshaped:
            out["no_written"].extend((n, fn) for n in unshaped)
        if missing or unshaped:
            out["verdicts"][fn] = "ABSENT"
            continue
        verdict = "agree"
        for field in WRITTEN_ARM_FIELDS:
            seen = {n: from_corpus[n][fn].get(field) for n in live}
            blank = [n for n in live if hdr_agreement.is_blank(seen[n])]
            if len(blank) == len(live):
                continue                      # agreement on an absence
            if blank:
                out["blank_rows"].append((fn, field, seen, blank))
                if verdict != "DISAGREE":
                    verdict = "BLANK"
            elif len({json.dumps(v, sort_keys=True, default=str)
                      for v in seen.values()}) > 1:
                out["disagreements"].append((fn, field, [seen[n] for n in live]))
                verdict = "DISAGREE"
        out["verdicts"][fn] = verdict
    if expected is not None:
        out["unrecorded"] = sorted(set(expected) - set(names))
    return out


# --------------------------------------------------------------------------
# (c) Identity — collapse (within one fire) and stability (across all three).

def headers_from_corpus(corpus):
    """{filename: written_header} out of one fire's corpus JSON, or {} if this image
    did not record one.

    PREFERRED OVER `hdr_agreement.headers_from_log`, which is a log parser: it locates
    a NoticeHeader block in stdout, bounds it, splices out interleaved BAML timestamps
    and tolerates blocks whose JSON never closes. On the real fire-1 TYC block that
    recovery reaches `revision` and loses `doc_level_ltb_date` entirely. None of that
    is a defect in the parser — it is the cost of reading values out of print output.
    `pcn_corpus_run.py` now records the written header per notice, so when it is there
    this reads a structured value and none of those failure modes can apply.

    Two further things the log path could not give, both of which this does:
      * `revision` is in neither of pcn_header_agreement's compared tuples, so the log
        path only ever supplied it incidentally, when recovery happened to reach it.
      * the values are what was WRITTEN (post-derivation, post-source-refusal), not the
        model's raw emission.

    A notice whose entry failed (`ok` false) is skipped rather than recorded empty: an
    errored fire has no header to compare, and a {} would read as "measured, all absent".
    """
    out = {}
    for fn, entry in (corpus or {}).items():
        if not isinstance(entry, dict) or not entry.get("ok"):
            continue
        wh = entry.get("written_header")
        if isinstance(wh, dict):
            out[fn] = wh
    return out


def content_hashes_by_fire(corpus_by_fire):
    """{filename: {fire_n: content_hash}} for notices where at least one fire recorded
    one. Absent (older images) leaves this empty and the check below vacuous."""
    out = {}
    for n, corpus in corpus_by_fire.items():
        for fn, entry in (corpus or {}).items():
            if isinstance(entry, dict) and entry.get("content_hash"):
                out.setdefault(fn, {})[n] = entry["content_hash"]
    return out


def check_same_bytes(corpus_by_fire):
    """Every fire must have read the SAME source bytes for a given filename, or a
    cross-fire header comparison is not a comparison at all.

    This closes a hole the gate could not see before. The whole instrument assumes the
    three fires differ only in sampling — "identical input, three answers" is the finding
    it exists to report. If the underlying PDF were replaced mid-set, two fires
    disagreeing would be CORRECT behaviour on different documents, and the gate would
    report it as instability. Now recorded, so the assumption is checked rather than
    assumed. Returns a list of blocking messages (empty when every filename is constant,
    and empty when no fire recorded a hash at all — an unrecordable check is not a pass,
    which is why `bytes_checked` is reported separately).
    """
    msgs = []
    for fn, by_n in sorted(content_hashes_by_fire(corpus_by_fire).items()):
        distinct = sorted(set(by_n.values()))
        if len(distinct) > 1:
            where = ", ".join(f"fire {n}={by_n[n][:19]}" for n in sorted(by_n))
            msgs.append(
                f"{fn}: the fires did not read the same source bytes ({where}) — a "
                f"cross-fire header comparison over different documents is void"
            )
    return msgs


def check_declared_bytes(corpus_by_fire, corpus_decl):
    """Every scored notice's bytes must match the sha256 the corpus DECLARES for it.

    `check_same_bytes` proves the fires read the same bytes as each other, but has no
    anchor: it cannot tell "all three fires read the same wrong file" from "all three
    read the right one". This compares each fire's `content_hash` to the sha256 in
    `_corpus`.documents. Every declared filename is mapped, the Diodes alias included,
    so a fire of either name is anchored to the one declared content.

    The declaration is bare 64-hex while `content_hash` carries a `sha256:` prefix; the
    prefix is stripped HERE, at the comparison site, not in the declaration.

    Returns blocking messages and never raises. A MISSING hash is not a block -- that is
    `bytes_coverage`'s job, and an unrecordable check must not read as a failure. A
    scored filename the corpus does not declare IS a block: the run measured a document
    the corpus does not know about.
    """
    msgs = []
    declared = {}
    for d in ((corpus_decl or {}).get("documents") or []):
        if not isinstance(d, dict):
            continue
        for fn in d.get("filenames") or []:
            declared[fn] = d.get("sha256")
    for fn, by_n in sorted(content_hashes_by_fire(corpus_by_fire).items()):
        if fn not in declared:
            msgs.append(
                f"{fn}: scored, but `_corpus`.documents does not declare it -- the run "
                f"measured a document the corpus does not declare"
            )
            continue
        want = declared[fn]
        for n in sorted(by_n):
            got = by_n[n]
            got_hex = got[len("sha256:"):] if isinstance(got, str) and got.startswith("sha256:") else got
            if got_hex != want:
                msgs.append(
                    f"{fn}: fire {n} read bytes with sha256 {str(got_hex)[:16]}... but "
                    f"`_corpus` declares {str(want)[:16]}... -- the fires may agree with "
                    f"each other and still all be reading the wrong file"
                )
    return msgs


def bytes_coverage(corpus_by_fire):
    """WHICH notices had their bytes proved constant across every fire, not whether any
    notice did.

    A set-wide boolean overstates the evidence, and on real data it would overstate it
    today. Measured 2026-09-30: only 11 of the 22 manifests in sandbox MinIO carry
    `source_key`, so before `source_content_hash` grew its sibling fallback some notices
    recorded no hash while others did. `bool(hashes)` was then True and the report read
    "same source bytes across fires: verified" — a claim covering documents that were
    never hashed at all. Coverage is therefore per notice, and a notice hashed by only
    SOME fires counts as unverified: two fires agreeing tells you nothing about the third
    fire's input.

    `unverified` is what to read. `complete` is true only when every scored notice was
    hashed by every fire.
    """
    fires = sorted(corpus_by_fire)
    hashes = content_hashes_by_fire(corpus_by_fire)
    scored = sorted({fn for corpus in corpus_by_fire.values()
                     for fn, e in (corpus or {}).items()
                     if isinstance(e, dict) and e.get("ok")})
    verified = [fn for fn in scored if fires and set(hashes.get(fn, {})) >= set(fires)]
    unverified = [fn for fn in scored if fn not in set(verified)]
    return {
        "fires": fires,
        "notices_scored": len(scored),
        "verified": verified,
        "unverified": unverified,
        "complete": bool(scored) and not unverified,
    }


def build_identity_records(headers_by_fire):
    """{n: {filename: build_identity(...) result}} for n in 1..3."""
    records = {}
    for n, headers in headers_by_fire.items():
        records[n] = {
            fn: notice_identity.build_identity(h.get("mfr"), h.get("doc_id"), h.get("revision"))
            for fn, h in headers.items()
        }
    return records


def compute_collapse(identity_records):
    """Collapse is reported from fire 1, and that is a REPORTING choice which
    (c)'s stability check makes safe — not a claim that identity is the same in
    every fire. It is not: at pin dd043b6, TYC-PCN-24-210412.pdf reads mfr
    'TE Connecvity' in some fires and 'TE' in others on identical bytes, so its
    key, and therefore this grouping, genuinely differs between fires.

    What makes fire 1 sufficient anyway is that compute_stability() below reads
    ALL THREE fires and routes exactly that case to identity_half_unstable,
    which blocks unless the notice is declared needs_review. So a fire-dependent
    grouping can never be quietly averaged away by being read from one fire — it
    surfaces as an instability finding. Reading fire 1 only avoids printing the
    same grouping three times over in the healthy case, where all three agree.
    Treat `distinct_notices` as fire 1's count, and read identity_half_unstable
    before trusting it."""
    fire1 = identity_records.get(1, {})
    by_key = {}
    incomplete = []
    for fn, ident in fire1.items():
        if not ident["complete"]:
            incomplete.append(fn)
            continue
        by_key.setdefault(ident["key"], []).append(fn)
    collapses = [
        {"key": k.replace(notice_identity.SEPARATOR, " | "), "files": sorted(v)}
        for k, v in sorted(by_key.items()) if len(v) > 1
    ]
    return {
        "filenames": len(fire1),
        "distinct_notices": len(by_key) + len(incomplete),
        "collapses": collapses,
        "incomplete_identity": sorted(incomplete),
    }


def compute_stability(identity_records, filenames):
    """Returns `(identity_half_unstable, revision_half_unstable, moving_fields)`.

    THE THIRD RETURN IS WHICH HALF MOVED, and it exists so the declaration rule can
    be keyed to the FIELD, per the 2026-10-27 ruling: a declaration about one field
    must not exempt another, and `{mfr, doc_id}` is two fields, not one. Without it
    the decision site sees only a filename and has to treat the pair as a unit, which
    lets a reason naming `doc_id` -- narrated on every notice since the doc_id
    precedence ruling -- exempt an `mfr` that moved.

    `moving_fields[fn]` is the subset of `_IDENTITY_HALF_FIELDS` whose value actually
    differs across the three fires. For the `None` case it is BOTH fields, because an
    identity that could not be formed at all names no moving half: requiring both to
    be declared is the conservative reading and never grants a notice-level exemption
    on the strength of one field's flag.
    """
    identity_half_unstable = []
    revision_half_unstable = []
    moving_fields = {}
    for fn in filenames:
        keys = [identity_records.get(n, {}).get(fn, {}).get("key") for n in (1, 2, 3)]
        distinct = set(keys)
        if len(distinct) <= 1:
            continue
        if None in distinct:
            # An incomplete identity (mfr or doc_id missing) in at least one
            # fire is at least as severe as a real mfr/doc_id difference: it
            # means identity could not be formed AT ALL in that fire. Lump it
            # with the half that decides WHICH notice a document is, never
            # with the revision-only case.
            identity_half_unstable.append(fn)
            moving_fields[fn] = tuple(_IDENTITY_HALF_FIELDS)
            continue
        components = [notice_identity.parse_notice_key(k) for k in keys]
        mfr_doc_id_pairs = {(c[0], c[1]) for c in components}
        if len(mfr_doc_id_pairs) > 1:
            identity_half_unstable.append(fn)
            moving_fields[fn] = tuple(
                f for i, f in enumerate(_IDENTITY_HALF_FIELDS)
                if len({c[i] for c in components}) > 1)
        else:
            revision_half_unstable.append(fn)
    return sorted(identity_half_unstable), sorted(revision_half_unstable), moving_fields


# --------------------------------------------------------------------------
# THE DECLARATION RULE — the one rule that decides what blocks.
#
# The exemption is EARNED BY THE PRODUCT DECLARING THE PROBLEM, not granted by
# the gate deciding to look away. A notice flagged needs_review goes to a
# human, so a disagreement there is a known, handled condition. A notice that
# disagrees while needs_review is False means the pipeline silently wrote one
# of two values with no flag -- which is the defect, and must block.
#
# Measured at pin dd043b6: TYC-PCN-24-210412.pdf disagrees on mfr
# ('TE Connecvity' | 'TE' | 'TE' -- the dropped "ti" ligature) with
# text_layer_degraded=True and needs_review=False in all three fires. So the
# gate is RED at that pin, correctly. PR #35 makes a degraded text layer set
# needs_review, which converts this notice from an undeclared silent write
# into a declared one -- so the gate goes green on the next pin by the
# pipeline getting better, not by the gate getting weaker.
#
# A notice whose header only disagrees (b), or whose identity half is
# unstable (c), is exempt from blocking only if needs_review == True in ALL THREE
# corpus_f{N}.json records AND a review reason declares a problem with the FIELD in
# question (ruling 2026-10-27; see `header_declaration_for_field_in_fire`) -- a flag
# raised about `doc_id` exempts nothing about `mfr`. There is no exemption at all
# for an ABSENT or NOT MEASURED header-agreement condition (an instrument
# gap, not a declared, handled value conflict) and none for
# revision_half_unstable (which never blocks in the first place, per (c)).
#
# Since 2026-10-26 the "header disagrees" input is the WRITTEN comparison
# (`compare_written_headers`), not the raw plain-mode run: the same rule, a different
# measurement, because "undeclared silent write" is a statement about writes. A field
# BLANK in one fire and populated in another has its own rule below
# (`apply_blank_fire_rule`): needs_review on the blank fire, not all three.

def needs_review_in_fire(corpus_by_fire, n, notice):
    """Did fire `n` set needs_review for `notice`? The single lookup both the
    all-fires rule and the blank-fire rule read, so they cannot disagree on what
    "declared" means."""
    return bool((corpus_by_fire.get(n, {}).get(notice) or {}).get("needs_review"))


def needs_review_in_all_fires(corpus_by_fire, notice):
    return all(needs_review_in_fire(corpus_by_fire, n, notice) for n in (1, 2, 3))


# Declarations are matched as substrings of `review_reasons`, not by a flag, because
# there is no flag: the product narrates, and a structured field would mean adding one
# and keeping two representations of the same fact in step.
#
# KEYED TO THE FIELD UNDER TEST (architect's ruling, 2026-10-27). `needs_review` is a
# DOCUMENT-level flag, and it went from 3/4/3 of ten notices on v0.2.1 to 10 of 10 on
# v0.2.2 because the doc_id precedence ruling makes the plugin narrate a `doc_id`
# reason on every notice (`sustainment.py:1670,1680`). Consumed as an exemption from
# header correctness, that flag let a note about `doc_id` -- which is not a scored
# header field -- buy a notice an exemption for `mfr`, `pub_date` and
# `doc_level_ltb_date`. A declaration about one field must not exempt another.
#
# The vocabulary, as the product phrases it (verified in the tree):
#   `header.<field> refused: '<v>' <clause>`  sustainment_header_trust.py:1533 -- ONE field
#   `region witness LOST the <name> region on page N (<why>); header fields <a, b>
#    were neither supplied nor corroborated`  sustainment.py:1804 -- the fields it NAMES
#   `header pass failed: <error>`             sustainment.py:760 -- EVERY field: the
#                                             pass raised, nothing was extracted
#   `region witness DISABLED for this document: <e>`  sustainment.py:1384 -- EVERY field
# Field names are shared vocabulary (witness_regions.py:83-88 declares the same keys
# pcn_ground_truth.json scores), so there is no alias table and none may be added.
#
# "could not be located" is deliberately NOT a marker. It used to be one, commented "no
# header region was locatable at all", and that was wrong: its only emitter is
# sustainment_header_trust.py:1347, a `_REFUSAL_CLAUSE` value, so the string only ever
# appears INSIDE a `header.<field> refused: ...` reason about one field, which the
# refusal shape below already covers. Re-adding it as a header-wide marker would
# re-widen the exemption to every field.
_HEADER_WIDE_DECLARATION_MARKERS = (
    "header pass failed",       # the header extraction itself raised: nothing extracted
    "region witness DISABLED",  # no field could be corroborated
)

# The two fields the identity half is made of. Which of them MOVED is reported by
# `compute_stability` and decided per field in `apply_declaration_rule`; this tuple is
# the fallback when no moving half can be named (identity not formed in some fire).
_IDENTITY_HALF_FIELDS = ("mfr", "doc_id")


def _declaration_field_base(field):
    """Strip one trailing `_source` and return the rest; otherwise `field` unchanged.

    The `_source` companion is the citation for the same field, not a field of its own.
    The product declares problems about `doc_level_ltb_date`; it never writes
    `header.doc_level_ltb_date_source refused`. Without this, a correct, specific
    declaration would fail to exempt the companion and the rule would be stricter than
    the ruling -- and the live TYC-PCN-24-210412 disagreement is on exactly that
    companion, so this is not hypothetical."""
    return field[:-len("_source")] if field.endswith("_source") else field


def _field_declaration_basis(corpus_by_fire, n, notice, field):
    """What, if anything, fire `n` declared about `field` -- as a phrase for the report,
    or None. The single place the vocabulary is read, so the predicate and the messages
    cannot disagree about what counted."""
    if not needs_review_in_fire(corpus_by_fire, n, notice):
        return None
    base = _declaration_field_base(field)
    reasons = [str(r) for r in
               ((corpus_by_fire.get(n, {}).get(notice) or {}).get("review_reasons") or [])]
    for marker in _HEADER_WIDE_DECLARATION_MARKERS:
        if any(marker in r for r in reasons):
            return f"a header-wide reason ({marker!r}) covers every field"
    if any(f"header.{base} refused" in r for r in reasons):
        return f"a review reason names `{base}` (header.{base} refused)"
    if any("region witness LOST" in r and base in r for r in reasons):
        return f"a review reason names `{base}` (region witness LOST)"
    return None


def header_declaration_for_field_in_fire(corpus_by_fire, n, notice, field):
    """Did fire `n` declare a problem with THIS header field of `notice`?

    True iff `needs_review` is set in that fire AND its `review_reasons` carry either a
    header-wide marker or a reason naming the field. `needs_review` is still required:
    a narrated reason on a document nobody is told to review is not a declaration.
    Read by the blank-fire rule directly (it is already per fire) and, three times, by
    the all-fires predicate."""
    return _field_declaration_basis(corpus_by_fire, n, notice, field) is not None


def header_declaration_for_field_in_all_fires(corpus_by_fire, notice, field):
    """`header_declaration_for_field_in_fire` in all three fires.

    Narrower than any document-level reading of `needs_review`, on two axes. Per
    NOTICE: a degraded text layer sets it unconditionally and permanently, which gave
    the one notice with a measurably wrong header an exemption no measurement could
    revoke -- the reason must name the header. Per FIELD: a reason naming `doc_id`
    must not exempt `mfr`. The region witness exists to survive a degraded layer, so a
    notice that wrote a wrong value from pixels with no declaration about THAT value has
    published it with no warning attached, which is what condition (e) is for."""
    return all(header_declaration_for_field_in_fire(corpus_by_fire, n, notice, field)
               for n in (1, 2, 3))


def _all_fires_basis(corpus_by_fire, notice, field):
    """The distinct bases across the three fires, as one string (for an exempted line)."""
    return "; ".join(sorted({_field_declaration_basis(corpus_by_fire, n, notice, field)
                             for n in (1, 2, 3)}))


def _why_not_declared(corpus_by_fire, notice, field, fires=(1, 2, 3)):
    """For a blocking line: a MISSING flag and a flag about the WRONG field are
    different defects with different fixes, and a red report must say which."""
    base = _declaration_field_base(field)
    unflagged = [n for n in fires if not needs_review_in_fire(corpus_by_fire, n, notice)]
    where = "all three fires" if len(fires) == 3 else f"fire {fires[0]}"
    if unflagged:
        return (f"needs_review is not True in fire(s) {unflagged} "
                f"(undeclared silent write of `{field}`)")
    return (f"needs_review=True in {where} but no reason names `{base}` -- a declaration "
            f"about another field is not a declaration about this one")


def check_header_correctness(header_totals_by_fire, corpus_by_fire):
    """(e) Was the written header CORRECT, not merely stable across fires?

    THE CASE THIS CATCHES, measured on the real f32 fire set: all three fires
    wrote `pub_date = 2024-06-10` for TYC. Agreement (b) therefore records
    pub_date as AGREE and says nothing — it compares the fires to each other,
    and they matched. The page says the notice was published on the 7th; 06-10
    is the portal's print stamp, the day the PDF was rendered. Stability over a
    wrong value is the one failure a cross-fire check structurally cannot see,
    so this condition reads `header_totals` from each fire's score JSON, which
    `pcn_score.py` computes against the `headers` block in ground truth.

    NOT OBSERVED IS NOT A PASS. Score JSONs from an image predating header
    scoring carry no `header_totals`; that is recorded as `observed: false` and
    does not block, exactly as `rates_available` does. It also is not reported
    as zero failures.

    THE DECLARATION EXEMPTION APPLIES HERE TOO, BUT NARROWED TO THE FIELD — see
    `header_declaration_for_field_in_all_fires`. A field the product flagged
    `needs_review` for, in all three fires, has not silently published a wrong
    value — a human sees it before it counts — which is the same reasoning that
    exempts a disagreeing field in (d). But `needs_review` ALONE is too weak: a
    degraded text layer sets it unconditionally and permanently, and the doc_id
    precedence ruling narrates a `doc_id` reason on every notice, so a
    document-level flag handed a measurably wrong `mfr` or `pub_date` an
    exemption no measurement could revoke. The decision is therefore made per
    `(notice, field)`: one notice may have one field exempted and another
    blocking, and each gets its own line. The failure is reported either way, and
    `strict_verdict` (which grants no exemptions) counts it regardless.
    """
    observed = {n: t for n, t in header_totals_by_fire.items() if t}
    block = {"observed": bool(observed), "fires": {}}
    blocking, exempted = [], []
    if not observed:
        block["reason"] = ("no fire score JSON carries header_totals — scored by an "
                           "image that predates header scoring. NOT a pass: the "
                           "headers were not measured against ground truth at all.")
        return block, blocking, exempted

    failures = {}  # notice -> {field: {fire: status}}
    for n, t in sorted(observed.items()):
        block["fires"][n] = {
            "exact": t.get("exact"), "fields_scored": t.get("fields_scored"),
            "clean": t.get("clean"), "observed": t.get("observed"),
            "unobserved": t.get("unobserved", []),
            "pending": t.get("pending", []),
        }
        # From the scorer, not a second copy: this was a hardcoded tuple of the
        # same five statuses, so a failure class added to pcn_score would have
        # been scored there and silently ignored HERE -- a new way to fail that
        # blocks nothing. `alias` is correctly absent, being a pass.
        for status in pcn_score.HEADER_FAILURES:
            for located in t.get(status, []):
                notice, _, field = located.partition(":")
                failures.setdefault(notice, {}).setdefault(field, {})[n] = status
    block["failing_notices"] = sorted(failures)

    for notice, by_field in sorted(failures.items()):
        for field, by_fire in sorted(by_field.items()):
            detail = "; ".join(f"fire {n}: {field} ({s})" for n, s in sorted(by_fire.items()))
            line = (f"{notice}: written header `{field}` does not match ground truth — "
                    f"{detail} (pcn_ground_truth.json notices[{notice}].headers)")
            if header_declaration_for_field_in_all_fires(corpus_by_fire, notice, field):
                exempted.append(line + " — exempted: needs_review=True in all three "
                                       "fires and "
                                + _all_fires_basis(corpus_by_fire, notice, field))
            else:
                blocking.append(line + " — blocking: "
                                + _why_not_declared(corpus_by_fire, notice, field))
    return block, blocking, exempted


def apply_declaration_rule(disagreements, identity_half_unstable, corpus_by_fire,
                           identity_moving_fields=None):
    """The all-fires declaration rule, decided PER FIELD.

    `disagreements` is `compare_written_headers`'s per-field rows,
    `(filename, field, [values])` -- NOT a collapsed notice set. Collapsing was the
    defect: a reason about `doc_id` (narrated on every notice since the doc_id
    precedence ruling) exempted a disagreement on `mfr`. Each row is exempt only if all
    three fires declared a problem with THAT field
    (`header_declaration_for_field_in_all_fires`).

    THE IDENTITY HALF IS KEYED TO THE MOVING FIELD TOO. `identity_moving_fields[notice]`
    is `compute_stability`'s report of which of `{mfr, doc_id}` actually differs across
    the fires; EVERY field in it must be declared, in every fire, or the notice blocks.
    A reason naming `doc_id` therefore no longer exempts an `mfr` that moved -- which
    was the last place in this file where a declaration about one field bought an
    exemption for another. Both fields are required when the caller supplies nothing
    (the pre-2026-10-27 shape) and when identity could not be FORMED in some fire,
    since an absent identity names no moving half."""
    blocking = []
    exempted = []
    for notice, field, values in sorted(disagreements, key=lambda r: (r[0], r[1])):
        if header_declaration_for_field_in_all_fires(corpus_by_fire, notice, field):
            exempted.append(
                f"{notice}: written-header disagreement on `{field}` {values!r} exempted — "
                f"needs_review=True in all three fires and "
                + _all_fires_basis(corpus_by_fire, notice, field)
            )
        else:
            blocking.append(
                f"{notice}: WRITTEN header fields disagree across fires on `{field}` "
                f"{values!r} — blocking: "
                + _why_not_declared(corpus_by_fire, notice, field)
            )
    moving_by_notice = identity_moving_fields or {}
    for notice in sorted(identity_half_unstable):
        moving = tuple(moving_by_notice.get(notice) or _IDENTITY_HALF_FIELDS)
        named = "/".join(moving)
        # EVERY moving field, in EVERY fire. `any` here would be the collapsing
        # defect again, one level down: `doc_id` declared, `mfr` moved, exempt.
        bases = []
        for n in (1, 2, 3):
            per_field = [_field_declaration_basis(corpus_by_fire, n, notice, f)
                         for f in moving]
            bases.append("; ".join(per_field) if all(per_field) else None)
        if all(bases):
            exempted.append(
                f"{notice}: identity-half instability (`{named}` differs across fires) "
                f"exempted — needs_review=True in all three fires and "
                + "; ".join(sorted(set(bases)))
            )
        else:
            undeclared = [
                f for f in moving
                if not all(_field_declaration_basis(corpus_by_fire, n, notice, f)
                           for n in (1, 2, 3))
            ]
            blocking.append(
                f"{notice}: identity half is unstable across fires on `{named}` — blocking: "
                + _why_not_declared(corpus_by_fire, notice, undeclared[0])
                + f" (every moving identity field must be declared; undeclared: "
                  f"{', '.join(undeclared)})"
            )
    return blocking, exempted


def apply_blank_fire_rule(blank_rows, corpus_by_fire):
    """The blank-fire rule: a header field that is blank in one fire and populated in
    another is declared on the BLANK fire, always -- and declared FOR THAT FIELD
    (`header_declaration_for_field_in_fire`), not merely `needs_review`: a flag raised
    about `doc_id` says nothing about the `pub_date` that fire wrote as nothing.
    `blank_rows` is `compare_written_headers`'s
    `(filename, field, {fire_n: value}, [blank_fire_ns])`.
    Returns `(blocking, exempted)` message lists.

    THE BLANK FIRE, NOT ALL THREE. The blank fire is the one that wrote nothing while
    another fire had a value, so it is the only fire with something to declare; the fires
    that populated the field have nothing to flag. Requiring all three would make a
    correct fire's silence the blocker, and the notice could then never be declared at
    all. Conversely a populated fire's needs_review proves nothing about the fire that
    wrote the blank, so only the blank fires are read.

    No exemption for a blank that is not declared: that is a silent write of nothing,
    the same defect `apply_declaration_rule` blocks for two populated values."""
    blocking, exempted = [], []
    for notice, field, seen, blank_fires in sorted(blank_rows, key=lambda r: (r[0], r[1])):
        populated = "; ".join(f"fire {m}={v!r}" for m, v in sorted(seen.items())
                              if m not in blank_fires)
        for n in blank_fires:
            if header_declaration_for_field_in_fire(corpus_by_fire, n, notice, field):
                exempted.append(
                    f"{notice}: `{field}` blank in fire {n}, populated in the others "
                    f"({populated}) — exempted: needs_review=True in fire {n} and "
                    + _field_declaration_basis(corpus_by_fire, n, notice, field)
                )
            else:
                blocking.append(
                    f"{notice}: `{field}` is blank in fire {n} but populated in the "
                    f"others ({populated}) — blocking, undeclared silent blank: "
                    + _why_not_declared(corpus_by_fire, notice, field, fires=(n,))
                )
    return blocking, exempted


def apply_written_arm(written, corpus_by_fire):
    """The written arm's contribution to blocking/exempted: value differences through
    the all-fires declaration rule, blanks through the blank-fire rule, and ABSENT / no
    `written_header` as unexempted instrument gaps (a gate that cannot measure does not
    pass)."""
    blocking, exempted = apply_declaration_rule(
        written["disagreements"], [], corpus_by_fire)
    b2, e2 = apply_blank_fire_rule(written["blank_rows"], corpus_by_fire)
    blocking.extend(b2)
    exempted.extend(e2)
    for fn, fires_missing in written["absent"]:
        blocking.append(
            f"{fn}: written header not recorded by fire(s) {fires_missing} — cannot be "
            f"said to agree; no declaration exemption for an instrument gap"
        )
    for n, fn in written["no_written"]:
        what = (f"fire {n} recorded no `written_header` for any notice"
                if fn is None else
                f"fire {n} recorded no `written_header` for {fn}")
        blocking.append(
            f"{what} (an image older than the recording, or a fire that produced none) — "
            f"not a disagreement, not measured"
        )
    return blocking, exempted


# --------------------------------------------------------------------------
# Scoring — assembles (a)-(d) into the report dict. Same path for both modes.

DEFECT_KINDS = ("missing", "spurious", "malformed")


def notice_defects(score):
    """Per-notice `missing` / `spurious` / `malformed` MPNs, for the notices with any.

    WHY THIS IS CARRIED AND THE TOTALS ARE NOT ENOUGH. `pcn_score.py` has always
    written a `per_notice` block naming the exact MPNs each notice lost, and this
    gate always threw it away and kept `totals`. On 2026-10-01 fire 3 scored
    890/898 while fires 1 and 2 scored 898/898 on verified-identical source
    bytes. The report said 8 parts went missing and could not say from where: the
    breakdown was in the pod's `fire3.log`, the Job had already reached `Failed`,
    and a `Failed` pod refuses `kubectl exec`. The first observed PARTS
    nondeterminism in this corpus was therefore unattributable, and nothing but
    a re-run could recover it.

    Per-fire totals say a run is red. Only this says where, and it is the
    cheapest possible fix because the data was already being computed.

    Returns `None` when there is no per-notice data to carry (the fire's score
    JSON was unreadable or predates `per_notice`) -- distinct from `{}`, which
    means every notice in that fire was clean. A reader must be able to tell
    "nothing wrong" from "nothing measured".

    A notice is included when it has any defect MPN, carries an `error` (absent
    from the run, or the run reported failure), or is simply not `clean` --
    that last case catches a notice whose counts do not add up even though all
    three lists came back empty.

    SIZE. The lists are carried WHOLE, not truncated. Worst case is a total
    extraction failure, where every one of the 898 harness MPNs is missing in
    every fire -- roughly 12 KB of JSON per fire. That is the run where a
    truncated list would be worth least, so the bound is accepted deliberately.
    """
    if score is None:
        return None
    per = score.get("per_notice")
    if not isinstance(per, dict):
        return None

    out = {}
    for fn in sorted(per):
        rec = per[fn] if isinstance(per[fn], dict) else {}
        lists = {kind: list(rec.get(kind) or []) for kind in DEFECT_KINDS}
        error = rec.get("error")
        if not any(lists.values()) and not error and rec.get("clean", True):
            continue
        entry = {
            "count": rec.get("count"),
            "exact": rec.get("exact"),
            "emitted": rec.get("emitted"),
            "clean": rec.get("clean"),
        }
        entry.update(lists)
        if error:
            entry["error"] = error
        out[fn] = entry
    return out


LOG_TAIL_BYTES_DEFAULT = 256 * 1024


def log_tail_bytes():
    """Cap on how much of one fire log is echoed, overridable by an operator.

    256 KiB per fire, so three failing fires add at most ~768 KiB to this
    process's stdout. The kubelet rotates a container's log at 10 MiB by
    default, and evicting the report from `kubectl logs` in order to preserve
    the logs would be a poor trade -- hence a cap rather than the whole file.
    """
    raw = os.environ.get("PCN_GATE_LOG_TAIL_BYTES")
    if not raw:
        return LOG_TAIL_BYTES_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        return LOG_TAIL_BYTES_DEFAULT
    return value if value > 0 else LOG_TAIL_BYTES_DEFAULT


def fire_log_tail(log_path, max_bytes):
    """`(text, total_bytes, omitted_bytes)` for the TAIL of one fire log.

    The tail, not the head: `pcn_corpus_run.py` prints its per-notice table and
    its missing/spurious lists last, so the end of the file is the diagnostic
    part. Decoded with `errors="replace"` and seeked to a byte offset, so a cut
    through a multi-byte character degrades one character rather than raising.

    Never raises. A log that cannot be read is itself a finding and must not
    take the report down with it -- by the time this runs the fires are over and
    the report is already assembled.
    """
    try:
        total = os.path.getsize(log_path)
    except OSError as exc:
        return (f"<could not stat {log_path}: {exc}>", None, None)
    try:
        with open(log_path, "rb") as fh:
            if total > max_bytes:
                fh.seek(total - max_bytes)
            data = fh.read()
    except OSError as exc:
        return (f"<could not read {log_path}: {exc}>", total, None)
    return (data.decode("utf-8", "replace"), total, max(0, total - len(data)))


# --------------------------------------------------------------------------
# Image identity: VOID, which is not a verdict.

#: `sha256:<hex>` anywhere in an image reference. Comparison is on the DIGEST
#: and never on the whole string: the same image is spelled
#: `ghcr.io/edgy-solutions/doc-tools@sha256:X` in the chart,
#: `ghcr.io/v2/edgy-solutions/doc-tools/manifests/sha256:X` in a registry
#: probe, and `ghcr.io/edgy-solutions/doc-tools@sha256:X` again in a pod's
#: `imageID` — three spellings, one image. A string compare would report
#: those as a mismatch and void a good report.
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")


def _digest_of(ref):
    """The `sha256:<64 hex>` in `ref`, or None.

    None is a real outcome, not a parse failure to be papered over: a
    tag-only reference (`...:latest`, `...:0.4.12`) names no digest, and a
    tag cannot be reconciled with anything — `:latest` has pointed at a
    config digest matching no image in this cluster's history. A reference
    that cannot be reduced to a digest is UNCOMPARABLE, and that is
    reported as such rather than guessed at.
    """
    if not ref or not isinstance(ref, str):
        return None
    m = _DIGEST_RE.search(ref)
    return m.group(0) if m else None


def parse_expectations(values):
    """`["chart=ghcr.io/...@sha256:X", ...]` -> `[{"source": ..., "ref": ...}]`.

    The SOURCE LABEL IS REQUIRED and is not cosmetic. "measured_image differs
    from the chart digest" and "measured_image differs from the pods'
    imageID" are different findings with different remedies — the first says
    the report is not about the image the chart declares, the second says the
    cluster is not running what the chart declares — and a report that says
    only "mismatch" leaves a reader unable to tell which. A bare value with
    no `source=` prefix is taken as source "unlabelled" rather than
    rejected, so an operator in a hurry still gets the comparison.
    """
    out = []
    for raw in values or []:
        for part in str(raw).split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                source, ref = part.split("=", 1)
                source, ref = source.strip() or "unlabelled", ref.strip()
            else:
                source, ref = "unlabelled", part
            if ref:
                out.append({"source": source, "ref": ref})
    return out


IDENTITY_MODES = ("rolled", "pre_roll")


def resolve_identity_mode(value):
    """`rolled` (the default) or `pre_roll`, and an unknown value is an ERROR.

    WHAT THE MODE IS FOR. It does not change a single score. It records what
    the measured image WAS at the time of the fire, which a reader of the
    committed report cannot otherwise recover:

    - `rolled` — the image is the one the chart pins and the pods run. This
      is every report this gate has ever written, and the identity check can
      be corroborated from inside the cluster by whoever reads a pod's
      `imageID`.
    - `pre_roll` — the image was BUILT but is not pinned by any chart and no
      pod is running it. The Job was created with an explicit image override
      (`scripts/pcn_gate_prefire.py`) so that a pin-bump PR can carry a
      report for the digest it lands, which is what closes the window where
      a new pin has no measurement.

    WHY UNKNOWN IS AN ERROR RATHER THAN A FALLBACK TO `rolled`. A typo would
    otherwise produce a report labelled as a measurement of the deployed
    system when it is nothing of the kind, and the label is the only thing
    distinguishing the two. Defaulting the ABSENT case to `rolled` is
    different and is safe: every report written before this existed was a
    rolled fire, so the absence has one true meaning.
    """
    mode = (value or "rolled").strip() or "rolled"
    if mode not in IDENTITY_MODES:
        raise SystemExit(
            f"unknown identity mode {mode!r}; expected one of "
            f"{', '.join(IDENTITY_MODES)}. This is refused rather than "
            f"defaulted: the mode is the only thing in the report that says "
            f"whether the measured image was one any pod was running, and a "
            f"report mislabelled `rolled` claims to describe the deployed "
            f"system."
        )
    return mode


def check_image_identity(measured, expectations, mode="rolled"):
    """Compare `measured_image` against what it was SUPPOSED to be.

    THE RULING (architect, 2026-10-02): "a report whose measured_image
    differs from the chart digest or the pods' imageID is VOID, not a
    verdict." Void is a third state beside pass and fail, because a
    mismatch does not tell you the corpus scored badly — it tells you the
    score is about some other image, so the pass/fail it carries is a
    statement about nothing. Reporting that as `fail` would be as wrong as
    reporting it as `pass`: someone would go looking for extraction defects
    that are not there.

    WHY THE EXPECTATIONS ARE SUPPLIED AND NEVER FETCHED. This function is
    told what to compare against; it does not reach into the cluster. The
    gate runs in a Job whose ServiceAccount has no Role at all (there is no
    `role.yaml` in charts/doc-tools/templates/), so it cannot read a pod's
    `imageID`, and the container carries no kubectl. Giving it that RBAC to
    let it grade itself would also be the weaker design: an instrument that
    sources its own expectation can agree with itself. So the chart digest
    arrives as an env var the chart renders, and the pods' imageID — when
    anyone supplies it — arrives from whoever could read it.

    WHICH COMPARISONS RAN IS PART OF THE RESULT. `checked` is False when no
    expectation was supplied, and every comparison is listed with its own
    `result`. This is the lesson from the `source_key` checks, which went
    inert on 11 of 22 manifests while a set-wide boolean still read
    "verified": a check that did not run must never be indistinguishable
    from a check that passed.

    A tag-only `measured_image`, or an expectation that carries no digest,
    is `uncomparable` and is ALSO void. The ruling's subject is digests; a
    report whose image is pinned by a moving tag cannot be reconciled with
    anything, and `:latest` is exactly the case that made "what is sandbox
    running?" unanswerable for weeks.

    `mode` IS RECORDED AND CHANGES NOTHING HERE, deliberately. A `pre_roll`
    fire measures an image no pod is running, so there is no `imageID` for
    anyone to supply and no chart that pins it: the expectation list is
    normally empty and `checked` is therefore False — UNRECONCILED, which is
    what this function already says in that case and what
    `_render_image_identity` already prints above the scores. That is the
    honest state and it must not be dressed up: the gate cannot read its own
    digest (no Role, no kubectl — see above), so in `pre_roll` the digest in
    `measured_image` is SELF-DECLARED by whoever created the Job.

    What corroborates it is outside this process, in two places, and neither
    is a claim this report gets to make about itself:

    1. `scripts/pcn_gate_prefire.py` reads the pod's `imageID` after the Job
       starts and refuses the fire if it is not the candidate — which is the
       cheap moment to find out, before 2.5 hours of vision calls.
    2. `tests/test_corpus_gate_guard.py` compares this report's
       `measured_image` against the digest the chart pins, in CI, from the
       two files. Two instruments, neither sourcing its own expectation.

    An expectation supplied in `pre_roll` is still compared, and still voids
    on a mismatch. Nobody should be silenced for having an answer.
    """
    measured_digest = _digest_of(measured)
    comparisons = []
    void_reasons = []

    for exp in expectations or []:
        exp_digest = _digest_of(exp["ref"])
        if measured_digest is None or exp_digest is None:
            result = "uncomparable"
            which = []
            if measured_digest is None:
                which.append(f"measured_image={measured!r} carries no sha256 digest")
            if exp_digest is None:
                which.append(f"{exp['source']} expectation {exp['ref']!r} carries no sha256 digest")
            void_reasons.append(
                f"image identity UNCOMPARABLE against {exp['source']}: "
                + "; ".join(which)
                + ". A tag is not an identity — this report cannot be shown to "
                  "be about the image it claims, so it is not a verdict."
            )
        elif measured_digest == exp_digest:
            result = "match"
        else:
            result = "mismatch"
            void_reasons.append(
                f"measured_image digest {measured_digest} differs from the "
                f"{exp['source']} digest {exp_digest}. This report is VOID, not "
                f"a fail: it scores a different image than the one "
                f"{exp['source']} declares, so neither its pass nor its "
                f"blocking list says anything about "
                f"{'the chart' if exp['source'] == 'chart' else exp['source']}."
            )
        comparisons.append({
            "source": exp["source"],
            "expected": exp["ref"],
            "expected_digest": exp_digest,
            "result": result,
        })

    return {
        "measured": measured,
        "measured_digest": measured_digest,
        # False means NO COMPARISON RAN. Not "nothing was wrong".
        "checked": bool(comparisons),
        "comparisons": comparisons,
        "void_reasons": void_reasons,
        # `rolled` or `pre_roll`. Carried here as well as at the top of the
        # report so that this block, which is what a reader quotes when
        # arguing about what was measured, cannot be quoted without it.
        "mode": mode,
        # True only in `pre_roll`, and it means: the digest above was asserted
        # by whoever created the Job and NOT verified by this process. It is a
        # separate key rather than a reading of `checked` because the two
        # answer different questions -- `checked: false` says no comparison
        # ran, this says no comparison COULD run from in here.
        "self_declared": mode == "pre_roll",
    }


def fires_needing_preservation(report, fires):
    """`[(report_entry, fire)]` for the fires whose log a reader will need.

    THE SELECTOR IS THE JOB'S VERDICT, NOT EACH FIRE'S EXIT CODE, and that
    distinction is the whole correctness of this feature. On 2026-10-01 all
    three fires exited 0; the Job failed because the GATE's verdict was `fail`,
    and it is fire 3's log that was then lost. A per-fire `exit != 0` selector
    would not have preserved the one log anyone wanted. So: a failing verdict
    preserves every fire log.

    Nor is "the fire with defects" sufficient. A red caused by header
    disagreement can leave every fire clean on parts, and the per-notice corpus
    JSON carries no header fields at all -- the header values the agreement
    check compared exist in the fire logs and nowhere else. Narrowing to the
    defective fire would discard exactly that evidence.

    On a PASSING verdict nothing is echoed, with one exception kept as a
    belt-and-braces: a fire whose own score JSON could not be read
    (`totals`/`defects` is None), or which exited non-zero, is a fire the report
    can say least about, and should not be able to pass quietly.
    """
    by_n = {f["n"]: f for f in fires}
    failing = report.get("verdict") != "pass"
    out = []
    for entry in report.get("fires", []):
        unmeasured = (entry.get("exit") != 0
                      or entry.get("totals") is None
                      or entry.get("defects") is None)
        fire = by_n.get(entry["n"])
        if fire is None or not (failing or unmeasured):
            continue
        out.append((entry, fire))
    return out


def annotate_log_preservation(report, fires, max_bytes):
    """Record, in the report itself, each log's size and whether it was echoed.

    Without this the report cannot tell a reader that the log they want is in
    `kubectl logs` rather than in a file they can no longer reach.
    """
    by_n = {f["n"]: f for f in fires}
    echoed = {entry["n"] for entry, _ in fires_needing_preservation(report, fires)}
    for entry in report.get("fires", []):
        fire = by_n.get(entry["n"])
        size = None
        if fire is not None:
            try:
                size = os.path.getsize(fire["log_path"])
            except OSError:
                size = None
        entry["log_bytes"] = size
        entry["log_echoed"] = entry["n"] in echoed
        entry["log_echo_cap_bytes"] = max_bytes if entry["n"] in echoed else None


def preserved_log_dumps(report, fires, max_bytes):
    """Yield one delimited block per fire log that has to outlive the pod.

    THE PROBLEM THIS SOLVES. Fire logs are written to the gate's working
    directory, which in the cluster is a path inside the pod. When a Job fails
    the pod is retained but refuses `exec` ("cannot exec into a container in a
    completed pod"), so the files are unreachable while the pod that holds them
    still exists -- `kubectl logs` keeps working the whole time. Echoing the
    logs into this process's own stdout therefore moves them from the one
    channel that closes to the one that does not, and needs no volume, no
    object store and no second credential.

    The delimiters are greppable on purpose: a reader pipes
    `kubectl logs job/<job>` through
    `sed -n '/BEGIN fire 3 log/,/END fire 3 log/p'`.
    """
    for entry, fire in fires_needing_preservation(report, fires):
        n = entry["n"]
        text, total, omitted = fire_log_tail(fire["log_path"], max_bytes)
        head = [
            "",
            f"===== BEGIN fire {n} log ({fire['log_path']}) =====",
            f"exit={entry.get('exit')} bytes={total} omitted_from_head={omitted} "
            f"cap={max_bytes}",
            "Reproduced because this run is not a clean pass. The file itself "
            "dies with the pod -- and a completed pod refuses `exec` while "
            "`kubectl logs` keeps serving -- so this text is the copy that "
            "outlives the Job.",
            "",
        ]
        yield "\n".join(head) + text.rstrip("\n") + f"\n\n===== END fire {n} log ====="


# The crop-seal counters carried into the report. The first two are the gate's own
# exit term (pcn_corpus_run.py requires both 0 on every fire, mirrored in
# `_reconstruct_exit` above); the rest are context — `stored_cut_*` counts cuts the
# repair FIXED, which is work done, not a failure, and `n_tables` is the population.
SEAL_COUNTERS = ("repaired_cut_tables", "errors",
                 "repaired_cut_words", "stored_cut_tables", "stored_cut_words",
                 "n_tables")


def aggregate_seal_totals(totals_by_fire):
    """Worst case per counter across the fires whose crop-seal JSON was read.

    Same shape and the same NOT-OBSERVED discipline as
    doc_tools/utils/ingest_rates.py::aggregate_rates_across_fires: a fire whose seal
    was not read contributes NOTHING — not a zero — and is named in `fires_missing`.
    MAX per counter, independently per counter, because the exit criterion is
    `repaired_cut_tables == 0 and errors == 0` on EVERY fire: one bad fire is the
    verdict, so the maximum is the number that decided it.

    `n_tables` is maxed on the same rule, which makes it the largest table population
    any fire saw rather than a denominator the fires are asserted to share. `by_fire`
    is the copy to read when they differ and `agreement` says whether they did — the
    fires have disagreed on measured rates before over one image (see the per-fire
    note in `score_fires`), so nothing here is reported once and assumed common.
    """
    keys = sorted(totals_by_fire)
    contributing = [k for k in keys if isinstance(totals_by_fire[k], dict)]
    block = {
        "fires": contributing,
        "fires_missing": [k for k in keys if k not in contributing],
        "agreement": True,
        "totals": {},
        "by_fire": {},
    }
    if not contributing:
        return block
    agreement = True
    for counter in SEAL_COUNTERS:
        per = {k: (totals_by_fire[k].get(counter) or 0) for k in contributing}
        block["totals"][counter] = max(per.values())
        block["by_fire"][counter] = per
        if len(set(per.values())) > 1:
            agreement = False
    block["agreement"] = agreement
    return block


def score_fires(base_dir, fires, expectations=None, identity_mode="rolled"):
    blocking = []
    exempted = []

    # (a) Fires.
    fires_ok = all(f["exit"] == 0 for f in fires)
    for f in fires:
        if f["exit"] != 0:
            blocking.append(
                f"fire {f['n']}: pcn_corpus_run.py exited {f['exit']} — parts/crop-seal "
                f"gate not met (see {f['log']})"
            )

    fire_reports = []
    corpus_by_fire = {}
    header_totals_by_fire = {}
    rates_by_fire = {}
    seal_totals_by_fire = {}
    for f in fires:
        corpus, corpus_err = _load_json_soft(f["corpus_path"])
        score, score_err = _load_json_soft(f["score_path"])
        # THE SEAL'S OWN NUMBERS, per fire. `seal_checked` already records whether the
        # seal TERM was evaluated; it says nothing about what the seal measured, and
        # until now the authority artifact carried no copy of that at all — a reader
        # of latest.json could see a red fire without learning that the crop seal, not
        # the parts score, is what made it red, and could not tell a fire that was
        # green with two stored cuts repaired from one with nothing to repair. The
        # error string is kept rather than raised: a missing seal JSON on a fire that
        # crashed is already blocking via its exit code, and in --from-logs without
        # --seal-prefix there is legitimately no seal to read.
        sealed, seal_err = (_load_json_soft(f["seal_path"])
                            if f.get("seal_path") else (None, None))
        # None, never {}: a seal that was not read is not a seal that found nothing.
        seal_totals = sealed.get("totals") if isinstance(sealed, dict) else None
        seal_totals_by_fire[f["n"]] = seal_totals
        corpus_by_fire[f["n"]] = corpus or {}
        rates_by_fire[f["n"]] = None  # unreadable score: not observed, not zero
        totals = None
        # None, not {}: "no per-notice data" and "every notice clean" are
        # different facts and the report must not blur them.
        defects = None
        if score is not None:
            totals = score.get("totals")
            defects = notice_defects(score)
            # Per fire, not once: a header that is correct in one fire and a
            # distractor in the next is two different facts and both must show.
            header_totals_by_fire[f["n"]] = score.get("header_totals")
            # Per fire, not once. The earlier "reported once, from fire 1" rested on
            # the claim that rates are a property of the image, not of the fire.
            # DISPROVED on pin a72a4a26 (same image, same invocation): fire 1
            # measured crops_row_short 0 of 10 and needs_review 3 of 10; fire 2
            # measured 1 of 10 and 4 of 10, and fire 2 was the fire that lost
            # parts (513/522). A fire with no "rates" key (images before PR #35)
            # maps to None: unavailable, never a zero.
            rates_by_fire[f["n"]] = score.get("rates") if "rates" in score else None
        if corpus_err or score_err:
            blocking.append(
                f"fire {f['n']}: could not read its own output ({corpus_err or score_err}) "
                f"— see {f['log']}"
            )
        fire_reports.append({
            "n": f["n"], "exit": f["exit"],
            "started_at": f["started_at"], "ended_at": f["ended_at"],
            "elapsed_s": f["elapsed_s"], "log": f["log"], "totals": totals,
            # Per-notice MPN lists. The totals say a fire is red; this says
            # which notice, and it is the only copy that outlives the pod.
            "defects": defects,
            # True in --run mode (the real exit code covered the seal) and in
            # --from-logs with --seal-prefix; False when the seal term could not
            # be evaluated.
            "seal_checked": f.get("seal_checked", True),
            # What the seal measured on this fire, or None when it was not read.
            "seal_totals": seal_totals,
            "seal_error": seal_err,
        })

    # Rates: worst case per flag across the fires that emitted any; None when no
    # fire did (images before PR #35), which is recorded as unavailable.
    _agg = aggregate_rates_across_fires(rates_by_fire)
    rates_available = bool(_agg["fires"])
    rates = _agg if rates_available else None

    # Crop seal: worst case per counter across the fires whose seal JSON was read.
    crop_seal = aggregate_seal_totals(seal_totals_by_fire)

    # (b) Header agreement.
    log_paths = [f["log_path"] for f in fires]
    header_exit, header_stdout = run_header_agreement(base_dir, log_paths)
    parsed_notices, absent_notices, not_measured_notices = parse_header_agreement(header_stdout)
    # RAW verdicts are ADVISORY (ruling 2026-10-26): they feed `unstable_raw`, never
    # a blocking list. Only an ABSENT / NOT MEASURED line (a measurement gap in the
    # plain run) or an unparseable crash still blocks below -- those are "the
    # instrument could not measure", and nothing here turns that into a pass.
    raw_flagged_notices = sorted(n for n, info in parsed_notices.items()
                                 if info["verdict"] in ("DISAGREE", "BLANK"))
    unstable_raw = unstable_raw_rows(parsed_notices)

    if absent_notices or not_measured_notices:
        parts = []
        if absent_notices:
            parts.append(f"{len(absent_notices)} notice(s) ABSENT in >=1 fire "
                          f"({', '.join(absent_notices)})")
        if not_measured_notices:
            parts.append(f"{len(not_measured_notices)} notice(s) NOT MEASURED "
                          f"({', '.join(not_measured_notices)})")
        blocking.append(
            "header agreement: " + "; ".join(parts) + " — an instrument gap, not a "
            "value disagreement; there is no declaration exemption for it "
            "(see header_agreement.log)"
        )
    elif header_exit != 0 and not raw_flagged_notices:
        # Defensive: an exit!=0 with none of the known verdict categories
        # parsed at all (e.g. a crash/traceback) must still block, not pass silently.
        # This is the instrument failing, not the raw reader being unsteady, so the
        # advisory ruling does not reach it.
        blocking.append(
            f"header_agreement exited {header_exit} but produced no parseable "
            f"per-notice verdict — treat as a hard failure (see header_agreement.log)"
        )

    # (c) Identity: collapse (fire 1) + stability (all three).
    #
    # SOURCE OF THE HEADERS. Preferred: the `written_header` each fire recorded in its
    # own corpus JSON. Fallback: recovering them from the fire's stdout. The fallback is
    # kept because a report may be scored over logs from an image that predates the
    # recording, and losing the identity check entirely at those pins would be worse
    # than parsing print output. Which source was used is reported, because the two are
    # NOT equivalent in fidelity — see `headers_from_corpus`. All-or-nothing per fire
    # set, deliberately: mixing a recorded header for one fire with a log-recovered one
    # for another would compare two different derivations and call the difference
    # instability.
    fires_by_n = {f["n"]: f for f in fires}
    from_corpus = {n: headers_from_corpus(corpus_by_fire.get(n)) for n in fires_by_n}
    if all(from_corpus.values()):
        headers_by_fire = from_corpus
        identity_source = "corpus_json"
    else:
        headers_by_fire = {n: hdr_agreement.headers_from_log(f["log_path"])
                            for n, f in fires_by_n.items()}
        identity_source = "fire_log"
    coverage = bytes_coverage(corpus_by_fire)
    blocking.extend(check_same_bytes(corpus_by_fire))
    blocking.extend(check_declared_bytes(corpus_by_fire, pcn_score.load_corpus()))
    for n, headers in headers_by_fire.items():
        if not headers:
            blocking.append(
                f"fire {n} ({fires_by_n[n]['log']}, headers via {identity_source}) "
                f"yielded no header at all — treated as an error, not an empty pass"
            )
    identity_records = build_identity_records(headers_by_fire)
    collapse = compute_collapse(identity_records)
    all_filenames = sorted(set().union(*[set(h) for h in headers_by_fire.values()]) or set())
    identity_half_unstable, revision_half_unstable, identity_moving_fields = compute_stability(
        identity_records, all_filenames)

    # (b') The BLOCKING header arm: the WRITTEN values, compared across the fires. Uses
    # `from_corpus` (the recorded written_header per fire) even when identity fell back
    # to the logs: the written arm never reads a log, and an image with no recording
    # is reported as such rather than compared on a different derivation.
    expected_files = (set().union(*[set(c) for c in corpus_by_fire.values()])
                      if corpus_by_fire else set())
    written = compare_written_headers(from_corpus, expected=expected_files)

    # (d) The declaration rule.
    d_blocking, d_exempted = apply_declaration_rule(
        [], identity_half_unstable, corpus_by_fire, identity_moving_fields)
    blocking.extend(d_blocking)
    exempted.extend(d_exempted)
    w_blocking, w_exempted = apply_written_arm(written, corpus_by_fire)
    blocking.extend(w_blocking)
    exempted.extend(w_exempted)

    # (e) Header correctness against ground truth — see check_header_correctness
    # for why agreement (b) cannot answer this.
    header_correctness, h_blocking, h_exempted = check_header_correctness(
        header_totals_by_fire, corpus_by_fire)
    blocking.extend(h_blocking)
    exempted.extend(h_exempted)

    # (f) Image identity — the VOID term. Evaluated LAST and overriding both
    # other verdicts: see check_image_identity for why a mismatch is neither
    # a pass nor a fail.
    image_identity = check_image_identity(
        os.environ.get("DOC_TOOLS_IMAGE") or None, expectations, identity_mode)

    verdict = "pass" if (fires_ok and not blocking) else "fail"
    if image_identity["void_reasons"]:
        verdict = "void"
    # By the 2026-10-26 ruling a RAW-only disagreement no longer blocks a pin: what
    # blocks is the written arm plus the identity arm. `header_exit` therefore left this
    # expression; the written arm's findings (no exemptions here, like every term of the
    # strict view) took its place. Nothing else in the expression changed.
    written_unsettled = bool(written["disagreements"] or written["blank_rows"]
                             or written["absent"] or written["no_written"])
    strict_verdict = "pass" if (
        fires_ok and not written_unsettled and not identity_half_unstable
        # A void report has no strict verdict either: both views describe a
        # score, and a score about the wrong image is not a stricter score.
        and not image_identity["void_reasons"]
        # No exemptions in the strict view, so a declared notice whose header is
        # wrong against the page still counts here.
        and not header_correctness.get("failing_notices")
    ) else "fail"

    report = {
        "schema": 1,
        "verdict": verdict,
        "strict_verdict": strict_verdict,
        "generated_at": _utcnow_iso(),
        "measured_image": os.environ.get("DOC_TOOLS_IMAGE") or None,
        # `rolled` (the chart pins it and pods run it) or `pre_roll` (built,
        # measured, pinned by nothing yet). ABSENT in every report written
        # before 2026-10-27, and absent means `rolled` -- see
        # `resolve_identity_mode` for why the absent case defaults and an
        # unknown one does not.
        "identity_mode": identity_mode,
        "measured_pin_note": os.environ.get("DOC_TOOLS_PIN_NOTE") or None,
        # WHICH comparisons ran, and what each one found. `checked: false`
        # means none ran — a report that was never reconciled with the chart
        # or the pods, which is the state the 2026-10-02 hand-run report was
        # in when it became the committed authority.
        "image_identity": image_identity,
        "fires": fire_reports,
        "rates_available": rates_available,
        # The AGGREGATE (worst case per flag, `summarize_rates`-compatible
        # `rates` sub-dict), with per-fire detail in `rates_by_fire`.
        "rates": rates,
        "rates_by_fire": rates_by_fire,
        # THE CROP SEAL, which is the term that has actually been failing: three
        # fires on pin sha256:85ad4c9d exited 1 on `repaired_cut_tables` alone while
        # fire 1 scored 522/522 parts. Worst case per counter plus per-fire detail;
        # `fires_missing` names any fire whose seal was not read, which is NOT the
        # same as a fire that measured zero. Additive to schema 1 — a consumer that
        # does not know this key is unaffected, and one that does must treat an
        # absent key (an older report) as unmeasured rather than clean.
        "crop_seal": crop_seal,
        # THE CORPUS THIS WAS MEASURED AGAINST, copied from the `_corpus` block of
        # pcn_ground_truth.json (which pcn_corpus_run.check_corpus_enumeration
        # asserts TARGETS against at startup). A score is a fraction and a report
        # that carries only the numerator cannot be compared with the next one:
        # "898/898" means something different the day a tenth notice is ingested.
        # Eight documents is the corpus until production traffic adds to it, and
        # this is the copy a reader of the report sees.
        "corpus": pcn_score.load_corpus(),
        "header_correctness": header_correctness,
        # The PLAIN-MODE (raw model output) run. `exit` is still measured and still
        # recorded; `blocks` says outright that it does not decide the verdict.
        "header_agreement": {
            "exit": header_exit,
            "blocks": False,
            "notices": parsed_notices,
            "absent": absent_notices,
            "not_measured": not_measured_notices,
        },
        # ADVISORY: the raw reader rotating between forms. Never blocks.
        "unstable_raw": unstable_raw,
        # THE BLOCKING header arm: written values compared across the fires.
        "written_agreement": {
            "verdicts": written["verdicts"],
            "disagreements": [list(d) for d in written["disagreements"]],
            "blank_rows": [{"notice": fn, "field": f,
                            "seen": {str(n): v for n, v in seen.items()},
                            "blank_fires": blank}
                           for fn, f, seen, blank in written["blank_rows"]],
            "absent": [list(a) for a in written["absent"]],
            "no_written": [list(a) for a in written["no_written"]],
            "unrecorded": written["unrecorded"],
        },
        "identity": {
            # Which derivation the identity numbers below came from, and whether the
            # fires were proved to have read the same bytes. A consumer that treats
            # "fire_log" as equivalent to "corpus_json" is overstating the evidence.
            "source": identity_source,
            # True only when EVERY scored notice was hashed by EVERY fire; the detail
            # below names the gaps, because a partial check is not a verified one.
            "bytes_checked": coverage["complete"],
            "bytes_coverage": coverage,
            "filenames": collapse["filenames"],
            "distinct_notices": collapse["distinct_notices"],
            "collapses": collapse["collapses"],
            "incomplete_identity": collapse["incomplete_identity"],
            "identity_half_unstable": identity_half_unstable,
            # Which of {mfr, doc_id} actually moved, per notice. The declaration rule
            # keys on this: a reason naming the other one exempts nothing. Both are
            # listed when identity could not be FORMED in some fire.
            "identity_moving_fields": {k: list(v)
                                       for k, v in sorted(identity_moving_fields.items())},
            "revision_half_unstable": revision_half_unstable,
        },
        "blocking": blocking,
        "exempted": exempted,
    }
    return report, header_stdout


# --------------------------------------------------------------------------
# Markdown report.

def _render_crop_seal_block(block):
    """The crop-seal block as plain text.

    Hand-rolled rather than reused from pcn_crop_seal.render(): that renderer takes a
    whole `{by_notice, totals}` seal document for ONE fire, and this is an aggregate
    over fires that has no `by_notice`. The per-notice detail stays in each fire's
    seal JSON next to its log; what belongs in the authority artifact is which counter
    decided the verdict and whether the fires agreed on it.
    """
    if not isinstance(block, dict) or not block.get("fires"):
        missing = (block or {}).get("fires_missing") or []
        tail = (f" (fires not read: {', '.join('f%s' % k for k in missing)})"
                if missing else "")
        return ("CROP SEAL  not observed — no fire's seal JSON was read" + tail
                + "\n  An unread seal is UNMEASURED, not clean: the gate's exit term "
                  "could not be\n  checked from this report. Pass --seal-prefix in "
                  "--from-logs mode.")
    fires = block["fires"]
    totals = block.get("totals") or {}
    by_fire = block.get("by_fire") or {}
    names = ", ".join(f"f{k}" for k in fires)
    lines = [f"CROP SEAL  (MAXIMA across {len(fires)} fire(s): {names})"]
    if block.get("fires_missing"):
        lines.append("  fires NOT read: "
                     + ", ".join(f"f{k}" for k in block["fires_missing"])
                     + "  (unmeasured, not zero)")
    if not block.get("agreement", True):
        lines.append("  fires DISAGREE on at least one counter — see per-fire below")
    for counter in SEAL_COUNTERS:
        per = by_fire.get(counter) or {}
        detail = " ".join(f"f{k}={v}" for k, v in sorted(per.items()))
        # The two gate terms are marked, so a reader does not have to know which of
        # these six numbers is allowed to be nonzero.
        term = "  <- GATE TERM, must be 0" if counter in ("repaired_cut_tables",
                                                          "errors") else ""
        lines.append(f"  {counter:<22} {totals.get(counter, 0):>5}{term}")
        if detail:
            lines.append(f"  {'':<22} {'':>5}   per fire: {detail}")
    lines.append("  stored_cut_* counts cuts the repair FIXED — work done, not a "
                 "failure.")
    return "\n".join(lines)


def _render_rates_block(rates_available, rates):
    """The rates block, rendered by `doc_tools.utils.ingest_rates.render_rates` — the
    SAME function the run log uses.

    Not a second renderer, deliberately. `summarize_rates` returns a nested shape
    (`{documents, errors, not_applicable, rates: {flag: {count, denominator}},
    chunk_tally}`), and a hand-rolled walk over it here would be a second place that has
    to know that shape. The earlier version of this function did exactly that, by
    iterating the top-level keys and printing each value's repr: it produced lines like
    "- `rates`: {'needs_review': {'count': 3, ...}}" and, worse, would have printed
    `chunk_tally: None` rather than the "not observed" that `render_rates` is careful to
    emit — turning a deliberate NOT-OBSERVED into something a reader would read as a
    zero. One renderer, one definition of what the numbers mean.

    The shape check is not defensive padding: this report may be produced over score
    JSONs written by an OLDER image, and `rates` being present does not prove it is the
    shape this version of `render_rates` expects. An unexpected shape is reported as
    such, with the payload, rather than crashing the gate or being silently reformatted
    into something that looks authoritative.
    """
    if not rates_available or rates is None:
        return (
            "not available — this pin predates PR #35, the commit that starts "
            "emitting `rates` in `score_f{N}.json`. Not printed as a zero."
        )
    if isinstance(rates, dict) and isinstance(rates.get("rates"), dict) and "fires" in rates:
        return "```" + "\n" + render_rates_across_fires(rates) + "\n" + "```"
    if not isinstance(rates, dict) or "rates" not in rates:
        return (
            "present but not in the shape `summarize_rates` produces (no `rates` key) "
            "— reported verbatim rather than reformatted:\n\n```\n"
            f"{json.dumps(rates, indent=2, default=str)}\n```"
        )
    return "```\n" + render_rates(rates) + "\n```"


def _render_corpus_block(corpus):
    """The denominator, stated in the report itself.

    A report that gives only a numerator cannot be compared with the next one:
    `898/898` means a different thing the day a tenth notice is ingested. The
    enumeration is copied from ground truth rather than recomputed here, so
    there is one definition of what the corpus is.
    """
    out = ["## Corpus measured against", ""]
    if not corpus:
        out.append("**NOT STATED** — the ground truth this was scored against "
                   "carries no `_corpus` block, so the denominator below is "
                   "whatever that file happened to contain. Not comparable with "
                   "a report that states its corpus.")
        return "\n".join(out)
    out += [
        f"- distinct documents: **{corpus.get('distinct_documents')}**",
        f"- scored entries (filenames): **{corpus.get('scored_entries')}**",
        f"- harness parts: **{corpus.get('gt_parts')}**, "
        f"distinct parts: **{corpus.get('distinct_parts')}**",
        "",
        corpus.get("statement", ""),
    ]
    # Read by name, so renaming the key in the ground-truth file silently drops
    # this paragraph from every published report. It was `nine_vs_eight` until the
    # 2026-10-10 widening made that name state the wrong numbers; the new name
    # carries none, so it does not need renaming again.
    note = corpus.get("source_sha256_rekey_note") or corpus.get("duplicate_pair_note") or corpus.get("nine_vs_eight")
    if note:
        out += ["", note]
    return "\n".join(out)


def _render_header_correctness_block(block):
    """(e) in the report: correct against the page, not merely stable."""
    out = ["## Header correctness (against ground truth)", ""]
    if not block:
        out.append("**NOT PRESENT** — this report was produced by a gate that did "
                   "not check header correctness.")
        return "\n".join(out)
    if not block.get("observed"):
        out.append(f"**NOT SCORED** — {block.get('reason', 'no header_totals')}")
        return "\n".join(out)
    out += ["| fire | exact/scored | clean | pending |", "|---|---|---|---|"]
    for n, f in sorted(block.get("fires", {}).items()):
        out.append(f"| {n} | {f.get('exact')}/{f.get('fields_scored')} | "
                   f"{f.get('clean')} | {', '.join(f.get('pending') or []) or '—'} |")
    out.append("")
    if block.get("failing_notices"):
        out.append("failing notices: " + ", ".join(block["failing_notices"])
                   + " — see Blocking/Exempted for the field and the class of "
                     "failure. A `distractor` is a value ground truth names and "
                     "explains; agreement across fires cannot detect one.")
    else:
        out.append("every established header field matched the page in every fire.")
    return "\n".join(out)


def _render_defects_block(report):
    """Per-notice defects, per fire. The block whose absence made a red run undiagnosable."""
    lines = [
        "Which notice lost what. A clean fire contributes nothing here.",
        "",
        "THE ABSENCE OF THIS BLOCK IS WHY THE 2026-10-01 RED COULD NOT BE "
        "DIAGNOSED: fire 3 scored 890/898 while fires 1 and 2 scored 898/898 on "
        "verified-identical source bytes, the report carried per-fire TOTALS "
        "only, and the breakdown died with the pod. Totals say a run is red; "
        "this says where.",
        "",
    ]

    unreadable = [e["n"] for e in report["fires"] if e.get("defects") is None]
    with_defects = [e for e in report["fires"] if e.get("defects")]

    if unreadable:
        lines.append(
            "- fire(s) " + ", ".join(str(n) for n in unreadable) +
            ": **no per-notice data**. That fire's score JSON could not be read, "
            "or was written by an image predating `per_notice`. Not a clean "
            "result -- an unmeasured one; see the echoed log below."
        )
        lines.append("")

    if not with_defects:
        if not unreadable:
            lines.append("No notice in any fire is missing a part, carries a spurious "
                         "one, or emitted a malformed one.")
        return "\n".join(lines)

    for entry in with_defects:
        defects = entry["defects"]
        totals = entry.get("totals") or {}
        lines.append(f"### fire {entry['n']}")
        lines.append("")
        lines.append("| notice | exact/count | missing | spurious | malformed | error |")
        lines.append("|---|---|---|---|---|---|")
        for fn in sorted(defects):
            rec = defects[fn]
            lines.append(
                f"| `{fn}` | {rec.get('exact')}/{rec.get('count')} | "
                f"{len(rec['missing'])} | {len(rec['spurious'])} | "
                f"{len(rec['malformed'])} | {rec.get('error') or ''} |"
            )
        lines.append("")
        for fn in sorted(defects):
            rec = defects[fn]
            for kind in DEFECT_KINDS:
                if rec[kind]:
                    listed = ", ".join(f"`{mpn}`" for mpn in rec[kind])
                    lines.append(f"- `{fn}` {kind} ({len(rec[kind])}): {listed}")
        lines.append("")

        # The per-notice lists and the headline totals are computed by the same
        # scorer over the same data, so they cannot legitimately disagree. If
        # they do, one of them is wrong and the report must say so rather than
        # presenting both as if either could be relied on.
        for kind in DEFECT_KINDS:
            summed = sum(len(rec[kind]) for rec in defects.values())
            stated = totals.get(kind)
            if stated is not None and summed != stated:
                lines.append(
                    f"**THE INSTRUMENT DISAGREES WITH ITSELF on fire {entry['n']}:** "
                    f"the per-notice lists account for {summed} {kind} part(s), the "
                    f"fire's totals say {stated}. Trust neither number until that is "
                    f"explained."
                )
                lines.append("")

    return "\n".join(lines).rstrip()


def _render_log_preservation_block(report):
    """Where to find each fire log, given that the files die with the pod."""
    lines = [
        "A fire log is written into the gate's working directory, which in the "
        "cluster is a path inside the pod. When the Job fails the pod is kept "
        "but refuses `exec` (\"cannot exec into a container in a completed "
        "pod\"), so those files become unreachable while `kubectl logs` keeps "
        "working -- which is exactly how fire 3's log was lost on 2026-10-01. "
        "So whenever the verdict is not `pass`, EVERY fire log is echoed into "
        "this run's own stdout, ahead of this report. Not just the fire that "
        "looks guilty: on 2026-10-01 all three fires exited 0 and the Job "
        "failed on the gate's own verdict, and a header-caused red leaves the "
        "header values in the logs and nowhere else.",
        "",
        "Retrieve one with:",
        "",
        "```",
        "kubectl logs job/<the failed job> | sed -n '/BEGIN fire 3 log/,/END fire 3 log/p'",
        "```",
        "",
        "| fire | log | bytes | echoed to stdout |",
        "|---|---|---|---|",
    ]
    for entry in report["fires"]:
        size = entry.get("log_bytes")
        cap = entry.get("log_echo_cap_bytes")
        if entry.get("log_echoed"):
            echoed = "yes"
            if size is not None and cap is not None and size > cap:
                echoed = f"yes, last {cap} bytes"
        else:
            echoed = "no — the verdict passed and this fire was measured"
        lines.append(
            f"| {entry['n']} | `{entry.get('log')}` | "
            f"{'unknown' if size is None else size} | {echoed} |"
        )
    return "\n".join(lines)


def _render_image_identity(identity):
    """The identity comparisons, INCLUDING the fact that none ran.

    "Reconciled against nothing" and "reconciled and agreed" must not render
    the same. The silent-inert failure mode is the one this repo keeps
    re-learning: `source_key` checks read as "verified" across a set where
    they were inert on half the manifests, and the committed authority report
    named a branch image for days because nothing ever compared it to the
    chart. So an unreconciled report says so, in its own section, above the
    scores.
    """
    if not identity:
        return ("### Identity\n\nNot recorded — this report predates the "
                "image-identity check (it carries no `image_identity` block), so "
                "whether it measured the declared image is **unknown**.")
    out = ["### Identity", ""]
    pre_roll = identity.get("mode") == "pre_roll"
    if pre_roll:
        out.append(
            "**PRE-ROLL FIRE.** This report measures an image that was BUILT "
            "and that no chart pins; no pod was running it. It is a "
            "measurement of that image's own extraction code against the "
            "model hosts, which is the whole of what this gate ever "
            "measures — but it is NOT a statement about the deployed "
            "system, and it becomes the authority for this digest only when "
            "a pin bump carrying it merges."
        )
        out.append("")
        out.append(
            "The digest below is **self-declared**: it is what whoever "
            "created the Job said the image was, and this process cannot "
            "check it — the gate's ServiceAccount has no Role and the "
            "container carries no kubectl, so it cannot read its own "
            "`imageID`. Two things outside this report corroborate it, and "
            "a reader who needs the identity proven should look at them "
            "rather than at this section: `scripts/pcn_gate_prefire.py` "
            "compares the pod's `imageID` to the candidate before the run "
            "spends its GPU time, and the CI guard compares this report's "
            "`measured_image` to the digest the chart pins."
        )
        out.append("")
    if not identity.get("checked"):
        out.append(
            "**NOT RECONCILED.** No expectation was supplied (`--expect-image` / "
            "`PCN_GATE_EXPECT_IMAGE`), so this run never compared the image it "
            "measured against the chart's pin or the pods' `imageID`."
        )
        out.append("")
        if pre_roll:
            out.append(
                "In a pre-roll fire that is the EXPECTED state and not a "
                "defect: the chart pins the OLD image, so a `chart=` "
                "expectation would void this report by construction, and "
                "there is no pod to read an `imageID` from. It is still the "
                "absence of an identity check and not a pass of one — what "
                "stands in for it is named above."
            )
        else:
            out.append(
                "That is not a pass of the identity check — it is the "
                "absence of one, and the verdict below is only as "
                "trustworthy as the unverified claim that `DOC_TOOLS_IMAGE` "
                "is the right image."
            )
        return "\n".join(out)
    out.append(f"- measured digest: `{identity.get('measured_digest') or 'none — not a digest'}`")
    out.append("")
    out.append("| expected by | digest | result |")
    out.append("|---|---|---|")
    for c in identity.get("comparisons", []):
        out.append(
            f"| {c['source']} | `{c.get('expected_digest') or c['expected']}` | "
            f"**{c['result']}** |")
    return "\n".join(out)


def render_markdown(report, gate_dir, command_str, log_paths):
    lines = []
    date = report["generated_at"][:10]
    lines.append(f"# PCN Corpus Gate Report — {date}")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if report["verdict"] == "void":
        # VOID COMES FIRST, and deliberately does NOT print what the
        # pass/fail terms found. A reader who sees "898/898" beside "VOID"
        # will remember the number and forget the void: that is how the
        # 2026-10-01 green check became evidence about a digest that never
        # reached main. The score is still in the JSON and in the per-fire
        # table below; what is withheld here is the SENTENCE that would
        # read as a verdict.
        lines.append("**VOID — this is not a verdict.**")
        lines.append("")
        lines.append(
            "The image this run measured is not the image it was supposed to "
            "measure, so neither a pass nor a fail can be read off it. The "
            "scores below describe *some* image; they are not evidence about "
            "the pin in the chart. Re-run the gate against the declared image."
        )
        lines.append("")
        for reason in report["image_identity"]["void_reasons"]:
            lines.append(f"- {reason}")
    elif report["verdict"] == "pass":
        reason = ("all three fires exited 0; every header disagreement / identity "
                   "instability, if any, was declared (needs_review=True) in all "
                   "three fires") if report["exempted"] else \
                  "all three fires exited 0, headers agreed, and identity was stable"
        lines.append(f"**PASS** — {reason}.")
    else:
        if not all(f["exit"] == 0 for f in report["fires"]):
            reason = "at least one fire did not exit 0 (parts/crop-seal gate not met)"
        else:
            reason = f"{len(report['blocking'])} blocking condition(s), see Blocking below"
        lines.append(f"**FAIL** — {reason}.")
    lines.append("")
    lines.append(f"Strict verdict (no declaration exemptions): **{report['strict_verdict'].upper()}**")
    lines.append("")
    lines.append("## Image measured")
    lines.append("")
    lines.append(f"- `DOC_TOOLS_IMAGE`: {report['measured_image'] or 'not set'}")
    lines.append(f"- `DOC_TOOLS_PIN_NOTE`: {report['measured_pin_note'] or 'not set'}")
    # `rolled` is stated as well as `pre_roll`, rather than printed only
    # when it is interesting. A section that is silent in the ordinary case
    # teaches a reader that silence means ordinary, and then an older report
    # with no mode at all reads as a rolled fire by the same silence when it
    # is in fact unlabelled.
    lines.append(f"- identity mode: `{report.get('identity_mode') or 'not recorded'}`")
    lines.append("")
    lines.append(_render_image_identity(report.get("image_identity")))
    lines.append("")
    lines.append(_render_corpus_block(report.get("corpus")))
    lines.append("")
    lines.append("## Per-fire results")
    lines.append("")
    lines.append("| fire | exit | elapsed_s | exact/gt | spurious | missing | malformed |")
    lines.append("|---|---|---|---|---|---|---|")
    for f in report["fires"]:
        t = f["totals"]
        if t is None:
            lines.append(f"| {f['n']} | {f['exit']} | {f['elapsed_s']} | ERROR — no output | — | — | — |")
        else:
            lines.append(
                f"| {f['n']} | {f['exit']} | {f['elapsed_s']} | {t['exact']}/{t['gt']} | "
                f"{t['spurious']} | {t['missing']} | {t['malformed']} |"
            )
    lines.append("")
    lines.append("## Crop seal")
    lines.append("")
    lines.append(_render_crop_seal_block(report.get("crop_seal")))
    lines.append("")
    lines.append("## Per-notice defects")
    lines.append("")
    lines.append(_render_defects_block(report))
    lines.append("")
    lines.append("## Rates")
    lines.append("")
    lines.append(_render_rates_block(report["rates_available"], report["rates"]))
    lines.append("")
    wa = report.get("written_agreement")
    if wa is not None:
        lines.append("## Written header agreement (BLOCKS unless declared)")
        lines.append("")
        lines.append("The values each fire WROTE (`written_header` in its corpus JSON), "
                     "compared over doc_type, mfr, pub_date, doc_level_ltb_date. "
                     "`revision` (never blocks) and `doc_id` (identity arm) are not "
                     "compared here.")
        lines.append("")
        lines.append("| notice | verdict |")
        lines.append("|---|---|")
        for fn, v in sorted(wa["verdicts"].items()):
            lines.append(f"| {fn} | {v} |")
        lines.append("")
        for fn, f, vals in wa["disagreements"]:
            lines.append(f"- DISAGREE {fn} `{f}`: "
                         + " | ".join(repr(v).replace("|", BAR_ESCAPE) for v in vals))
        for r in wa["blank_rows"]:
            lines.append(f"- BLANK vs POPULATED {r['notice']} `{r['field']}`: blank in "
                         f"fire(s) {r['blank_fires']}; seen {r['seen']}")
        for fn, missing in wa["absent"]:
            lines.append(f"- ABSENT {fn}: not recorded by fire(s) {missing}")
        for n, fn in wa["no_written"]:
            lines.append(f"- NO written_header: fire {n}"
                         + (f", {fn}" if fn else " (whole fire)"))
        if wa["unrecorded"]:
            lines.append(f"- not recorded by any fire (not blocked here; parts arm / "
                         f"bytes coverage own it): {', '.join(wa['unrecorded'])}")
        lines.append("")
    lines.append("## Raw reader instability (advisory, never blocks)")
    lines.append("")
    lines.append("The raw model output rotated between these forms across the fires. "
                 "The written value (above) is what blocks; a row here with a clean "
                 "written arm is an unsteady reader that the trust logic absorbed. It "
                 "is listed so that stays visible.")
    lines.append("")
    if report.get("unstable_raw"):
        for r in report["unstable_raw"]:
            lines.append(f"- {r['notice']} `{r['field']}`: "
                         + " | ".join(f.replace("|", BAR_ESCAPE) for f in r["forms"]))
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Header agreement (raw plain-mode run; advisory)")
    lines.append("")
    lines.append(f"exit: {report['header_agreement']['exit']} "
                 f"(does not decide the verdict)")
    lines.append("")
    if report["header_agreement"]["notices"]:
        lines.append("| notice | verdict | disagreeing fields |")
        lines.append("|---|---|---|")
        for notice, info in sorted(report["header_agreement"]["notices"].items()):
            # `v` holds the raw printed values, which the instrument separates
            # with " | " -- unescaped, that ends the markdown cell early and
            # shifts every column after it. Not hypothetical: the 2026-10-09 run
            # disagreed on exactly one field, and its printed line holds two bar
            # separators plus a literal newline escape inside the third value, so
            # the row describing the only red in that run is the row that breaks.
            cells = [f"`{k}`: " + v.replace("|", BAR_ESCAPE)
                     for k, v in info["fields"].items()]
            fields = ", ".join(cells) or "—"
            lines.append(f"| {notice} | {info['verdict']} | {fields} |")
        lines.append("")
    if report["header_agreement"]["absent"]:
        lines.append(f"ABSENT (not measured by >=1 fire): {', '.join(report['header_agreement']['absent'])}")
        lines.append("")
    if report["header_agreement"]["not_measured"]:
        lines.append(f"NOT MEASURED: {', '.join(report['header_agreement']['not_measured'])}")
        lines.append("")
    lines.append(_render_header_correctness_block(report.get("header_correctness")))
    lines.append("")
    lines.append("## Identity")
    lines.append("")
    ident = report["identity"]
    lines.append(f"filenames: {ident['filenames']}, distinct_notices: {ident['distinct_notices']}")
    lines.append("")
    lines.append(f"header source: `{ident.get('source', 'fire_log')}`"
                 + ("" if ident.get("source") == "corpus_json" else
                    " (recovered from stdout — this image records no `written_header`)"))
    cov = ident.get("bytes_coverage") or {}
    if cov.get("complete"):
        lines.append(f"same source bytes across fires: verified for all "
                     f"{cov['notices_scored']} notices across {len(cov['fires'])} fires")
    elif cov.get("verified"):
        lines.append(f"same source bytes across fires: verified for "
                     f"{len(cov['verified'])} of {cov['notices_scored']} notices — "
                     f"NOT verified for "
                     + ", ".join(f"`{f}`" for f in cov["unverified"])
                     + " (no `content_hash` from every fire)")
    else:
        lines.append("same source bytes across fires: NOT VERIFIABLE "
                     "(no `content_hash` recorded at this pin)")
    lines.append("")
    lines.append("### Collapses (same notice, multiple files; fire 1)")
    lines.append("")
    if ident["collapses"]:
        for c in ident["collapses"]:
            lines.append(f"- `{c['key']}`: {', '.join(c['files'])}")
    else:
        lines.append("(none)")
    if ident["incomplete_identity"]:
        lines.append("")
        lines.append(f"Incomplete identity (mfr or doc_id missing, fire 1): {', '.join(ident['incomplete_identity'])}")
    lines.append("")
    lines.append("### Identity-half unstable across fires (BLOCKS unless declared)")
    lines.append("")
    _moving = ident.get("identity_moving_fields") or {}
    lines.append(", ".join(
        f"{fn} (`{'/'.join(_moving[fn])}` moved)" if _moving.get(fn) else fn
        for fn in ident["identity_half_unstable"]) or "(none)")
    lines.append("")
    lines.append("### Revision-half unstable across fires (never blocks)")
    lines.append("")
    lines.append(", ".join(ident["revision_half_unstable"]) or "(none)")
    lines.append("")
    lines.append("## Blocking")
    lines.append("")
    if report["blocking"]:
        for b in report["blocking"]:
            lines.append(f"- {b}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Exempted")
    lines.append("")
    if report["exempted"]:
        for e in report["exempted"]:
            lines.append(f"- {e}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## How it was run")
    lines.append("")
    lines.append(f"Command: `{command_str}`")
    lines.append("")
    lines.append("Logs:")
    for p in log_paths:
        lines.append(f"- `{p}`")
    lines.append("")
    lines.append("### Reaching a fire log after the pod is gone")
    lines.append("")
    lines.append(_render_log_preservation_block(report))
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------

def dated_report_name(generated_at):
    """Archive filename for one run's markdown report.

    PER RUN, NOT PER DAY -- this used to be `report-{generated_at[:10]}.md`,
    and the date alone is not a run identity. The second run of a UTC day
    silently OVERWROTE the first one's archived report, and git shows that as
    an ordinary modification, so nothing anywhere says a measurement was
    destroyed. `main` carries the proof: `report-2026-10-01.md` and
    `report-2026-10-01-rereduced.md` are two different runs of the same day,
    and the second survives only because a human noticed and renamed it by
    hand. A third run that night overwrote the file again on the publish
    branch, which is how this was found.

    `latest.json` SHOULD keep overwriting -- it is the pointer the CI guard
    reads and "latest" is its whole contract. The dated markdown is the
    archive, and an archive that drops a run defeats its only purpose.

    The colons of the ISO timestamp are stripped because they are illegal in
    Windows filenames, and the rest of the ISO form is kept so the names still
    sort chronologically as plain text. `scripts/pcn_gate_publish.py` picks the
    file up through its `report-*.md` glob, so the longer name needs no change
    there.
    """
    return "report-%s.md" % generated_at.replace(":", "")


def build_parser():
    """The CLI, as its own function so a default can be ASSERTED.

    Extracted from `main` for one reason: `--identity-mode` has to default
    to None so that PCN_GATE_IDENTITY_MODE is reachable, and a default
    nobody can read is a default nobody can test. The pre-roll path
    overrides ENV, not argv -- it copies the CronJob command verbatim --
    so if this flag ever acquires a non-None default the override goes
    inert and every pre-roll report is labelled `rolled`.
    """
    parser = argparse.ArgumentParser(
        description="Score the PCN/PDN corpus harness as a release gate: three "
                     "sequential fires, header agreement, and notice identity "
                     "stability, reduced to one pass/fail verdict.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true",
                       help="Run three fires now, then score them (default).")
    mode.add_argument("--from-logs", metavar="DIR",
                       help="Score an already-completed fire set in DIR instead "
                            "of running new fires.")
    parser.add_argument("--log-prefix", default="fire",
                         help="--from-logs only: log filename prefix (default: fire).")
    parser.add_argument("--corpus-prefix", default="corpus_f",
                         help="--from-logs only: corpus JSON filename prefix (default: corpus_f).")
    parser.add_argument("--score-prefix", default="score_f",
                         help="--from-logs only: score JSON filename prefix (default: score_f).")
    parser.add_argument("--seal-prefix", default=None,
                         help="--from-logs only: crop-seal JSON filename prefix (e.g. seal_f). "
                              "Supply it whenever the seal files exist: without it the "
                              "reconstructed fire exit code cannot evaluate the crop-seal "
                              "term and every fire is reported seal_checked: false.")
    parser.add_argument("--out-dir", default=None,
                         help="Where to write latest.json and the dated markdown. "
                              "USE THIS FOR ANY DIAGNOSTIC RUN. The default is "
                              "docs/corpus-gate, which is the report the CI guard reads "
                              "as the authority for the pinned image — a --from-logs run "
                              "over fixture logs will otherwise silently replace a real "
                              "measurement with a synthetic one (measured_image: null), "
                              "and the overwrite is invisible until someone reads git "
                              "status. Overrides PCN_GATE_REPORT_DIR.")
    parser.add_argument("--expect-image", action="append", default=None,
                         metavar="SOURCE=REF",
                         help="What DOC_TOOLS_IMAGE is SUPPOSED to be, as "
                              "source=reference (repeatable, or comma-separated): "
                              "e.g. --expect-image chart=ghcr.io/o/doc-tools@sha256:... "
                              "--expect-image pods=ghcr.io/o/doc-tools@sha256:... . "
                              "Any mismatch makes the report VOID (verdict: void, "
                              "exit 2) rather than a fail: a score of the wrong "
                              "image is not a worse score, it is not a score. "
                              "Comparison is on the sha256 digest, so registry "
                              "spelling differences do not matter and a tag-only "
                              "reference on either side is reported uncomparable "
                              "(also void). Defaults to PCN_GATE_EXPECT_IMAGE. "
                              "Supplying nothing leaves the run UNRECONCILED, "
                              "which the report says in as many words -- it is "
                              "not a pass of this check.")
    parser.add_argument("--identity-mode", default=None,
                         choices=IDENTITY_MODES,
                         help="What the measured image IS, relative to the "
                              "chart: `rolled` (default) means the chart pins "
                              "it and the pods run it; `pre_roll` means it was "
                              "BUILT and measured before anything pins it, so "
                              "a pin-bump PR can carry a report for the digest "
                              "it lands. It changes no score and no verdict -- "
                              "it is a LABEL on the report, and the only thing "
                              "that tells a later reader whether the measured "
                              "image was one any pod was running. In `pre_roll` "
                              "the digest is self-declared by whoever created "
                              "the Job (this process cannot read its own: no "
                              "Role, no kubectl), and the report says so. "
                              "Defaults to PCN_GATE_IDENTITY_MODE, then "
                              "`rolled`; an unknown value is refused rather "
                              "than defaulted. Set by "
                              "scripts/pcn_gate_prefire.py, which is also what "
                              "corroborates the digest, from the pod imageID, "
                              "before the run spends its GPU time.")
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    # The pods' imageID cannot be read from inside the gate's Job: its
    # ServiceAccount has no Role (there is no role.yaml in
    # charts/doc-tools/templates/) and the container carries no kubectl. So
    # expectations are SUPPLIED -- by the chart for its own pin, and by
    # whoever can read a pod for the imageID -- never fetched. See
    # check_image_identity.
    expectations = parse_expectations(
        args.expect_image
        if args.expect_image is not None
        else [os.environ.get("PCN_GATE_EXPECT_IMAGE", "")]
    )

    # Validated here, before any fire runs, so a typo costs nothing instead of
    # 2.5 hours of vision calls and a mislabelled report.
    identity_mode = resolve_identity_mode(
        args.identity_mode
        if args.identity_mode is not None
        else os.environ.get("PCN_GATE_IDENTITY_MODE")
    )

    if args.from_logs:
        base_dir = args.from_logs
        fires = collect_from_logs(base_dir, args.log_prefix, args.corpus_prefix,
                                   args.score_prefix, args.seal_prefix)
        command_str = (
            f"{sys.executable} scripts/pcn_corpus_gate.py --from-logs {base_dir} "
            f"--log-prefix {args.log_prefix} --corpus-prefix {args.corpus_prefix} "
            f"--score-prefix {args.score_prefix}"
            + (f" --seal-prefix {args.seal_prefix}" if args.seal_prefix else "")
        )
    else:
        base_dir = os.environ.get("PCN_GATE_DIR", "/tmp/pcn-gate")
        fires = run_fires(base_dir)
        command_str = f"{sys.executable} scripts/pcn_corpus_gate.py --run"

    report, header_stdout = score_fires(
        base_dir, fires, expectations, identity_mode)

    # Report dir default is docs/corpus-gate, relative to repo root. ^docs/ is
    # the ENTIRE paths-ignore list on the build workflow, so a committed report
    # there does NOT trigger the ~29-minute multi-arch image build. That is the
    # reason for this location, not a filing convenience.
    #
    # --out-dir wins over the env var, which wins over the default. The flag
    # exists because the default is the AUTHORITY the CI guard reads: a
    # diagnostic --from-logs run over fixture logs writes a synthetic report
    # (measured_image: null, seal_checked: false) straight over a real pinned
    # measurement, and nothing in the output says so. That happened while this
    # instrument was being built and was caught only by reading git status.
    report_dir = (args.out_dir
                  or os.environ.get("PCN_GATE_REPORT_DIR")
                  or "docs/corpus-gate")
    if not os.path.isabs(report_dir):
        report_dir = os.path.join(REPO_ROOT, report_dir)
    os.makedirs(report_dir, exist_ok=True)

    log_paths = [f["log_path"] for f in fires]

    # Annotated BEFORE rendering, because the report has to be able to tell a
    # reader that the log they want is in `kubectl logs` and not in a file.
    tail_bytes = log_tail_bytes()
    annotate_log_preservation(report, fires, tail_bytes)
    markdown = render_markdown(report, base_dir, command_str, log_paths)

    latest_path = os.path.join(report_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    dated_path = os.path.join(report_dir, dated_report_name(report["generated_at"]))
    with open(dated_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    # ORDER IS LOAD-BEARING: the echoed logs go out BEFORE the report, so that
    # if the kubelet rotates this container's log the thing evicted is the
    # reproduced log and not the report. The report is also committed to git by
    # the publisher; the echoed log exists nowhere else.
    for chunk in preserved_log_dumps(report, fires, tail_bytes):
        print(chunk)

    print(markdown)

    # 2, NOT 1. A void report and a failing report call for opposite
    # actions -- re-run against the right image vs. go fix an extraction
    # defect -- and a caller that can only see "non-zero" will treat the
    # first as the second. The publisher and the CronJob both read this
    # status, so the distinction has to live in the number.
    if report["verdict"] == "void":
        return 2
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
