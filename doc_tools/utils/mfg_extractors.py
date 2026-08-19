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
EXTRACTOR_VERSION = "0.1.0"

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
            {"canonical": "NAS", "pattern": r"NAS[\s\-]?([0-9]{2,5}[A-Z0-9\-/]*)"},
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
        ],
    },
    "durations": {
        "pattern": r"\b([0-9]+(?:\.[0-9]+)?)\s*(min(?:ute)?s?|hours?|hrs?|days?)\b",
        "to_minutes": {"min": 1, "minute": 1, "minutes": 1, "hr": 60, "hrs": 60,
                       "hour": 60, "hours": 60, "day": 1440, "days": 1440},
    },
    "hazard": {
        "pattern": r"\bClass\s?([0-9]\.[0-9][A-Z]?)\b",
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
    "operations": {
        "title_types": ["Title"],   # add "Header"/"NarrativeText" via override if needed
        "patterns": [r"\bOperation\s+(\d{3,4})\b", r"^\s*(\d{4})\b"],
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
    found: List[str] = []
    seen = set()
    up = text or ""
    for fam in sc["families"]:
        for m in re.finditer(fam["pattern"], up, re.I):
            canon = f"{fam['canonical']}-{_norm_number(m.group(1))}"
            if canon not in seen:
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
    for pat in cfg["part_numbers"]["patterns"]:
        for m in re.finditer(pat, text or "", re.I):
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


def extract_hazard(text: str, cfg: Dict[str, Any]) -> Optional[str]:
    m = re.search(cfg["hazard"]["pattern"], text or "", re.I)
    if m:
        return f"Class {m.group(1).upper()}"
    for term in cfg["hazard"]["lexicon"]:
        if re.search(rf"\b{re.escape(term)}\b", text or "", re.I):
            return term.upper()
    return None


def extract_slang(text: str, cfg: Dict[str, Any]) -> List[str]:
    hits = []
    for g in cfg["slang"]["gazetteer"]:
        if re.search(rf"\b{re.escape(g)}\b", text or "", re.I):
            hits.append(g)
    return hits


# --------------------------------------------------------------------------- #
# Operations (procedure numbers) — structural
# --------------------------------------------------------------------------- #
def extract_operations(elements: List[dict], cfg: Dict[str, Any]) -> Tuple[List[str], List[Anomaly]]:
    """Operation numbers read from heading elements (structural, not LLM)."""
    oc = cfg["operations"]
    ttypes = set(oc["title_types"])
    ops: List[str] = []
    seen = set()
    for el in elements:
        if el.get("type") not in ttypes:
            continue
        text = el.get("text", "") or ""
        for pat in oc["patterns"]:
            for m in re.finditer(pat, text):
                v = m.group(1)
                if v not in seen:
                    seen.add(v)
                    ops.append(v)
    return sorted(ops), []


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
