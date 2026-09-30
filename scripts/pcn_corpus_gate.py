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
import pcn_header_agreement as hdr_agreement  # noqa: E402

from doc_tools.utils import notice_identity  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE_COUNT = 3

# --------------------------------------------------------------------------
# Per-notice verdict / field lines, as printed by pcn_header_agreement.compare()
# in PLAIN mode (no --written): this gate never runs --written (see (b) below).
#   "<notice>                                   agree"
#   "<notice>                                   DISAGREE"
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
NOTICE_VERDICT_RE = re.compile(r"^(?P<notice>\S.*?)\s{2,}(?P<verdict>agree|DISAGREE)\s*$")
NOTICE_ABSENT_RE = re.compile(r"^(?P<notice>\S.*?)\s{2,}ABSENT\s*$")
NOTICE_NOT_MEASURED_RE = re.compile(r"^(?P<notice>\S.*?)\s{2,}NOT MEASURED\s*$")
FIELD_LINE_RE = re.compile(r"^ {6}(?P<field>\S+) +(?P<vals>.+)$")


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
    # PLAIN MODE ONLY, never --written: the --written replay cannot build the
    # vision witness the product consults and declines for the degraded
    # notice, so a --written comparison would measure the pre-witness trust
    # logic, not what the product does. The plain comparison is what this
    # gate blocks on.
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


# --------------------------------------------------------------------------
# (c) Identity — collapse (within one fire) and stability (across all three).

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
    identity_half_unstable = []
    revision_half_unstable = []
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
            continue
        components = [notice_identity.parse_notice_key(k) for k in keys]
        mfr_doc_id_pairs = {(c[0], c[1]) for c in components}
        if len(mfr_doc_id_pairs) > 1:
            identity_half_unstable.append(fn)
        else:
            revision_half_unstable.append(fn)
    return sorted(identity_half_unstable), sorted(revision_half_unstable)


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
# unstable (c), is exempt from blocking only if needs_review == True for that
# notice in ALL THREE corpus_f{N}.json records. There is no exemption at all
# for an ABSENT or NOT MEASURED header-agreement condition (an instrument
# gap, not a declared, handled value conflict) and none for
# revision_half_unstable (which never blocks in the first place, per (c)).

def needs_review_in_all_fires(corpus_by_fire, notice):
    return all(
        bool((corpus_by_fire.get(n, {}).get(notice) or {}).get("needs_review"))
        for n in (1, 2, 3)
    )


def apply_declaration_rule(disagree_notices, identity_half_unstable, corpus_by_fire):
    blocking = []
    exempted = []
    for notice in sorted(disagree_notices):
        if needs_review_in_all_fires(corpus_by_fire, notice):
            exempted.append(
                f"{notice}: header disagreement exempted — needs_review=True in all three fires"
            )
        else:
            blocking.append(
                f"{notice}: header fields disagree across fires and needs_review is not "
                f"True in all three fires (undeclared silent write) — see header_agreement.log"
            )
    for notice in sorted(identity_half_unstable):
        if needs_review_in_all_fires(corpus_by_fire, notice):
            exempted.append(
                f"{notice}: identity-half instability (mfr/doc_id differ across fires) "
                f"exempted — needs_review=True in all three fires"
            )
        else:
            blocking.append(
                f"{notice}: identity half (mfr/doc_id) is unstable across fires and "
                f"needs_review is not True in all three fires"
            )
    return blocking, exempted


# --------------------------------------------------------------------------
# Scoring — assembles (a)-(d) into the report dict. Same path for both modes.

