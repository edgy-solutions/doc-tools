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
     - both sides dotted-numeric (`"2.0"` vs `"1.15"`, `"1"` vs `"2"`, which
       is the one-segment case of the same pattern) -> split on `.`, map
       each segment to `int`, zero-pad the shorter tuple to the longer
       one's length, and compare the tuples segment-wise. `2.0` vs `1.15`
       is `(2, 0)` vs `(1, 15)` -> `2.0` is newer. `2.0.1` vs `2.0` is
       `(2, 0, 1)` vs `(2, 0, 0)` -> `2.0.1` is newer. Zero-padding also
       means equivalent spellings of the SAME revision compare equal
       rather than ordered: `1.0` vs `1.00` is `(1, 0)` vs `(1, 0)`, and
       `01` vs `1` is `(1,)` vs `(1,)`. An equal comparison is not
       "revision_order_unknown" — `classify_pair` reports it as
       `duplicate_copy` (judgment call relocated; see that function).
     - both sides a single alphabetic character (`"A"` vs `"B"`) -> compare.
   Everything else — mixed alpha/numeric (`"A"` vs `"1"`), multi-token
   strings (`"Rev1"`), a printed dash against anything, a dotted value with
   a non-numeric segment (`"1.A"` vs `"1.B"`), ONE SIDE ABSENT, two absent
   values colliding into the same key before this even runs — returns
   `revision_order_unknown`. Getting a direction backwards would hide the
   NEWER notice behind the OLDER one, which is strictly worse than
   declining to answer, so this module never invents a total order.

   One-side-absent WAS in the decidable list, on the reasoning that a
   vendor leaves the first release unmarked and stamps only later
   reprints. Real fires retired it: see `_compare_revisions`. The header
   pass reported 'R5', None, 'R5' over three fires of the same bytes, so
   an absent revision carries no information about the document until the
   extractor reports it reproducibly. This is the one rule in this module
   that measurement reversed, and it is recorded rather than quietly
   dropped because the original reasoning still sounds right.

5. BYTES OUTRANK THE KEY. An equal `content_hash` is checked before the
   keys are compared at all, so identical bytes can never be placed in a
   revision relation to themselves. See `classify_pair`.
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

# Dotted-numeric revision shape, e.g. "2", "2.0", "2.0.1" — one or more
# all-digit segments joined by '.'. Subsumes the pure-integer case (a single
# segment), so `_compare_revisions` has no separate integer-only branch.
_DOTTED_NUMERIC_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_SINGLE_ALPHA_RE = re.compile(r"^[a-z]$")


