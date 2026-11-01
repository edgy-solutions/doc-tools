"""Turn a validated batch profile plus saved extraction responses into CSV rows.

Reads files only. It does NOT fetch (no network, no credentials: the route that
serves the catalogue fields is never called from here), does NOT parse an
ambiguous date, does NOT apply steward corrections, and special-cases no
``header.*`` name: every ``source.field`` resolves through ``Catalogue``, so a
newly served field needs no change here.

Exit codes: 0 rows written; 1 a block / row_ambiguous / corrections refusal /
catalogue resolution error / unreadable input; 2 the profile was refused.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from doc_tools.batch.profile import Catalogue, _norm_row_field, load_profile, validate_profile

_FULL = ("january february march april may june july august "
         "september october november december").split()
# Full English names and their 3-letter abbreviations; nothing else names a month.
_MONTH_NAME = {**{n: i for i, n in enumerate(_FULL, 1)}, **{n[:3]: i for i, n in enumerate(_FULL, 1)}}
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ]\S+)?\Z")
_D_MON_Y = re.compile(r"(\d{1,2}) ([A-Za-z]+) (\d{4})\Z")
_MON_D_Y = re.compile(r"([A-Za-z]+) (\d{1,2}), (\d{4})\Z")
_NUM = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\Z")
_CONTAINERS = ("Extraction", "Notice", "ExtractionRow", "EvidenceRef")


class ExportError(Exception):
    """An export-level failure: nothing is written."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class Resolved:
    """One column with its catalogue entry resolved: where its value lives."""
    output: str
    container: str | None
    wire_name: str | None
    row_field: str | None
    absent_block: bool
    date: bool
    on_unresolvable: str | None
    landing: str | None


def _ymd(y: int, m: int, d: int) -> str | None:
    try:
        return datetime.date(y, m, d).isoformat()
    except ValueError:
        return None


def normalise_date(raw: str) -> str | None:
    """ISO date only where the input FORCES it; ``None`` otherwise.

    ``05/12/2023`` is 5 Dec or 12 May by vendor country, so both components <= 12
    is None, as is anything outside the three closed branches. No stripping:
    surrounding whitespace is an unresolvable value, not a tolerated one.
    """
    if m := _ISO.match(raw):
        return _ymd(*map(int, m.groups()))
    if m := _D_MON_Y.match(raw):
        mon = _MONTH_NAME.get(m.group(2).lower())
        return _ymd(int(m.group(3)), mon, int(m.group(1))) if mon else None
    if m := _MON_D_Y.match(raw):
        mon = _MONTH_NAME.get(m.group(1).lower())
        return _ymd(int(m.group(3)), mon, int(m.group(2))) if mon else None
    if m := _NUM.match(raw):
        a, b, y = map(int, m.groups())
        # Equal components choose nothing: 05/05 is 5 May under either reading.
        if a == b:
            return _ymd(y, a, b)
        if a > 12 >= b:
            return _ymd(y, b, a)
        if b > 12 >= a:
            return _ymd(y, a, b)
    return None


def resolve_columns(profile: dict, cat: Catalogue) -> list:
    out = []
    for col in profile["columns"]:
        src = col.get("source")
        container = wire_name = row_field = None
        absent_block = False
        if src:
            field = src["field"]
            wire = (cat.by_name.get(field) or {}).get("wire")
            if not isinstance(wire, dict) or wire.get("container") not in _CONTAINERS:
                raise ExportError("field_unresolvable",
                                  f"column {col['output']!r}: {field!r} has wire {wire!r}, "
                                  f"not one of {_CONTAINERS}")
            container, wire_name = wire["container"], wire["name"]
            if src.get("row_field") is not None:
                row_field = _norm_row_field(src["row_field"])
            absent_block = src.get("absent_row") == "block"
        out.append(Resolved(col["output"], container, wire_name, row_field, absent_block,
                            col.get("format") == "iso8601", col.get("on_unresolvable"),
                            col.get("landing")))
    return out


def _wire_value(c: Resolved, row: dict):
    if c.container == "ExtractionRow":
        return row.get(c.wire_name)
    return (row.get("evidence_ref") or {}).get(c.wire_name)


def _group_parts(rows: list) -> list:
    """Rows grouped by part_index, in first-appearance order."""
    groups: dict = {}
    for r in rows:
        groups.setdefault(r["part_index"], []).append(r)
    return list(groups.values())


