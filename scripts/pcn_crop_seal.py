"""SEAL: does the shipped crop-bottom repair actually contain the glyphs, on the
real corpus PDFs? Read-only. No S3 writes, no crop PNGs downloaded or modified,
no manifest mutated. `repair_table_crops` (doc_tools/utils/crop_geometry.py) is
never called here — this only calls the pure `corrected_bottom` and
`_rows_for_best_table` helpers it is built from, against real page geometry.

WHAT IT MEASURES. For every Table element that carries
`metadata.coordinates.points` + `layout_height`, this recomputes the element's
box in PDF points and asks pdfplumber's `extract_words()`, on the real source
PDF, which words that box's bottom edge slices through — see `_cut_words` for
the exact rule, including the mandatory sibling-exclusion clause (below). It
reports TWO verdicts per table:

  stored    words cut by the bottom edge AS RECORDED in the manifest — i.e.
            what is actually sitting in S3 right now and what the vision model
            actually saw when a notice was ingested.
  repaired  words cut by the bottom edge `corrected_bottom` would produce —
            i.e. what the SHIPPED rule in crop_geometry.py produces when run
            against the same real geometry.

WHY THEY DIFFER, AND WHY ONLY `repaired` GATES THE EXIT CODE. The crop repair
runs at INGEST time, inside `doc_tools/components/document_parser.py`, and
rewrites crop PNGs before they are uploaded to S3. The manifests this seal
reads were produced by an EARLIER image, built before that repair existed, so
`stored_cut` is non-empty for 8 tables across 4 of the 9 corpus notices, and
will stay non-empty until those 4 notices are re-ingested through an image that
carries the fix.

That 8/4 is NOT the 9/5 the 2026-09-24 clipping survey reported, and the
difference is not a disagreement. The survey counted nine table INSTANCES, and
Diodes appears three times in its table and onsemi twice, so its nine rows span
only four distinct documents — plus a fifth notice, TYC, whose row is the
99%-of-glyph-kept one that the survey's own repair table marks `unchanged /
COVERED`. This module does not count that table as cut, because no glyph is
sliced. Measured at pin 600c454: `TYC … n_tables=5 stored=0 repaired=0`.
That is expected. It is not a code regression; it is a live measure of the
re-ingest backlog, and `stored_cut` never affects the exit code because of it.
`repaired_cut` is the one that must stay at zero: it tests the shipped rule
against the real PDFs, independent of which image produced whatever happens to
be sitting in S3 today. A non-zero `repaired_cut_tables` means the fix itself
is wrong, not that a notice is stale.

SIBLING EXCLUSION IS LOAD-BEARING, NOT AN OPTIMIZATION. unstructured routinely
splits one visual table into several Table elements (a header block, a body
block, a continuation block, ...). A word can sit hard against element A's
bottom edge — and so read as "cut" by A in isolation — while actually being
shown whole inside sibling element B's own crop. A first survey pass that
measured cuts without excluding words already covered by a sibling's box
reported 924 false "lost" words. Every cut this module reports has been
checked against every OTHER Table element's recorded box on the same page
first; a word fully contained (1pt tolerance, all four sides) in any sibling's
box is not counted as cut, no matter which edge it grazes.

USAGE

    python scripts/pcn_crop_seal.py --json /tmp/pcn_crop_seal.json
    python scripts/pcn_crop_seal.py --file PCN23-002.pdf --file TYC-PCN-24-210412.pdf

Exit status is 0 only when `repaired_cut_tables == 0` and `errors == 0`.
`stored_cut` never affects it, by design (see above).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from doc_tools.utils import crop_geometry  # noqa: E402
from doc_tools.utils import provenance  # noqa: E402

Box = Tuple[float, float, float, float]  # (x0, top, x1, bottom), PDF points


def _harness():
    """`pcn_corpus_run`, imported lazily.

    Deliberately NOT a module-level import. `pcn_corpus_run` imports this
    module at its top, so importing it back at our top would be a cycle; and
    because the entry point is registered as `__main__` rather than under its
    own filename, that cycle resolves by loading a SECOND copy of whichever
    module was not the entry point. Both files are pure definitions today so
    two copies behave identically, but it is a trap for anyone who later adds
    import-time state. Keeping this lazy means the harness path — which passes
    `bucket`, `pick_fn` and `files` in explicitly — never imports us back at
    all, and only standalone `main()` ever reaches for the sibling module.
    """
    import pcn_corpus_run
    return pcn_corpus_run


def source_key(c, key: str, man: dict, fn: str, bucket: str) -> Optional[str]:
    """The source PDF's own S3 key for this manifest.

    A manifest may carry it directly (`source_key`); otherwise the source PDF
    is a sibling of the manifest's own prefix (everything before
    `/generated/`), named `.../<filename>`.
    """
    if man.get("source_key"):
        return man["source_key"]
    pref = key.split("/generated/")[0] + "/"
    for o in c.list_objects_v2(Bucket=bucket, Prefix=pref).get("Contents", []):
        if o["Key"].endswith("/" + fn):
            return o["Key"]
    return None


def _cut_words(words: List[dict], el_box_pts: Box, bottom: float,
               sibling_boxes: List[Box]) -> List[str]:
    """Words from one page cut by a bottom edge at `bottom`, per the spec rule:
    the edge must pass through the word's vertical extent, the word must be
    horizontally within the element's own column span, and the word must not
    be fully contained (1pt tolerance) in any sibling Table element's box on
    the same page.

    `sibling_boxes` must come from the SAME world as `bottom`: stored sibling
    boxes for the stored verdict, repaired ones for the repaired verdict. See
    the pass-2 comment in `_measure_notice` for why mixing them misreports."""
    x0, _top, x1, _bottom = el_box_pts
    cut: List[str] = []
    for w in words:
        if not (w["top"] < bottom - 0.5 and w["bottom"] > bottom + 0.5):
            continue
        if not (w["x1"] > x0 - 1 and w["x0"] < x1 + 1):
            continue
        covered_by_sibling = False
        for sx0, stop, sx1, sbot in sibling_boxes:
            if (sx0 - 1 <= w["x0"] and w["x1"] <= sx1 + 1
                    and stop - 1 <= w["top"] and w["bottom"] <= sbot + 1):
                covered_by_sibling = True
                break
        if covered_by_sibling:
            continue
        cut.append(w["text"])
    return cut


def _measure_notice(pdf_path: str, elements: List[dict]) -> Tuple[int, List[dict], List[dict]]:
    """Measure one notice's Table elements against its own source PDF.

    Returns (n_tables, stored_cut, repaired_cut) — `n_tables` counts only Table
    elements carrying enough metadata to compute a box at all.
    """
    import pdfplumber

    tbl_els = provenance.table_elements(elements)

    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)

        # Pass 1: every measurable table's box, grouped by page (for sibling
        # exclusion) and kept in element order (for the measurement pass).
        entries: List[dict] = []
        boxes_by_page: Dict[int, List[Tuple[int, Box]]] = {}
        for i, el in enumerate(tbl_els):
            meta = el.get("metadata") or {}
            page_number = meta.get("page_number")
            coords = meta.get("coordinates") or {}
            points = coords.get("points")
            layout_height = coords.get("layout_height")
            if not page_number or not points or not layout_height:
                continue
            if not (1 <= page_number <= n_pages):
                continue
            page_height_pts = pdf.pages[page_number - 1].height
            if not page_height_pts:
                continue
            scale = float(layout_height) / float(page_height_pts)
            if scale <= 0:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            el_box_pts: Box = (min(xs) / scale, min(ys) / scale,
                               max(xs) / scale, max(ys) / scale)
            entries.append({"idx": i, "page": page_number, "box": el_box_pts})
            boxes_by_page.setdefault(page_number, []).append((i, el_box_pts))

        words_cache: Dict[int, list] = {}
        tables_cache: Dict[int, list] = {}

        # Pass 2: every table's REPAIRED box, before any cut test runs.
        #
        # This pass exists so the two verdicts get sibling sets from the same
        # world. Sibling exclusion asks "is this word shown whole in some other
        # crop on this page?", and the answer differs between the two verdicts:
        # a re-ingest repairs EVERY table on the page, not just the one under
        # test. Testing a repaired bottom against stored siblings mixes the two
        # worlds and can report a word as cut when the crop that actually holds
        # it whole was repaired too — a false FAIL on the one verdict that gates
        # the exit code.
        rep_boxes_by_page: Dict[int, List[Tuple[int, Box]]] = {}
        for e in entries:
            page_number, el_box_pts = e["page"], e["box"]
            pp_page = pdf.pages[page_number - 1]
            if page_number not in tables_cache:
                tables_cache[page_number] = pp_page.find_tables()
            row_boxes = crop_geometry._rows_for_best_table(
                tables_cache[page_number], el_box_pts)
            e["repaired_bottom"] = crop_geometry.corrected_bottom(
                el_box_pts, row_boxes, pp_page.height)
            rep_boxes_by_page.setdefault(page_number, []).append(
                (e["idx"], (el_box_pts[0], el_box_pts[1], el_box_pts[2],
                            e["repaired_bottom"])))

        stored_cut: List[dict] = []
        repaired_cut: List[dict] = []

        for e in entries:
            page_number, el_box_pts = e["page"], e["box"]
            pp_page = pdf.pages[page_number - 1]

            if page_number not in words_cache:
                words_cache[page_number] = pp_page.extract_words()
            words = words_cache[page_number]

            stored_sibs = [b for (j, b) in boxes_by_page[page_number]
                           if j != e["idx"]]
            repaired_sibs = [b for (j, b) in rep_boxes_by_page[page_number]
                             if j != e["idx"]]

            stored_words = _cut_words(words, el_box_pts, el_box_pts[3], stored_sibs)
            if stored_words:
                stored_cut.append({"page": page_number,
                                   "bottom_pts": round(el_box_pts[3], 1),
                                   "words": stored_words})

            repaired_words = _cut_words(words, el_box_pts, e["repaired_bottom"],
                                        repaired_sibs)
            if repaired_words:
                repaired_cut.append({"page": page_number,
                                     "bottom_pts": round(e["repaired_bottom"], 1),
                                     "words": repaired_words})

    return len(entries), stored_cut, repaired_cut


def seal_corpus(c, by_file: Dict[str, list], files: Optional[List[str]] = None,
                *, bucket: Optional[str] = None, pick_fn=None) -> dict:
    """Measure stored vs. repaired crop cuts across the corpus. Read-only: opens
    each source PDF read-only from a temp copy and never writes to S3.

    `files` defaults to every filename in `pcn_corpus_run.TARGETS`, `bucket` to
    its `BUCKET`, and `pick_fn` to its `pick` — the SAME manifest-preference
    logic the corpus harness uses, so this measures the manifest a scoring run
    would have used. The harness passes all three in explicitly, which is what
    keeps this module from importing it back (see `_harness`).
    """
    if files is None or bucket is None or pick_fn is None:
        h = _harness()
        if files is None:
            files = [t["file"] for t in h.TARGETS]
        if bucket is None:
            bucket = h.BUCKET
        if pick_fn is None:
            pick_fn = h.pick

    by_notice: Dict[str, dict] = {}
    totals = {
        "n_tables": 0, "stored_cut_tables": 0, "repaired_cut_tables": 0,
        "stored_cut_words": 0, "repaired_cut_words": 0, "errors": 0,
    }

    for fn in files:
        cands = by_file.get(fn) or []
        if not cands:
            by_notice[fn] = {"ok": False, "error": "no manifest found"}
            totals["errors"] += 1
            continue

        key, m = pick_fn(fn, cands)
        tmpd = tempfile.mkdtemp(prefix="pcn_crop_seal_")
        try:
            elements = json.loads(
                c.get_object(Bucket=bucket, Key=m["text_location"])
                ["Body"].read())
            sk = source_key(c, key, m, fn, bucket)
            if not sk:
                raise RuntimeError("source PDF key not found alongside manifest")
            raw = c.get_object(Bucket=bucket, Key=sk)["Body"].read()
            pdf_path = os.path.join(tmpd, fn)
            with open(pdf_path, "wb") as f:
                f.write(raw)

            n_tables, stored_cut, repaired_cut = _measure_notice(pdf_path, elements)
            by_notice[fn] = {
                "ok": True, "n_tables": n_tables,
                "stored_cut": stored_cut, "repaired_cut": repaired_cut,
            }
            totals["n_tables"] += n_tables
            totals["stored_cut_tables"] += len(stored_cut)
            totals["repaired_cut_tables"] += len(repaired_cut)
            totals["stored_cut_words"] += sum(len(e["words"]) for e in stored_cut)
            totals["repaired_cut_words"] += sum(len(e["words"]) for e in repaired_cut)
        except Exception as e:  # noqa: BLE001 - one bad PDF/manifest must not stop the corpus
            by_notice[fn] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            totals["errors"] += 1
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)

    return {"by_notice": by_notice, "totals": totals}


def render(sealed: dict) -> str:
    """Compact text report: one line per notice, then a FAIL line for every
    repaired-cut table (the only ones that indicate a real problem)."""
    by_notice, t = sealed["by_notice"], sealed["totals"]
    out = [f"{'notice':38} {'tables':>6} {'stored_cut':>10} {'repaired_cut':>12}"]
    for fn, r in by_notice.items():
        if not r.get("ok"):
            out.append(f"{fn:38} ERROR {r.get('error')}")
            continue
        out.append(f"{fn:38} {r['n_tables']:>6} {len(r['stored_cut']):>10} "
                   f"{len(r['repaired_cut']):>12}")
    out.append(f"TOTAL tables={t['n_tables']} "
              f"stored_cut_tables={t['stored_cut_tables']} "
              f"stored_cut_words={t['stored_cut_words']} "
              f"repaired_cut_tables={t['repaired_cut_tables']} "
              f"repaired_cut_words={t['repaired_cut_words']} errors={t['errors']}")
    for fn, r in by_notice.items():
        if not r.get("ok"):
            continue
        for e in r["repaired_cut"]:
            out.append(f"FAIL {fn} p{e['page']} bottom={e['bottom_pts']} words={e['words']}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", dest="json_out", help="write the sealed dict here")
    ap.add_argument("--file", action="append", dest="files",
                    help="restrict to this filename (repeatable); default: every "
                         "filename in pcn_corpus_run.TARGETS")
    a = ap.parse_args()

    h = _harness()
    c = h.s3_client()
    by_file = h.find_manifests(c)
    sealed = seal_corpus(c, by_file, files=a.files, bucket=h.BUCKET, pick_fn=h.pick)
    print(render(sealed))
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(sealed, f, indent=2, default=str)
        print(f"\nWROTE {a.json_out}")

    t = sealed["totals"]
    return 1 if (t["repaired_cut_tables"] or t["errors"]) else 0


if __name__ == "__main__":
    sys.exit(main())
