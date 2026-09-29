"""Do the NoticeHeader fields AGREE across repeated fires of the same corpus?

Two modes, both driven off the stdout of `scripts/pcn_corpus_run.py` (BAML INFO
logging included, so each notice's `---Parsed Response (class NoticeHeader)---`
block is present):

  default    Compares the RAW model output for `doc_id`, `doc_type`, `mfr`,
             `mfr_source`, `pub_date`, `pub_date_source`, `doc_level_ltb_date`,
             `doc_level_ltb_date_source` — exactly what the header LLM emitted,
             before any downstream trust logic touches it. No S3, no doc_tools
             import, no network: it only reads the log files given on argv.

  --written  Compares what would actually be WRITTEN to the graph, which is the
             operative gate. `doc_type` does not come from the model at all —
             it is `doc_tools.utils.sustainment_header_trust.doc_type_from_titles`
             applied to the notice's own `Title` elements (see that function's
             docstring: the header model's `doc_type` flips PCN/PDN/PCN across
             identical-input fires, a vendor's own title does not). `mfr`,
             `pub_date`, and `doc_level_ltb_date` are taken AFTER
             `refuse_unsourced_header_values(header_dict, index)` — a value the
             source document does not actually contain is dropped, not merely
             flagged — run against each notice's real positioned index, built
             from the same elements the corpus run itself extracted from MinIO.
             This mode needs S3 credentials (`S3_ENDPOINT_URL`,
             `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) and a `doc_tools`
             importable on `PYTHONPATH`.

WHY "AGREE", NOT "IDENTICAL BYTES". Temperature 0 does not make the inference
server bit-deterministic, and the margin is measured, not assumed. Over three
header-only fires of these 9 notices with the client pinned at temperature 0
(2026-09-28), the RAW output still disagreed on 6 fields across 4 notices, while
the same 3 fires' WRITTEN values disagreed on 2 fields across 2 notices. On the
parts side the pinned vision client came closer to identity — its out-token
counts matched exactly between fires 2 and 3 over all 19 calls, and fire 1
differed on 3 — which is precisely why identity must not be the criterion: a
run that is *nearly* deterministic fails an identity test for reasons that say
nothing about correctness. So this instrument's question is never "did
fire 2 reproduce fire 1's exact JSON" but "did every fire land on the SAME
value for each field that matters" — agreement is the criterion, and any
disagreement is reported by field and by value, never summarized away.

WHY THIS MATTERS FOR RE-INGEST. A header field that disagrees across
identically-configured fires is not a one-off model hiccup to shrug off — it
means the value that lands in the graph depends on which fire happened to run,
which is exactly the failure mode `--written` mode exists to close (a title
derivation and a source-refusal are meant to make the WRITTEN value stable
even when the raw model output is not). Header agreement is part of the
re-ingest gate ALONGSIDE the parts score from `pcn_score.py` — a corpus run
that scores 898/898 on parts but flips `mfr` between fires has not earned a
re-ingest either.

USAGE:
    python scripts/pcn_header_agreement.py fire1.log fire2.log [fire3.log ...]
    python scripts/pcn_header_agreement.py --written fire1.log fire2.log ...

Exit codes: 0 = every compared field agreed on every notice; 1 = at least one
notice disagreed on at least one field; 2 = usage error (fewer than two logs).
"""
import json
import os
import re
import sys

MARKER = "---Parsed Response (class NoticeHeader)---"

# {log basename: {notice: why}} for blocks that needed tolerant recovery. Reported
# by main() so a recovered parse is never silent -- a gate must not be told
# "agreed" without being told the log was damaged.
PARSE_RECOVERED = {}


class _NotMeasured:
    """A field the log never yielded, as distinct from a field the model emitted as
    null. Tolerant recovery stops at the damage, and the fields after it are simply
    not in evidence -- `doc_level_ltb_date` really was lost this way on a real fire.
    Comparing that as None asserts the model emitted null, which is a claim the log
    does not support, and it lands in the table as a value disagreement. It must
    still fail the gate (a gate needs a measurement), but under its own name."""

    __slots__ = ()

    def __repr__(self):
        return "<NOT MEASURED>"


NOT_MEASURED = _NotMeasured()

