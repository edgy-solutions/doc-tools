"""Recompute (or re-check) the BASELINE_RATIOS in `doc_tools.utils.text_layer_health`.

The detector's constants are measured, not chosen, so they need a way to be re-measured
when the corpus grows or a new vendor's typography turns up. This prints, per notice, the
control count and every judged ligature pair's retention under the CURRENT constants, then
prints the ratios recomputed from the notices you declare healthy -- so a drift between
what is committed and what the corpus now says is visible in one run.

Two ways in, because the measurement has to be runnable from both sides:

    # in the pod, against MinIO, using the corpus run's own manifest picker
    python scripts/text_layer_baseline.py --healthy-only

    # on a workstation, against a dump of the same elements
    python scripts/text_layer_baseline.py --elements corpus_elements.json

`--damaged` names the notices that are KNOWN damaged; they are excluded from the baseline
and reported separately, because a baseline computed over a document with no `ti` in it
would define the damage as normal and the detector would stop firing.
"""
import argparse
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from doc_tools.utils import text_layer_health as H  # noqa: E402

DAMAGED_DEFAULT = ("TYC-PCN-24-210412.pdf",)


def load_from_dump(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {fn: H.text_of_elements(rec["elements"]) for fn, rec in data.items()}


def load_from_s3():
    sys.path.insert(0, "/app/scripts")
    import pcn_corpus_run as R

    c = R.s3_client()
    by_file = R.find_manifests(c)
    out = {}
    for t in R.TARGETS:
        fn = t["file"]
        if fn not in by_file:
            continue
        _key, m = R.pick(fn, by_file[fn])
        elements = json.loads(
            c.get_object(Bucket=R.BUCKET, Key=m["text_location"])["Body"].read())
        out[fn] = H.text_of_elements(elements)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elements", help="local JSON dump: {filename: {elements: [...]}}")
    ap.add_argument("--damaged", nargs="*", default=list(DAMAGED_DEFAULT))
    ap.add_argument("--healthy-only", action="store_true",
                    help="print only the recomputed baseline block")
    args = ap.parse_args()

    texts = load_from_dump(args.elements) if args.elements else load_from_s3()
    damaged = set(args.damaged)

    totals = {b: 0 for b in H.LIGATURE_BIGRAMS}
    control_total = 0

    if not args.healthy_only:
        print("=== per notice, under the COMMITTED constants ===")
    for fn in sorted(texts):
        text = texts[fn]
        res = H.assess_text_layer(text)
        detail = res["text_layer_detail"]
        if not args.healthy_only:
            flag = "DEGRADED" if res["text_layer_degraded"] else "ok"
            print("  %-34s %-9s retention=%s control=%d%s"
                  % (fn[:34], flag, res["text_layer_retention"],
                     detail["control_bigram_count"],
                     "  [declared damaged]" if fn in damaged else ""))
            for b in sorted(detail["judged"]):
                d = detail["judged"][b]
                print("        %-3s obs=%-5d exp=%-8s retention=%.3f %s"
                      % (b, d["observed"], d["expected"], d["retention"],
                         "<-- fires" if d["retention"] < H.DEGRADED_THRESHOLD else ""))
        if fn in damaged:
            continue
        words = H._words(text)
        control_total += sum(H._counts(words, H.CONTROL_BIGRAMS).values())
        for b, n in H._counts(words, H.LIGATURE_BIGRAMS).items():
            totals[b] += n

    print()
    print("=== baseline recomputed over %d healthy notices (control n=%d) ==="
          % (len(texts) - len(damaged & set(texts)), control_total))
    drift = []
    for b in H.LIGATURE_BIGRAMS:
        got = totals[b] / control_total if control_total else 0.0
        committed = H.BASELINE_RATIOS.get(b, 0.0)
        delta = abs(got - committed)
        if delta > 0.02:
            drift.append((b, committed, got))
        print('    "%s": %.4f,   # committed %.4f%s'
              % (b, got, committed, "   <-- DRIFT" if delta > 0.02 else ""))
    print()
    print("DRIFT: %s" % (drift or "none, committed constants match the corpus"))


if __name__ == "__main__":
    main()
