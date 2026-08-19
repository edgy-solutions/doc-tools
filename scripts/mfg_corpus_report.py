"""Run the deterministic extractors over a corpus of parsed WIs and emit a
report that is safe to carry back to an agent that must never see the documents.

Operating model (see docs/manufacturing-extraction-findings.md, "corpus not
agent-accessible"): the agent builds this instrument; the USER runs it against the
real corpus and returns the report. So the report is a CONTRACT WITH A HUMAN
COURIER — small, self-describing, and safe *by construction*:

  * The report code NEVER writes document text into the report. It emits COUNTS,
    redacted SHAPES (digits -> '#', e.g. 'PN-1001' -> 'PN-####'), and anomaly
    KINDS. Values are shown only if you pass --include-values (your judgement on
    a slice you deem safe).
  * Documents are identified by index + a short filename hash. The index->path
    map is written to a SEPARATE *.local-map.json you keep locally and do NOT
    share — so anomalies are traceable to a document on your side without any
    path leaving your machine.
  * The report is STAMPED: extractor version, config hash, corpus label, doc
    count, timestamp — so run N+1 can be compared to run N.

The first run's product is the ANOMALY distribution, not the recall number: it
tells the agent how the real corpus differs from the synthetic fixtures. Each
anomaly class becomes a new fixture variant or a real extractor fix.

Input: a directory of parsed element lists (unstructured `text.json` shape:
a JSON list of element dicts). Deterministic only — no LLM, no network.

Two modes:
  LOCAL (--input DIR): deterministic-only over a directory of text.json files.
  MINIO COMPARISON (--minio-prefix): the real instrument. Pairs each doc's
    persisted extraction.json (arm 1 = the pipeline's LLM output) with its
    text.json (input to both) and diffs it against the deterministic extractors
    (arm 2 = the script) over the SAME elements. Three-way per field:
    script_only = LLM MISSED it, llm_only = script MISSED it, agree. Only fields
    with a deterministic arm are scored (standards, parts, figures, operations,
    hazard); judgment fields (is_value_added, process_category, ...) are reported
    as LLM-only coverage, NEVER as wins. Read-only S3 (list + get); endpoint/creds
    from the standard env (S3_ENDPOINT_URL / AWS_ACCESS_KEY_ID /
    AWS_SECRET_ACCESS_KEY / MINIO_SECURE) — no new env name invented. Same elision
    (never writes document text; --include-values opts in per safe slice).

Run (PowerShell):
  # deterministic-only over local text.json
  <python> scripts/mfg_corpus_report.py --input <dir> --label <slice> [--include-values]
  # LLM-vs-script comparison over a MinIO prefix (drop docs -> pipeline runs -> point here)
  <python> scripts/mfg_corpus_report.py --minio-prefix manufacturing/ \
      [--bucket processing-artifacts] [--include-values] [--out report.json]
"""
import argparse
import collections
import datetime
import glob as globmod
import hashlib
import importlib.util
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load_extractors():
    path = os.path.join(ROOT, "doc_tools", "utils", "mfg_extractors.py")
    spec = importlib.util.spec_from_file_location("mfg_extractors", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shape(tok: str) -> str:
    """Redact a token to its structure: digits -> '#', letters/sep preserved."""
    return re.sub(r"\d", "#", str(tok))


def _shapes(tokens):
    return dict(collections.Counter(_shape(t) for t in tokens))


def _config_hash(cfg) -> str:
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _iter_docs(input_dir, pattern):
    for path in sorted(globmod.glob(os.path.join(input_dir, pattern), recursive=True)):
        base = os.path.basename(path).lower()
        if "groundtruth" in base or "_repro_response" in base:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, list):
            yield path, data


# --------------------------------------------------------------------------- #
# MinIO comparison mode: LLM (persisted extraction.json) vs deterministic script,
# over the SAME text.json. The pipeline already runs this A/B on every ingest.
# --------------------------------------------------------------------------- #
import re as _re

_FILENAME_RE = _re.compile(r"figure-\d+-\d+\.jpg$", _re.I)
_JUDGMENT_FIELDS = ["is_value_added", "is_safety_critical", "process_category",
                    "action_verb", "justification"]
# Only these have a deterministic arm — the ONLY fields the comparison can score.
_COMPARED_FIELDS = ["standards", "parts", "figures", "operations", "hazard"]


