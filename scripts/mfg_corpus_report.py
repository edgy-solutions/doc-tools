"""Corpus report: the pipeline's own LLM output vs the deterministic extractors.

Operating model (docs/manufacturing-extraction-findings.md, "corpus not
agent-accessible"): the agent builds this instrument; the USER runs it against
the real corpus and returns the report. So the report is a CONTRACT WITH A HUMAN
COURIER — small, self-describing, and safe *by construction*:

  * The report code NEVER writes document text into the report. It emits COUNTS,
    redacted SHAPES (digits -> '#', e.g. 'PN-1001' -> 'PN-####'), and anomaly
    KINDS. Free text is redacted token-wise (letters -> 'a') with only a small
    allowlist of STRUCTURAL keywords preserved, so a heading's *format* is
    legible while its content is not. Values appear only with --include-values.
  * Documents are identified by index + a short hash. The index->object-key map
    goes to a SEPARATE *.local-map.json you keep locally (object keys only, never
    document text).
  * STAMPED: extractor version, config hash, bucket/prefix, doc count, the
    generation range of the parses, timestamp — so run N+1 compares to run N.

Two modes:
  LOCAL (--input DIR): deterministic-only over a directory of text.json files.
  MINIO COMPARISON (--minio-prefix): the real instrument. For each document it
    pairs the pipeline's persisted extraction.json (arm 1 = the LLM) with its
    text.json (the input BOTH arms read) and diffs that against the deterministic
    extractors (arm 2 = the script). Three-way per field: script_only = LLM
    MISSED it, llm_only = script MISSED it, agree.

WHAT CHANGED AFTER THE FIRST REAL CORPUS RUN (2026-09-17, 6 docs). That run was
the product it was supposed to be: it confirmed one prediction overwhelmingly
and exposed three defects IN THIS INSTRUMENT. Reading a broken measurement as a
finding is the failure this round exists to prevent.

  1. ARTIFACT PAIRING WAS WRONG. It assumed text.json lived at
     {base}/generated/*/text.json. In the real bucket it sits BESIDE
     extraction.json, so the operator had to hand-patch the script. Pairing is
     now LAYOUT-AGNOSTIC (sibling, generated/, any nested) and REPORTS which
     layout it found, so the truth is measured instead of assumed. It also walks
     text.json-only and extraction.json-only documents instead of skipping them
     silently — an unpaired doc is a finding (the LLM stage never ran), not a gap
     in the denominator.
  2. THE OPERATIONS DISCRIMINANT CLAIMED A CAUSE IT COULD NOT SUPPORT. It
     reported 57 "procedure_pollution_candidates" while the structural arm found
     ONE operation in six documents. With a blind structural arm, an llm_only
     operation is indistinguishable from a real operation the script missed —
     so the pollution claim is now CONDITIONAL on the structural arm having
     recall, and says so in the report when it abstains. A discriminator that
     misclassifies is worse than none.
  3. TWO COMPARISONS WERE COUNTING IDENTICAL VALUES AS DISAGREEMENTS. The script
     canonicalises 'MP 1234' -> 'MP-1234'; the LLM emitted 'MP1234'; the naive
     normaliser called that a mutual miss. And the LLM packs several standards
     into one string ('MP-123, MP-456', '[MP-123-K, MP-456]'). Both sides now go
     through the SAME family canonicalisation after multi-value splitting. Parts
     compare on a PREFIX-STRIPPED CORE, because agree==0 was an artifact of the
     script keeping 'PN-' while the LLM emits the bare number.

  Also added: NAS/MS cross-field collision measurement (aerospace tokens are
  simultaneously spec numbers and fastener part numbers — the arms were filing
  them in different fields and both were being counted as misses), three-state
  judgment coverage (a bool False is NOT an unanswered field — the old metric
  conflated them), and parse-side diagnostics so an empty document can be
  attributed to an OOM'd/truncated parse rather than blamed on the LLM.

Read-only S3 (list + get). Endpoint/creds from the standard env
(S3_ENDPOINT_URL / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / MINIO_SECURE) —
no new env name invented.

Run (PowerShell):
  # LLM-vs-script comparison over a MinIO prefix
  <python> scripts/mfg_corpus_report.py --minio-prefix manufacturing/ \
      [--bucket processing-artifacts] [--limit N] [--include-values] [--out report.json]
  # deterministic-only over local text.json files
  <python> scripts/mfg_corpus_report.py --input <dir> --label <slice>
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


# --------------------------------------------------------------------------- #
# Redaction helpers — the report's safety is that text is never written, only
# shapes. Digits -> '#'. Free text additionally has letters -> 'a', EXCEPT a
# small allowlist of structural words, so "Operation 0020 - Install Bracket"
# reads as "OPERATION #### - aaaaaaa aaaaaaa": the format is legible, the
# content is not.
# --------------------------------------------------------------------------- #
_KEEP_WORDS = {
    "OPERATION", "OP", "STEP", "TASK", "SECTION", "FIGURE", "FIG", "TABLE",
    "NOTE", "WARNING", "CAUTION", "PAGE", "REV", "REVISION", "SHEET", "ITEM",
    "PROCEDURE", "FINAL", "INSPECT", "INSPECTION", "ASSY", "ASSEMBLY",
}


#: Unicode dashes/spaces, folded to ASCII. The extractor folds these before
#: MATCHING, but the report was shaping the RAW value — so one real family showed
#: up as two shapes, 'AAA-AAA-AAA-###' and 'AAA‑AAA‑AAA‑###', and
#: looked like two different things to add to the config.
_FOLD = {**dict.fromkeys(map(ord, "‐‑‒–—―−"), "-"),
         **dict.fromkeys(map(ord, "   "), " ")}


def _fold(s) -> str:
    return str(s).translate(_FOLD)


def _shape(tok) -> str:
    """Redact a token to its structure: digits -> '#'."""
    return re.sub(r"\d", "#", _fold(tok))


def _shapes(tokens) -> dict:
    return dict(collections.Counter(_shape(t) for t in tokens))


def _shape_alpha(tok) -> str:
    """FULLY redacted shape: letters -> 'A', digits -> '#'.

    Used for document families the committed config does NOT know — which are by
    definition site/customer-specific. `_shape` redacts only digits, so it would
    carry an internal family prefix out of the operator's machine verbatim. That
    is enough to write a pattern from ('AAA-AAA-AAA-###' says everything a regex
    needs) without the report ever naming anyone's scheme.
    """
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "#", _fold(tok)))


def _shapes_alpha(tokens) -> dict:
    return dict(collections.Counter(_shape_alpha(t) for t in tokens))


def _safe_text_shape(text, cap: int = 56) -> str:
    """Redact FREE TEXT: digits -> '#', letters -> 'a', structural words kept."""
    out = []
    for tok in re.findall(r"\S+|\s+", (text or "").strip()[:cap]):
        if tok.isspace():
            out.append(" ")
            continue
        bare = re.sub(r"[^A-Za-z]", "", tok).upper()
        if bare in _KEEP_WORDS:
            out.append(re.sub(r"\d", "#", tok).upper())
        else:
            out.append(re.sub(r"[A-Za-z]", "a", re.sub(r"\d", "#", tok)))
    return "".join(out)


def _topn(counter: collections.Counter, n: int = 8) -> dict:
    return dict(counter.most_common(n))


def _config_hash(cfg) -> str:
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Value canonicalisation — both arms must be normalised THE SAME WAY or
# identical values are scored as mutual misses (defect #3 above).
# --------------------------------------------------------------------------- #
_FILENAME_RE = re.compile(r"figure-\d+-\d+\.jpg$", re.I)
_PART_PREFIX = re.compile(r"^(?:P/?N|PART|ASS?Y)[\s\-.]*", re.I)
_JUDGMENT_FIELDS = ["is_value_added", "is_safety_critical", "process_category",
                    "action_verb", "justification"]
# Scored fields = those with a LEGITIMATE deterministic arm.
#
# `hazard` was REMOVED after the operator checked run 2's values: the LLM emits
# '1.1D' where the document actually says '1.1 -1.3' and, elsewhere, '1.4'. It is
# INFERRING a hazard classification — and inventing the division letter — not
# quoting one. A field the document does not print cannot have a regex arm, and
# scoring it reports the script "missing" text that was never there. It is
# reported unscored, with the reason, so the judgement is visible rather than
# quietly dropped.
_COMPARED_FIELDS = ["standards", "parts", "figures", "operations"]
_LLM_ONLY_FIELDS = {
    "hazard": "NOT SCORED — the LLM infers this; the document does not print it "
              "verbatim (observed: document says '1.1 -1.3' / '1.4', LLM emits "
              "'1.1D', adding a division letter that is not in the text). Treat "
              "LLM hazard values as unverified classifications, not extractions.",
}


def _split_multi(value) -> list:
    """The LLM packs several ids into one string: 'MP-123, MP-456',
    '[MP-123-K, MP-456]', 'MP123; MP456'. Split before canonicalising."""
    s = str(value or "").strip().strip("[]{}()")
    return [p.strip() for p in re.split(r"[;,]", s) if p.strip()]


def _norm_tok(s) -> str:
    return re.sub(r"[\s\-]+", "-", _fold(s).strip().upper()).strip("-")


def _loose(s) -> str:
    """Namespace-free key for cross-field collision detection."""
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


_HAZ_PREFIX = re.compile(r"^CLASS[\s\-]*", re.I)


def _haz_core(v) -> str:
    """Script emits 'Class 1.1D', the LLM emits bare '1.1D' — same namespace
    mismatch as parts, same fix, or identical hazards score as mutual misses."""
    return _HAZ_PREFIX.sub("", _norm_tok(v))


def _part_core(v) -> str:
    """Strip the PN/ASSY namespace so 'PN-1234567-YYY' and the bare
    '1234567-YYY' the LLM emits compare equal (defect #3)."""
    s = re.sub(r"\s+", "-", str(v).strip().upper())
    s = _PART_PREFIX.sub("", s)
    return re.sub(r"-{2,}", "-", s).strip("-")


def _canon_standards(values, cfg, mx):
    """Put arbitrary standard strings through the SAME family canonicalisation
    the script uses. Returns (canonical_set, unrecognised_pieces)."""
    canon, unknown = set(), []
    for raw in values:
        for piece in _split_multi(raw):
            found, _ = mx.extract_standards(piece, cfg)
            if found:
                canon.update(found)
            else:
                unknown.append(_norm_tok(piece))
    return canon, unknown


# --------------------------------------------------------------------------- #
# Arms
# --------------------------------------------------------------------------- #
def _llm_steps(extraction: dict) -> list:
    return [s for aug in (extraction.get("augmentations") or [])
            for s in (aug.get("steps") or [])]


def _tri_state(steps, field) -> dict:
    """Three-state coverage. A bool False is an ANSWER, not an absence — the old
    two-state metric conflated them and made 'starvation' unfalsifiable."""
    n = len(steps)
    absent = true = false = answered = 0
    for s in steps:
        v = s.get(field, None)
        if v is None or (isinstance(v, (str, list, dict)) and len(v) == 0):
            absent += 1
        elif isinstance(v, bool):
            answered += 1
            true += 1 if v else 0
            false += 0 if v else 1
        else:
            answered += 1
    out = {"n": n, "answered": answered, "absent": absent}
    if true or false:
        out["true"], out["false"] = true, false
    return out


def llm_doc_sets(extraction: dict, cfg, mx) -> dict:
    """Doc-level value sets from the persisted extraction.json (arm 1 = LLM)."""
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
    raw_std = coll("standard_ref") | coll("military_and_industry_standards")
    std_canon, std_unknown = _canon_standards(raw_std, cfg, mx)
    raw_parts = {p for v in coll("internal_part_numbers") for p in _split_multi(v)}
    return {
        "standards": std_canon,
        "standards_unknown_family": std_unknown,
        "parts": {_part_core(p) for p in raw_parts if _part_core(p)},
        "parts_raw": raw_parts,
        "figures": figs,
        "operations": {_norm_tok(o) for o in coll("procedure_id")},
        "hazard": {_haz_core(h) for h in coll("hazard_class")},
        "_prose_figrefs": len(figs_all - figs),
        "_n_steps": len(steps),
        "_judgment": {f: _tri_state(steps, f) for f in _JUDGMENT_FIELDS},
    }


def script_doc_sets(elements: list, cfg, mx) -> dict:
    """Doc-level value sets from the deterministic extractors (arm 2 = script)."""
    full = "\n".join(e.get("text", "") or "" for e in elements)
    stds, std_anom = mx.extract_standards(full, cfg)
    parts, _ = mx.extract_part_numbers(full, cfg)
    ops_detailed, _ = mx.extract_operations_detailed(elements, cfg)
    ops = [h["id"] for h in ops_detailed]
    binds, fanom = mx.bind_figures_to_steps(elements, cfg)
    haz = {_haz_core(h) for h in mx.extract_hazard_all(full, cfg)}
    return {
        "standards": set(stds),
        "parts": {_part_core(p) for p in parts if _part_core(p)},
        "parts_raw": set(parts),
        "figures": {b["figure"] for b in binds},
        "operations": {_norm_tok(o) for o in ops},
        "hazard": haz,
        "_bindings": binds,
        "_fig_anomalies": fanom,
        "_std_anomalies": std_anom,
        "_ops_detailed": ops_detailed,
        "_full_text": full,
    }


def _public_family_prefixes(cfg) -> set:
    """Canonical prefixes from the COMMITTED config — public by construction, so
    safe to render verbatim. Anything else is site-specific and gets redacted."""
    return {f["canonical"].upper() for f in cfg["standards"]["families"]}


def _safe_shape(tok, public: set) -> str:
    head = re.match(r"[A-Za-z\-]+", str(tok))
    prefix = head.group(0).upper().strip("-") if head else ""
    return _shape(tok) if prefix in public else _shape_alpha(tok)


def corroborate_llm_values(ls, ss, elements, cfg, mx) -> dict:
    """For EVERY value the LLM emitted, is it actually in the document?

    This is the absolute measure the script-vs-script diff cannot give: a field
    can disagree because the script missed it, OR because the LLM invented it,
    and only the document settles which. It is the same guard the sustainment
    extractor already runs ('affected_mpn not found verbatim in OCR text
    (possible hallucination)'), generalised to every field.

    Verdicts:
      exact    — the value appears verbatim in the text
      loose    — it appears once separators/spacing/case are folded away (the
                 same identifier written differently, or split by a line break)
      absent   — nothing matching is in the document: INVENTED
      base_only (hazard only) — the number is printed but the division letter is not

    Figures are checked against the document's actual crop FILENAMES rather than
    its text, because a filename is never printed in the prose.
    """
    text = ss["_full_text"]
    norm_text = mx.normalize_text(text).upper()
    loose_text = re.sub(r"[^A-Z0-9]", "", norm_text)
    doc_figures = {os.path.basename(str((e.get("metadata") or {}).get("image_path") or "")
                                    .replace("\\", "/")).upper()
                   for e in elements if (e.get("metadata") or {}).get("image_path")}
    public = _public_family_prefixes(cfg)

    out = {}
    for field in ("standards", "parts", "operations", "figures", "hazard"):
        counts, absent_shapes = collections.Counter(), collections.Counter()
        for v in sorted(ls.get(field) or ()):
            if field == "hazard":
                verdict = mx.corroborate_hazard(v, text)
            elif field == "figures":
                verdict = "exact" if str(v).upper() in doc_figures else "absent"
            else:
                nv = mx.normalize_text(v).upper().strip()
                lv = re.sub(r"[^A-Z0-9]", "", nv)
                if nv and nv in norm_text:
                    verdict = "exact"
                elif lv and lv in loose_text:
                    verdict = "loose"
                else:
                    verdict = "absent"
            counts[verdict] += 1
            if verdict == "absent":
                absent_shapes[_safe_shape(v, public)] += 1
        out[field] = {"counts": dict(counts), "absent_shapes": _topn(absent_shapes, 8)}
    return out


def _three_way(sset: set, lset: set) -> dict:
    return {"agree": sorted(sset & lset),
            "script_only": sorted(sset - lset),   # LLM missed it
            "llm_only": sorted(lset - sset)}      # script missed it


# --------------------------------------------------------------------------- #
# Parse-side diagnostics — so an empty document can be ATTRIBUTED (an OOM'd or
# truncated parse) instead of blamed on the LLM.
# --------------------------------------------------------------------------- #
def element_diagnostics(elements: list) -> dict:
    types = collections.Counter(e.get("type") for e in elements)
    pages, with_coords, with_imgpath = set(), 0, 0
    heading_candidates = collections.defaultdict(collections.Counter)
    for e in elements:
        meta = e.get("metadata") or {}
        p = meta.get("page_number")
        if p is not None:
            pages.add(p)
        if meta.get("coordinates"):
            with_coords += 1
        if meta.get("image_path"):
            with_imgpath += 1
        text = (e.get("text") or "").strip()
        # Where DO operation headings live? Short, numeric-or-'operation'-ish
        # text, grouped by element type, redacted to shape. This is what tells
        # the next round which types/patterns the structural arm must accept.
        if text and len(text) <= 80 and re.search(r"(?i)\b(op|operation)\b|\b\d{3,4}\b", text):
            heading_candidates[e.get("type")][_safe_text_shape(text)] += 1
    return {
        "n_elements": len(elements),
        "element_types": _topn(types, 15),
        "n_pages": len(pages),
        "max_page": max(pages) if pages else None,
        "elements_with_coordinates": with_coords,
        "elements_with_image_path": with_imgpath,
        "heading_candidate_shapes": {k: _topn(v, 6) for k, v in
                                     sorted(heading_candidates.items(),
                                            key=lambda kv: -sum(kv[1].values()))[:6]},
    }


def figure_diagnostics(script: dict, elements: list) -> dict:
    binds = script["_bindings"]
    per_step = collections.Counter(b["step_element_id"] for b in binds)
    directions = collections.Counter(b.get("direction") for b in binds)
    markers = sum(1 for e in elements if e.get("type") in ("Image", "Figure"))
    return {
        "_legend": {
            "markers": "figure crops unstructured found in this document",
            "bound": "markers the geometry binder attached to a step (bound + flagged = markers)",
            "flagged": "markers that could NOT be attached -> review lane",
            "distinct_steps_bound_to": "how many different steps received >=1 figure (spread)",
            "max_figures_on_one_step": "worst pile-up on a single step",
            "bind_direction": "attached to the step BEFORE (preceding) or AFTER (following) it",
        },
        "markers": markers,
        "bound": len(binds),
        "flagged": len(script["_fig_anomalies"]),
        "distinct_steps_bound_to": len(per_step),
        "max_figures_on_one_step": max(per_step.values()) if per_step else 0,
        "bind_direction": dict(directions),
        "anomaly_kinds": dict(collections.Counter(a["kind"] for a in script["_fig_anomalies"])),
    }


def _diagnose(elements, n_steps_llm, manifest, elem_diag, structural_ops=0,
              has_extraction=True) -> dict:
    """Name WHERE a document failed, so an empty result is attributed.

    'no steps' is TWO different events and run 2 conflated them. A document with
    no procedural content SHOULD yield zero steps — that is the extractor being
    right, not failing. Only zero steps DESPITE procedural content is a defect.
    Operator-confirmed on run 2: the one `llm_empty` document is a 3-page PDF
    with no steps in it at all, so the flag was accusing a correct result.
    """
    flags = []
    if not has_extraction:
        # NO extraction.json EXISTS. The extraction stage never ran or never
        # wrote output — which is a PIPELINE failure, not a model failure. The
        # previous version had no way to tell, so it saw zero steps beside real
        # structure and blamed the LLM for producing nothing when in truth
        # nothing had run. Opposite defects, opposite fixes.
        flags.append("no_extraction_artifact")
    elif not elements:
        flags.append("parse_empty")
    elif n_steps_llm == 0:
        # structural operations present => the document HAS procedure structure
        # and the LLM still produced nothing. That is the real failure shape.
        flags.append("llm_empty_despite_content" if structural_ops
                     else "no_steps_no_procedural_content")
    mf_pages = None
    if isinstance(manifest, dict):
        mf_pages = len(manifest.get("pages") or []) or None
        if mf_pages and elem_diag["max_page"] and elem_diag["max_page"] < mf_pages:
            # elements stop before the last rendered page -> truncated parse,
            # the shape a memory-bounded/OOM'd hi-res run leaves behind.
            flags.append("parse_truncated_vs_manifest")
    if elements and elem_diag["elements_with_coordinates"] == 0:
        flags.append("no_coordinates")  # geometry figure-binding degraded
    return {"flags": flags or ["ok"], "manifest_pages": mf_pages}


def compare_doc(elements, extraction, manifest, cfg, mx, include_values,
                has_extraction=True) -> dict:
    ss = script_doc_sets(elements, cfg, mx)
    ls = llm_doc_sets(extraction, cfg, mx)
    elem_diag = element_diagnostics(elements)

    fields, tws = {}, {}
    for f in _COMPARED_FIELDS:
        tw = _three_way(ss[f], ls[f])
        tws[f] = tw
        entry = {"agree": len(tw["agree"]),
                 "script_only": len(tw["script_only"]),
                 "llm_only": len(tw["llm_only"]),
                 "script_only_shapes": _shapes(tw["script_only"]),
                 "llm_only_shapes": _shapes(tw["llm_only"])}
        if include_values:
            entry["values"] = tw
        fields[f] = entry

    # Standards the LLM found in a family the committed config does NOT know are
    # script MISSES. Run 2 routed them out of the diff entirely, which is why it
    # reported standards llm_only=0 while the script was in fact missing real ids.
    unk = ls["standards_unknown_family"]
    if unk:
        fields["standards"]["llm_only"] += len(set(unk))
        fields["standards"]["llm_only_unknown_family"] = len(set(unk))
        fields["standards"]["llm_only_shapes"] = {
            **fields["standards"]["llm_only_shapes"], **_shapes_alpha(unk)}

    # Fields with NO legitimate deterministic arm: reported, never scored, and
    # carrying the reason so the exclusion is a visible judgement.
    llm_only_fields = {
        name: {"reason": reason, "count": len(ls.get(name) or ()),
               "shapes": _shapes(ls.get(name) or ())}
        for name, reason in _LLM_ONLY_FIELDS.items()
    }
    # Hazard is not scored, but every claimed value IS checked against the text.
    # exact = printed; base_only = the number is there but the division letter is
    # NOT (an invented letter); absent = wholly inferred. This is the fabrication
    # measurement, run over every document instead of one manual search.
    haz_corr = collections.Counter()
    haz_detail = []
    for v in sorted(ls.get("hazard") or ()):
        verdict = mx.corroborate_hazard(v, ss["_full_text"])
        haz_corr[verdict] += 1
        haz_detail.append({"shape": _shape(v), "corroboration": verdict})
    if "hazard" in llm_only_fields:
        llm_only_fields["hazard"]["corroboration"] = dict(haz_corr)
        llm_only_fields["hazard"]["per_value"] = haz_detail
        # QUARANTINE VERDICT. Measured on the corpus: every hazard value carried a
        # division letter that is not printed. A field the model fabricates in
        # 100% of cases is not "extraction with caveats" — it must not reach a
        # reviewer as though it were read off the page.
        _tot = sum(haz_corr.values())
        _fab = haz_corr.get("base_only", 0) + haz_corr.get("absent", 0)
        if _tot:
            llm_only_fields["hazard"]["verdict"] = (
                "FABRICATED IN ALL CASES — no value is corroborated by the document. "
                "Do NOT surface these as extractions; drop the field or mark it an "
                "unverified classification in the review UI."
                if _fab == _tot else
                f"{_fab}/{_tot} values not corroborated by the document")
        llm_only_fields["hazard"]["corroboration_legend"] = {
            "exact": "the full class incl. division letter IS printed in the document",
            "base_only": "the numeric class is printed but the LETTER is not — invented letter",
            "absent": "nothing resembling it is in the text — wholly inferred",
        }

    # Which rule produced each structural operation — so an over-matching pattern
    # names itself instead of hiding among real hits.
    ops_prov = {
        "by_pattern_index": dict(collections.Counter(
            h["pattern_index"] for h in ss["_ops_detailed"])),
        "by_element_type": dict(collections.Counter(
            h["element_type"] for h in ss["_ops_detailed"])),
        "pattern_legend": {i: p for i, p in enumerate(cfg["operations"]["patterns"])},
    }

    # NAS/MS et al are BOTH spec numbers and fastener part numbers. When the two
    # arms file the same token in different fields, both sides score it a miss
    # and the disagreement is a taxonomy artifact, not an extraction failure.
    cross = {
        "script_standard_is_llm_part": sorted(
            {_shape(s) for s in ss["standards"] if _loose(s) in {_loose(p) for p in ls["parts"]}}),
        "script_part_is_llm_standard": sorted(
            {_shape(p) for p in ss["parts"] if _loose(p) in {_loose(s) for s in ls["standards"]}}),
    }

    # The pollution claim is CONDITIONAL: with a blind structural arm an
    # llm_only operation cannot be distinguished from a real one the script
    # missed. Abstain loudly rather than assert a cause (defect #2).
    structural_recall = len(ss["operations"])
    ops_llm_only = tws["operations"]["llm_only"]          # the LIST, not the count
    pollution = {
        "llm_only_count": len(ops_llm_only),
        "llm_only_shapes": _shapes(ops_llm_only),
        "structural_arm_found": structural_recall,
    }
    if structural_recall == 0:
        pollution["claim"] = ("UNSUPPORTED — the structural arm found no operations in "
                              "this document, so an llm_only operation is indistinguishable "
                              "from one the script missed. Not counted as pollution.")
        pollution["pollution_candidates"] = None
    else:
        pollution["claim"] = "supported — structural arm has recall on this document"
        pollution["pollution_candidates"] = ops_llm_only
    if include_values:
        pollution["llm_only_values"] = ops_llm_only

    return {
        "n_steps_llm": ls["_n_steps"],
        "llm_prose_figrefs": ls["_prose_figrefs"],
        "parse": elem_diag,
        "figures_diag": figure_diagnostics(ss, elements),
        "fields": fields,
        "llm_grounding": corroborate_llm_values(ls, ss, elements, cfg, mx),
        "llm_only_fields": llm_only_fields,
        "cross_field_collisions": cross,
        "llm_standards_unknown_family_shapes": _topn(
            collections.Counter(_shape_alpha(u) for u in ls["standards_unknown_family"]), 10),
        "operations_pollution": pollution,
        "operations_provenance": ops_prov,
        "llm_judgment_coverage": ls["_judgment"],
        "diagnosis": _diagnose(elements, ls["_n_steps"], manifest, elem_diag,
                               len(ss["operations"]), has_extraction),
    }


# --------------------------------------------------------------------------- #
# MinIO: layout-agnostic artifact discovery (defect #1)
# --------------------------------------------------------------------------- #
def _s3_client():
    import boto3  # lazy: only needed in MinIO mode
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


def discover_docs(s3, bucket, prefix):
    """Pair text.json / extraction.json / manifest.json WITHOUT assuming a layout.

    Tries, in order: sibling (same directory), {base}/generated/*/, any nested
    path under {base}. Records which layout matched so the real one is MEASURED.
    Documents missing either artifact are yielded too — an extraction-less parse
    means the LLM stage never ran, which is a finding, not a gap.
    """
    paginator = s3.get_paginator("list_objects_v2")
    keys, lastmod, sizes = [], {}, {}
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            keys.append(o["Key"])
            lastmod[o["Key"]] = o.get("LastModified")
            sizes[o["Key"]] = o.get("Size")
    texts = {k.rsplit("/", 1)[0]: k for k in keys if k.endswith("/text.json")}
    extrs = {k.rsplit("/", 1)[0]: k for k in keys if k.endswith("/extraction.json")}
    mans = {k.rsplit("/", 1)[0]: k for k in keys if k.endswith("/manifest.json")}

    used_text = set()
    docs = []
    for edir, ekey in sorted(extrs.items()):
        tkey, layout = None, None
        if edir in texts:
            tkey, layout = texts[edir], "sibling"
        else:
            gen = sorted(d for d in texts if d.startswith(edir + "/generated/"))
            nested = sorted(d for d in texts if d.startswith(edir + "/"))
            if gen:
                tkey, layout = texts[gen[0]], "generated"
            elif nested:
                tkey, layout = texts[nested[0]], "nested"
        if tkey:
            used_text.add(tkey)
        mkey = mans.get(edir) or (mans.get(tkey.rsplit("/", 1)[0]) if tkey else None)
        docs.append({"extraction_key": ekey, "text_key": tkey, "manifest_key": mkey,
                     "layout": layout or "unpaired_no_text",
                     "last_modified": lastmod.get(ekey),
                     "text_bytes": sizes.get(tkey), "extraction_bytes": sizes.get(ekey)})
    # parses with no extraction at all — the LLM stage never produced anything
    for tdir, tkey in sorted(texts.items()):
        if tkey in used_text:
            continue
        docs.append({"extraction_key": None, "text_key": tkey,
                     "manifest_key": mans.get(tdir), "layout": "unpaired_no_extraction",
                     "last_modified": lastmod.get(tkey),
                     "text_bytes": sizes.get(tkey), "extraction_bytes": None})
    return docs


def run_minio(args, mx, cfg):
    s3 = _s3_client()
    found = discover_docs(s3, args.bucket, args.minio_prefix)
    if args.limit:
        found = found[: args.limit]

    per_doc, local_map, gen = [], {}, []
    agg = {f: collections.Counter() for f in _COMPARED_FIELDS}
    layouts, diagnoses, skipped = collections.Counter(), collections.Counter(), collections.Counter()
    unknown_fam, cross_tot = collections.Counter(), collections.Counter()
    haz_tot, ground_tot = collections.Counter(), collections.Counter()

    for i, d in enumerate(found):
        doc_id = f"doc_{i:04d}"
        local_map[doc_id] = {k: d[k] for k in ("extraction_key", "text_key", "manifest_key")}
        layouts[d["layout"]] += 1

        elements = _get_json(s3, args.bucket, d["text_key"]) if d["text_key"] else []
        if not isinstance(elements, list):
            elements = []
        extraction = (_get_json(s3, args.bucket, d["extraction_key"])
                      if d["extraction_key"] else {"augmentations": []})
        domain = (extraction.get("domain_type") or "").lower()
        if d["extraction_key"] and domain and domain != "manufacturing":
            skipped["non_manufacturing"] += 1
            continue
        manifest = None
        if d["manifest_key"]:
            try:
                manifest = _get_json(s3, args.bucket, d["manifest_key"])
            except Exception:  # noqa: BLE001 — a missing manifest is a diag, not a crash
                manifest = None

        rec = compare_doc(elements, extraction, manifest, cfg, mx, args.include_values,
                          has_extraction=bool(d["extraction_key"]))
        rec.update({"doc": doc_id, "layout": d["layout"],
                    "generated_at": d["last_modified"].isoformat() if d["last_modified"] else None,
                    "text_bytes": d["text_bytes"], "extraction_bytes": d["extraction_bytes"]})
        per_doc.append(rec)
        if d["last_modified"]:
            gen.append(d["last_modified"].isoformat())
        for f in _COMPARED_FIELDS:
            for cls in ("agree", "script_only", "llm_only"):
                agg[f][cls] += rec["fields"][f][cls]
        for flag in rec["diagnosis"]["flags"]:
            diagnoses[flag] += 1
        unknown_fam.update(rec["llm_standards_unknown_family_shapes"])
        haz_tot.update(rec["llm_only_fields"].get("hazard", {}).get("corroboration", {}))
        for fld, g in rec["llm_grounding"].items():
            for verdict, n in g["counts"].items():
                ground_tot[f"{fld}.{verdict}"] += n
        cross_tot["script_standard_is_llm_part"] += len(rec["cross_field_collisions"]["script_standard_is_llm_part"])
        cross_tot["script_part_is_llm_standard"] += len(rec["cross_field_collisions"]["script_part_is_llm_standard"])

    blind = sum(1 for r in per_doc if r["operations_pollution"]["structural_arm_found"] == 0)
    stamp = {
        "mode": "minio-comparison",
        "report_version": "0.2.0",
        "extractor_version": mx.EXTRACTOR_VERSION,
        "config_hash": _config_hash(cfg),
        "bucket": args.bucket, "prefix": args.minio_prefix,
        "doc_count": len(per_doc),
        "generation_range": [min(gen), max(gen)] if gen else None,
        "generated_at": args.stamp_date or datetime.date.today().isoformat(),
        "values_included": args.include_values,
        "layouts": dict(layouts),
        "diagnoses": dict(diagnoses),
        "skipped": dict(skipped),
    }
    report = {
        "stamp": stamp,
        "legend": {
            "script_only": "LLM MISSED it (script found)",
            "llm_only": "script MISSED it (LLM found)",
            "scored_fields": _COMPARED_FIELDS,
            "note": "Judgment fields are LLM-only coverage, NOT wins. Both arms are "
                    "canonicalised identically before diffing; parts compare on a "
                    "prefix-stripped core.",
            "operations_caveat": f"{blind}/{len(per_doc)} documents had ZERO structural "
                                 f"operations, so their llm_only operations are NOT counted "
                                 f"as pollution — see per_doc[].operations_pollution.claim",
        },
        "field_totals": {f: dict(agg[f]) for f in _COMPARED_FIELDS},
        "llm_grounding_totals": dict(ground_tot),
        "llm_grounding_legend": {
            "exact": "the LLM's value appears verbatim in the document",
            "loose": "appears once separators/spacing/case are folded (same id, written differently)",
            "absent": "NOT in the document — invented",
            "base_only": "hazard only: the number is printed, the division letter is not",
            "note": "this is the ABSOLUTE hallucination measure; the script-vs-LLM diff "
                    "cannot tell 'script missed it' from 'LLM invented it', the document can.",
        },
        "hazard_corroboration_totals": dict(haz_tot),
        "cross_field_collision_totals": dict(cross_tot),
        "llm_standards_unknown_family_shapes": _topn(unknown_fam, 25),
        "per_doc": per_doc,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    map_path = os.path.splitext(args.out)[0] + ".local-map.json"
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(local_map, f, indent=2)

    print(f"MinIO comparison  bucket={args.bucket}  prefix={args.minio_prefix}  "
          f"docs={len(per_doc)}  extractor v{mx.EXTRACTOR_VERSION}  report v{stamp['report_version']}")
    print(f"  layouts   : {dict(layouts)}")
    print(f"  diagnoses : {dict(diagnoses)}")
    if stamp["generation_range"]:
        print(f"  generation: {stamp['generation_range'][0]} .. {stamp['generation_range'][1]}")
    print("  field       agree | LLM-missed | script-missed")
    for f in _COMPARED_FIELDS:
        c = agg[f]
        print(f"    {f:11s} {c['agree']:5d} | {c['script_only']:10d} | {c['llm_only']:13d}")
    print("  LLM GROUNDING (is each LLM value actually in the document?):")
    for fld in ("standards", "parts", "operations", "figures", "hazard"):
        row = {k.split(".", 1)[1]: v for k, v in ground_tot.items() if k.startswith(fld + ".")}
        if row:
            absent = row.get("absent", 0)
            tot = sum(row.values())
            print(f"    {fld:11s} {row}   -> {absent}/{tot} NOT in the document")
    if haz_tot:
        _fab = haz_tot.get("base_only", 0) + haz_tot.get("absent", 0)
        _tot = sum(haz_tot.values())
        flag = "   *** FABRICATED IN ALL CASES — do not surface as extractions ***" \
            if _tot and _fab == _tot else ""
        print(f"  HAZARD corroboration: {dict(haz_tot)} -> {_fab}/{_tot} NOT corroborated{flag}")
    print(f"  cross-field collisions: {dict(cross_tot)}")
    if blind:
        print(f"  NOTE: {blind}/{len(per_doc)} docs had a BLIND structural arm — their "
              f"llm_only operations are NOT claimed as pollution.")
    print(f"  report -> {args.out}   (SHAREABLE, elided)")
    print(f"  local map -> {map_path}   (KEEP LOCAL — object keys only)")


# --------------------------------------------------------------------------- #
# Local mode (deterministic only, no LLM arm)
# --------------------------------------------------------------------------- #
def _iter_local(input_dir, pattern):
    for path in sorted(globmod.glob(os.path.join(input_dir, pattern), recursive=True)):
        base = os.path.basename(path).lower()
        if "groundtruth" in base or "_repro_response" in base or "report" in base:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, list):
            yield path, data


def run_local(args, mx, cfg):
    per_doc, local_map = [], {}
    totals = collections.Counter()
    for idx, (path, els) in enumerate(_iter_local(args.input, args.glob)):
        doc_id = f"doc_{idx:04d}"
        local_map[doc_id] = path
        ss = script_doc_sets(els, cfg, mx)
        diag = element_diagnostics(els)
        totals["standards"] += len(ss["standards"])
        totals["parts"] += len(ss["parts"])
        totals["figures"] += len(ss["figures"])
        totals["operations"] += len(ss["operations"])
        per_doc.append({
            "doc": doc_id,
            "hash": hashlib.sha1(os.path.basename(path).encode()).hexdigest()[:8],
            "parse": diag,
            "standards": {"count": len(ss["standards"]), "shapes": _shapes(ss["standards"])},
            "parts": {"count": len(ss["parts"]), "shapes": _shapes(ss["parts"])},
            "operations": {"count": len(ss["operations"]), "shapes": _shapes(ss["operations"])},
            "figures_diag": figure_diagnostics(ss, els),
        })
    report = {"stamp": {"mode": "local-deterministic", "report_version": "0.2.0",
                        "extractor_version": mx.EXTRACTOR_VERSION,
                        "config_hash": _config_hash(cfg), "corpus_label": args.label,
                        "doc_count": len(per_doc),
                        "generated_at": args.stamp_date or datetime.date.today().isoformat()},
              "totals": dict(totals), "per_doc": per_doc}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(os.path.splitext(args.out)[0] + ".local-map.json", "w", encoding="utf-8") as f:
        json.dump(local_map, f, indent=2)
    print(f"local deterministic  docs={len(per_doc)}  totals={dict(totals)}")
    print(f"  report -> {args.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="LOCAL mode: directory of element-list JSON files")
    ap.add_argument("--minio-prefix", help="MINIO comparison mode: S3 prefix to scan")
    ap.add_argument("--bucket", default=os.getenv("DAGSTER_STORAGE_BUCKET", "processing-artifacts"))
    ap.add_argument("--glob", default="**/*text.json")
    ap.add_argument("--label", default="unlabeled")
    ap.add_argument("--limit", type=int, default=0, help="cap documents (smoke runs)")
    ap.add_argument("--include-values", action="store_true",
                    help="include actual values (only on a slice you deem safe)")
    ap.add_argument("--out", default="mfg_corpus_report.json")
    ap.add_argument("--stamp-date", default="")
    args = ap.parse_args()

    mx = _load_extractors()
    cfg = mx.load_extractor_config()
    if args.minio_prefix:
        return run_minio(args, mx, cfg)
    if not args.input:
        ap.error("--input is required for local mode (or pass --minio-prefix)")
    return run_local(args, mx, cfg)


if __name__ == "__main__":
    main()
