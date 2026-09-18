"""Diagnose PCN/PDN parts extraction against the document's own table structure.

WHY. A review demo surfaced two distinct defects that look similar in the UI and
have opposite causes:
  * MISSING part numbers — affected parts in the table that never got extracted.
  * ALIAS parts shown as affected — values pulled from a column that is not the
    affected-part column (a 'Product Family' / 'Replacement' / 'Pin To Pin
    Compatible' column), so the review shows a real-looking part number that is
    not the part the notice is about.

The second one is COLUMN MISATTRIBUTION, and it is deterministic information: the
table header says which column is which. So rather than asking a model to grade
itself, this walks the parsed table grid, classifies every column, and then asks —
for each extracted part — WHICH COLUMN DID THIS COME FROM. A part sourced from a
replacement or alias column is the defect, named at its cause.

Reuses the already-tested grid logic in doc_tools/utils/table_text_layer.py
(find_header_row / find_title_row / pair_columns / looks_like_mpn) rather than
re-implementing table reading, and adds the one vocabulary it lacks: ALIAS
columns, which is the category the demo's bad rows came from.

Read-only. Standard S3 env (S3_ENDPOINT_URL / AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY / MINIO_SECURE).

Run:
  python scripts/pdn_parts_diagnostic.py --prefix sustainment/inbound/ [--doc adi_run3]
  python scripts/pdn_parts_diagnostic.py --prefix sustainment/ --out pdn_diag.json
"""
import argparse
import collections
import html as _html
import importlib.util
import json
import os
import re

