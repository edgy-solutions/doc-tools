"""Shared canonical DMC string canonicalizer.

Per the architect's B3 framing: "same-canonicalizer-both-sides" — the
B2 ingest writer and the B3 read path (Engine E's /resolve_dmc) must
use the IDENTICAL function for normalizing DMC strings. Two parallel
implementations would reproduce the exact `n_candidates=0`-when-it-
should-match failure that 49a3fdb (the B2 DMC string-form fix) just
closed at the write layer.

This module is the single source of truth. `s1000d_ingest` imports
`canonicalize_dmc` for the write path; Engine E (neo4j_expert)
imports it for the /resolve_dmc read path. A bug in canonicalization
fails both tests identically — exactly the property the rule was
named for.

Per S1000D Issue 4.2 (and back-compatible with 5.0 / 6.0), the
canonical DMC string form is:

    <mic>-<sdc>-<sysc>-<ssc><sssc>-<asy>-<dis><dvar>-<info><ivar>-<itemloc>

Field widths and concatenation rules (CONCAT means no separator
between the two fields):

    mic           variable length (model identification code, typically
                  6-14 chars, uppercase alphanumeric)
    sdc           1 char (system difference code, alpha)
    sysc          2 chars (system code, typically digits but allows
                  hyphen-extended in some specs)
    ssc + sssc    CONCAT, 1+1=2 chars (sub-system + sub-sub-system)
    asy           2 chars (assembly code)
    dis + dvar    CONCAT, 2+1=3 chars (disassembly code + variant)
    info + ivar   CONCAT, 3+1=4 chars (info code + variant)
    itemloc       1 char (item location code)

Example: `EXAMPLE-B-72-30-10-00A-520A-A`
  mic=EXAMPLE, sdc=B, sysc=72, ssc=3, sssc=0, asy=10,
  dis=00, dvar=A, info=520, ivar=A, itemloc=A.

Acceptable input forms (all normalize to the canonical above):

    EXAMPLE-B-72-30-10-00A-520A-A         (already canonical)
    DMC-EXAMPLE-B-72-30-10-00A-520A-A     (with "DMC-" prefix)
    example-b-72-30-10-00a-520a-a         (lowercase)
    "  DMC-EXAMPLE-B-72-30-10-00A-520A-A "  (whitespace padding)

Forms that DO NOT canonicalize (returns None):

    Random strings, partial DMCs, non-S1000D identifiers. The phone
    book must return 0 candidates honestly when the input isn't a
    DMC — not every instance query is one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# The canonical form, as a regex. Anchored. UPPERCASE expected after
# normalization. Field groupings match the docstring's table.
#
# mic is intentionally permissive (1+ chars, alphanumeric) so test
# corpora (with any well-formed MIC) validate alongside production MICs.
_CANONICAL_RE = re.compile(
    r"^"
    r"(?P<mic>[A-Z0-9]+)"
    r"-"
    r"(?P<sdc>[A-Z])"
    r"-"
    r"(?P<sysc>[A-Z0-9]{2})"
    r"-"
    r"(?P<sscn>[A-Z0-9]{2})"     # ssc + sssc (concatenated)
    r"-"
    r"(?P<asy>[A-Z0-9]{2})"
    r"-"
    r"(?P<disvar>[A-Z0-9]{3})"   # dis + dvar (concatenated)
    r"-"
    r"(?P<infovar>[A-Z0-9]{4})"  # info + ivar (concatenated)
    r"-"
    r"(?P<itemloc>[A-Z])"
    r"$"
)


@dataclass(frozen=True)
class DMCFields:
    """The decomposed DMC. Useful when callers need the parts (e.g.,
    for substring search, not just exact match)."""
    mic: str
    sdc: str
    sysc: str
    ssc: str
    sssc: str
    asy: str
    dis: str
    dvar: str
    info: str
    ivar: str
    itemloc: str

    @property
    def canonical(self) -> str:
        return (
            f"{self.mic}-{self.sdc}-{self.sysc}-{self.ssc}{self.sssc}-"
            f"{self.asy}-{self.dis}{self.dvar}-{self.info}{self.ivar}-"
            f"{self.itemloc}"
        )


def canonicalize_dmc(raw: Optional[str]) -> Optional[str]:
    """Normalize a DMC-shaped input string to its canonical form.

    Returns the canonical string on success, None if the input isn't a
    recognizable DMC. NEVER raises on user input; the contract is
    "honest miss" — if you can't canonicalize, return None and let
    the caller report 0 candidates.

    Used by:
      - doc_tools.parsers.s1000d_ingest.extract_facts (WRITE path)
      - agent_fleet.neo4j_expert.main /resolve_dmc handler (READ path)

    These two paths must agree on the canonical form. A bug here
    breaks both, which is the architectural property the
    same-canonicalizer-both-sides rule named.
    """
    if not raw:
        return None
    fields = parse_dmc(raw)
    return fields.canonical if fields else None


def parse_dmc(raw: Optional[str]) -> Optional[DMCFields]:
    """Same as canonicalize_dmc but returns the decomposed fields.

    Useful for substring queries or for emitting structured logs that
    name which field a bad input failed to match.
    """
    if not raw:
        return None
    s = raw.strip().upper()

    # Strip the literal "DMC-" prefix some callers include
    if s.startswith("DMC-"):
        s = s[4:]

    # Strip surrounding quotes
    s = s.strip('"').strip("'")

    # Replace any underscores or runs of whitespace with single hyphens
    # (DMC strings sometimes get round-tripped through filenames with
    # different separator conventions).
    s = re.sub(r"[\s_]+", "-", s)

    m = _CANONICAL_RE.match(s)
    if not m:
        return None

    # Decompose ssc/sssc and dis/dvar and info/ivar from their
    # concatenated forms.
    sscn = m.group("sscn")     # 2 chars
    disvar = m.group("disvar")  # 3 chars
    infovar = m.group("infovar")  # 4 chars

    return DMCFields(
        mic=m.group("mic"),
        sdc=m.group("sdc"),
        sysc=m.group("sysc"),
        ssc=sscn[0],
        sssc=sscn[1],
        asy=m.group("asy"),
        dis=disvar[0:2],
        dvar=disvar[2],
        info=infovar[0:3],
        ivar=infovar[3],
        itemloc=m.group("itemloc"),
    )


def assemble_canonical_dmc(
    *,
    mic: str, sdc: str, sysc: str,
    ssc: str, sssc: str, asy: str,
    dis: str, dvar: str, info: str, ivar: str,
    itemloc: str,
) -> str:
    """Assemble a canonical DMC string from the decomposed dmCode
    attributes (what extract_facts reads from S1000D XML).

    Use this in the WRITE path so the writer's output is canonical by
    construction — not by accident of how a join happens to format.
    Same function the canonicalizer's regex normalizes TO.

    The B2 ingest's extract_facts calls this to build facts.dmc;
    Engine E's /resolve_dmc handler calls canonicalize_dmc(query) to
    normalize a user query to the same form for the lookup.
    """
    return (
        f"{mic.upper()}-"
        f"{sdc.upper()}-"
        f"{sysc.upper()}-"
        f"{ssc.upper()}{sssc.upper()}-"
        f"{asy.upper()}-"
        f"{dis.upper()}{dvar.upper()}-"
        f"{info.upper()}{ivar.upper()}-"
        f"{itemloc.upper()}"
    )


# =============================================================================
# MIL-STD-40051 WPNO canonicalizer (per architect's 40051-track assignment,
# 2026-06-13). The 40051 wpno is the analog of S1000D's DMC — the WP-level
# instance identifier. Same "same-canonicalizer-both-sides" rule: the WP
# ingest reader and any future WP phone-book read path must use the
# IDENTICAL function. Lives in the same file as canonicalize_dmc so the
# byte-identity drift guard between agent_fleet/utils and doc-tools covers
# both round-trips with one assertion.
#
# IMPORTANT: 40051 wpno values DO NOT have a single fixed grammar. The DTD
# declares `wpno` as `CDATA` — any string is valid. Observed forms in
# 40051 TMs include:
#   - "EXAMPLE-X-XXXX-VAR"  (full type + WP num + TM number + variant)
#   - "P0005"               (type + WP num only; no TM tail)
#   - "introwp_name"        (descriptive name; underscore-separated)
#
# Therefore canonicalize_wpno is a NORMALIZER, not a structural validator.
# It returns None only when input is empty/whitespace-only — anything else
# is canonicalized to a deterministic form. The "honest miss" applies to
# garbage input, not to legitimate variant shapes.
#
# Canonicalization rules:
#   1. strip surrounding whitespace + quotes
#   2. lowercase
#   3. replace any run of whitespace OR underscore with a single hyphen
#   4. reject pure-empty + strings with no alphanumeric character
#   5. return verbatim normalized form
# =============================================================================

_WPNO_HAS_ALNUM = re.compile(r"[a-z0-9]")


@dataclass(frozen=True)
class WPNOFields:
    """Decomposed 40051 wpno. The structured form `<type><num>-<tm_id>`
    when the input matches that grammar; otherwise wptype/wpnum are
    empty and the full string lives in tm_id. The canonical form is
    always recoverable via `.canonical`."""
    wptype: str
    wpnum: str
    tm_id: str

    @property
    def canonical(self) -> str:
        if self.wptype and self.wpnum:
            return f"{self.wptype}{self.wpnum}-{self.tm_id}" if self.tm_id else f"{self.wptype}{self.wpnum}"
        return self.tm_id


_WPNO_STRUCTURED_RE = re.compile(
    r"^"
    r"(?P<wptype>[a-z])"
    r"(?P<wpnum>[0-9]+)"
    r"(?:-(?P<tail>[a-z0-9-]+))?"
    r"$"
)


def canonicalize_wpno(raw: Optional[str]) -> Optional[str]:
    """Normalize a 40051 wpno string to its canonical form.

    Returns the canonical string on success, None if the input is
    empty or contains no alphanumeric character (true garbage).
    NEVER raises on user input — "honest miss" for true garbage,
    successful normalization for any well-formed identifier.

    Used by:
      - doc_tools.parsers.mil_40051_ingest.read_40051_wp (WRITE path)
      - any future 40051 phone-book read path (analogous to /resolve_dmc)

    Same-canonicalizer-both-sides: a bug here fails write and read
    paths identically. The drift guard between agent_fleet/utils and
    doc-tools enforces that the two copies stay byte-identical so this
    property holds for both DMC and wpno.
    """
    fields = parse_wpno(raw)
    return fields.canonical if fields else None


def parse_wpno(raw: Optional[str]) -> Optional[WPNOFields]:
    """Same as canonicalize_wpno but returns the decomposed fields.

    For inputs matching the structured "type+num-tail" grammar, wptype
    and wpnum are extracted; for unstructured inputs (descriptive name
    form like "rpstl_introwp"), they're empty and the full string is
    tm_id.
    """
    if not raw:
        return None
    s = raw.strip().strip('"').strip("'")
    s = re.sub(r"[\s_]+", "-", s)
    s = s.lower()
    if not _WPNO_HAS_ALNUM.search(s):
        return None
    m = _WPNO_STRUCTURED_RE.match(s)
    if m:
        return WPNOFields(
            wptype=m.group("wptype"),
            wpnum=m.group("wpnum"),
            tm_id=m.group("tail") or "",
        )
    return WPNOFields(wptype="", wpnum="", tm_id=s)


def assemble_canonical_wpno(*, wptype: str, wpnum: str, tm_id: str) -> str:
    """Assemble a canonical wpno from its decomposed parts.

    Use this in the WRITE path so the writer's output is canonical by
    construction (mirrors assemble_canonical_dmc).

    If wptype/wpnum are both empty (unstructured form), returns tm_id
    lowercased — the round-trip identity for descriptive-name wpnos.
    """
    if wptype and wpnum:
        if tm_id:
            return f"{wptype.lower()}{wpnum}-{tm_id.lower()}"
        return f"{wptype.lower()}{wpnum}"
    return tm_id.lower()