# Written fields derived from the block itself; `doc_type` is excluded because it comes
# from the notice's Title elements, not from the model's output, so log damage cannot
# make it unmeasured.
WRITTEN_FROM_BLOCK = ("mfr", "pub_date", "doc_level_ltb_date")
NOTICE_RE = re.compile(r"^--- (\S+\.pdf)\b")

# BAML logs asynchronously, so another function's output can be spliced into the
# MIDDLE of a line of a parsed block. Observed on a real fire (2026-09-28, TYC at
# pin 7104b595), where the block's last line ran
#     "summary": "... parts due2026-09-29T03:13:52.328 [BAML INFO] Function TranscribePage:
# leaving the JSON string unterminated. Cutting the host line at the splice is what
# makes the fields before it readable.
INTERLEAVE_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+\s*\[BAML\b")

# "field": <json scalar>. Scalars only, deliberately: every field this instrument
# compares is a scalar, and half of an array is not a value worth recovering.
SCALAR_RE = re.compile(
    r'"(?P<k>[A-Za-z_][A-Za-z0-9_]*)"\s*:\s*'
    r'(?P<v>"(?:[^"\\]|\\.)*"|null|true|false|-?\d+(?:\.\d+)?)'
)

# Default-mode comparison: the raw NoticeHeader fields as the model emitted them.
RAW_FIELDS = (
    "doc_id", "doc_type", "mfr", "mfr_source",
    "pub_date", "pub_date_source",
    "doc_level_ltb_date", "doc_level_ltb_date_source",
)

# --written-mode comparison: what actually reaches the graph after doc_type is
# re-derived from the title and the source-refusal has run. Order and membership
# match `pinned_written_agreement.py`'s proven WRITTEN tuple.
WRITTEN_FIELDS = ("doc_type", "mfr", "pub_date", "doc_level_ltb_date")


def _block_region(lines, start):
    """The lines belonging to the block that begins at `start`, stopping at the next
    notice line, the next marker, or end of file.

    THIS BOUND IS THE FIX. The previous version brace-matched with no stop condition
    and then resumed at wherever it had got to, so a block whose braces never balanced
    consumed the REST OF THE FILE: every later notice went unseen and was then reported
    as ABSENT, which reads as "that fire never measured it" rather than "one block did
    not parse". On a real 9-notice fire that turned one corrupt block into 8 bogus
    ABSENTs and a failing gate.
    """
    out = []
    j = start + 1
    while j < len(lines):
        s = lines[j]
        if NOTICE_RE.match(s) or s.strip() == MARKER:
            break
        out.append(s)
        j += 1
    return out, j


def _parse_strict(region):
    """The original brace-match, confined to one block's region. dict, or None if the
    braces never balance or the text is not JSON."""
    buf, depth, started = [], 0, False
    for s in region:
        if not started:
            if "{" not in s:
                if s.strip() and not s.startswith(" "):
                    return None
                continue
            started = True
        buf.append(s)
        depth += s.count("{") - s.count("}")
        if depth <= 0:
            break
    if not started or depth > 0:
        return None
    try:
        return json.loads("\n".join(buf))
    except Exception:  # noqa: BLE001
        return None


def _parse_tolerant(region):
    """Scalar fields recovered from a block that never closes: cut each line at an
    interleaved BAML stamp, then take the first occurrence of each field.

    This recovers the fields BEFORE the damage and nothing after it. How much that
    is depends on where the splice landed, and it is NOT always everything the gate
    compares: on the real fire-1 TYC block recovery reached `revision`, losing
    `doc_level_ltb_date` and `doc_level_ltb_date_source`. A field after the damage is
    left ABSENT, and `compare` renders absence as NOT_MEASURED rather than None --
    recovery narrows the loss, it does not erase it.
    """
    text = "\n".join(
        (s[:m.start()] if (m := INTERLEAVE_RE.search(s)) else s) for s in region
    )
    out = {}
    for m in SCALAR_RE.finditer(text):
        k = m.group("k")
        if k in out:
            continue
        try:
            out[k] = json.loads(m.group("v"))
        except Exception:  # noqa: BLE001
            continue
    return out


def headers_from_log(path):
    """{notice_filename: {field: value}} — the LAST parsed NoticeHeader block per
    notice in this log.

    A notice can be reprocessed within a single fire (e.g. a retry), and the block
    that determines what gets written is the LAST one, so the last block wins.

    Blocks are read one bounded region at a time (see `_block_region`). A region that
    parses as JSON is used as-is; one that does not falls back to scalar recovery, and
    the notice is recorded in `PARSE_RECOVERED` so the caller can say so out loud. A
    region that yields nothing at all keeps the old `_parse_error` marker.
    """
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    out, notice, i = {}, None, 0
    while i < len(lines):
        if NOTICE_RE.match(lines[i]):
            notice = NOTICE_RE.match(lines[i]).group(1)
            i += 1
            continue
        if lines[i].strip() == MARKER and notice:
            region, end = _block_region(lines, i)
            parsed = _parse_strict(region)
            if parsed is None:
                parsed = _parse_tolerant(region)
                if parsed:
                    PARSE_RECOVERED.setdefault(os.path.basename(path), {})[notice] = (
                        "block did not close (interleaved log); %d scalar field(s) "
                        "recovered from before the splice" % len(parsed)
                    )
                else:
                    parsed = {"_parse_error": "block unreadable"}
                    PARSE_RECOVERED.setdefault(os.path.basename(path), {})[notice] = (
                        "block unreadable, nothing recovered"
                    )
            out[notice] = parsed  # LAST block wins
            i = end
            continue
        i += 1
    return out



def written_from_raw(fires, index_by_file):
    """Replay each fire's raw NoticeHeader dicts through the same trust logic the
    product applies before writing, using each notice's real positioned index.

    Returns `(written_fires, refusals)` where `written_fires` has the same shape
    as `fires` (list of `(name, {notice: {field: value}})`) restricted to
    `WRITTEN_FIELDS`, and `refusals` is `[(fire_name, notice, reason), ...]`.
    """
    from doc_tools.utils import sustainment_header_trust as sht

    written_fires = []
    refusals = []
    for name, raw in fires:
        w = {}
        for fn, hdr in raw.items():
            if fn not in index_by_file or not isinstance(hdr, dict):
                continue
            index, titles = index_by_file[fn]
            d = dict(hdr)
            reasons = sht.refuse_unsourced_header_values(d, index)
            doc_type, _doc_type_source = sht.doc_type_from_titles(titles)
            d["doc_type"] = doc_type
            # A written value computed from a raw field the log never yielded is
            # not a measurement of anything, however well the trust logic ran on it.
            w[fn] = {
                k: (NOT_MEASURED if k in WRITTEN_FROM_BLOCK and k not in hdr
                    else d.get(k))
                for k in WRITTEN_FIELDS
            }
            for r in reasons:
                refusals.append((name, fn, r))
        written_fires.append((name, w))
    return written_fires, refusals


def build_index_by_file():
    """Fetch every corpus notice's elements from MinIO and build its positioned
    index, reusing `pcn_corpus_run.py`'s own S3 plumbing rather than duplicating
    it (`s3_client`, `find_manifests`, `pick`, `BUCKET`, `TARGETS`)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pcn_corpus_run as R  # noqa: E402  (sibling module, not an installed package)
    from doc_tools.utils import provenance  # noqa: E402
    from doc_tools.utils import sustainment_header_trust as sht  # noqa: E402

    # Which doc_tools this run measures, before a single S3 call — same reason
    # pcn_corpus_run.py prints its extractor path before doing anything else.
    print(f"extractor  = {os.path.dirname(sht.__file__)}")

    c = R.s3_client()
    by_file = R.find_manifests(c)
    index_by_file = {}
    for t in R.TARGETS:
        fn = t["file"]
        if fn not in by_file:
            continue
        key, m = R.pick(fn, by_file[fn])
        elements = json.loads(
            c.get_object(Bucket=R.BUCKET, Key=m["text_location"])["Body"].read())
        index_by_file[fn] = (
            provenance.build_positioned_index(elements),
            sht.titles_from_elements(elements),
        )
    return index_by_file


def compare(fires, fields):
    """Print the per-notice agreement table for `fires` (list of `(name, {notice:
    {field: value}})`) over `fields`.

    Returns `(notices, disagreements, unmeasured)`, both lists of `(notice, field)`.
    They are kept apart deliberately: a DISAGREE is evidence the fires produced
    different values, a NOT MEASURED is evidence of nothing at all. Both fail the
    gate, and conflating them would let a damaged log be reported as instability in
    the extractor."""
    notices = []
    for _, h in fires:
        for n in h:
            if n not in notices:
                notices.append(n)

    disagreements, unmeasured = [], []
    for n in notices:
        vals = [h.get(n) or {} for _, h in fires]
        missing = [name for (name, _), v in zip(fires, vals) if not v]
        if missing:
            # A notice one fire measured and another did not CANNOT be said to agree —
            # nothing was measured to agree with — and this is a gate: the usual cause is
            # a fire that died partway, which is the last thing to wave through. ONE
            # failure, named by its real cause: comparing the present fire's fields
            # against a fire that has none would report every field as a disagreement
            # and bury the one fact that matters under six derived ones.
            print(f"{n:44s} ABSENT")
            print(f"      not measured by: {missing}")
            disagreements.append((n, "<absent>"))
            continue
        row_bad, row_unmeasured = [], []
        for f in fields:
            seen = [v.get(f, NOT_MEASURED) for v in vals]
            if any(s is NOT_MEASURED for s in seen):
                row_unmeasured.append((f, seen))
            elif len({json.dumps(s, sort_keys=True, default=str) for s in seen}) > 1:
                row_bad.append((f, seen))
        if row_bad:
            verdict = "DISAGREE"
        elif row_unmeasured:
            verdict = "NOT MEASURED"
        else:
            verdict = "agree"
        print(f"{n:44s} {verdict}")
        for f, seen in row_bad:
            print(f"      {f:22s} " + " | ".join(repr(s) for s in seen))
            disagreements.append((n, f))
        for f, seen in row_unmeasured:
            # Named separately so nobody reads a damaged log as evidence that the
            # values differ. The gate still fails; the reason is different.
            print(f"      {f:22s} " + " | ".join(repr(s) for s in seen)
                  + "   <- not in evidence, not a value difference")
            unmeasured.append((n, f))
    return notices, disagreements, unmeasured


def main(argv):
    written = "--written" in argv
    logs = [a for a in argv if a != "--written"]
    if len(logs) < 2:
        print("usage: pcn_header_agreement.py LOG LOG [LOG ...] [--written]",
              file=sys.stderr)
        print("need at least two logs to measure agreement across fires",
              file=sys.stderr)
        return 2

    fires = [(os.path.basename(p), headers_from_log(p)) for p in logs]
    print(f"{len(fires)} fires: " + ", ".join(n for n, _ in fires))
    if PARSE_RECOVERED:
        # Say it before the verdict, not after. A gate that reports agreement off a
        # damaged log has to disclose the damage, or the next reader takes "HELD" to
        # mean the log was clean.
        n = sum(len(v) for v in PARSE_RECOVERED.values())
        print(f"PARSER NOTE: {n} block(s) did not parse as JSON and were read by "
              f"scalar recovery. Compared fields are whatever survived; a field "
              f"after the damage is treated as ABSENT, never invented.")
        for log, per in sorted(PARSE_RECOVERED.items()):
            for notice, why in sorted(per.items()):
                print(f"   {log:24s} {notice:34s} {why}")
    print()

    refusals = []
    if written:
        index_by_file = build_index_by_file()
        fires_cmp, refusals = written_from_raw(fires, index_by_file)
        fields = WRITTEN_FIELDS
    else:
        fires_cmp, fields = fires, RAW_FIELDS

    notices, disagreements, unmeasured = compare(fires_cmp, fields)

    if written:
        print()
        print(f"refusals: {len(refusals)} over {len(fires)} fires")
        for name, fn, reason in refusals:
            print(f"   {name:20s} {fn[:30]:30s} {reason}")

    print()
    if disagreements or unmeasured:
        if disagreements:
            print(f"HEADER AGREEMENT FAILED on {len(disagreements)} field(s)")
        if unmeasured:
            # Say what is true: the gate is not met, but these fields carry no verdict
            # on whether the fires agree. Re-run the fire to measure them.
            print(f"HEADER AGREEMENT NOT ESTABLISHED on {len(unmeasured)} further "
                  f"field(s): a fire's log was damaged where that field is emitted, "
                  f"so no comparison was possible. This is not a disagreement.")
        return 1
    # "agreed", never "identical" — see WHY "AGREE", NOT "IDENTICAL BYTES" above. The
    # distinction is the whole point of the gate and must not leak out of the summary line.
    print(f"HEADER AGREEMENT HELD over {len(notices)} notices x {len(fields)} fields")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
