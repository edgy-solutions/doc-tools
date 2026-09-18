"""Deterministic (code, not LLM) extractors for manufacturing work instructions.

These fill the pattern/lookup/geometry fields that a reasoning model does *worse*
than a regex while the load makes it drop the judgment fields it is actually good
at (see docs/manufacturing-extraction-findings.md): standards / MP docs
(regex + normalization), internal part numbers (regex), figure->step binding
(geometry / reading-order), durations, hazard class, and material slang.

Design contract:
  * Pure Python, light imports (re/os/typing + optional yaml). Importable by the
    repro harness without the Dagster/BAML stack.
  * Every extractor returns (results, anomalies). `anomalies` is the miss-path:
    a token that matched a known prefix but is malformed, a [FIGURE] marker with
    no resolvable step, etc. Callers route anomalies to the review lane — a miss
    is a needs_review row, NEVER a silent null.
  * Config is a committed default (DEFAULT_EXTRACTOR_CONFIG) overlaid by an
    optional YAML/JSON spec pointed at by MANUFACTURING_EXTRACTORS_SPEC — same
    shape as manufacturing_overlay.active_overlay(). Patterns/gazetteers are DATA,
    tunable per deployment without a code change.
"""
import copy
import os
import re
from typing import Any, Dict, List, Optional, Tuple

Anomaly = Dict[str, Any]

# Bump when patterns/config semantics change — stamped into corpus reports so a
# later run can be compared against an earlier one.
EXTRACTOR_VERSION = "0.5.0"   # 0.5.0: NAS/MS/AN reclassified standards -> parts (corpus-measured)

