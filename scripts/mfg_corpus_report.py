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

Run (PowerShell):
  <python> scripts/mfg_corpus_report.py --input <dir> --label <slice-name> \
      [--glob "**/*text.json"] [--include-values] [--out report.json]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="directory of parsed element-list JSON files")
    ap.add_argument("--glob", default="**/*text.json", help="glob under --input (default **/*text.json)")
    ap.add_argument("--label", default="unlabeled", help="corpus slice label (stamped)")
    ap.add_argument("--include-values", action="store_true",
                    help="include actual extracted values (use only on a slice you deem safe)")
    ap.add_argument("--out", default="mfg_corpus_report.json")
    ap.add_argument("--stamp-date", default="", help="ISO date override (else today)")
    args = ap.parse_args()

    mx = _load_extractors()
    cfg = mx.load_extractor_config()

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