def _norm_tok(s: str) -> str:
    return _re.sub(r"[\s\-]+", "-", str(s).strip().upper()).strip("-")


def _filled(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, bool):
        return v
    return True


def _llm_steps(extraction: dict):
    return [s for aug in (extraction.get("augmentations") or [])
            for s in (aug.get("steps") or [])]


def llm_doc_sets(extraction: dict) -> dict:
    """Doc-level value sets from a persisted extraction.json (arm 1 = the LLM)."""
    steps = _llm_steps(extraction)

    def coll(field):
        vals = set()
        for s in steps:
            v = s.get(field)
            if v is None:
                continue
            if isinstance(v, list):
                vals.update(str(x).strip() for x in v if str(x).strip())
            elif str(v).strip():
                vals.add(str(v).strip())
        return vals

    figs_all = coll("figure_references")
    figs = {f for f in figs_all if _FILENAME_RE.search(f)}
    stds = coll("standard_ref") | coll("military_and_industry_standards")
    cov = {f: round(sum(1 for s in steps if _filled(s.get(f))) / (len(steps) or 1), 2)
           for f in _JUDGMENT_FIELDS}
    return {
        "standards": {_norm_tok(x) for x in stds},
        "parts": {_norm_tok(x) for x in coll("internal_part_numbers")},
        "figures": figs,
        "operations": coll("procedure_id"),
        "hazard": {_norm_tok(x) for x in coll("hazard_class")},
        "_prose_figrefs": len(figs_all - figs),
        "_n_steps": len(steps),
        "_judgment_coverage": cov,
    }


def script_doc_sets(mx, cfg, elements: list) -> dict:
    """Doc-level value sets from the deterministic extractors (arm 2 = the script)."""
    full = "\n".join(e.get("text", "") or "" for e in elements)
    stds, _ = mx.extract_standards(full, cfg)
    parts, _ = mx.extract_part_numbers(full, cfg)
    ops, _ = mx.extract_operations(elements, cfg)
    binds, fanom = mx.bind_figures_to_steps(elements, cfg)
    haz = {f"CLASS-{m.upper()}" for m in _re.findall(cfg["hazard"]["pattern"], full, _re.I)}
    return {
        "standards": {_norm_tok(s) for s in stds},
        "parts": {_norm_tok(p) for p in parts},
        "figures": {b["figure"] for b in binds},
        "operations": set(ops),
        "hazard": haz,
        "_fig_anomalies": len(fanom),
    }


def _three_way(sset: set, lset: set) -> dict:
    return {"agree": sorted(sset & lset),
            "script_only": sorted(sset - lset),   # LLM missed it
            "llm_only": sorted(lset - sset)}       # script missed it


def compare_doc(mx, cfg, elements: list, extraction: dict, include_values: bool) -> dict:
    ss = script_doc_sets(mx, cfg, elements)
    ls = llm_doc_sets(extraction)
    fields = {}
    for f in _COMPARED_FIELDS:
        tw = _three_way(ss[f], ls[f])
        entry = {"agree": len(tw["agree"]),
                 "script_only": len(tw["script_only"]),   # LLM missed
                 "llm_only": len(tw["llm_only"]),          # script missed
                 "script_only_shapes": _shapes(tw["script_only"]),
                 "llm_only_shapes": _shapes(tw["llm_only"])}
        if include_values:
            entry["values"] = tw
        fields[f] = entry
    return {
        "n_steps_llm": ls["_n_steps"],
        "llm_prose_figrefs": ls["_prose_figrefs"],   # non-resolvable 'Figure 3'/'1' refs
        "script_figure_anomalies": ss["_fig_anomalies"],
        # llm_only operations = procedure_id pollution candidates (furniture)
        "procedure_pollution_candidates": fields["operations"]["llm_only"],
        "fields": fields,
        "llm_judgment_coverage": ls["_judgment_coverage"],  # LLM-only; NOT a win
    }


def _s3_client():
    import boto3  # lazy: only needed in MinIO mode, present in the deployment env
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        use_ssl=os.getenv("MINIO_SECURE", "false").lower() == "true",
        verify=False,
    )


def _get_json(s3, bucket, key):
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8"))