def _cell(c: Resolved, doc: dict, part: list | None, where: str, inherited: dict, warn):
    """(value, raw): the mapped cell, and the raw string when it is unresolvable."""
    if c.container is None:
        return "", None
    if c.container == "Extraction":
        v = doc.get(c.wire_name)
    elif c.container == "Notice":
        v = (doc.get("notice") or {}).get(c.wire_name)
    else:
        if not part:  # a no-parts row: part columns are empty, not a lost value
            return "", None
        if c.row_field is None:
            # No selector is possible here: row_field is REFUSED when the wire name is
            # not shared. That is right for row.mpn, the part identity repeated on
            # every row, and wrong for row.needs_review or row.source_snippet, which
            # vary per row and still cannot be selected. So the first row is taken and
            # a disagreement is REPORTED rather than resolved silently by position.
            row = part[0]
            seen = {json.dumps(_wire_value(c, r), sort_keys=True, default=str) for r in part}
            if len(seen) > 1:
                warn(f"warning: {where}, column {c.output!r}: the rows of this part carry "
                     f"{len(seen)} different {c.wire_name!r} values and no selector is "
                     "possible; took the first row")
        else:
            hits = [r for r in part if r["field"] == c.row_field]
            if len(hits) > 1:
                raise ExportError("row_ambiguous", f"{where}, column {c.output!r}: "
                                  f"{len(hits)} rows have field {c.row_field!r}")
            if not hits:
                if c.absent_block:
                    raise ExportError("absent_row", f"{where}, column {c.output!r}: "
                                      f"no row has field {c.row_field!r}")
                return "", None
            row = hits[0]
        if row.get("obtained_via") == "inherited_doc_level":
            inherited[c.output] = inherited.get(c.output, 0) + 1
        v = _wire_value(c, row)
    if v is None or v == "":
        return "", None
    s = str(v)
    if not c.date:
        return s, None
    iso = normalise_date(s)
    if iso is not None:
        return iso, None
    if c.on_unresolvable == "block":
        raise ExportError("date_unresolvable", f"{where}, column {c.output!r}: {s!r}")
    return "", (s if c.on_unresolvable == "land" else None)


def export_rows(doc: dict, cols: list, granularity: str, inherited: dict, warn) -> list:
    """Row dicts (keyed by output name) for one extraction response."""
    nid = doc.get("notice_id")
    if doc.get("corrected_by") is not None:
        raise ExportError("export_corrections_not_applied",
                          f"notice {nid!r}: corrected_by is set; the route serves "
                          "the uncorrected review.json values")
    parts = _group_parts(doc.get("rows") or [])
    if doc.get("part_count") != len(parts):
        warn(f"warning: notice {nid!r}: part_count={doc.get('part_count')} but rows carry "
             f"{len(parts)} distinct part_index values; exporting from the rows")
    units = [None] if granularity == "notice" else (parts or [None])
    result = []
    for part in units:
        where = f"notice {nid!r}, part " + (repr(part[0]["part_index"]) if part else "(none)")
        row = {c.output: "" for c in cols}
        for c in cols:
            v, raw = _cell(c, doc, part, where, inherited, warn)
            if v:
                row[c.output] = v
            if raw is not None:
                prior = row[c.landing]
                row[c.landing] = f"{prior}; {raw}" if prior else raw
        if granularity == "notice_part" and not parts and "no_parts" in row:
            row["no_parts"] = "true"
        result.append(row)
    return result


def _load_extractions(paths: list) -> list:
    files: list = []
    for p in map(Path, paths):
        files.extend(sorted(p.glob("*.json")) if p.is_dir() else [p])
    docs = []
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ExportError("input_unreadable", f"{f.name}: {e}")
        if not isinstance(doc, dict):
            raise ExportError("input_unreadable", f"{f.name}: not a JSON object")
        docs.append(doc)
    if not docs:
        raise ExportError("input_unreadable", "no extraction files found")
    return docs


def _write(path: Path, cols: list, rows: list) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([c.output for c in cols])
            for r in rows:
                w.writerow([r[c.output] for c in cols])
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m doc_tools.batch.cli",
                                 description="Export saved extraction responses through a batch profile.")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--extraction", action="append", required=True,
                    help="a saved extraction JSON, or a directory of *.json; repeatable")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fail-on-warning", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    def err(m):
        print(m, file=sys.stderr)

    cat = Catalogue.load()
    try:
        profile = load_profile(a.profile)
    except (OSError, ValueError) as e:
        err(f"profile unreadable: {e}")
        return 2
    findings = validate_profile(profile, cat)
    for f in findings:
        err(f"{f.severity} {f.code} {f.where}: {f.detail}")
    if any(f.severity == "error" or (a.fail_on_warning and f.severity == "warning") for f in findings):
        return 2
    try:
        cols = resolve_columns(profile, cat)
        docs = _load_extractions(a.extraction)
        inherited: dict = {}
        rows = [r for d in docs for r in export_rows(d, cols, profile["granularity"], inherited, err)]
        if not a.dry_run:
            _write(Path(a.out), cols, rows)
    except ExportError as e:
        err(f"export failed, nothing written: {e}")
        return 1
    if inherited:
        err(f"note: {sum(inherited.values())} selected row(s) are inherited_doc_level "
            f"(a doc-level value repeated onto a part) in column(s): {', '.join(sorted(inherited))}")
    err(f"{'validated' if a.dry_run else 'wrote'} {len(rows)} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
