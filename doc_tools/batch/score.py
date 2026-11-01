"""Score the CLI's exported rows against a hand-typed truth set.

Reads files only. It does NOT fetch (no network, no credentials, no catalogue:
the scorer never resolves a field), does NOT re-validate the profile (the CLI
did), and does NOT normalise before comparing: not case, not whitespace, not
date form, because a scorer that normalises again hides the defect it exists to
find. The one thing a cell can say beyond its value is ``<empty>``, reserved.

Truth cells: a value must equal the exported cell byte for byte; an EMPTY cell
asserts nothing (a half-filled truth set is the normal case); ``<empty>``
asserts the exported cell is empty. In a KEY column ``<empty>`` also names the
empty string, since a no-parts row has an empty part key.

Two artifacts. The scorecard (``--scorecard``) carries integers, floats, profile
column names and fixed vocabulary only, so it may leave the box. The detail
(``--detail``) carries the values and never does. Diagnostics on stderr name
line numbers and counts, never a cell value.

A truth row the export never produced is not a gap in the scorecard: each of
its asserted cells counts against the column it names, in the ``not_exported``
bucket. So no rate can read 100% while rows are missing -- not ``totals.rate``
and not a single column's. One invariant holds at both levels: the five buckets
(``match``, ``mismatch``, ``expected_empty_got_value``,
``expected_value_got_empty``, ``not_exported``) sum to ``asserted``, and
``rate`` is always ``match / asserted``.

Exit codes: 0 scored; 1 duplicated key, unreadable input, or a truth column /
key the profile does not declare; 2 ``--fail-under`` given and ``totals.rate``
is below it (or null: nothing was asserted).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from doc_tools.batch.profile import load_profile

EMPTY = "<empty>"
DETAIL_BANNER = "# CONTAINS VALUES -- this file does not leave the box. The scorecard does."


class ScoreError(Exception):
    """A scoring-level failure: nothing is written."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class Scored:
    """The profile's identity as the scorer needs it: its name, columns and the join keys."""
    name: str
    granularity: str
    columns: tuple
    keys: tuple