# Columns that hold a part-shaped value which is NOT the affected part. This is
# the vocabulary table_text_layer lacks, and it is where the demo's bad rows came
# from: a family/alias column reads exactly like a part number to a model that is
# looking at pixels instead of at the header.
ALIAS_HEADERS = (
    "product family", "family", "alias", "cross reference", "cross-reference",
    "xref", "equivalent", "pin to pin", "pin-to-pin", "compatible", "base part",
    "generic", "series", "similar", "second source",
)


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def html_to_grid(h: str):
    """text_as_html -> list[list[str]] (tags stripped, entities unescaped)."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", h or "", re.S | re.I)
    grid = []
    for r in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)
        grid.append([_html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in cells])
    return grid


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().upper()


# --------------------------------------------------------------------------- #
# Redaction. Sandbox runs are against PUBLISHED manufacturer notices, where raw
# values are fine. A work corpus is not, and an instrument that leaks by default
# is an instrument you cannot point at the thing you actually need to measure.
# So values are SHAPES unless the operator opts in per slice.
# --------------------------------------------------------------------------- #
REDACT_VALUES = True
REDACT_HEADERS = False


def shape(v) -> str:
    """digits -> '#', letters -> 'A'. A part number's STRUCTURE is what a
    diagnosis needs ('AAA-####-A' says everything); its identity is not."""
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "#", str(v)))


def fmt(v):
    """How a part-number-ish value is rendered into the report."""
    return str(v) if not REDACT_VALUES else shape(v)


def fmt_header(v):
    """Column headers are the DIAGNOSTIC PAYLOAD — 'Product Family',
    'Replacement Part', 'EOL Devices' are the vocabulary that tells us which
    columns mean what, and they are generic industry language rather than
    anyone's identifiers. They are therefore kept verbatim by default, with
    --redact-headers for a corpus where even a column label is sensitive.
    """
    return shape(v) if REDACT_HEADERS else str(v)


def classify_columns(header_row, tl):
    """affected | replacement | alias | other, per column.

    ALIAS is tested FIRST: 'Base Part Number' contains 'part number' and would
    otherwise be read as the affected column, which is the misattribution this
    tool exists to catch.
    """
    out = []
    for cell in (header_row or []):
        h = _norm(cell).lower()
        if any(a in h for a in ALIAS_HEADERS):
            out.append("alias")
        elif any(a in h for a in tl.REPLACEMENT_HEADERS):
            out.append("replacement")
        elif any(a in h for a in tl.AFFECTED_HEADERS):
            out.append("affected")
        else:
            out.append("other")
    return out


def index_tables(elements, tl):
    """Every table cell -> where it sits and what kind of column it is."""
    tables, cell_index = [], collections.defaultdict(list)
    for ti, el in enumerate(e for e in elements if e.get("type") == "Table"):
        html = (el.get("metadata") or {}).get("text_as_html", "") or ""
        grid = html_to_grid(html)
        if not grid:
            continue
        hrow = tl.find_header_row(grid)
        header = grid[hrow] if hrow is not None else None
        classes = classify_columns(header, tl) if header else []
        # A table whose header row was not found (page-continuation tables lose
        # it) has UNKNOWN column semantics — that is itself a finding, because
        # affected/replacement cannot be told apart at all.
        tables.append({"table": ti, "rows": len(grid), "header_row": hrow,
                       "header": [fmt_header(h) for h in (header or [])],
                       "col_classes": classes,
                       "header_found": hrow is not None})
        start = (hrow + 1) if hrow is not None else 0
        for ri in range(start, len(grid)):
            for ci, cell in enumerate(grid[ri]):
                v = _norm(cell)
                if not v:
                    continue
                cls = classes[ci] if ci < len(classes) else "unknown"
                cell_index[v].append({"table": ti, "row": ri, "col": ci, "col_class": cls})
    return tables, cell_index


def locate(value, cell_index):
    """Where did an extracted part come from? Handles the OCR-truncation case."""
    v = _norm(value)
    if v in cell_index:
        return "exact", cell_index[v]
    # The affected cell is frequently OCR-truncated ('AD7873ACPZ' printed, cell
    # reads '7873ACPZ'), so a strict match would call a CORRECT extraction a
    # hallucination. Suffix/prefix containment is reported as its own class.
    for cell, hits in cell_index.items():
        if len(cell) >= 4 and (v.endswith(cell) or cell.endswith(v) or cell in v or v in cell):
            return "partial", hits
    return "absent", []


def diagnose(elements, llm_parts, tl):
    tables, cell_index = index_tables(elements, tl)
    by_source = collections.Counter()
    findings = []
    extracted_norm = set()

    for p in llm_parts:
        mpn = p.get("affected_mpn")
        if not mpn:
            continue
        extracted_norm.add(_norm(mpn))
        how, hits = locate(mpn, cell_index)
        if how == "absent":
            by_source["not_in_any_table"] += 1
            findings.append({"kind": "not_in_any_table", "value": fmt(mpn)})
            continue
        classes = {h["col_class"] for h in hits}
        # Worst-case classification: if it appears ONLY in a non-affected column
        # that is the misattribution; if it also appears in an affected column
        # the extraction is defensible.
        if "affected" in classes:
            by_source[f"affected_{how}"] += 1
        elif "replacement" in classes:
            by_source["from_replacement_column"] += 1
            findings.append({"kind": "from_replacement_column", "value": fmt(mpn),
                             "cols": sorted(classes)})
        elif "alias" in classes:
            by_source["from_alias_column"] += 1
            findings.append({"kind": "from_alias_column", "value": fmt(mpn),
                             "cols": sorted(classes)})
        elif "unknown" in classes:
            by_source["from_unheadered_table"] += 1
            findings.append({"kind": "from_unheadered_table", "value": fmt(mpn)})
        else:
            by_source["from_other_column"] += 1
            findings.append({"kind": "from_other_column", "value": fmt(mpn),
                             "cols": sorted(classes)})

    # Recall: part-shaped cells in an AFFECTED column that were never extracted.
    missing = []
    for cell, hits in cell_index.items():
        if not any(h["col_class"] == "affected" for h in hits):
            continue
        if not tl.looks_like_mpn(cell):
            continue
        if cell in extracted_norm:
            continue
        if any(cell in e or e in cell for e in extracted_norm):
            continue          # OCR-truncation counterpart already extracted
        missing.append(cell)

    return {"tables": tables, "by_source": dict(by_source),
            "n_extracted": len(extracted_norm),
            "missing_from_affected_columns": [fmt(x) for x in sorted(missing)],
            "findings": findings}


def llm_parts_from(extraction: dict, review: dict):
    """Parts as the pipeline persisted them (extraction.json preferred)."""
    parts = []
    for aug in (extraction or {}).get("augmentations", []) or []:
        notice = aug.get("notice") or aug
        parts.extend(notice.get("impacted_parts") or [])
    if parts:
        return parts
    # fall back to review.json review_items (field_path parts[i].affected_mpn)
    for it in (review or {}).get("review_items", []) or []:
        if str(it.get("field_path", "")).endswith(".affected_mpn"):
            parts.append({"affected_mpn": it.get("value")})
    return parts


def _doc_label(text_dir: str, prefix: str) -> str:
    """A readable, UNIQUE label per document (the old code collapsed many)."""
    rel = text_dir[len(prefix):] if text_dir.startswith(prefix) else text_dir
    rel = rel.strip("/")
    if "/generated/" in f"/{rel}/":
        rel = rel.split("/generated/")[0]
    return rel or text_dir


def discover_docs(s3, bucket, prefix):
    """Pair text.json / extraction.json / review.json WITHOUT assuming a depth.

    THE BUG THIS REPLACES: the doc root was computed as the first THREE path
    segments. Any corpus whose documents sit deeper collapsed every one of them
    onto the same computed root, and because the artifacts were stored in a dict
    keyed by that root, each document silently OVERWROTE the last — dozens of
    notices reported as one. It is the same hardcoded-layout mistake already
    fixed in mfg_corpus_report.py, repeated here.

    Instead: the text.json's own directory is the anchor, and the run WALKS UP
    toward the prefix looking for the extraction/review that own it (they sit at
    the document root while text.json sits under generated/<name>/). Sibling,
    parent, grandparent — all handled, and the distance is reported so the real
    layout is measured rather than assumed.
    """
    pag = s3.get_paginator("list_objects_v2")
    keys = []
    for pg in pag.paginate(Bucket=bucket, Prefix=prefix):
        for o in pg.get("Contents", []):
            keys.append(o["Key"])

    def dirmap(fname):
        return {k.rsplit("/", 1)[0]: k for k in keys if k.endswith("/" + fname)}

    texts, extrs, revs = dirmap("text.json"), dirmap("extraction.json"), dirmap("review.json")
    docs = []
    for tdir in sorted(texts):
        ek = rk = None
        layout = None
        parts = tdir.split("/")
        for i in range(len(parts), 0, -1):          # self, then walk upward
            cand = "/".join(parts[:i])
            if ek is None and cand in extrs:
                ek = extrs[cand]
                hops = len(parts) - i
                layout = "sibling" if hops == 0 else f"ancestor+{hops}"
            if rk is None and cand in revs:
                rk = revs[cand]
            if ek and rk:
                break
        docs.append({"doc": _doc_label(tdir, prefix), "text_key": texts[tdir],
                     "extraction_key": ek, "review_key": rk,
                     "layout": layout or "no_extraction"})
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="sustainment/inbound/")
    ap.add_argument("--bucket", default=os.getenv("DAGSTER_STORAGE_BUCKET", "processing-artifacts"))
    ap.add_argument("--doc", action="append", help="only these doc roots (repeatable)")
    ap.add_argument("--tl-path", default="/app/doc_tools/utils/table_text_layer.py")
    ap.add_argument("--out", default="")
    ap.add_argument("--include-values", action="store_true",
                    help="emit raw part numbers instead of shapes (published notices, "
                         "or a slice you have judged safe)")
    ap.add_argument("--redact-headers", action="store_true",
                    help="also shape column headers (they are kept verbatim by default "
                         "because they ARE the diagnostic payload)")
    args = ap.parse_args()

    global REDACT_VALUES, REDACT_HEADERS
    REDACT_VALUES = not args.include_values
    REDACT_HEADERS = args.redact_headers

    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
                      aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
                      use_ssl=os.getenv("MINIO_SECURE", "false").lower() == "true",
                      verify=False)
    tl = _load_module("table_text_layer", args.tl_path)

    found = discover_docs(s3, args.bucket, args.prefix)
    layouts = collections.Counter(d["layout"] for d in found)

    print(f"redaction: values={'SHAPES' if REDACT_VALUES else 'RAW'}, "
          f"headers={'shaped' if REDACT_HEADERS else 'verbatim'}"
          f"{'' if REDACT_VALUES else '   <-- raw values: confirm this slice is safe to carry'}")
    print(f"discovered {len(found)} document(s) under '{args.prefix}'   layouts={dict(layouts)}")
    if not found:
        print("  NOTHING PAIRED — every document needs a text.json. Check the prefix.")

    report = {}
    for d in found:
        doc = d["doc"]
        if args.doc and doc not in args.doc:
            continue
        get = lambda key: json.loads(s3.get_object(Bucket=args.bucket, Key=key)["Body"].read())
        elements = get(d["text_key"])
        extraction = get(d["extraction_key"]) if d["extraction_key"] else {}
        review = get(d["review_key"]) if d["review_key"] else {}
        parts = llm_parts_from(extraction, review)
        res = diagnose(elements, parts, tl)
        report[doc] = res

        print(f"\n=== {doc} ===  extracted={res['n_extracted']}")
        for t in res["tables"]:
            if t["col_classes"]:
                print(f"   table{t['table']} hdr_found={t['header_found']} "
                      f"cols={t['col_classes']}")
            else:
                print(f"   table{t['table']} hdr_found={t['header_found']} (NO HEADER -> "
                      f"column semantics UNKNOWN)")
        print(f"   source of extracted parts: {res['by_source']}")
        if res["missing_from_affected_columns"]:
            m = res["missing_from_affected_columns"]
            print(f"   MISSING from affected columns ({len(m)}): {m[:12]}")
        for f in res["findings"][:10]:
            print(f"   !! {f['kind']}: {f.get('value')} {f.get('cols','')}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
