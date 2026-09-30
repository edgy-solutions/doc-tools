"""Deterministic Level-2 dedupe identity for sustainment (PCN/PDN) notices.

Pure library — no boto3, no Dagster, no network I/O, no BAML import. It reads
the three header fields `NoticeHeader` ALREADY carries (`mfr`, `doc_id`,
`revision` — see baml_src/sustainment.baml) and turns them into:

  * a deterministic, human-readable dedupe KEY (`notice_key`), stable across
    processes and re-runs, so two extractions of the same notice on two
    different Dagster pods produce the SAME key; and
  * a CLASSIFIER (`classify_pair`) that compares two already-extracted,
    already-keyed records and says how they relate: the same bytes twice
    ("identical"), the same notice re-rendered ("duplicate_copy"), one
    revision superseding another ("supersedes" / "superseded_by"), a
    revision pair whose order cannot be safely inferred
    ("revision_order_unknown"), or two unrelated notices ("distinct").

This module owns the KEY and the CLASSIFIER only. It does not decide what to
DO with a duplicate/supersession (skip ingest, flag for review, etc.) and it
does not watch S3 for new documents — that is the sensor lane's job
(doc_tools/plugins/sustainment.py calls in at extraction time; see that
module for where the key gets computed and attached to the review payload).

-------------------------------------------------------------------------
JUDGMENT CALLS made in this module (read before changing behaviour):

1. CORPORATE-SUFFIX STRIPPING is CONSERVATIVE, on purpose. `_CORPORATE_SUFFIXES`
   is a short, unambiguous list of full suffix WORDS ("incorporated", "inc",
   "corporation", "corp", "company", "co", "limited", "ltd", "llc", "gmbh",
   "plc"), stripped only as the LAST whitespace-delimited token of an already
   normalized name, and only if something is left over afterward. The
   tradeoff: this can fail to collapse some genuinely-equivalent spellings
   (a rarer, cheaper mistake — a missed dedupe that a human or the exact
   content_hash match will still catch downstream) rather than risk
   collapsing two DIFFERENT manufacturers into one key (a silent correctness
   bug — a real notice from company B would be classified as a
   revision/duplicate of company A's notice). We accept more false
   negatives on suffix-equivalence to avoid any false positive on identity.
   The suffix list lives in a module constant, as data, not inline logic.

2. `revision=None` ("the notice shows none", per the BAML field docstring)
   and `revision='-'` ("the notice prints a dash") are KEPT DISTINCT. `None`
   encodes as a private sentinel component (`_ABSENT_REVISION`) that cannot
   be produced by normalizing any real printed string; `'-'` normalizes
   like any other component (to `"-"`). Collapsing the two would treat "we
   don't know if this notice was ever revisioned" the same as "this notice
   explicitly prints no revision," which the schema deliberately keeps apart.

3. NO `hashlib`-digest key. `notice_key()` returns the normalized,
   human-readable triple itself (joined on a control-character separator),
   not a digest. A digest would need the readable triple exposed
   *alongside* it to be debuggable in a log anyway (an opaque hex string
   tells a reviewer nothing about why two notices collided) — so the
   readable form IS the key, and there is nothing extra to keep in sync.
   `notice_key()` never calls Python's `hash()` (salted per process, would
   silently produce a different key per Dagster pod) or any `hashlib`
   function; determinism is verified by a test asserting an exact literal
   key string.

4. REVISION ORDERING is decided ONLY where genuinely unambiguous:
     - one side absent (`None`), the other printed  -> printed is newer.
       (A vendor typically leaves the first release unmarked and stamps
       only later reprints with an explicit revision.)
     - both sides purely numeric (`"1"` vs `"2"`)    -> integer compare.
     - both sides a single alphabetic character (`"A"` vs `"B"`) -> compare.
   Everything else — mixed alpha/numeric (`"A"` vs `"1"`), multi-token
   strings (`"Rev1"`), a printed dash against anything, two absent values
   colliding into the same key before this even runs — returns
   `revision_order_unknown`. Getting a direction backwards would hide the
   NEWER notice behind the OLDER one, which is strictly worse than
   declining to answer, so this module never invents a total order.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# ASCII Unit Separator (0x1F). Not producible by `normalize_component` (which
# only casefolds, strips a small fixed punctuation set, and collapses
# whitespace) and not realistically present in text pulled out of a PDF's
# text layer, so it can join the three normalized components and still be
# split back apart unambiguously by `parse_notice_key`.
SEPARATOR = "\x1f"

# Sentinel for "revision is None" (the notice shows no revision at all),
# distinct from the printed string "-" (the notice prints a dash) and from
# anything `normalize_component` could ever produce from real text — it is
# prefixed with ASCII Record Separator (0x1E), a second control character
# that never appears in normalized text either. See judgment call #2 above.
_ABSENT_REVISION = "\x1eabsent-revision"

# Judgment call #1: conservative, whole-word corporate suffixes only,
# stripped as the trailing token of an already-normalized (casefolded,
# punctuation-stripped) name. Data, not logic — extend this list rather than
# adding stripping rules elsewhere.
_CORPORATE_SUFFIXES = (
    "incorporated", "inc",
    "corporation", "corp",
    "company", "co",
    "limited", "ltd",
    "llc", "gmbh", "plc",
)

# Punctuation that varies by typesetting and carries no identity information
# ('.', ',', apostrophes for things like "O'Brien"-style names). Deliberately
# does NOT include '-': a printed dash is a real, meaningful revision value
# (see judgment call #2) and hyphens can be meaningful inside doc_id tokens.
_NOISE_PUNCTUATION_RE = re.compile(r"[.,']")
_WHITESPACE_RE = re.compile(r"\s+")

_NUMERIC_RE = re.compile(r"^[0-9]+$")
_SINGLE_ALPHA_RE = re.compile(r"^[a-z]$")


def normalize_component(value) -> str:
    """Normalize one header component for identity comparison.

    Case-folds, drops typesetting-variant punctuation (`.`, `,`, `'`),
    collapses internal whitespace runs to a single space, and strips
    surrounding whitespace. `None` normalizes to `""`.

    Generic text normalization only — corporate-suffix stripping (judgment
    call #1) is mfr-specific and applied separately by `notice_key`, not
    here, so this function stays meaningful for doc_id and revision too.
    """
    if value is None:
        return ""
    text = str(value).casefold()
    text = _NOISE_PUNCTUATION_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _strip_corporate_suffix(normalized_mfr: str) -> str:
    """Drop a single trailing corporate-suffix token from an ALREADY
    normalized manufacturer name. Never strips down to nothing, and never
    touches a suffix-like token that is not the last one (so it cannot
    consume part of a genuine brand name that merely contains one of these
    words earlier on)."""
    if not normalized_mfr:
        return normalized_mfr
    tokens = normalized_mfr.split(" ")
    if len(tokens) > 1 and tokens[-1] in _CORPORATE_SUFFIXES:
        stripped = " ".join(tokens[:-1])
        if stripped:
            return stripped
    return normalized_mfr


def notice_key(mfr, doc_id, revision) -> str:
    """Build the deterministic Level-2 dedupe key from a notice's header.

    Returns the normalized (mfr, doc_id, revision) triple joined on
    `SEPARATOR`. The key IS the human-readable normalized triple (see
    judgment call #3 in the module docstring) — there is no separate digest
    to keep in sync with it. Deterministic and stable across processes: it
    depends only on the three inputs and fixed module data, never on
    Python's salted `hash()` or any run/process-specific state.

    `mfr` and `doc_id` normalize through `normalize_component` (`mfr` also
    gets corporate-suffix stripping). `revision` is nullable AND `'-'` is a
    real printed value (see judgment call #2): `None` maps to a private
    absent-revision sentinel that cannot collide with any printed string,
    including `'-'`.

    This function does not decide whether `mfr`/`doc_id` are "present
    enough" to trust — it will happily build a key from empty strings if
    asked. The caller (doc_tools/plugins/sustainment.py, via
    `build_identity` below) is responsible for deciding when a header is too
    incomplete to key at all, because only the caller knows whether an empty
    `mfr` means "the header pass failed" or "the document legitimately
    prints no manufacturer name" (both reach this module as falsy).
    """
    mfr_component = _strip_corporate_suffix(normalize_component(mfr))
    doc_id_component = normalize_component(doc_id)
    revision_component = _ABSENT_REVISION if revision is None else normalize_component(revision)
    return SEPARATOR.join((mfr_component, doc_id_component, revision_component))


def parse_notice_key(key: str) -> Tuple[str, str, str]:
    """Split a `notice_key()` output back into (mfr_component, doc_id_component,
    revision_component). Exists both as a directly useful inverse and as the
    internal mechanism `classify_pair` uses to compare the (mfr, doc_id)
    portion of two keys that differ only by revision."""
    parts = key.split(SEPARATOR)
    if len(parts) != 3:
        raise ValueError(f"not a notice_key()-shaped key: {key!r}")
    return parts[0], parts[1], parts[2]


def build_identity(mfr, doc_id, revision) -> dict:
    """Compose the full identity record for one notice's header — the shape
    meant to be dropped straight into an extraction's `stats`/review payload
    as `notice_identity`.

    Unlike `notice_key`, this function DOES decide whether a key can be
    formed. `mfr` and `doc_id` missing/empty each block key formation;
    `revision` never does (its absence is a legitimate observation with its
    own encoding inside `notice_key`, not a failure).

    WHY mfr AND doc_id ARE TREATED THE SAME WAY DESPITE DIFFERENT SCHEMA
    NULLABILITY. `doc_id` is required by the BAML schema, but
    `doc_tools.utils.sustainment_merge.empty_header` sets `mfr=""` on a
    totally failed header pass (an exception during extraction), while a
    *successful* header pass can also legitimately produce `mfr=None` (the
    document prints no manufacturer name anywhere — a correct answer per
    the NoticeHeader.mfr docstring, not a failure). Both a failed header and
    a real no-mfr document reach this function as a falsy `mfr`, and this
    function cannot and does not try to tell them apart. Building a key out
    of an empty mfr either way would let every failed-header document (and
    every real no-mfr document) collide under one key with every other —
    exactly the hazard this function exists to avoid. So: no key, for
    either reason, and the `note` field says which component was missing so
    a human reading the payload is not left guessing.

    Returns a dict with:
      key                 -- the deterministic key, or None if not formable.
      mfr, doc_id, revision            -- the raw values as extracted.
      normalized_mfr, normalized_doc_id, normalized_revision
                           -- the human-readable normalized triple (present
                              only when `key` is not None).
      complete             -- bool, whether a key was formed.
      note                 -- human-readable explanation when `key` is None,
                               else None.
    """
    mfr_missing = not mfr
    doc_id_missing = not doc_id
    if mfr_missing or doc_id_missing:
        missing = [name for name, is_missing in (("mfr", mfr_missing), ("doc_id", doc_id_missing))
                   if is_missing]
        return {
            "key": None,
            "mfr": mfr,
            "doc_id": doc_id,
            "revision": revision,
            "normalized_mfr": None,
            "normalized_doc_id": None,
            "normalized_revision": None,
            "complete": False,
            "note": f"no notice_identity key: missing {' and '.join(missing)}",
        }
    key = notice_key(mfr, doc_id, revision)
    n_mfr, n_doc_id, n_revision = parse_notice_key(key)
    return {
        "key": key,
        "mfr": mfr,
        "doc_id": doc_id,
        "revision": revision,
        "normalized_mfr": n_mfr,
        "normalized_doc_id": n_doc_id,
        "normalized_revision": n_revision,
        "complete": True,
        "note": None,
    }


def _compare_revisions(rev_a: str, rev_b: str) -> Optional[int]:
    """Compare two revision COMPONENTS (as produced inside a notice_key —
    i.e. either `_ABSENT_REVISION` or a normalized printed string). Returns
    a positive int if `a` is newer, negative if `a` is older, 0 if equal,
    or None if the order is not decidable (see judgment call #4)."""
    absent_a = rev_a == _ABSENT_REVISION
    absent_b = rev_b == _ABSENT_REVISION
    if absent_a and absent_b:
        return 0
    if absent_a != absent_b:
        # One side never printed a revision at all; treat the printed side
        # as the later one (judgment call #4).
        return -1 if absent_a else 1
    if _NUMERIC_RE.match(rev_a) and _NUMERIC_RE.match(rev_b):
        na, nb = int(rev_a), int(rev_b)
        return (na > nb) - (na < nb)
    if _SINGLE_ALPHA_RE.match(rev_a) and _SINGLE_ALPHA_RE.match(rev_b):
        return (rev_a > rev_b) - (rev_a < rev_b)
    return None


def classify_pair(a: dict, b: dict) -> dict:
    """Classify the relationship between two already-extracted, already-keyed
    notice records.

    Each of `a`/`b` is expected to look like:
        {"key": str | None, "content_hash": str, "revision": str | None,
         "doc_id": ..., "mfr": ...}
    (`key` is normally the output of `notice_key`/`build_identity`;
    `revision` here is the RAW value, used only to report it back in the
    reason text on decidable orderings.)

    Returns `{"relation": str, "reason": str}`. `relation` is one of:
      "identical"              -- same key, same content_hash: the same bytes.
      "duplicate_copy"         -- same key, different content_hash: same
                                   notice identity, different bytes (a
                                   re-render, a re-scan, a corrected typo).
      "supersedes"             -- same (mfr, doc_id), different revision,
                                   and `a` is the NEWER revision of `b`.
      "superseded_by"          -- same (mfr, doc_id), different revision,
                                   and `a` is the OLDER revision of `b`.
      "revision_order_unknown" -- same (mfr, doc_id), different revision,
                                   but the order cannot be safely decided
                                   (judgment call #4) — a REAL, reachable
                                   outcome, not a fallback that never fires.
      "distinct"                -- different (mfr, doc_id), or either record
                                   has no key at all (header too incomplete
                                   to assert identity — treated as distinct
                                   rather than risked as a false match).
    """
    key_a, key_b = a.get("key"), b.get("key")
    if not key_a or not key_b:
        missing = "a" if not key_a else "b"
        return {
            "relation": "distinct",
            "reason": (
                f"record {missing} has no notice_identity key (header mfr/doc_id was "
                f"incomplete) — identity cannot be asserted, so the pair is treated as "
                f"distinct rather than risked as a false match"
            ),
        }

    if key_a == key_b:
        hash_a, hash_b = a.get("content_hash"), b.get("content_hash")
        if hash_a is not None and hash_b is not None and hash_a == hash_b:
            return {
                "relation": "identical",
                "reason": "same notice_identity key and same content_hash — the same bytes",
            }
        return {
            "relation": "duplicate_copy",
            "reason": (
                "same notice_identity key, different content_hash — same notice "
                "identity, different bytes (a re-render, a re-scan, or a corrected typo)"
            ),
        }

    mfr_a, doc_a, rev_a = parse_notice_key(key_a)
    mfr_b, doc_b, rev_b = parse_notice_key(key_b)
    if mfr_a != mfr_b or doc_a != doc_b:
        return {"relation": "distinct", "reason": "different (mfr, doc_id) identity"}

    order = _compare_revisions(rev_a, rev_b)
    if order is None:
        return {
            "relation": "revision_order_unknown",
            "reason": (
                f"same (mfr, doc_id); revisions {a.get('revision')!r} vs "
                f"{b.get('revision')!r} differ but their order is not decidable (not "
                f"both numeric, not both single-alphabetic, and neither side is simply "
                f"absent) — guessing would risk hiding the newer notice behind the "
                f"older one"
            ),
        }
    if order > 0:
        return {
            "relation": "supersedes",
            "reason": (
                f"same (mfr, doc_id); revision {a.get('revision')!r} is newer than "
                f"{b.get('revision')!r}"
            ),
        }
    return {
        "relation": "superseded_by",
        "reason": (
            f"same (mfr, doc_id); revision {a.get('revision')!r} is older than "
            f"{b.get('revision')!r}"
        ),
    }
