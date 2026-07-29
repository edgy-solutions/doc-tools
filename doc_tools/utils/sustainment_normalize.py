"""Deterministic PCN/PDN doc_type normalization + field reconcile helpers.

Kept out of the plugin so it is unit-testable without importing the heavy
Dagster/BAML stack. All pure functions.
"""
import re
from typing import Optional


def normalize_doc_id(raw: str) -> str:
    """Normalize a notice's doc_id into a stable, URL/key-safe identifier.

    doc_id is a KEY everywhere downstream — the grouped-review workflow id, the
    MinIO artifact-prefix lookup, the SUSTAINMENT graph IRI, the provenance index
    — but its two sources are messy: the header LLM extracts the number 'exactly
    as printed' (spaces, '#' reel-style codes, e.g. 'PCN # 23-002') and the path
    fallback can yield a path fragment ('inbound/adi_23_0120'). Left raw, '#' and
    spaces break URL keys (a '#' truncates a Restate ingress URL as a fragment ->
    the review-batch call 502s) and the SAME document keyed two ways never joins.

    Collapse to a clean slug: drop any leading path segments (the path fallback),
    replace every run of non-[A-Za-z0-9._-] with a single '-', and trim edge
    punctuation. Human-readable ('PCN # 23-002' -> 'PCN-23-002') and safe as a key
    everywhere. SCOPE: the doc_id / notice IDENTIFIER only — MPNs and *_source
    snippets stay VERBATIM (they are provenance join keys matched against the
    document text; normalizing them would break the page/bbox resolve)."""
    s = (raw or "").strip()
    if not s:
        return "unknown"
    s = s.rsplit("/", 1)[-1]                       # drop leading path segments
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)        # unsafe runs -> single dash
    s = re.sub(r"-{2,}", "-", s).strip("-._ ")     # tidy repeats + edge punctuation
    return s or "unknown"


# Vendor label vocabulary -> canonical enum. PDN terms cover discontinuance /
# obsolescence / EOL / PTN; PCN terms cover process/product change. An explicit
# "PCN"/"PDN" code is always taken verbatim; otherwise keyword classification.
_PDN_TERMS = (
    "discontinu", "obsolesc", "end of life", "end-of-life", "eol",
    "product termination", "last time buy", "last-time-buy", "last order",
    "last-order", "ptn",
)
_PCN_TERMS = (
    "process change", "product change", "product/process", "product-process",
    "change notification", "change notice",
)


def normalize_doc_type(raw) -> str:
    """Map a vendor doc-type label (or a DocType enum value) to 'PCN' | 'PDN'.

    The header model already returns a DocType enum; this is the deterministic
    safety net for raw vendor strings (e.g. 'PTN', 'Product Obsolescence
    Notification') and for coercing an enum to a plain string. An explicit
    'PCN'/'PDN' wins; then PDN keywords (a discontinuance stated as a "change"
    is still a discontinuance for routing); then PCN keywords; else a
    conservative PCN default (callers flag genuinely-unknown types for review).
    """
    s = str(getattr(raw, "value", raw) or "").strip().lower()
    if s == "pcn":
        return "PCN"
    if s == "pdn":
        return "PDN"
    if any(t in s for t in _PDN_TERMS):
        return "PDN"
    if any(t in s for t in _PCN_TERMS):
        return "PCN"
    return "PCN"


def is_known_doc_type(raw) -> bool:
    """True if the label mapped from an explicit code or a keyword hit (not the
    conservative default) — lets the caller flag unclassifiable types."""
    s = str(getattr(raw, "value", raw) or "").strip().lower()
    return (s in ("pcn", "pdn")
            or any(t in s for t in _PDN_TERMS)
            or any(t in s for t in _PCN_TERMS))


def clean_replacement(rep: Optional[str]) -> Optional[str]:
    """A genuine replacement_mpn is ONE part number. A comma-separated value is a
    list — in practice a 'Qualification Vehicle' column that a vision model
    mislabeled as a replacement on a PCN (which has no replacements) — so drop it.
    A real single replacement (e.g. 'AD7873ARUZ') is preserved unchanged.
    """
    if not isinstance(rep, str):
        return rep
    r = rep.strip()
    if not r or "," in r:
        return None
    return r


def effective_ltb(part_ltb: Optional[str], doc_level_ltb: Optional[str]) -> Optional[str]:
    """Per-part LTB ownership: prefer the per-row date, fall back to doc-level.

    Empirically (MinIO corpus scan) LTB lives per-row in most real docs, with a
    single doc-level date in others — so a part with its own date wins, and a
    part without one inherits the document-level date.
    """
    p = part_ltb.strip() if isinstance(part_ltb, str) else part_ltb
    return p if p else doc_level_ltb


_COUNT_RE = re.compile(
    r"(\d[\d,]{0,6})\s+(?:[\w/.\-]+\s+){0,3}?(?:parts?|devices?|mpns?|products?|items?|skus?)\b",
    re.I,
)


def summary_stated_count(summary: Optional[str]) -> Optional[int]:
    """Best-effort: the part count the summary prose claims, or None.

    Feeds the cross-pass sanity check (stated count vs len(impacted_parts)).
    Intentionally lenient and non-authoritative — a miss just means "no check".
    """
    if not summary:
        return None
    m = _COUNT_RE.search(summary)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None