def normalize_component(value) -> str:
    """Normalize one header component for identity comparison.

    Case-folds, drops typesetting-variant punctuation (`.`, `,`, `'`),
    collapses internal whitespace runs to a single space, and strips
    surrounding whitespace. `None` normalizes to `""`.

    Generic text normalization only — corporate-suffix stripping (judgment
    call #1) is mfr-specific and applied separately by `notice_key`, not
    here. This function stays meaningful for doc_id, where a dot is always
    typesetting noise. It is NOT used for revision — `normalize_revision`
    below keeps the dot, because for a revision the dot is structural
    (separates `2.0` from `2`, `0`) rather than noise; see that function.
    """
    if value is None:
        return ""
    text = str(value).casefold()
    text = _NOISE_PUNCTUATION_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def normalize_revision(value) -> str:
    """Normalize a revision header component for identity comparison.

    Does everything `normalize_component` does EXCEPT strip the `.` that
    separates dotted revision segments (`"2.0"`, `"1.15"`): case-folds,
    strips `,` and `'`, collapses internal whitespace runs to a single
    space, strips surrounding whitespace — but leaves internal `.`
    characters alone. A revision's dot is structural, not typesetting noise
    (it is what makes `2.0` distinct from `2` and `0`, and what makes
    `_compare_revisions`'s segment-wise comparison possible at all); that
    is the opposite of `doc_id`/`mfr`, where a dot is always noise
    (`"Diodes, Incorporated."`). `normalize_component` is still correct for
    those two components — do not change it.

    A LEADING or TRAILING `.` is still stripped, after the above: a
    trailing dot is typesetting (`"2."` is revision `2` followed by a
    sentence period, not a structural dot), not a revision segment
    separator. Only dots BETWEEN digits/characters are structural.

    `None` normalizes to `""` for parity with `normalize_component`, though
    in practice `notice_key` never reaches this branch — it handles
    `revision=None` itself via `_ABSENT_REVISION` before calling here.
    """
    if value is None:
        return ""
    text = str(value).casefold()
    # Strip ',' and ''' only — NOT '.' — then collapse whitespace.
    text = text.replace(",", "").replace("'", "")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = text.strip(".")
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
    gets corporate-suffix stripping). `revision` normalizes through
    `normalize_revision` instead — it does everything `normalize_component`
    does except strip the `.` that separates dotted revision segments
    (`"2.0"`), because that dot is structural for a revision, not
    typesetting noise; see `normalize_revision`. `revision` is also nullable
    AND `'-'` is a real printed value (see judgment call #2): `None` maps to
    a private absent-revision sentinel that cannot collide with any printed
    string, including `'-'`.

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
    revision_component = _ABSENT_REVISION if revision is None else normalize_revision(revision)
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
        # NOT DECIDABLE -- and this was shipped decided the other way, wrongly.
        # An absent revision is not evidence that the notice printed none; it is
        # equally the header pass failing to report one. Three fires over the
        # byte-identical Diodes PCN-2683 pair at pin dd043b6 read revision
        # 'R5', None, 'R5' for THE SAME BYTES, with the two copies swapping
        # which one carried it. So "one side absent" arises from extraction
        # nondeterminism as readily as from a real revision difference, and
        # ordering on it asserted that a document supersedes its own identical
        # copy. Declining costs a missed supersedes, which the next arrival can
        # still establish; deciding cost a false one.
        return None
    if _DOTTED_NUMERIC_RE.match(rev_a) and _DOTTED_NUMERIC_RE.match(rev_b):
        # Segment-wise, zero-padded tuple compare — NOT a string or whole-value
        # integer compare. Subsumes the pure-integer case (one segment each).
        # Zero-padding is what makes "2.0.1" > "2.0" (extra trailing segment is
        # newer) and what makes "1.0" == "1.00" / "01" == "1" (equivalent
        # spellings of the same revision, not an ordering) -- see judgment call
        # #4 and classify_pair's `order == 0` branch below.
        segs_a = tuple(int(s) for s in rev_a.split("."))
        segs_b = tuple(int(s) for s in rev_b.split("."))
        width = max(len(segs_a), len(segs_b))
        segs_a = segs_a + (0,) * (width - len(segs_a))
        segs_b = segs_b + (0,) * (width - len(segs_b))
        return (segs_a > segs_b) - (segs_a < segs_b)
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
      "identical"              -- same content_hash: the same bytes. Checked
                                   BEFORE the keys, and independently of them,
                                   because identical bytes cannot supersede
                                   themselves however the header pass keyed
                                   them.
      "duplicate_copy"         -- reached two ways: (a) same key, different
                                   content_hash: same notice identity,
                                   different bytes (a re-render, a re-scan,
                                   a corrected typo); or (b) different key
                                   but same (mfr, doc_id) AND the revisions
                                   are equivalent SPELLINGS of the same
                                   revision (`"1.0"` vs `"1.00"`, `"01"` vs
                                   `"1"` — `_compare_revisions` returns 0
                                   without the keys being textually equal).
                                   Route (b) is the same identity with
                                   different bytes too, just discovered via
                                   revision-order equality instead of a key
                                   match.
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

    # BYTES FIRST, BEFORE THE KEYS ARE COMPARED. Identical bytes cannot stand in
    # any revision relation to themselves, so an equal content_hash settles the
    # pair whatever the keys say. The order of these two checks is load-bearing,
    # not tidiness: this test used to sit INSIDE the `key_a == key_b` branch
    # below, so a pair whose keys differed only because the header pass reported
    # the revision inconsistently never reached it and came back "supersedes" --
    # measured on the Diodes PCN-2683 pair, same sha256, one copy declared to
    # supersede the other. A key difference over equal bytes is a fact about the
    # extractor, not about the documents; the corpus gate reports it as identity
    # instability rather than letting the dedupe act on it.
    hash_a, hash_b = a.get("content_hash"), b.get("content_hash")
    if hash_a is not None and hash_b is not None and hash_a == hash_b:
        return {
            "relation": "identical",
            "reason": (
                "same content_hash — the same bytes"
                if key_a == key_b else
                f"same content_hash — the same bytes, though the notice_identity "
                f"keys differ ({key_a!r} vs {key_b!r}): the header pass did not "
                f"report the same revision twice for identical bytes, and a "
                f"document cannot supersede its own copy"
            ),
        }

    if key_a == key_b:
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
                f"{b.get('revision')!r} differ but their order is not decidable "
                f"(not both dotted-numeric, not both single-alphabetic, or one side is "
                f"absent and an absent revision may be a header miss rather than "
                f"a document that prints none) — guessing would risk hiding the "
                f"newer notice behind the older one"
            ),
        }
    if order == 0:
        return {
            "relation": "duplicate_copy",
            "reason": (
                f"same (mfr, doc_id); revisions {a.get('revision')!r} vs "
                f"{b.get('revision')!r} differ only in how the SAME revision was "
                f"spelled (e.g. '1.0' vs '1.00', or a leading zero) — same notice "
                f"identity, not an ordering"
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
