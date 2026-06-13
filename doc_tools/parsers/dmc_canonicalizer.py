"""Shared canonical DMC string canonicalizer.

Per the architect's B3 framing: "same-canonicalizer-both-sides" — the
B2 ingest writer and the B3 phone-book reader must use the IDENTICAL
function for normalizing DMC strings. Two parallel implementations
would reproduce the exact `n_candidates=0`-when-it-should-match
failure that 49a3fdb (the B2 DMC string-form fix) just closed at the
write layer.

This module is the single source of truth. `s1000d_ingest` imports
`canonicalize_dmc` for the write path; the B3 phone book imports it
for the read path. A bug in canonicalization fails both tests
identically — exactly the property the rule was named for.

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

Example: `SANDBOXRTX-B-72-30-10-00A-520A-A`
  mic=SANDBOXRTX, sdc=B, sysc=72, ssc=3, sssc=0, asy=10,
  dis=00, dvar=A, info=520, ivar=A, itemloc=A.

Acceptable input forms (all normalize to the canonical above):

    SANDBOXRTX-B-72-30-10-00A-520A-A         (already canonical)
    DMC-SANDBOXRTX-B-72-30-10-00A-520A-A     (with "DMC-" prefix)
    sandboxrtx-b-72-30-10-00a-520a-a         (lowercase)
    "  DMC-SANDBOXRTX-B-72-30-10-00A-520A-A "  (whitespace padding)

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
# corpora like SANDBOXRTX validate alongside production MICs.
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
      - agent_fleet.dmc_phone_book.main (READ path)

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

    The B2 ingest's extract_facts calls this to build facts.dmc; the
    B3 phone book calls canonicalize_dmc(query) to normalize a user
    query to the same form for the lookup.
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
