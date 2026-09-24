"""Drive the real product entry point over the 9-notice PCN/PDN corpus and score it.

WHY THIS FILE IS COMMITTED. It has been rebuilt from scratch twice, because every
previous version lived only in `/tmp` inside a pod that was later replaced. A
measurement harness that dies with the pod makes every run a reconstruction, and
two reconstructions cannot be compared with any confidence. It lives in `scripts/`
now so the next run is a copy plus one command, and so the corpus list and the
ground-truth counts have exactly one home.

USAGE (from a checkout, against a deployed pod):

    kubectl cp scripts/pcn_corpus_run.py sandbox/<pod>:/tmp/pcn_corpus_run.py
    kubectl exec -n sandbox <pod> -- python /tmp/pcn_corpus_run.py

    # long runs (the vision notices take 130-300s each) — detach and poll:
    kubectl exec -n sandbox <pod> -- sh -c \
        'nohup python /tmp/pcn_corpus_run.py > /tmp/corpus.log 2>&1 &'
    kubectl exec -n sandbox <pod> -- tail -5 /tmp/corpus.log

On Windows/Git-Bash prefix kubectl calls with MSYS_NO_PATHCONV=1, or MSYS rewrites
`/tmp/...` into a Windows path before kubectl ever sees it.

DO NOT trust an `echo EXIT_CODE=$?` sentinel written from a PowerShell double-quoted
string: PowerShell expands its own `$?` (a boolean) before the payload reaches the
pod, and you get `EXIT_CODE=True`. This script's completion signal is the final line
of its own output and the presence of every notice key in the JSON.

WRITES: `/tmp/pcn_corpus.json` in the pod, and nothing else. No S3 writes, no Neo4j,
no Jena, no Weaviate, no DataHub, no Dagster materialization. The extraction
functions are called directly and results are kept in memory.
"""
import json
import os
import sys
import time
import traceback

# Before importing doc_tools: keep this measurement run's spans out of the shared
# Langfuse project. `doc_tools.telemetry.observed_trace` is fail-soft and no-ops
# without credentials, so popping these makes the run silent rather than breaking it.
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)
# The prompt must come from the committed file, not from whatever a Langfuse label
# points at today, or the measurement is not reproducible.
os.environ.setdefault("PROMPT_SOURCE", "file")

import boto3

BUCKET = os.getenv("PCN_BUCKET", "processing-artifacts")
PREFIX = "sustainment/inbound/"
OUT = os.getenv("PCN_OUT", "/tmp/pcn_corpus.json")

# THE CORPUS AND THE GROUND TRUTH, in one place.
#
# `gt` is the affected-part count established in docs/pcn-corpus-validation-2026-09-21.md
# and re-confirmed against stored extraction.json in
# docs/pcn-product-baseline-2026-09-22.md section 5. The total is 896. Do not adjust a
# gt value to make a run look better; a disagreement with these numbers is the finding.
TARGETS = [
    {"file": "TYC-PCN-24-210412.pdf",           "gt": 24},
    {"file": "Diodes_PCN_2683_Rev1_EOL.pdf",    "gt": 402},
    {"file": "Diodes_PCN_2683_FULLGREEN.pdf",   "gt": 402},
    {"file": "EOL-36_BYV34-400,-BYV34-500.pdf", "gt": 4},
    {"file": "ADI_PDN_23_0120.pdf",             "gt": 1},
    {"file": "PCN23-002.pdf",                   "gt": 18},
    {"file": "PCN24-029.pdf",                   "gt": 1},
    {"file": "onsemi_Generic_IPCN25300X.pdf",   "gt": 19},
    {"file": "onsemi_Generic_PD26044X1.pdf",    "gt": 25},
]
GT_TOTAL = sum(t["gt"] for t in TARGETS)

# Three notices have MORE THAN ONE manifest in the bucket and the copies are not
# equivalent — see docs/pcn-product-baseline-2026-09-22.md section 3, which rules on
# provenance for each. Pinning the manifest key here keeps a later run from silently
# picking a different copy and reporting the difference as a code change.
PREFER = {
    "ADI_PDN_23_0120.pdf":
        "sustainment/inbound/adi_run3/generated/ADI_PDN_23_0120_pdf/manifest.json",
    "onsemi_Generic_IPCN25300X.pdf":
        "sustainment/inbound/onsemi_truthkey/generated/onsemi_Generic_IPCN25300X_pdf/manifest.json",
}


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def find_manifests(c):
    """Every manifest.json under the inbound prefix, keyed by the filename it declares."""
    by_file = {}
    token = None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": PREFIX}
        if token:
            kw["ContinuationToken"] = token
        r = c.list_objects_v2(**kw)
        for o in r.get("Contents", []):
            if not o["Key"].endswith("/manifest.json"):
                continue
            try:
                m = json.loads(c.get_object(Bucket=BUCKET, Key=o["Key"])["Body"].read())
            except Exception:
                continue
            fn = m.get("filename")
            if fn:
                by_file.setdefault(fn, []).append((o["Key"], m))
        if not r.get("IsTruncated"):
            break
        token = r.get("NextContinuationToken")
    return by_file


