"""Score a PCN corpus run by PART NUMBER IDENTITY, never by count.

WHY THIS EXISTS. The 2026-09-23 run printed `TOTAL 896 / 896` and was recorded
as hitting ground truth exactly. It had not. `PCN23-002.pdf` returned eighteen
parts whose eighteenth was `SYTYD-122HP-1+`, a misread of `SYTX9-122HP-1+`
produced by a table crop cut 47% of the way through the glyphs of its last row.
The real part was missing and a wrong string stood in its place, so the count
balanced and the miss was reported as a pass.

A counting instrument cannot see a substitution: one out, one in, total
unchanged. That makes it worse than no instrument, because it converts a miss
into a pass and does so silently. Scoring here is therefore set comparison
against `pcn_ground_truth.json`, and `len(parts)` is never the score.

Every notice reports four numbers:

    exact     emitted MPNs that are in ground truth
    spurious  emitted MPNs that are NOT in ground truth   <- the SYTYD class
    missing   ground-truth MPNs that were not emitted     <- the SYTX9 class
    malformed emitted MPNs whose CONTENT is real but whose SHAPE is not:
              one cell carrying two part numbers, embedded newlines, stray
              enclosing punctuation. Reported separately because the value is
              on the page — it is the extraction that has not finished the job.

`exact` is the score. `spurious` and `missing` move independently and a run
where both rise by one is precisely the failure this file was written for.

HEADERS ARE SCORED HERE TOO, AND THEY FAIL DIFFERENTLY. Ground truth grew a
per-notice `headers` block (2026-09-30), read off the page rather than off a
run, and this file consumes it. The reason it has to exist alongside the
three-fire agreement check in `pcn_corpus_gate.py` is that AGREEMENT IS NOT
CORRECTNESS: three fires can write `2024-06-10` for TYC's `pub_date` and agree
perfectly. That value is the portal's print stamp — the day the PDF was
rendered — and the notice was published on the 7th. Agreement would report
that as settled; only ground truth can report it as wrong.

So a header field lands in one of seven states, and the ones that are not
`exact` are kept apart because they are different defects with different fixes:

    exact        the written value is the page's value
    distractor   the written value is one ground truth DECLARES as wrong, and
                 says why: `2024-06-10` for TYC's pub_date is the print stamp,
                 `TE Connecvity` is the degraded text layer's dropped `ti`
                 ligature, `TE` is the witness reading the logo wordmark. The
                 value is ON the page; the wrong one was picked. That is a
                 field-attribution failure, addressable in the prompt.
    wrong        a value ground truth does not account for at all. Not the same
                 defect as above and must not be totalled with it: a declared
                 distractor is a known trap, an undeclared value may be
                 invention.
    misformatted the right content in a shape nothing downstream can use
                 (`07-JUN-24` for `2024-06-07`). The parts scorer's `malformed`
                 class, applied to headers: the value is on the page, the
                 extraction has not finished the job. NOT credited as exact.
    unreadable   a date this scorer will not guess at. `6/10/24` is ambiguous
                 between June 10 and 6 October, so it is neither credited nor
                 attributed to a distractor — see `normalize_date`.
    absent       ground truth says the page carries this value and nothing was
                 written. A miss.
    pending      ground truth records `value: null` — the field has NOT been
                 established (TYC's `doc_level_ltb_date`, where the text layer
                 and the witness disagree and the page has not been read
                 directly). NOT SCORED, in either direction. Scoring a field
                 against a guess would manufacture a result; reporting it
                 silently as a pass would hide the gap. It is printed as
                 pending and excluded from every total.

A run that never recorded headers (any image before the `written_header`
field) reports `observed: false`. That is NOT ZERO and NOT A PASS: the header
section prints NOT SCORED and names the reason, because a header score of
"0 failures" over a run that measured no headers is the exact shape of a
guard that is green because it never ran.

USAGE

    # score a run that has just finished, or one saved earlier
    python scripts/pcn_score.py /tmp/pcn_corpus.json
    python scripts/pcn_score.py /tmp/pcn_corpus.json --json /tmp/score.json

Exit status is 0 only when every notice scores exact == count with nothing
spurious, missing or malformed, AND no established header field is anything
but exact.

NOTE ON THE OTHER EXIT CODE. `pcn_corpus_run.py:main()` keeps its own exit
criterion — parts and crop-seal only — deliberately unchanged. The gate reads
that code as "parts/crop-seal failure inside the fire" and reproduces its
terms in `_reconstruct_exit` for `--from-logs`, so folding headers into it
would silently change what a fire's exit code means in two places at once.
Header correctness reaches the gate as its own reported condition, off the
`header_totals` block this file writes into the score JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List

GT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "pcn_ground_truth.json")

# A part number that arrives carrying one of these has not been cleanly
# extracted even when every character of it is real: a comma or a newline means
# the cell held more than one value and was never split, and a run of interior
# whitespace means cell text was concatenated. Kept deliberately narrow — an
# MPN legitimately contains hyphens, plus signs, slashes and dots, so none of
# those appear here.
_MALFORMED_MARKERS = ("\n", "\r", "\t", ",", "  ")


def is_malformed(mpn: str) -> bool:
    return any(m in (mpn or "") for m in _MALFORMED_MARKERS)


def load_ground_truth(path: str = GT_PATH) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["notices"]


def load_corpus(path: str = GT_PATH) -> Dict[str, Any]:
    """The `_corpus` block: what the corpus IS, as an enumeration.

    Carried in the ground-truth file rather than in a document because this is
    the denominator every score is divided by, and the gate reads this file.
    `check_ground_truth` in pcn_corpus_run.py asserts TARGETS against it and
    aborts the run on a disagreement; pcn_corpus_gate.py copies it into the
    committed report so a report states the corpus it measured. Returns {} if
    absent, so an older ground-truth file still loads.
    """
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("_corpus") or {}


def score_notice(emitted: List[str], gt_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Set comparison between what a notice emitted and what it should have.

    Multiplicity is deliberately ignored: ground truth is a set of distinct part
    numbers, so a notice that emits the same MPN twice is not credited twice.
    The duplicate still shows up, as `emitted` exceeding `exact + spurious`.
    """
    gt = list(gt_entry["mpns"])
    gt_set = set(gt)
    emitted_set = set(emitted)

    exact = sorted(emitted_set & gt_set)
    spurious = sorted(emitted_set - gt_set)
    missing = sorted(gt_set - emitted_set)
    malformed = sorted(m for m in emitted_set if is_malformed(m))

    return {
        "count": gt_entry["count"],
        "emitted": len(emitted),
        "distinct": len(emitted_set),
        "exact": len(exact),
        "spurious": spurious,
        "missing": missing,
        "malformed": malformed,
        "clean": not spurious and not missing and not malformed
                 and len(exact) == gt_entry["count"],
    }