# --------------------------------------------------------------------------- #
# Config (committed defaults; override via MANUFACTURING_EXTRACTORS_SPEC)
# --------------------------------------------------------------------------- #
DEFAULT_EXTRACTOR_CONFIG: Dict[str, Any] = {
    # Standards / MP documents. Each family has a canonical prefix and a regex
    # matching its variants (spaces/hyphens/none) + the number. Normalization
    # rebuilds "<CANONICAL>-<number>" so 'J STD 001', 'JSTD001', 'J-STD 001' all
    # collapse to 'J-STD-001' (the normalization the prompt currently asks a 120B
    # to do by hand).
    "standards": {
        "families": [
            {"canonical": "MIL-PRF", "pattern": r"MIL[\s\-]?PRF[\s\-]?([0-9]{3,6}[A-Z0-9\-/]*)"},
            {"canonical": "MIL-STD", "pattern": r"MIL[\s\-]?STD[\s\-]?([0-9]{3,6}[A-Z0-9\-/]*)"},
            {"canonical": "MIL-DTL", "pattern": r"MIL[\s\-]?DTL[\s\-]?([0-9]{3,6}[A-Z0-9\-/]*)"},
            {"canonical": "J-STD", "pattern": r"J[\s\-]?STD[\s\-]?([0-9]{2,4}[A-Z0-9\-/]*)"},
            {"canonical": "IPC", "pattern": r"IPC[\s\-]?([A-Z]?[0-9]{2,4}[A-Z0-9\-/]*)"},
            {"canonical": "ISO", "pattern": r"ISO[\s\-]?([0-9]{3,5}[A-Z0-9\-/:]*)"},
            {"canonical": "ASTM", "pattern": r"ASTM[\s\-]?([A-Z]?[0-9]{2,4}[A-Z0-9\-/]*)"},
            {"canonical": "AMS", "pattern": r"AMS[\s\-]?([0-9]{3,5}[A-Z0-9\-/]*)"},
            # NAS / MS / AN are NOT here on purpose — see part_numbers below.
            {"canonical": "STD", "pattern": r"\bSTD[\s\-]?([0-9]{3,5}[A-Z0-9\-/]*)"},
            {"canonical": "SPEC", "pattern": r"\bSPEC[\s\-]?([0-9]{3,5}[A-Z0-9\-/]*)"},
            {"canonical": "MP", "pattern": r"\bMP[\s\-]?([0-9]{3,6}[A-Z0-9\-/]*)"},
        ],
        # A token with a known prefix but a malformed / missing number -> near-miss
        # anomaly (matched-but-malformed), routed to review rather than dropped.
        "near_miss": r"\b(MIL|J[\s\-]?STD|IPC|ISO|ASTM|AMS|NAS|STD|SPEC|MP)[\s\-]+(?![0-9])",
    },
    "part_numbers": {
        # Match the WHOLE token (prefix included). Keeping 'PN-1001' rather than
        # stripping to '1001' preserves the namespace and avoids colliding with
        # bare find/quantity numbers. Separators normalized to a single hyphen.
        "patterns": [
            r"\bPN[\s\-]?[0-9][0-9A-Z\-]{2,}\b",
            r"\bPART-[0-9]{3,}\b",
            r"\bASS?Y\.?\s*[0-9][0-9A-Z\-]{2,}\b",
            r"\bADH-[0-9]{2,}[0-9A-Z\-]*\b",
            # AEROSPACE HARDWARE CALLOUTS ARE PART NUMBERS, NOT STANDARDS.
            # NAS/MS/AN were in the standards families until the corpus said
            # otherwise: cross-field measurement found tokens the script filed as
            # STANDARDS and the LLM filed as PARTS (e.g. a NAS bolt callout), and
            # the LLM is right — 'NAS1100E3-5' is a bolt on a parts list, not a
            # specification the step complies with. Filing them as standards both
            # inflated the standards column and made parts agreement impossible,
            # since the two arms were putting the same token in different fields.
            r"\bNAS[0-9][0-9A-Z\-/]*\b",
            r"\bMS[0-9]{4,}[0-9A-Z\-/]*\b",
            r"\bAN[0-9]{3,}[0-9A-Z\-/]*\b",
        ],
    },
    "durations": {
        "pattern": r"\b([0-9]+(?:\.[0-9]+)?)\s*(min(?:ute)?s?|hours?|hrs?|days?)\b",
        "to_minutes": {"min": 1, "minute": 1, "minutes": 1, "hr": 60, "hrs": 60,
                       "hour": 60, "hours": 60, "day": 1440, "days": 1440},
    },
    # MEASURED 2026-09-17: script recall was ZERO across six documents while the LLM
    # found hazard classes — the single pattern demanded the literal word "Class"
    # adjacent. The bare form is added, but ONLY with a division letter
    # (1.1D, 1.3C): a bare '1.3' is indistinguishable from a dimension or a version
    # and would trade a false negative for a false positive. `pattern` is kept for
    # callers that pass the singular key.
    "hazard": {
        "pattern": r"\bClass\s?([0-9]\.[0-9][A-Z]?)\b",
        "patterns": [
            r"\bClass\s?([0-9]\.[0-9][A-Z]?)\b",
            r"\b(1\.[1-6][A-HJKLNS])\b",
        ],
        "lexicon": ["ESD", "static", "explosive", "hazmat", "biohazard", "FOD"],
    },
    "slang": {
        "gazetteer": ["loctite", "rtv", "epoxy", "zip tie", "safety wire", "hex nut",
                      "silicone", "isopropyl alcohol", "alcohol", "ipa",
                      "anti-static foam", "threadlocker", "sealant"],
    },
    # Operation (procedure) numbers read STRUCTURALLY from heading elements — the
    # positional fact, not an LLM guess. An LLM procedure_id that is NOT in this set
    # is a pollution candidate (e.g. a document number grabbed from page furniture).
    # MEASURED 2026-09-17: the first real corpus run found ONE operation across six
    # documents — the structural arm was effectively blind, which also invalidated
    # the pollution discriminant built on top of it. Cause: real headings are not
    # reliably typed `Title`, and "Operation 0020" is only one of several printed
    # forms. Types are widened and the patterns are ANCHORED (they require the word
    # OPERATION/OP, or a line that IS the number) so widening does not let page
    # furniture like a 'DWG-4500-01' document number in through the back door.
    # MEASURED 2026-09-17 (run 2, values reviewed by the operator):
    #   * Footer ADDED — an operation whose number is printed only in the page's
    #     bottom block was missed entirely, and footers carry 'OPERATION ####'
    #     hundreds of times per document.
    #   * 3-digit match REMOVED — it pulled a part number's trailing '-305' in as
    #     an operation. Operations in this corpus are 4-digit; the looser rule
    #     bought nothing and cost a false positive.
    #   * The bare-dash rule now requires WHITESPACE around the separator, so
    #     '0020 - Final Inspect' still matches while the part number '7685-1234'
    #     no longer does. That single space is the whole discriminant.
    "operations": {
        "title_types": ["Title", "Header", "Footer", "NarrativeText",
                        "UncategorizedText", "ListItem"],
        "patterns": [
            r"\bOPERATION\s*[#:.\-]?\s*(\d{4})\b",
            r"\bOP\.?\s*[#:.\-]?\s*(\d{4})\b",
            r"^\s*(\d{4})\s+[-–—:]\s+\S",   # '0020 - Final Inspect' (spaced!)
            r"^\s*(\d{4})\s*$",             # a line that is only the number
        ],
    },
    # Bind a [FIGURE]/Image element to the nearest step element on the SAME page,
    # preferring the nearest preceding step (fall back to the nearest following).
    "figure_binder": {
        "same_page_only": True,
        "prefer": "preceding",          # "preceding" | "following" | "nearest"
        "marker_types": ["Image", "Figure"],
        "step_types": ["NarrativeText", "ListItem"],
    },
}


