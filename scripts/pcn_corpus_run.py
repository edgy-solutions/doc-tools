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

TO MEASURE A CANDIDATE TREE rather than the deployed pin, set PYTHONPATH — copying a
checkout into the pod is NOT enough:

    kubectl exec -n sandbox <pod> -- sh -c \
        'cd /tmp/cand && PYTHONPATH=/tmp/cand:/app python scripts/pcn_corpus_run.py'

The pod sets `PYTHONPATH=/app` and this file lives in `scripts/`, so without that the
candidate's `doc_tools` is never imported and the run measures the image while looking
entirely normal. Every run prints `extractor = <path>` twice for exactly this reason;
read it before quoting a number. See `import_provenance` below.

DO NOT trust an `echo EXIT_CODE=$?` sentinel written from a PowerShell double-quoted
string: PowerShell expands its own `$?` (a boolean) before the payload reaches the
pod, and you get `EXIT_CODE=True`. This script's completion signal is the final line
of its own output and the presence of every notice key in the JSON.

WRITES: `/tmp/pcn_corpus.json` and `/tmp/pcn_score.json` in the pod, and nothing
else. No S3 writes, no Neo4j,
no Jena, no Weaviate, no DataHub, no Dagster materialization. The extraction
functions are called directly and results are kept in memory.
"""
import hashlib
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
from doc_tools.utils.ingest_rates import render_rates, summarize_rates  # noqa: E402

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


def import_provenance(doc_tools_file: str, driver_file: str) -> dict:
    """Which `doc_tools` this run imported, and whether it is this driver's own tree.

    Sibling of `_assert_prompts_resolvable` above, for the same failure shape: the run
    completes, prints plausible numbers, and never touched the thing under test. Measured
    2026-09-27, and it voided two measurements before anyone looked.

    The pod sets `PYTHONPATH=/app`, and this driver lives in `scripts/`. So `sys.path[0]`
    is `<tree>/scripts` — a directory with no `doc_tools` package inside it — and `/app`
    wins every import. That is CORRECT for the documented use (measure the deployed pin)
    and silently wrong for the other one (copy a candidate tree into /tmp and measure it):
    the candidate's modules are never loaded. The half of that bug which announced itself
    was an `AttributeError` for a symbol only the candidate defines; the half that did not
    was a baseline-vs-candidate A/B in which both arms ran identical `/app` code and
    dutifully agreed.

    The spot-check that hides it is `cd <tree> && python -c "import doc_tools"`, because
    `-c` puts the cwd first and prints the candidate path. Only a script under `scripts/`
    reproduces what a real run resolves.
    """
    pkg_dir = os.path.realpath(os.path.dirname(doc_tools_file))
    tree = os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(driver_file)), os.pardir))
    return {"package": pkg_dir, "tree": tree,
            "is_driver_tree": pkg_dir == os.path.realpath(os.path.join(tree, "doc_tools"))}


def render_import_provenance(p: dict) -> str:
    """Two lines naming what is being measured, plus a warning when those differ.

    Printed twice on purpose — once at startup and once beside the score — because a
    report is copied from the tail of a log, and a provenance line scrolled off the top
    protects nobody.
    """
    lines = [f"extractor  = {p['package']}", f"driver     = {p['tree']}"]
    if not p["is_driver_tree"]:
        lines.append(
            "WARNING  the extractor is NOT this driver's tree, so every number below "
            f"describes {p['package']} and says nothing about uncommitted work in "
            f"{p['tree']}. To measure this tree instead, relaunch with "
            f"PYTHONPATH={p['tree']}:/app")
    return "\n".join(lines)


BUCKET = os.getenv("PCN_BUCKET", "processing-artifacts")
PREFIX = "sustainment/inbound/"
OUT = os.getenv("PCN_OUT", "/tmp/pcn_corpus.json")
SCORE_OUT = os.getenv("PCN_SCORE_OUT", "/tmp/pcn_score.json")
SEAL_OUT = os.getenv("PCN_SEAL_OUT", "/tmp/pcn_crop_seal.json")

# THE CORPUS AND THE GROUND TRUTH, in one place.
#
# `gt` is the affected-part count established in docs/pcn-corpus-validation-2026-09-21.md
# and re-confirmed against stored extraction.json in
# docs/pcn-product-baseline-2026-09-22.md section 5. The total is 924 (898 until the
# 2026-10-10 widening below). Do not adjust a
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
    # WIDENED 2026-10-10, the second permitted kind of change to these numbers:
    # two notices INGESTED, which is the only way this corpus grows (the bucket
    # was enumerated in full on 2026-09-30 and held nothing unseen). TI carries
    # no last-time-buy date at all and is the first `expect_absent` header field;
    # IDT's parts grid is COLUMN-MAJOR, a shape no other notice here has. Total
    # 898 -> 924 over 496 -> 522 distinct.
    {"file": "TI_PCN_20210316000.pdf",          "gt": 9},
    {"file": "IDT_PDN_OV-19-05.pdf",            "gt": 17},
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
    """Every manifest.json under the inbound prefix, keyed by the filename it declares.

    Resolves each document directory (generated/<base_name>/) through its
    current.json pointer when present (versioned layout,
    doc_tools/components/document_parser.py), else falls back to a legacy
    manifest.json sitting directly in that directory (the 9 pre-versioning
    notices already in MinIO, which have no current.json and never will —
    there is no migration). Each document directory yields AT MOST ONE
    manifest candidate: this is what actually fixes the bug versioning
    introduced — naively globbing every key ending "/manifest.json" would
    also match every {version}/manifest.json nested under a versioned
    directory, so one notice would surface N manifests (one per historical
    version) and silently keep whichever the dict-building loop saw last.
    Different INBOUND COPIES of a notice (e.g. diodes_2683 vs diodes_bbox,
    see PREFER above) are still different document directories and still
    both appear as separate candidates for the same filename — only the
    version fan-out within a single document directory is collapsed.
    """
    current_keys = {}   # doc_dir -> current.json key
    legacy_keys = {}    # doc_dir -> manifest.json key (unversioned layout only)
    token = None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": PREFIX}
        if token:
            kw["ContinuationToken"] = token
        r = c.list_objects_v2(**kw)
        for o in r.get("Contents", []):
            key = o["Key"]
            if key.endswith("/current.json"):
                current_keys[key[: -len("/current.json")]] = key
            elif key.endswith("/manifest.json"):
                # Legacy-shaped iff this manifest.json sits directly under
                # generated/<base_name>/ (parent-of-parent == "generated").
                # A versioned manifest.json sits one level deeper, under
                # generated/<base_name>/<version>/, and is only ever reached
                # via that directory's current.json pointer, never listed
                # here directly.
                parts = key.split("/")
                if len(parts) >= 3 and parts[-3] == "generated":
                    legacy_keys[key[: -len("/manifest.json")]] = key
        if not r.get("IsTruncated"):
            break
        token = r.get("NextContinuationToken")

    by_file = {}
    for doc_dir in set(current_keys) | set(legacy_keys):
        manifest_key = None
        if doc_dir in current_keys:
            try:
                pointer = json.loads(
                    c.get_object(Bucket=BUCKET, Key=current_keys[doc_dir])["Body"].read()
                )
                manifest_key = pointer.get("manifest_key")
            except Exception:
                manifest_key = None
            if not manifest_key:
                # current.json present but unreadable/malformed — fall back
                # to a legacy manifest.json in the same directory if one
                # happens to exist; otherwise this document dir is skipped.
                manifest_key = legacy_keys.get(doc_dir)
        else:
            manifest_key = legacy_keys[doc_dir]

        if not manifest_key:
            continue
        try:
            m = json.loads(c.get_object(Bucket=BUCKET, Key=manifest_key)["Body"].read())
        except Exception:
            continue
        fn = m.get("filename")
        if fn:
            by_file.setdefault(fn, []).append((manifest_key, m))
    return by_file


def pick(fn, candidates):
    """Prefer the manifest this corpus has ruled on; otherwise the lexically first key,
    so an unpinned notice still resolves deterministically across runs.

    PREFER pins a DOCUMENT DIRECTORY (an inbound copy) — matched by prefix, not only by
    exact key. find_manifests() now resolves each document directory through its
    current.json pointer when present (versioned layout), so a pinned notice's surviving
    candidate key may be either the legacy `.../manifest.json` PREFER was written
    against, or `.../{version}/manifest.json` once that directory has been reprocessed.
    Exact-match alone would silently stop pinning the day the pinned copy is first
    reprocessed — falling through to the lexical-first fallback with no code change to
    explain it. find_manifests() already collapses each directory's own version history
    to a single current candidate, so this fallback only ever discriminates between
    genuinely different inbound copies (diodes_2683 vs diodes_bbox, etc.), never between
    stale versions of the same copy.
    """
    want = PREFER.get(fn)
    if want:
        want_dir = want[: -len("/manifest.json")] if want.endswith("/manifest.json") else want
        for key, m in candidates:
            if key == want or key.startswith(want_dir + "/"):
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


def source_content_hash(c, manifest, manifest_key=None, fn=None):
    """sha256 of the SOURCE PDF's bytes, as `notice_identity.classify_pair` expects.

    Why the source PDF and not the extracted text: `content_hash` exists in
    `classify_pair` to answer "are these the same bytes?" ahead of any revision
    comparison, and the thing an ingress sensor holds is the uploaded object. Hashing
    `text.json` instead would answer a different question — two partitioning runs over
    one identical PDF produce different text extractions (that is exactly why `PREFER`
    above has to pin a manifest), so a text hash would report the same document as two.

    `manifest["source_key"]` is declared by the producer
    (doc_tools/components/document_parser.py) and is preferred, because it is the key
    the producer named rather than one derived by string surgery.

    THE FALLBACK IS NOT OPTIONAL, measured 2026-09-30: only 11 of the 22 manifests in
    sandbox MinIO carry `source_key` at all. All three `ADI_PDN_23_0120.pdf` manifests
    and six of the seven `onsemi_Generic_IPCN25300X.pdf` ones predate the field. Without
    a fallback those notices would hash to None forever, the gate would record their
    bytes as unverifiable, and `check_same_bytes` would be permanently inert on exactly
    the documents it exists to guard — green because it never ran. So when the field is
    absent the source PDF is located as a sibling of the manifest's own prefix
    (everything before `/generated/`), which is the same resolution
    `pcn_crop_seal.source_key` already uses against these same manifests.

    Returns None only when both routes fail, because a missing hash must not fail a
    scoring run — the consequence of None is recorded where it is consumed
    (`bytes_coverage` in the gate), not raised here.
    """
    key = manifest.get("source_key")
    if not key and manifest_key and fn:
        pref = manifest_key.split("/generated/")[0] + "/"
        try:
            for o in c.list_objects_v2(Bucket=BUCKET, Prefix=pref).get("Contents", []):
                if o["Key"].endswith("/" + fn):
                    key = o["Key"]
                    break
        except Exception:  # noqa: BLE001
            key = None
    if not key:
        return None
    try:
        body = c.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except Exception:  # noqa: BLE001
        return None
    return "sha256:" + hashlib.sha256(body).hexdigest()


def written_header(notice):
    """The header AS WRITTEN — the values that actually reach the graph, taken off the
    constructed `SustainmentNotice` rather than off the model's raw output.

    THIS IS THE POINT OF RECORDING IT. `pcn_header_agreement.py` had to recover these
    from a fire's stdout: locate each NoticeHeader block, bound it, splice out
    interleaved BAML log stamps, and tolerate blocks whose JSON never closes (on the
    real TYC block that recovery reaches `revision` and loses the two
    `doc_level_ltb_date*` fields outright). Every one of those hazards is an artifact of
    reading a log. The plugin already holds the values; recording them here means the
    gate compares what was written instead of what could be salvaged from print output.

    NORMALIZATION, and why it is not cosmetic. `SustainmentNotice` stores `mfr` and
    `pub_date` as non-Optional strings, so the plugin coerces a missing/refused value to
    "" on the way in. The log-derived path renders the same absence as None. Comparing
    "" against None across two sources would report a DISAGREEMENT where both sources
    observed the same absence, so "" is mapped back to None here — absence has one
    spelling. `doc_type` is left exactly as written, including its "PCN" default, because
    that default is a real written value: it selects the disposition ruleset downstream.
    """
    def blank_to_none(v):
        return v if v not in ("", None) else None

    return {
        # The identity triple first — `notice_identity.build_identity` takes exactly
        # these three, and `revision` is in NEITHER of pcn_header_agreement's compared
        # tuples, so the log path could not supply it at all.
        "mfr": blank_to_none(notice.mfr),
        "doc_id": blank_to_none(notice.doc_id),
        "revision": blank_to_none(notice.revision),
        # The rest of pcn_header_agreement.WRITTEN_FIELDS.
        "doc_type": notice.doc_type,
        "pub_date": blank_to_none(notice.pub_date),
        "doc_level_ltb_date": blank_to_none(notice.doc_level_ltb_date),
    }


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
        # The written header and the source bytes' hash, so a consumer (the release
        # gate) can compare identity and header stability across fires from THIS file
        # and never parse a log. `stats["notice_identity"]` — the composed key — is
        # already inside `stats` below; it is not copied up here, because two copies of
        # one fact in one document is how they drift.
        "written_header": written_header(aug.notice),
        "content_hash": source_content_hash(c, manifest, manifest_key, fn),
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
    check_corpus_enumeration(gt)


def check_corpus_enumeration(gt):
    """TARGETS must also agree with the `_corpus` enumeration, or the run is
    measuring against a corpus nobody wrote down.

    WHAT THIS IS FOR. "Eight documents is the corpus until production traffic
    adds to it" was established by listing every object in every bucket; left in
    prose it would be a claim a reader has to go and re-check. Here it is an
    INPUT: the enumeration states 9 scored rows over 8 distinct document
    contents, 898 harness parts, 496 distinct parts, and every one of those four
    numbers is recomputed from TARGETS and the notices block and must match.

    The distinct-parts arithmetic is the one that catches a real mistake. The
    Diodes pair is one document under two filenames, so 402 of the 898 is the
    same notice scored a second time; 898 - 402 = 496. If a later edit adds a
    notice and bumps gt_parts without working out whether it is a new document,
    this fails at startup instead of shipping a report whose denominator means
    something different from the one before it.
    """
    corpus = pcn_score.load_corpus()
    if not corpus:
        raise SystemExit("ground truth has no `_corpus` block: the corpus is then "
                         "whatever TARGETS happens to say, which is what that block "
                         "exists to prevent")
    files = {t["file"] for t in TARGETS}
    docs = corpus["documents"]
    enumerated = {fn for d in docs for fn in d["filenames"]}
    if enumerated != files:
        raise SystemExit(
            f"`_corpus`.documents and TARGETS name different notices: "
            f"only in _corpus {sorted(enumerated - files)}, "
            f"only in TARGETS {sorted(files - enumerated)}")
    if corpus["scored_entries"] != len(TARGETS):
        raise SystemExit(f"`_corpus`.scored_entries={corpus['scored_entries']} but "
                         f"TARGETS has {len(TARGETS)} rows")
    if corpus["distinct_documents"] != len(docs):
        raise SystemExit(f"`_corpus`.distinct_documents="
                         f"{corpus['distinct_documents']} but documents[] lists "
                         f"{len(docs)}")
    if corpus["gt_parts"] != GT_TOTAL:
        raise SystemExit(f"`_corpus`.gt_parts={corpus['gt_parts']} but TARGETS sums "
                         f"to {GT_TOTAL}")
    # One representative filename per distinct document content, so a document
    # ingested under two names contributes its parts once.
    distinct = sum(gt[d["filenames"][0]]["count"] for d in docs)
    if corpus["distinct_parts"] != distinct:
        raise SystemExit(f"`_corpus`.distinct_parts={corpus['distinct_parts']} but "
                         f"one representative per distinct document sums to {distinct}")


def main():
    _assert_prompts_resolvable()
    check_ground_truth()
    c = s3_client()
    print(f"bucket={BUCKET} endpoint={os.getenv('S3_ENDPOINT_URL')}")
    print(f"pipeline_version={os.getenv('DOC_TOOLS_VERSION', 'doc-tools@unstamped')}")
    print(f"VISION_MAX_TOKENS={os.getenv('VISION_MAX_TOKENS')}")

    # WHICH doc_tools is about to be measured. Before the first S3 call, and before the
    # plugin import below can make the question look answered.
    import doc_tools
    prov = import_provenance(doc_tools.__file__, __file__)
    print(render_import_provenance(prov))

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
                  f"near_cap={st.get('crops_near_cap')} row_short={st.get('crops_row_short')} "
                  f"text_layer_degraded={st.get('text_layer_degraded')} "
                  f"(retention={st.get('text_layer_retention')}) "
                  f"collapsed={st.get('parts_collapsed_duplicate') or 0}/"
                  f"{st.get('parts_collapsed_no_mpn') or 0}",
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
                         ("crops_failed", "crops_truncated", "crops_near_cap",
                          "crops_row_short", "text_layer_degraded")
                         if st.get(k)) or "-"
        print(f"{t['file']:38} {r['parts']:>8}  {str(r['needs_review']):>6}  {flags}")

    # Aggregated RATES over this run — see doc_tools/utils/ingest_rates.py. A rate
    # rising run over run is what a production failure actually looks like; nobody
    # reads the per-notice lines above in steady state. `chunk_tally` is omitted: this
    # harness drives the plugin directly and never writes a chunk, so
    # written_without_vector was never observed here (see that module's NOT-OBSERVED
    # note — it must render as "not observed", never as a 0).
    rates_summary = summarize_rates(results.values())
    print()
    print(render_rates(rates_summary))

    print()
    scored = pcn_score.score_run(results, pcn_score.load_ground_truth())
    scored["rates"] = rates_summary
    print(render_import_provenance(prov))
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
