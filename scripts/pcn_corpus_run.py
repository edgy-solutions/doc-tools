"""Drive the real product entry point over the 9-notice PCN/PDN corpus and score it.

WHY THIS FILE IS COMMITTED. It has been rebuilt from scratch twice, because every
previous version lived only in `/tmp` inside a pod that was later replaced. A
measurement harness that dies with the pod makes every run a reconstruction, and
two reconstructions cannot be compared with any confidence. It lives in `scripts/`
now so the next run is a copy plus one command, and so the corpus list and the
ground-truth counts have exactly one home.

SCORING IS BY PART NUMBER, NOT BY COUNT. This script drives the corpus and
records what came back; `pcn_score.py` decides what that is worth, against the
part numbers in `pcn_ground_truth.json`. The split is deliberate — see the top
of `pcn_score.py` for the run that made it necessary, where a misread part
number filled the slot of the real one and a miss printed as 896/896.

USAGE (from a checkout, against a deployed pod). All three files travel together;
the run aborts at startup if the corpus list and the ground truth disagree:

    for f in pcn_corpus_run.py pcn_score.py pcn_ground_truth.json; do
        kubectl cp "scripts/$f" "sandbox/<pod>:/tmp/$f"
    done
    kubectl exec -n sandbox <pod> -- python /tmp/pcn_corpus_run.py

    # score a saved run again later, without re-extracting anything:
    python scripts/pcn_score.py /tmp/pcn_corpus.json

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

WRITES: `/tmp/pcn_corpus.json` and `/tmp/pcn_score.json` in the pod, and nothing
else. No S3 writes, no Neo4j,
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcn_score  # noqa: E402  (sibling module, not an installed package)
import pcn_crop_seal  # noqa: E402  (sibling module, not an installed package)

# Belt-and-braces cwd check. The load-bearing fix lives in
# doc_tools/plugins/base.py::AugmentationPlugin._ensure_prompts_available (raises
# PromptUnavailableError naming every missing prompt file), because THIS harness is
# not the only caller of the plugin — a Dagster run is another. But this script is
# launched directly, sometimes from the wrong cwd, and the failure mode measured
# 2026-09-24 was ugly to diagnose: three notices returned 0 parts while a fourth
# looked fine (it never needed a prompt, reading the deterministic text-layer tier
# instead), and the only tell was wall time. Failing here, before a single S3 call,
# gives a name and a fix instead of a silent partial run.
_REQUIRED_PROMPT_FILES = [
    "prompts/sustainment_header_instructions.md",
    "prompts/sustainment_parts_instructions.md",
]


def _assert_prompts_resolvable():
    missing = [p for p in _REQUIRED_PROMPT_FILES if not os.path.exists(p)]
    if missing:
        raise SystemExit(
            f"Required prompt file(s) not found from cwd={os.getcwd()!r}: {missing}. "
            "Run this script from the application root (/app in the pod)."
        )


BUCKET = os.getenv("PCN_BUCKET", "processing-artifacts")
PREFIX = "sustainment/inbound/"
OUT = os.getenv("PCN_OUT", "/tmp/pcn_corpus.json")
SCORE_OUT = os.getenv("PCN_SCORE_OUT", "/tmp/pcn_score.json")
SEAL_OUT = os.getenv("PCN_SEAL_OUT", "/tmp/pcn_crop_seal.json")

# THE CORPUS AND THE GROUND TRUTH, in one place.
#
# `gt` is the affected-part count established in docs/pcn-corpus-validation-2026-09-21.md
# and re-confirmed against stored extraction.json in
# docs/pcn-product-baseline-2026-09-22.md section 5. The total is 898. Do not adjust a
# gt value to make a run look better; a disagreement with these numbers is the finding.
#
# TYC MOVED 24 -> 26 ON 2026-09-24, and with it the total 896 -> 898. This is the one
# permitted kind of change to these numbers: ground truth was WRONG, not unflattering.
# Two of TYC's Customer-Part-Number cells hold two part numbers each joined by
# comma+newline, and pcn_ground_truth.json carried them glued so the total would read
# as the documented 24. A two-part cell is two parts. Splitting them raises the
# denominator and LOWERS the score (893/898), which is the direction that tells you it
# was a correction and not a tune. Reports predating this keep their 896.
TARGETS = [
    {"file": "TYC-PCN-24-210412.pdf",           "gt": 26},
    {"file": "Diodes_PCN_2683_Rev1_EOL.pdf",    "gt": 402},
    {"file": "Diodes_PCN_2683_FULLGREEN.pdf",   "gt": 402},
    {"file": "EOL-36_BYV34-400,-BYV34-500.pdf", "gt": 4},
    {"file": "ADI_PDN_23_0120.pdf",             "gt": 1},
    {"file": "PCN23-002.pdf",                   "gt": 18},
    {"file": "PCN24-029.pdf",                   "gt": 1},
    {"file": "onsemi_Generic_IPCN25300X.pdf",   "gt": 19},
    {"file": "onsemi_Generic_PD26044X1.pdf",    "gt": 25},
]
# Progress-line denominator only. The score comes from the PART NUMBERS in
# pcn_ground_truth.json, and check_ground_truth() makes a disagreement fatal.
GT_TOTAL = sum(t["gt"] for t in TARGETS)

# Three notices have MORE THAN ONE manifest in the bucket and the copies are not
# equivalent — see docs/pcn-product-baseline-2026-09-22.md section 3, which rules on
# provenance for each. Pinning the manifest key here keeps a later run from silently
# picking a different copy and reporting the difference as a code change.
PREFER = {
    # Three byte-identical copies of the PDF exist (diodes_2683, diodes_bbox,
    # diodes_tier1 — all MD5 abe083fe8bab0e963874777280e8e293). Identical *source
    # bytes* do not make the manifests interchangeable: each names its own
    # text_location, produced by its own partitioning run, and THAT is what this
    # harness reads. The baseline measured diodes_bbox, so this measures diodes_bbox.
    "Diodes_PCN_2683_Rev1_EOL.pdf":
        "sustainment/inbound/diodes_bbox/generated/Diodes_PCN_2683_Rev1_EOL_pdf/manifest.json",
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


def check_ground_truth():
    """TARGETS and pcn_ground_truth.json must agree, or the run has two answers.

    TARGETS carries a count so the progress lines have something to print against
    while the run is still going; the ground-truth file carries the part numbers
    that actually decide the score. Two places holding the same fact is how they
    drift, so the disagreement is made fatal at startup rather than discovered in
    a report afterwards.
    """
    gt = pcn_score.load_ground_truth()
    for t in TARGETS:
        entry = gt.get(t["file"])
        if entry is None:
            raise SystemExit(f"{t['file']} is in TARGETS but not in the ground-truth file")
        if entry["count"] != t["gt"]:
            raise SystemExit(f"{t['file']}: TARGETS says gt={t['gt']}, "
                             f"ground truth says {entry['count']}")
        if len(entry["mpns"]) != entry["count"]:
            raise SystemExit(f"{t['file']}: ground truth lists {len(entry['mpns'])} "
                             f"MPNs but declares count={entry['count']}")
    extra = set(gt) - {t["file"] for t in TARGETS}
    if extra:
        raise SystemExit(f"ground truth has notices TARGETS does not: {sorted(extra)}")


def main():
    _assert_prompts_resolvable()
    check_ground_truth()
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

    # The per-notice flag table stays, because the instrumentation counters are
    # what say HOW a notice went wrong. It deliberately no longer carries a
    # gt/got/gap column: a count next to ground truth invites reading the count
    # as the score, and on 2026-09-23 exactly that turned a substitution into a
    # reported pass. The score comes from pcn_score, below, and only from there.
    print()
    print(f"{'notice':38} {'emitted':>8}  review  flags")
    for t in TARGETS:
        r = results[t["file"]]
        if not r.get("ok"):
            print(f"{t['file']:38} {'ERR':>8}  {r.get('error')}")
            continue
        st = r["stats"]
        flags = ",".join(k for k in
                         ("crops_failed", "crops_truncated", "crops_near_cap", "crops_row_short")
                         if st.get(k)) or "-"
        print(f"{t['file']:38} {r['parts']:>8}  {str(r['needs_review']):>6}  {flags}")

    print()
    scored = pcn_score.score_run(results, pcn_score.load_ground_truth())
    print(pcn_score.render(scored))
    with open(SCORE_OUT, "w") as f:
        json.dump(scored, f, indent=2)
    print(f"\nWROTE {OUT}")
    print(f"WROTE {SCORE_OUT}")

    # Crop-seal: does the shipped crop-bottom repair actually contain the glyphs
    # on these notices' real PDFs? Read-only, no S3 writes — see pcn_crop_seal.py.
    # Wrapped broad: a scoring run that already succeeded must not be reported as
    # failed because the seal itself hit an unrelated problem.
    sealed = None
    try:
        # bucket/pick_fn/files passed explicitly so the seal never imports this
        # module back — see pcn_crop_seal._harness for why that matters.
        sealed = pcn_crop_seal.seal_corpus(
            c, by_file, files=[t["file"] for t in TARGETS],
            bucket=BUCKET, pick_fn=pick)
        print()
        print(pcn_crop_seal.render(sealed))
        with open(SEAL_OUT, "w") as f:
            json.dump(sealed, f, indent=2, default=str)
        print(f"WROTE {SEAL_OUT}")
    except Exception as e:
        print(f"CROP SEAL SKIPPED: {type(e).__name__}: {e}")

    if not all(r.get("ok") for r in results.values()):
        return 1
    tt = scored["totals"]
    seal_ok = sealed is None or (
        sealed["totals"]["repaired_cut_tables"] == 0 and sealed["totals"]["errors"] == 0)
    return 0 if (tt["exact"] == tt["gt"] and not tt["spurious"]
                 and not tt["missing"] and not tt["malformed"] and seal_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