def _iter_minio(s3, bucket, prefix):
    """Yield (extraction_key, text_key, last_modified) for each doc with both
    artifacts. Read-only: list + get, nothing else."""
    paginator = s3.get_paginator("list_objects_v2")
    keys, lastmod = [], {}
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            keys.append(o["Key"])
            lastmod[o["Key"]] = o.get("LastModified")
    keyset = set(keys)
    for ek in sorted(k for k in keys if k.endswith("/extraction.json")):
        base_dir = ek[: -len("/extraction.json")]
        tjs = sorted(k for k in keyset
                     if k.startswith(base_dir + "/generated/") and k.endswith("/text.json"))
        yield ek, (tjs[0] if tjs else None), lastmod.get(ek)


def run_minio(args, mx, cfg):
    s3 = _s3_client()
    per_doc, local_map = [], {}
    agg = {f: collections.Counter() for f in _COMPARED_FIELDS}
    gen = []
    skipped = collections.Counter()
    for i, (ek, tk, lm) in enumerate(_iter_minio(s3, args.bucket, args.minio_prefix)):
        doc_id = f"doc_{i:04d}"
        if tk is None:
            skipped["no_text_json"] += 1
            continue
        extraction = _get_json(s3, args.bucket, ek)
        if (extraction.get("domain_type") or "").lower() != "manufacturing":
            skipped["non_manufacturing"] += 1
            continue
        elements = _get_json(s3, args.bucket, tk)
        rec = compare_doc(mx, cfg, elements, extraction, args.include_values)
        rec["doc"] = doc_id
        rec["generated_at"] = lm.isoformat() if lm else None
        per_doc.append(rec)
        local_map[doc_id] = {"extraction_key": ek, "text_key": tk}  # object keys only
        if lm:
            gen.append(lm.isoformat())
        for f in _COMPARED_FIELDS:
            for cls in ("agree", "script_only", "llm_only"):
                agg[f][cls] += rec["fields"][f][cls]

    stamp = {
        "mode": "minio-comparison",
        "extractor_version": mx.EXTRACTOR_VERSION,
        "config_hash": _config_hash(cfg),
        "bucket": args.bucket, "prefix": args.minio_prefix,
        "doc_count": len(per_doc),
        "generation_range": [min(gen), max(gen)] if gen else None,
        "generated_at": args.stamp_date or datetime.date.today().isoformat(),
        "values_included": args.include_values,
        "skipped": dict(skipped),
    }
    report = {
        "stamp": stamp,
        "legend": {"script_only": "LLM MISSED it (script found)",
                   "llm_only": "script MISSED it (LLM found)",
                   "note": "only these fields have a deterministic arm: "
                           + ", ".join(_COMPARED_FIELDS)
                           + ". Judgment fields are LLM-only coverage, NOT wins."},
        "field_totals": {f: dict(agg[f]) for f in _COMPARED_FIELDS},
        "per_doc": per_doc,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    map_path = os.path.splitext(args.out)[0] + ".local-map.json"
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(local_map, f, indent=2)

    print(f"MinIO comparison  bucket={args.bucket}  prefix={args.minio_prefix}  "
          f"docs={len(per_doc)}  extractor v{mx.EXTRACTOR_VERSION}")
    if stamp["generation_range"]:
        print(f"  parse/extraction generation range: {stamp['generation_range'][0]} .. "
              f"{stamp['generation_range'][1]}  (aggregate by generation, not across)")
    print("  field: agree | script_only(LLM missed) | llm_only(script missed)")
    for f in _COMPARED_FIELDS:
        c = agg[f]
        print(f"    {f:11s} agree={c['agree']:4d}  LLM-missed={c['script_only']:4d}  "
              f"script-missed={c['llm_only']:4d}")
    if skipped:
        print(f"  skipped: {dict(skipped)}")
    print(f"  report -> {args.out}  (SHAREABLE, elided)")
    print(f"  local map -> {map_path}  (KEEP LOCAL — doc_id -> object keys)")
    print("  NOTE: llm_only operations are procedure_id pollution candidates; "
          "judgment fields are LLM-only coverage, not wins.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="LOCAL mode: directory of parsed element-list JSON files")
    ap.add_argument("--minio-prefix", help="MINIO comparison mode: S3 prefix to scan")
    ap.add_argument("--bucket", default=os.getenv("DAGSTER_STORAGE_BUCKET", "processing-artifacts"),
                    help="MINIO mode bucket (default $DAGSTER_STORAGE_BUCKET or processing-artifacts)")
    ap.add_argument("--glob", default="**/*text.json", help="glob under --input (default **/*text.json)")
    ap.add_argument("--label", default="unlabeled", help="corpus slice label (stamped)")
    ap.add_argument("--include-values", action="store_true",
                    help="include actual extracted values (use only on a slice you deem safe)")
    ap.add_argument("--out", default="mfg_corpus_report.json")
    ap.add_argument("--stamp-date", default="", help="ISO date override (else today)")
    args = ap.parse_args()

    mx = _load_extractors()
    cfg = mx.load_extractor_config()

    if args.minio_prefix:
        return run_minio(args, mx, cfg)
    if not args.input:
        ap.error("--input is required for local mode (or pass --minio-prefix for comparison mode)")

    per_doc = []
    local_map = {}
    agg_std_shapes = collections.Counter()
    agg_part_shapes = collections.Counter()
    agg_anom = collections.Counter()
    totals = collections.Counter()

    for idx, (path, els) in enumerate(_iter_docs(args.input, args.glob)):
        doc_id = f"doc_{idx:04d}"
        local_map[doc_id] = path
        full_text = "\n".join(e.get("text", "") or "" for e in els)
        pages = {(e.get("metadata") or {}).get("page_number") for e in els}

        stds, std_anom = mx.extract_standards(full_text, cfg)
        parts, _ = mx.extract_part_numbers(full_text, cfg)
        binds, fig_anom = mx.bind_figures_to_steps(els, cfg)
        n_markers = sum(1 for e in els if e.get("type") in ("Image", "Figure"))

        anomalies = std_anom + fig_anom
        for a in anomalies:
            agg_anom[a["kind"]] += 1
        agg_std_shapes.update(_shape(s) for s in stds)
        agg_part_shapes.update(_shape(p) for p in parts)
        totals["standards"] += len(stds)
        totals["parts"] += len(parts)
        totals["figures_markers"] += n_markers
        totals["figures_bound"] += len(binds)
        totals["figures_flagged"] += len(fig_anom)

        rec = {
            "doc": doc_id,
            "hash": hashlib.sha1(os.path.basename(path).encode()).hexdigest()[:8],
            "n_elements": len(els), "n_pages": len([p for p in pages if p is not None]),
            "standards": {"count": len(stds), "shapes": _shapes(stds)},
            "part_numbers": {"count": len(parts), "shapes": _shapes(parts)},
            "figures": {"markers": n_markers, "bound": len(binds), "flagged": len(fig_anom)},
            "anomaly_kinds": dict(collections.Counter(a["kind"] for a in anomalies)),
        }
        if args.include_values:
            rec["values"] = {"standards": sorted(stds), "part_numbers": sorted(parts),
                             "anomalies": anomalies}
        per_doc.append(rec)

    stamp = {
        "extractor_version": mx.EXTRACTOR_VERSION,
        "config_hash": _config_hash(cfg),
        "corpus_label": args.label,
        "doc_count": len(per_doc),
        "generated_at": args.stamp_date or datetime.date.today().isoformat(),
        "input_glob": args.glob,
        "values_included": args.include_values,
    }
    report = {
        "stamp": stamp,
        "totals": dict(totals),
        "standard_shape_distribution": dict(agg_std_shapes),
        "part_shape_distribution": dict(agg_part_shapes),
        "anomaly_distribution": dict(agg_anom),
        "per_doc": per_doc,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    map_path = os.path.splitext(args.out)[0] + ".local-map.json"
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(local_map, f, indent=2)

    # human summary
    print(f"corpus '{stamp['corpus_label']}'  docs={stamp['doc_count']}  "
          f"extractor v{stamp['extractor_version']}  cfg {stamp['config_hash']}  "
          f"{stamp['generated_at']}")
    print(f"  totals: {dict(totals)}")
    print(f"  standard shapes : {dict(agg_std_shapes)}")
    print(f"  part shapes     : {dict(agg_part_shapes)}")
    print(f"  anomaly kinds   : {dict(agg_anom) if agg_anom else '(none)'}")
    print(f"  report -> {args.out}   (SHAREABLE, elided)")
    print(f"  local map -> {map_path}   (KEEP LOCAL — maps doc_id -> path, do not share)")
    if not args.include_values:
        print("  values elided (counts + shapes only). Re-run --include-values on a safe slice to see them.")


if __name__ == "__main__":
    main()