#: Unicode dashes / spaces that real documents use and ASCII-only patterns miss.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_SPACES = dict.fromkeys(map(ord, "   "), " ")


def normalize_text(s) -> str:
    """Fold Unicode dashes/spaces to ASCII before matching.

    MEASURED 2026-09-17: a site document family appears in the corpus written
    with U+2011 NON-BREAKING HYPHENS. Every ASCII-only pattern missed it, and the
    same identifier written with ASCII hyphens matched — so ONE real family was
    reported as two different ones and half of it counted as a miss. Folding is
    done at the extractor boundary so no individual pattern has to remember.
    """
    return str(s or "").translate(_DASHES).translate(_SPACES)


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_extractor_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Committed defaults overlaid by an optional per-deployment spec.

    Path comes from the arg or MANUFACTURING_EXTRACTORS_SPEC. YAML preferred
    (falls back to JSON); a missing PyYAML degrades to JSON so the pure-Python
    harness still runs. An unreadable or absent spec -> defaults unchanged.
    """
    cfg = copy.deepcopy(DEFAULT_EXTRACTOR_CONFIG)
    path = path or os.getenv("MANUFACTURING_EXTRACTORS_SPEC")
    if not path or not os.path.exists(path):
        return cfg
    text = open(path, "r", encoding="utf-8").read()
    override: Optional[dict] = None
    try:
        import yaml  # type: ignore
        override = yaml.safe_load(text)
    except Exception:  # noqa: BLE001  (no yaml, or not yaml) -> try json
        import json
        try:
            override = json.loads(text)
        except Exception:  # noqa: BLE001
            override = None
    if isinstance(override, dict):
        _deep_merge(cfg, override)
    return cfg


# --------------------------------------------------------------------------- #
# Standards / MP documents
# --------------------------------------------------------------------------- #
def _norm_number(num: str) -> str:
    return re.sub(r"[\s\-]+", "-", num.strip().upper()).strip("-")


def extract_standards(text: str, cfg: Dict[str, Any]) -> Tuple[List[str], List[Anomaly]]:
    """Normalized standard/MP identifiers found in `text`, plus near-miss anomalies.

    'MIL PRF 81733' -> 'MIL-PRF-81733'; 'J STD 001'/'JSTD001' -> 'J-STD-001'.
    """
    sc = cfg["standards"]
    up = normalize_text(text)

    # Collect every family hit WITH ITS SPAN first. Families overlap by design —
    # 'MIL-STD-1234' matches the MIL-STD family AND the generic STD family (on the
    # 'STD-1234' substring), which silently counted one real standard as two and
    # inflated every script total. Keep the WIDEST span at a position and discard
    # anything strictly contained in it.
    hits = []
    for fam in sc["families"]:
        for m in re.finditer(fam["pattern"], up, re.I):
            hits.append((m.start(), m.end(),
                         f"{fam['canonical']}-{_norm_number(m.group(1))}"))
    found: List[str] = []
    seen = set()
    for i, (s, e, canon) in enumerate(hits):
        contained = any(s2 <= s and e2 >= e and (e2 - s2) > (e - s)
                        for j, (s2, e2, _) in enumerate(hits) if j != i)
        if contained or canon in seen:
            continue
        seen.add(canon)
        found.append(canon)
    anomalies: List[Anomaly] = []
    if sc.get("near_miss"):
        for m in re.finditer(sc["near_miss"], up, re.I):
            anomalies.append({"kind": "standard_near_miss",
                              "detail": f"prefix '{m.group(1).upper()}' not followed by a number"})
    return found, anomalies


# --------------------------------------------------------------------------- #
# Internal part numbers
# --------------------------------------------------------------------------- #
def extract_part_numbers(text: str, cfg: Dict[str, Any]) -> Tuple[List[str], List[Anomaly]]:
    out: List[str] = []
    seen = set()
    text = normalize_text(text)
    for pat in cfg["part_numbers"]["patterns"]:
        for m in re.finditer(pat, text, re.I):
            val = re.sub(r"\s+", "-", m.group(0).strip().upper())
            val = re.sub(r"-{2,}", "-", val)
            if val and val not in seen:
                seen.add(val)
                out.append(val)
    return out, []


# --------------------------------------------------------------------------- #
# Durations / hazard / slang (lighter)
# --------------------------------------------------------------------------- #
def extract_duration_minutes(text: str, cfg: Dict[str, Any]) -> Optional[int]:
    m = re.search(cfg["durations"]["pattern"], text or "", re.I)
    if not m:
        return None
    qty = float(m.group(1))
    unit = m.group(2).lower().rstrip("s")
    mult = cfg["durations"]["to_minutes"].get(unit) or cfg["durations"]["to_minutes"].get(unit + "s")
    return int(qty * mult) if mult else None


def _hazard_patterns(cfg: Dict[str, Any]) -> List[str]:
    hc = cfg["hazard"]
    return list(hc.get("patterns") or ([hc["pattern"]] if hc.get("pattern") else []))


def extract_hazard(text: str, cfg: Dict[str, Any]) -> Optional[str]:
    for pat in _hazard_patterns(cfg):
        m = re.search(pat, text or "", re.I)
        if m:
            return f"Class {m.group(1).upper()}"
    for term in cfg["hazard"]["lexicon"]:
        if re.search(rf"\b{re.escape(term)}\b", text or "", re.I):
            return term.upper()
    return None


def corroborate_hazard(value: str, text: str) -> str:
    """Is an LLM-claimed hazard class ACTUALLY PRINTED in the document?

    Returns 'exact' | 'base_only' | 'absent'.

    WHY THIS EXISTS INSTEAD OF A SCORED REGEX ARM. Operator review of the corpus
    found the LLM emitting '1.1D' where the document says '1.1 -1.3' and, later,
    '1.4'. So the model is not extracting the class, it is CLASSIFYING — and it
    invented the division letter. A recall comparison is meaningless for a field
    the document may not print; what matters is whether each claimed value is
    corroborated by the text.

    The three-way answer is the useful one:
      exact     — the full class (with its division letter) is in the text
      base_only — the numeric class is there but the LETTER is not: the shape of
                  an invented division letter, and the case actually observed
      absent    — nothing resembling it is in the text: wholly inferred

    Matching is deliberately tolerant (dashes folded, whitespace/newline allowed
    between the number and the letter) so a hyphenated range like '1.1 -1.3' or a
    class split across a line break still corroborates. A manual Ctrl-F cannot be
    trusted on scanned text; this can be run over every document at once.
    """
    t = normalize_text(text)
    v = re.sub(r"(?i)^class\s*", "", normalize_text(value)).strip().upper()
    m = re.match(r"(\d\.\d)\s*([A-Z]?)", v)
    if not m:
        return "absent"
    base, letter = m.group(1), m.group(2)
    if letter and re.search(rf"{re.escape(base)}\s*{letter}\b", t, re.I):
        return "exact"
    if re.search(rf"{re.escape(base)}(?![.\d])", t):
        return "exact" if not letter else "base_only"
    return "absent"


def extract_hazard_all(text: str, cfg: Dict[str, Any]) -> List[str]:
    """Every hazard class in the text (doc-level). Kept HERE rather than
    re-implemented by callers so the pattern list has exactly one home."""
    out: List[str] = []
    for pat in _hazard_patterns(cfg):
        for m in re.finditer(pat, text or "", re.I):
            val = f"Class {m.group(1).upper()}"
            if val not in out:
                out.append(val)
    return out


def extract_slang(text: str, cfg: Dict[str, Any]) -> List[str]:
    hits = []
    for g in cfg["slang"]["gazetteer"]:
        if re.search(rf"\b{re.escape(g)}\b", text or "", re.I):
            hits.append(g)
    return hits


# --------------------------------------------------------------------------- #
# Operations (procedure numbers) — structural
# --------------------------------------------------------------------------- #
def extract_operations_detailed(elements: List[dict],
                                cfg: Dict[str, Any]) -> Tuple[List[dict], List[Anomaly]]:
    """Operations WITH provenance: which element type and which pattern produced
    each hit.

    Provenance exists because a widened pattern set is only trustworthy if its
    hits are auditable. When the operator reviewed run 2 they found two false
    positives hiding among real operation numbers; without knowing WHICH rule
    fired, the only remedy is to re-guess. With it, an over-matching pattern
    names itself.
    """
    oc = cfg["operations"]
    ttypes = set(oc["title_types"])
    hits: Dict[str, dict] = {}
    for el in elements:
        if el.get("type") not in ttypes:
            continue
        text = normalize_text(el.get("text", ""))
        for pi, pat in enumerate(oc["patterns"]):
            for m in re.finditer(pat, text, re.I | re.M):
                v = m.group(1)
                if v not in hits:
                    hits[v] = {"id": v, "element_type": el.get("type"), "pattern_index": pi}
    return sorted(hits.values(), key=lambda h: h["id"]), []


def extract_operations(elements: List[dict], cfg: Dict[str, Any]) -> Tuple[List[str], List[Anomaly]]:
    """Operation numbers read from heading elements (structural, not LLM)."""
    detailed, anomalies = extract_operations_detailed(elements, cfg)
    return [h["id"] for h in detailed], anomalies


# --------------------------------------------------------------------------- #
# Figure -> step binding (geometry / reading order)
# --------------------------------------------------------------------------- #
def _basename(p: Optional[str]) -> Optional[str]:
    return os.path.basename(str(p).replace("\\", "/")) if p else None


def bind_figures_to_steps(elements: List[dict], cfg: Dict[str, Any]) -> Tuple[List[dict], List[Anomaly]]:
    """Bind each figure element to the nearest step element on the same page.

    Returns (bindings, anomalies). A figure with no step on its page (e.g. cover
    art) is NOT dropped and NOT mis-attached — it becomes an anomaly for review.
    Uses page_number + reading order (element index); no LLM. This is the fix for
    the measured 0/N figure_references collapse when markers are stranded from
    their step.
    """
    fb = cfg["figure_binder"]
    marker_types = set(fb["marker_types"])
    step_types = set(fb["step_types"])
    prefer = fb.get("prefer", "preceding")

    def page(el):
        return (el.get("metadata") or {}).get("page_number")

    bindings: List[dict] = []
    anomalies: List[Anomaly] = []
    for i, el in enumerate(elements):
        if el.get("type") not in marker_types:
            continue
        fname = _basename((el.get("metadata") or {}).get("image_path"))
        pg = page(el)
        # candidate step elements on the same page, with their index distance
        cand = [(abs(j - i), j, e) for j, e in enumerate(elements)
                if e.get("type") in step_types and (not fb["same_page_only"] or page(e) == pg)]
        if not cand:
            anomalies.append({"kind": "figure_unbound",
                              "detail": f"figure on page {pg} has no step to bind to",
                              "figure": fname})
            continue
        preceding = sorted([c for c in cand if c[1] < i], key=lambda c: c[0])
        following = sorted([c for c in cand if c[1] > i], key=lambda c: c[0])
        if prefer == "preceding":
            chosen = (preceding or following)[0]
        elif prefer == "following":
            chosen = (following or preceding)[0]
        else:
            chosen = sorted(cand, key=lambda c: c[0])[0]
        step_el = chosen[2]
        if not fname:
            anomalies.append({"kind": "figure_no_target",
                              "detail": f"[FIGURE] on page {pg} has no resolvable filename"})
            continue
        bindings.append({
            "figure": fname, "page_number": pg,
            "step_element_id": step_el.get("element_id"),
            "step_snippet": (step_el.get("text", "") or "")[:60],
            "direction": "preceding" if chosen in preceding else "following",
        })
    return bindings, anomalies