def _read(path, label: str, need: list) -> tuple:
    """(header, rows) of a CSV; a missing column or a ragged row is unreadable."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rd = csv.DictReader(fh)
            rows = list(rd)
            header = list(rd.fieldnames or [])
    except (OSError, ValueError, csv.Error) as e:
        raise ScoreError("input_unreadable", f"{label}: {type(e).__name__}")
    missing = [c for c in need if c not in header]
    if missing:
        raise ScoreError("input_unreadable", f"{label}: no column(s) {missing}")
    for n, r in enumerate(rows, 2):
        if None in r or None in r.values():
            raise ScoreError("input_unreadable", f"{label}: line {n} is ragged")
    return header, rows


def _index(rows: list, keys: tuple, code: str, label: str, truth: bool) -> dict:
    out: dict = {}
    for n, r in enumerate(rows, 2):
        k = tuple("" if truth and r[c] == EMPTY else r[c] for c in keys)
        if k in out:
            raise ScoreError(code, f"{label}: line {n} repeats the key of line {out[k][0]}; "
                                   f"the join is ambiguous -- declare a further --key column")
        out[k] = (n, r)
    return out


def score(sc: Scored, rows: list, truth_header: list, truth: list, warn) -> tuple:
    """(scorecard dict, detail rows) for exported rows against truth rows."""
    undeclared = [c for c in truth_header if c not in sc.columns]
    if undeclared:
        raise ScoreError("truth_column_undeclared", f"{undeclared} not declared by profile {sc.name!r}")
    t_idx = _index(truth, sc.keys, "truth_key_duplicated", "truth", True)
    r_idx = _index(rows, sc.keys, "rows_key_duplicated", "rows", False)
    scored = [c for c in sc.columns if c not in sc.keys]
    buckets = ("match", "mismatch", "expected_empty_got_value",
               "expected_value_got_empty", "not_exported")
    cols = {c: dict(asserted=0, **{b: 0 for b in buckets}) for c in scored}
    detail: list = []
    joined = 0
    for k, (_, t) in t_idx.items():
        kd = dict(zip(sc.keys, k))
        if k not in r_idx:
            for c in scored:
                if t.get(c, "") != "":
                    cols[c]["asserted"] += 1
                    cols[c]["not_exported"] += 1
            detail.append({"kind": "truth_only", **kd})
            continue
        joined += 1
        got_row = r_idx[k][1]
        for c in scored:
            want = t.get(c, "")
            if want == "":
                continue
            got, a = got_row[c], cols[c]
            a["asserted"] += 1
            if want == EMPTY:
                bucket = "match" if got == "" else "expected_empty_got_value"
            elif got == "":
                bucket = "expected_value_got_empty"
            else:
                bucket = "match" if got == want else "mismatch"
            a[bucket] += 1
            if bucket != "match":
                detail.append({"kind": bucket, **kd, "column": c, "expected": want, "got": got})
    for k in r_idx:
        if k not in t_idx:
            detail.append({"kind": "exported_only", **dict(zip(sc.keys, k))})
    for a in cols.values():
        a["rate"] = a["match"] / a["asserted"] if a["asserted"] else None
    totals = {k: sum(a[k] for a in cols.values()) for k in ("asserted", *buckets)}
    totals["rate"] = totals["match"] / totals["asserted"] if totals["asserted"] else None
    card = {"scorecard_version": 1, "profile": sc.name, "granularity": sc.granularity,
            "keys": list(sc.keys),
            "rows": {"exported": len(r_idx), "truth": len(t_idx), "joined": joined,
                     "truth_only": len(t_idx) - joined, "exported_only": len(r_idx) - joined},
            "columns": cols,
            "totals": totals}
    if card["rows"]["truth_only"] or card["rows"]["exported_only"]:
        warn(f"warning: {card['rows']['truth_only']} truth row(s) not exported, "
             f"{card['rows']['exported_only']} exported row(s) not in the truth set")
    return card, detail


def _atomic(path: Path, write) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            write(fh)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _write_card(path: Path, card: dict) -> None:
    def write(fh):
        json.dump(card, fh, indent=2)
        fh.write("\n")
    _atomic(path, write)


def _write_detail(path: Path, keys: tuple, detail: list) -> None:
    def write(fh):
        fh.write(DETAIL_BANNER + "\n")
        w = csv.DictWriter(fh, ["kind", *keys, "column", "expected", "got"], restval="")
        w.writeheader()
        w.writerows(detail)
    _atomic(path, write)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m doc_tools.batch.score",
                                 description="Score exported rows against a truth set; no value is printed.")
    ap.add_argument("--rows", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--key", action="append", required=True)
    ap.add_argument("--scorecard", required=True)
    ap.add_argument("--detail")
    ap.add_argument("--fail-under", type=float)
    a = ap.parse_args(argv)

    def err(m):
        print(m, file=sys.stderr)

    try:
        try:
            profile = load_profile(a.profile)
            sc = Scored(profile["name"], profile["granularity"],
                        tuple(c["output"] for c in profile["columns"]), tuple(a.key))
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise ScoreError("input_unreadable", f"profile: {type(e).__name__}")
        bad = [k for k in sc.keys if k not in sc.columns]
        if bad:
            raise ScoreError("key_undeclared", f"--key {bad} not declared by profile {sc.name!r}")
        _, rows = _read(a.rows, "rows", list(sc.columns))
        t_header, truth = _read(a.truth, "truth", list(sc.keys))
        card, detail = score(sc, rows, t_header, truth, err)
        _write_card(Path(a.scorecard), card)
        if a.detail:
            _write_detail(Path(a.detail), sc.keys, detail)
    except ScoreError as e:
        err(f"scoring failed, nothing written: {e}")
        return 1
    rate = card["totals"]["rate"]
    err(f"scored {card['rows']['joined']} joined row(s); totals.rate="
        f"{'null' if rate is None else round(rate, 4)}")
    if a.fail_under is not None and (rate is None or rate < a.fail_under):
        err(f"totals.rate is below --fail-under {a.fail_under}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