# --------------------------------------------------------------------------
# HEADER scoring against notices[*].headers. See the module docstring for why
# the failure classes are kept apart instead of totalled as "wrong".

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DMY_DATE = re.compile(r"^(\d{1,2})[-/ ]([A-Za-z]{3,9})\.?[-/, ]+(\d{2,4})$")

# Header field names whose values are dates. `pub_date` and `doc_level_ltb_date`
# today; the suffix rule covers a field added later without a second edit here.
_DATE_FIELD_SUFFIX = "_date"

# Statuses that mean the field was scored and did not pass. `pending` and the
# unobserved case are absent BY DESIGN — neither is a failure, and neither is a
# pass (module docstring).
HEADER_FAILURES = ("distractor", "wrong", "misformatted", "unreadable", "absent")

# `alias` is a PASS and is deliberately absent from HEADER_FAILURES: the field
# was answered with a spelling ground truth accepts as verbatim-correct, just
# not the canonical one. It is counted apart from `exact` all the same, so a
# report never has to explain why `exact` is short of `fields_scored` with no
# failure beside it.
HEADER_PASSES = ("exact", "alias")


def normalize_date(v: Any) -> str | None:
    """`YYYY-MM-DD` for the date spellings these notices actually print, else None.

    Accepted: ISO, and the day-month-year forms that appear on the PCN pages and
    in the vision witness's transcriptions — `07-JUN-24`, `10-Jun-2024`,
    `8 June 2024`. A two-digit year below 70 is read as 20xx.

    `6/10/24` IS DELIBERATELY NOT ACCEPTED, and that is the whole point of this
    function being narrow. An all-numeric slash date is irreducibly ambiguous
    between US order (June 10) and day-first order (6 October) — two different
    days, not two spellings of one. TYC's portal print header carries exactly
    that form, so the temptation to parse it is real, and giving in would let
    this scorer decide by assumption which calendar date the extractor meant,
    then grade its own assumption. A date it cannot read without guessing is
    reported `unreadable` instead: not credited, and not attributed to a
    declared distractor either.
    """
    if not isinstance(v, str):
        return None
    s = v.strip()
    m = _ISO_DATE.match(s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = _DMY_DATE.match(s)
        if not m:
            return None
        d = int(m.group(1))
        mo = _MONTHS.get(m.group(2)[:3].lower(), 0)
        y = int(m.group(3))
        if y < 100:
            y += 2000 if y < 70 else 1900
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _fold_text(v: Any) -> str | None:
    """Case- and whitespace-insensitive form, for deciding whether two header
    strings carry the same CONTENT. Used only after an exact comparison has
    already failed, so it can never turn a match into a near-match."""
    if not isinstance(v, str):
        return None
    return " ".join(v.split()).casefold() or None


def is_date_field(name: str) -> bool:
    return name.endswith(_DATE_FIELD_SUFFIX)


def accepted_forms(spec: Dict[str, Any]) -> tuple:
    """Every spelling of this field ground truth accepts, CANONICAL FIRST.

    A field with no `accepted` block has exactly one acceptable spelling -- its
    `value` -- so this returns a one-element tuple and every caller downstream
    can use the same comparator whether or not the field has aliases. Underscore
    keys are prose, the convention everywhere in pcn_ground_truth.json.

    WHY THIS EXISTS. A verbatim field can have more than one correct reading of
    one page: TYC's heading is `TE Connectivity`, its damaged text layer hands
    an extractor `TE Connecvity`, and its logo renders as `TE`. Comparing a
    written string raw against `value` makes two of those three a failure and
    the field's verdict a coin flip -- which is what three fires did on
    2026-10-08. Comparison is canonical-after-alias: resolve what was written
    to its canonical form first, then compare canonical forms.

    A declared `accepted` block that omits its own `value` RAISES. A canonical
    form outside its own accepted set is incoherent, and inserting it quietly
    would hide a ground-truth defect behind a passing score.
    """
    expected = spec.get("value")
    raw = spec.get("accepted")
    if raw is None:
        return (expected,) if expected is not None else ()
    if isinstance(raw, dict):
        forms = [k for k in raw if not str(k).startswith("_")]
    elif isinstance(raw, (list, tuple)):
        forms = list(raw)
    else:
        raise ValueError(
            f"`accepted` must be a list or a dict, got {type(raw).__name__}")
    if expected not in forms:
        raise ValueError(
            f"ground truth defect: `value` {expected!r} is not in its own `accepted` "
            f"set {forms!r} -- the canonical form must be one of the accepted spellings")
    return tuple([expected] + [f for f in forms if f != expected])


def declared_distractors(name: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """The `not` block, prose keys dropped, checked DISJOINT from `accepted`.

    One spelling cannot be both verbatim-correct and a declared trap. If ground
    truth says both, neither answer is right: letting `accepted` win would
    credit a trap, letting `not` win would fail a correct reading -- so this
    raises and names the field. The folded compare is included because `TE` in
    one block and `te` in the other is the same contradiction.
    """
    declared = {k: v for k, v in (spec.get("not") or {}).items()
                if not str(k).startswith("_")}
    forms = accepted_forms(spec)
    folded = {_fold_text(f) for f in forms} - {None}
    clash = sorted(b for b in declared
                   if b in forms or _fold_text(b) in folded)
    if clash:
        raise ValueError(
            f"ground truth defect in field {name!r}: {clash!r} appears in BOTH "
            f"`accepted` and `not` -- a spelling cannot be verbatim-correct and a "
            f"declared distractor")
    return declared


def score_header_field(name: str, written: Any,
                       spec: Dict[str, Any]) -> Dict[str, Any]:
    """One header field: what was written, what the page says, and — when they
    differ — WHICH KIND of wrong it is."""
    expected = spec.get("value")
    forms = accepted_forms(spec)
    declared = declared_distractors(name, spec)
    out: Dict[str, Any] = {"field": name, "expected": expected, "got": written}

    if expected is None:
        out["status"] = "pending"
        out["why"] = (spec.get("status")
                      or "ground truth records no established value for this field")
        out["candidates"] = sorted(spec.get("candidates") or {})
        return out

    if written in (None, ""):
        out["status"] = "absent"
        return out
    if written == expected:
        out["status"] = "exact"
        return out

    # CANONICAL-AFTER-ALIAS. An accepted non-canonical spelling is a correct
    # answer, and it is resolved BEFORE the distractor scan so a value ground
    # truth accepts can never be reported as a trap. The alias match is
    # exact-string on purpose: a folded-only match falls through to the shape
    # check below and is still reported `misformatted`, so this step cannot
    # launder a mangled spelling into a pass.
    if written in forms:
        out["status"] = "alias"
        out["canonical"] = expected
        accepted_why = spec.get("accepted")
        if isinstance(accepted_why, dict):
            out["why"] = accepted_why.get(written)
        return out

    dated = is_date_field(name)
    norm_w = normalize_date(written) if dated else _fold_text(written)

    # A DECLARED distractor outranks every other diagnosis. Ground truth named
    # this value and said why it is wrong; that reason is more informative than
    # anything inferred below, and reporting it as merely "wrong" would throw
    # away the one piece of evidence that distinguishes a known trap.
    for bad, why in declared.items():
        norm_b = normalize_date(bad) if dated else _fold_text(bad)
        if written == bad or (norm_w is not None and norm_w == norm_b):
            out["status"] = "distractor"
            out["matched"] = bad
            out["why"] = why
            return out

    # Shape check against EVERY accepted form, not just the canonical one: a
    # mangled spelling of an accepted alias carries the same content as the
    # page, so it is misformatted rather than unaccounted-for.
    norm_forms = {f: (normalize_date(f) if dated else _fold_text(f)) for f in forms}
    if norm_w is not None and norm_w in {v for v in norm_forms.values()
                                         if v is not None}:
        out["status"] = "misformatted"
        out["canonical"] = expected
        return out
    if dated and norm_w is None:
        out["status"] = "unreadable"
        return out
    out["status"] = "wrong"
    return out


def score_headers(written: Any, headers: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Score one notice's written header against its ground-truth block.

    Returns None when ground truth declares no headers for the notice — there is
    nothing to score and nothing to report, which is different from a notice
    whose headers were declared and not measured.

    `observed: false` is that second case: ground truth has values, the run
    recorded no `written_header` (every image before that field existed). The
    fields are listed with no status so the report can say NOT SCORED rather
    than printing zero failures over an unmeasured notice.
    """
    spec = {k: v for k, v in (headers or {}).items() if not k.startswith("_")}
    if not spec:
        return None
    if not isinstance(written, dict):
        return {"observed": False, "fields": {},
                "declared": sorted(spec),
                "reason": "the run recorded no written_header for this notice"}

    fields = {name: score_header_field(name, written.get(name), s)
              for name, s in sorted(spec.items())}
    by_status: Dict[str, List[str]] = {}
    for name, f in fields.items():
        by_status.setdefault(f["status"], []).append(name)
    scored = [n for n, f in fields.items() if f["status"] != "pending"]
    return {
        "observed": True,
        "fields": fields,
        "scored": sorted(scored),
        "by_status": {k: sorted(v) for k, v in by_status.items()},
        "exact": len(by_status.get("exact", [])),
        "alias": len(by_status.get("alias", [])),
        "clean": not any(by_status.get(s) for s in HEADER_FAILURES),
    }


def header_totals(per: Dict[str, Any]) -> Dict[str, Any]:
    """Corpus-wide header numbers, with every failure located as `notice:field`.

    `clean` and `observed` are SEPARATE booleans on purpose. A run that measured
    nothing has no failures, so `clean` alone would read as success; `observed`
    is what says whether `clean` is a measurement or a vacuum.
    """
    t: Dict[str, Any] = {"notices_with_gt": 0, "notices_observed": 0,
                         "unobserved": [], "fields_scored": 0, "exact": 0,
                         "aliases": [], "pending": []}
    for s in HEADER_FAILURES:
        t[s] = []
    for fn, p in sorted(per.items()):
        h = p.get("headers")
        if not h:
            continue
        t["notices_with_gt"] += 1
        if not h.get("observed"):
            t["unobserved"].append(fn)
            continue
        t["notices_observed"] += 1
        t["fields_scored"] += len(h["scored"])
        t["exact"] += h["exact"]
        for name in h["by_status"].get("alias", []):
            t["aliases"].append(f"{fn}:{name}")
        for name in h["by_status"].get("pending", []):
            t["pending"].append(f"{fn}:{name}")
        for s in HEADER_FAILURES:
            t[s] += [f"{fn}:{name}" for name in h["by_status"].get(s, [])]
    t["observed"] = bool(t["notices_with_gt"]) and not t["unobserved"]
    t["clean"] = not any(t[s] for s in HEADER_FAILURES)
    return t


def score_run(results: Dict[str, Any], gt: Dict[str, Any]) -> Dict[str, Any]:
    per: Dict[str, Any] = {}
    for fn, entry in gt.items():
        res = results.get(fn)
        if res is None:
            per[fn] = {"count": entry["count"], "error": "notice absent from run",
                       "exact": 0, "spurious": [], "missing": list(entry["mpns"]),
                       "malformed": [], "emitted": 0, "distinct": 0, "clean": False}
            continue
        if not res.get("ok"):
            per[fn] = {"count": entry["count"],
                       "error": res.get("error", "run reported failure"),
                       "exact": 0, "spurious": [], "missing": list(entry["mpns"]),
                       "malformed": [], "emitted": 0, "distinct": 0, "clean": False}
            continue
        per[fn] = score_notice([m for m in (res.get("mpns") or []) if m], entry)

    # Headers, attached to every notice INCLUDING the absent/failed ones above:
    # a notice that never ran has unobserved headers, which must read as
    # unobserved rather than vanish from the header totals' denominator.
    for fn, entry in gt.items():
        res = results.get(fn)
        written = res.get("written_header") if isinstance(res, dict) else None
        scored_headers = score_headers(written, entry.get("headers"))
        if scored_headers is not None:
            per[fn]["headers"] = scored_headers

    totals = {
        "gt": sum(e["count"] for e in gt.values()),
        "exact": sum(p["exact"] for p in per.values()),
        "spurious": sum(len(p["spurious"]) for p in per.values()),
        "missing": sum(len(p["missing"]) for p in per.values()),
        "malformed": sum(len(p["malformed"]) for p in per.values()),
        "emitted": sum(p["emitted"] for p in per.values()),
    }
    return {"per_notice": per, "totals": totals,
            "header_totals": header_totals(per)}


def render(scored: Dict[str, Any]) -> str:
    per, t = scored["per_notice"], scored["totals"]
    out = [f"{'notice':38} {'gt':>4} {'emit':>5} {'exact':>6} {'spur':>5} "
           f"{'miss':>5} {'malf':>5}", "-" * 72]
    for fn, p in per.items():
        out.append(f"{fn:38} {p['count']:>4} {p['emitted']:>5} {p['exact']:>6} "
                   f"{len(p['spurious']):>5} {len(p['missing']):>5} "
                   f"{len(p['malformed']):>5}"
                   + ("" if p.get("clean") else "  <<"))
    out += ["-" * 72,
            f"{'TOTAL':38} {t['gt']:>4} {t['emitted']:>5} {t['exact']:>6} "
            f"{t['spurious']:>5} {t['missing']:>5} {t['malformed']:>5}", ""]
    out.append(f"SCORE {t['exact']} / {t['gt']} by exact part number")
    if t["emitted"] != t["exact"]:
        out.append(f"      ({t['emitted']} parts emitted - that is NOT the score)")
    for fn, p in per.items():
        if p.get("error"):
            out.append(f"\n{fn}: ERROR {p['error']}")
            continue
        if p["spurious"]:
            out.append(f"\n{fn} spurious (emitted, not a real part):")
            out += [f"    {m!r}" for m in p["spurious"]]
        if p["missing"]:
            out.append(f"\n{fn} missing (real part, not emitted):")
            out += [f"    {m!r}" for m in p["missing"]]
        if p["malformed"]:
            out.append(f"\n{fn} malformed (real content, unusable shape):")
            out += [f"    {m!r}" for m in p["malformed"]]
    out.append("")
    out.append(render_headers(scored))
    return "\n".join(out)


def render_headers(scored: Dict[str, Any]) -> str:
    """The header section. Prints nothing but a line of explanation when ground
    truth declares no headers, so the absence is stated rather than looking like
    a clean sweep."""
    t = scored.get("header_totals") or {}
    if not t.get("notices_with_gt"):
        return ("HEADERS  no notice in ground truth carries a `headers` block — "
                "nothing scored (this is not a pass)")

    out = ["HEADERS  scored against notices[*].headers in pcn_ground_truth.json",
           f"{'notice':38} {'field':20} {'status':12} value", "-" * 100]
    for fn, p in sorted(scored["per_notice"].items()):
        h = p.get("headers")
        if not h:
            continue
        if not h.get("observed"):
            out.append(f"{fn:38} {'(all declared)':20} {'NOT SCORED':12} "
                       f"{h.get('reason', '')}")
            continue
        for name, f in h["fields"].items():
            got = f["got"] if f["got"] not in (None, "") else "-"
            out.append(f"{fn:38} {name:20} {f['status']:12} {got!r}")

    out += ["-" * 100]
    if t["notices_observed"]:
        out.append(f"HEADER SCORE {t['exact']} / {t['fields_scored']} established "
                   f"fields exact, over {t['notices_observed']} of "
                   f"{t['notices_with_gt']} notices with ground truth")
    if t["unobserved"]:
        out.append("      HEADERS NOT SCORED for " + ", ".join(t["unobserved"])
                   + " — the run recorded no written_header. NOT a pass: nothing "
                     "was measured.")
    if t.get("aliases"):
        out.append("      accepted alias, counted as correct but NOT as `exact` (the "
                   "written spelling is in the field's `accepted` set; the canonical "
                   "form is not what was written): " + ", ".join(t["aliases"]))
    if t["pending"]:
        out.append("      pending (ground truth not established, excluded from the "
                   "score): " + ", ".join(t["pending"]))

    for fn, p in sorted(scored["per_notice"].items()):
        h = p.get("headers")
        if not h or not h.get("observed"):
            continue
        for name, f in h["fields"].items():
            if f["status"] == "distractor":
                out.append(f"\n{fn} {name}: DECLARED DISTRACTOR {f['got']!r} "
                           f"(ground truth: {f['expected']!r})\n    {f['why']}")
            elif f["status"] == "wrong":
                out.append(f"\n{fn} {name}: wrong — wrote {f['got']!r}, page says "
                           f"{f['expected']!r}, and ground truth does not account "
                           f"for what was written")
            elif f["status"] == "misformatted":
                out.append(f"\n{fn} {name}: misformatted — {f['got']!r} is the same "
                           f"value as {f['expected']!r} in an unusable shape")
            elif f["status"] == "unreadable":
                out.append(f"\n{fn} {name}: unreadable — {f['got']!r} is not a date "
                           f"this scorer will guess at (see normalize_date)")
            elif f["status"] == "absent":
                out.append(f"\n{fn} {name}: absent — nothing written, page says "
                           f"{f['expected']!r}")
            elif f["status"] == "alias":
                out.append(f"\n{fn} {name}: accepted alias — wrote {f['got']!r}, "
                           f"canonical is {f['expected']!r}. Verbatim-correct, NOT "
                           f"a failure."
                           + (f"\n    {f['why']}" if f.get("why") else ""))
            elif f["status"] == "pending":
                out.append(f"\n{fn} {name}: PENDING, not scored — {f['why']}"
                           + (f"\n    candidates: {', '.join(f['candidates'])}"
                              if f.get("candidates") else ""))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("results", help="pcn_corpus.json from a run")
    ap.add_argument("--ground-truth", default=GT_PATH)
    ap.add_argument("--json", dest="json_out", help="also write the scored dict here")
    a = ap.parse_args()

    with open(a.results, encoding="utf-8") as f:
        results = json.load(f)
    scored = score_run(results, load_ground_truth(a.ground_truth))
    print(render(scored))
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(scored, f, indent=2)
        print(f"\nWROTE {a.json_out}")

    t = scored["totals"]
    parts_ok = (t["exact"] == t["gt"] and not t["spurious"]
                and not t["missing"] and not t["malformed"])
    # An UNOBSERVED header block does not fail this: a pre-written_header run is
    # a parts measurement and says nothing about headers either way. What would
    # fail is an observed field that is not exact. The two are kept apart so a
    # green exit never rests on a header pass that was never measured — the
    # report says NOT SCORED out loud for that case.
    return 0 if (parts_ok and (scored.get("header_totals") or {}).get("clean", True)) else 1


if __name__ == "__main__":
    sys.exit(main())