def pick(fn, candidates):
    """Prefer the manifest this corpus has ruled on; otherwise the lexically first key,
    so an unpinned notice still resolves deterministically across runs."""
    want = PREFER.get(fn)
    if want:
        for key, m in candidates:
            if key == want:
                return key, m
    return sorted(candidates, key=lambda kv: kv[0])[0]


def build_full_text(elements):
    """Reproduce build_knowledge_graph's global-pass input EXACTLY
    (doc_tools/assets/semantic_assets.py, the `full_text_parts` loop). The router's
    text-only branch reads this string, so a difference here is a difference in what
    is being measured."""
    parts, current_page = [], None
    for el in elements:
        text = el.get("text", "")
        if not text:
            continue
        page_num = el.get("metadata", {}).get("page_number")
        if page_num is not None and page_num != current_page:
            parts.append(f"\n--- Page {page_num} ---\n")
            current_page = page_num
        parts.append(f"[{el.get('type', 'Text')}] {text}")
    return "\n".join(parts)


def run_one(plugin, c, fn, manifest_key, manifest):
    doc_id = manifest["doc_id"]
    elements = json.loads(
        c.get_object(Bucket=BUCKET, Key=manifest["text_location"])["Body"].read())
    full_text = build_full_text(elements)

    t0 = time.time()
    nodes = plugin.process_fulltext(
        full_text, doc_id, manifest.get("metadata", {}),
        elements=elements, manifest=manifest, s3_client=c, bucket=BUCKET)
    elapsed = round(time.time() - t0, 1)

    aug = nodes[0].domain_augmentation
    stats = dict(aug.stats or {})
    parts = list(aug.notice.impacted_parts or [])
    return {
        "ok": True,
        "manifest_key": manifest_key,
        "doc_id": doc_id,
        "elapsed_s": elapsed,
        "parts": len(parts),
        "mpns": [p.affected_mpn for p in parts],
        "needs_review": bool(aug.needs_review),
        "review_reasons": list(aug.review_reasons or []),
        "doc_review_reasons": list((aug.review or {}).get("doc_review_reasons") or []),
        "stats": stats,
    }


def main():
    c = s3_client()
    print(f"bucket={BUCKET} endpoint={os.getenv('S3_ENDPOINT_URL')}")
    print(f"pipeline_version={os.getenv('DOC_TOOLS_VERSION', 'doc-tools@unstamped')}")
    print(f"VISION_MAX_TOKENS={os.getenv('VISION_MAX_TOKENS')}")

    from doc_tools.plugins.sustainment import SustainmentPlugin
    plugin = SustainmentPlugin(domain_type="sustainment")

    by_file = find_manifests(c)
    results = {}
    for t in TARGETS:
        fn = t["file"]
        cands = by_file.get(fn) or []
        if not cands:
            results[fn] = {"ok": False, "error": "no manifest found", "gt": t["gt"]}
            print(f"MISSING MANIFEST  {fn}")
            continue
        key, m = pick(fn, cands)
        print(f"--- {fn}  ({len(cands)} manifest(s), using {key})", flush=True)
        try:
            r = run_one(plugin, c, fn, key, m)
        except Exception as e:
            r = {"ok": False, "error": f"{type(e).__name__}: {e}",
                 "traceback": traceback.format_exc()}
            print(f"    FAILED {type(e).__name__}: {e}", flush=True)
        r["gt"] = t["gt"]
        r["n_manifests"] = len(cands)
        results[fn] = r
        if r.get("ok"):
            st = r["stats"]
            print(f"    parts={r['parts']}/{t['gt']}  elapsed={r['elapsed_s']}s  "
                  f"needs_review={r['needs_review']}  "
                  f"failed={st.get('crops_failed')} trunc={st.get('crops_truncated')} "
                  f"near_cap={st.get('crops_near_cap')} row_short={st.get('crops_row_short')}",
                  flush=True)

    with open(OUT, "w") as f:
        json.dump(results, f, indent=2, default=str)

    got = sum(r.get("parts", 0) for r in results.values() if r.get("ok"))
    print()
    print(f"{'notice':38} {'gt':>4} {'got':>4} {'gap':>4}  review  flags")
    for t in TARGETS:
        r = results[t["file"]]
        if not r.get("ok"):
            print(f"{t['file']:38} {t['gt']:>4} {'ERR':>4} {'?':>4}  {r.get('error')}")
            continue
        st = r["stats"]
        flags = ",".join(k for k in
                         ("crops_failed", "crops_truncated", "crops_near_cap", "crops_row_short")
                         if st.get(k)) or "-"
        print(f"{t['file']:38} {t['gt']:>4} {r['parts']:>4} {t['gt'] - r['parts']:>4}  "
              f"{str(r['needs_review']):>6}  {flags}")
    print()
    print(f"TOTAL {got} / {GT_TOTAL}")
    print(f"WROTE {OUT}")
    return 0 if all(r.get("ok") for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