def score_fires(base_dir, fires):
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
    rates = None
    rates_available = False
    for idx, f in enumerate(fires):
        corpus, corpus_err = _load_json_soft(f["corpus_path"])
        score, score_err = _load_json_soft(f["score_path"])
        corpus_by_fire[f["n"]] = corpus or {}
        totals = None
        if score is not None:
            totals = score.get("totals")
            # rates: singular in the report, not one per fire. All three fires run
            # the same pinned image in one gate invocation, so rates availability
            # (and the rates themselves) are a property of the image, not of which
            # fire happened to run. Reported once, from fire 1.
            if idx == 0:
                if "rates" in score:
                    rates_available = True
                    rates = score["rates"]
                else:
                    # Images before PR #35 do not emit "rates" at all. Absence is
                    # recorded as rates_available: false, never rendered as a zero.
                    rates_available = False
                    rates = None
        if corpus_err or score_err:
            blocking.append(
                f"fire {f['n']}: could not read its own output ({corpus_err or score_err}) "
                f"— see {f['log']}"
            )
        fire_reports.append({
            "n": f["n"], "exit": f["exit"],
            "started_at": f["started_at"], "ended_at": f["ended_at"],
            "elapsed_s": f["elapsed_s"], "log": f["log"], "totals": totals,
            # True in --run mode (the real exit code covered the seal) and in
            # --from-logs with --seal-prefix; False when the seal term could not
            # be evaluated.
            "seal_checked": f.get("seal_checked", True),
        })

    # (b) Header agreement.
    log_paths = [f["log_path"] for f in fires]
    header_exit, header_stdout = run_header_agreement(base_dir, log_paths)
    parsed_notices, absent_notices, not_measured_notices = parse_header_agreement(header_stdout)
    disagree_notices = sorted(n for n, info in parsed_notices.items()
                               if info["verdict"] == "DISAGREE")

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
    elif header_exit != 0 and not disagree_notices:
        # Defensive: an exit!=0 with none of the three known verdict categories
        # parsed at all (e.g. a crash/traceback) must still block, not pass silently.
        blocking.append(
            f"header_agreement exited {header_exit} but produced no parseable "
            f"per-notice verdict — treat as a hard failure (see header_agreement.log)"
        )

    # (c) Identity: collapse (fire 1) + stability (all three).
    fires_by_n = {f["n"]: f for f in fires}
    headers_by_fire = {n: hdr_agreement.headers_from_log(f["log_path"])
                        for n, f in fires_by_n.items()}
    for n, headers in headers_by_fire.items():
        if not headers:
            blocking.append(
                f"fire {n} log ({fires_by_n[n]['log']}) yielded no NoticeHeader blocks "
                f"at all — treated as an error, not an empty pass"
            )
    identity_records = build_identity_records(headers_by_fire)
    collapse = compute_collapse(identity_records)
    all_filenames = sorted(set().union(*[set(h) for h in headers_by_fire.values()]) or set())
    identity_half_unstable, revision_half_unstable = compute_stability(identity_records, all_filenames)

    # (d) The declaration rule.
    d_blocking, d_exempted = apply_declaration_rule(
        disagree_notices, identity_half_unstable, corpus_by_fire)
    blocking.extend(d_blocking)
    exempted.extend(d_exempted)

    verdict = "pass" if (fires_ok and not blocking) else "fail"
    strict_verdict = "pass" if (
        fires_ok and header_exit == 0 and not identity_half_unstable
    ) else "fail"

    report = {
        "schema": 1,
        "verdict": verdict,
        "strict_verdict": strict_verdict,
        "generated_at": _utcnow_iso(),
        "measured_image": os.environ.get("DOC_TOOLS_IMAGE") or None,
        "measured_pin_note": os.environ.get("DOC_TOOLS_PIN_NOTE") or None,
        "fires": fire_reports,
        "rates_available": rates_available,
        "rates": rates,
        "header_agreement": {
            "exit": header_exit,
            "notices": parsed_notices,
            "absent": absent_notices,
            "not_measured": not_measured_notices,
        },
        "identity": {
            "filenames": collapse["filenames"],
            "distinct_notices": collapse["distinct_notices"],
            "collapses": collapse["collapses"],
            "incomplete_identity": collapse["incomplete_identity"],
            "identity_half_unstable": identity_half_unstable,
            "revision_half_unstable": revision_half_unstable,
        },
        "blocking": blocking,
        "exempted": exempted,
    }
    return report, header_stdout


# --------------------------------------------------------------------------
# Markdown report.

def _render_rates_block(rates_available, rates):
    if not rates_available or rates is None:
        return (
            "not available — this pin predates PR #35, the commit that starts "
            "emitting `rates` in `score_f{N}.json`. Not printed as a zero."
        )
    lines = []
    for k in sorted(rates):
        lines.append(f"- `{k}`: {rates[k]}")
    return "\n".join(lines) if lines else "(empty rates dict)"


def render_markdown(report, gate_dir, command_str, log_paths):
    lines = []
    date = report["generated_at"][:10]
    lines.append(f"# PCN Corpus Gate Report — {date}")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if report["verdict"] == "pass":
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
    lines.append("## Rates")
    lines.append("")
    lines.append(_render_rates_block(report["rates_available"], report["rates"]))
    lines.append("")
    lines.append("## Header agreement")
    lines.append("")
    lines.append(f"exit: {report['header_agreement']['exit']}")
    lines.append("")
    if report["header_agreement"]["notices"]:
        lines.append("| notice | verdict | disagreeing fields |")
        lines.append("|---|---|---|")
        for notice, info in sorted(report["header_agreement"]["notices"].items()):
            fields = ", ".join(f"`{k}`: {v}" for k, v in info["fields"].items()) or "—"
            lines.append(f"| {notice} | {info['verdict']} | {fields} |")
        lines.append("")
    if report["header_agreement"]["absent"]:
        lines.append(f"ABSENT (not measured by >=1 fire): {', '.join(report['header_agreement']['absent'])}")
        lines.append("")
    if report["header_agreement"]["not_measured"]:
        lines.append(f"NOT MEASURED: {', '.join(report['header_agreement']['not_measured'])}")
        lines.append("")
    lines.append("## Identity")
    lines.append("")
    ident = report["identity"]
    lines.append(f"filenames: {ident['filenames']}, distinct_notices: {ident['distinct_notices']}")
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
    lines.append(", ".join(ident["identity_half_unstable"]) or "(none)")
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
    return "\n".join(lines)


# --------------------------------------------------------------------------

def main(argv):
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
    args = parser.parse_args(argv)

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

    report, header_stdout = score_fires(base_dir, fires)

    # Report dir default is docs/corpus-gate, relative to repo root. ^docs/ is
    # the ENTIRE paths-ignore list on the build workflow, so a committed report
    # there does NOT trigger the ~29-minute multi-arch image build. That is the
    # reason for this location, not a filing convenience.
    report_dir = os.environ.get("PCN_GATE_REPORT_DIR", "docs/corpus-gate")
    if not os.path.isabs(report_dir):
        report_dir = os.path.join(REPO_ROOT, report_dir)
    os.makedirs(report_dir, exist_ok=True)

    log_paths = [f["log_path"] for f in fires]
    markdown = render_markdown(report, base_dir, command_str, log_paths)

    latest_path = os.path.join(report_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    dated_path = os.path.join(report_dir, f"report-{report['generated_at'][:10]}.md")
    with open(dated_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(markdown)

    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
