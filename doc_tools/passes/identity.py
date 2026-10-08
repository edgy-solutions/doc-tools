"""``identity.document_identity`` — the document-identity pass.

The architect's 2026-10-02 order, as recorded verbatim in
``doc_tools/utils/content_kind.py``'s ``UNBUILT_PASSES`` comment:

    "document number, revision, CAGE code, contract/program identifiers from
    title blocks and DOORS module attributes, verbatim with sources, refused
    if not printed"

This module is that pass. It is the only declared pass of the three
format-level kinds (``pdf``, ``engineering-document``, ``doors-export``), none
of which declares a domain, because under the same ruling a format-level drop's
ORIGIN is resolved from this evidence rather than asserted by its kind.

DETERMINISTIC AND LLM-FREE, deliberately
----------------------------------------
A label match can be SEALED on a fixture: run it once, and the answer is the
answer. An LLM pass cannot — this repo has a long record of header fields that
moved between fires on byte-identical input, so "sealing" one costs three fires
and still leaves serving nondeterminism as a residual. Identity fields are the
scalars every downstream claim is keyed on, so they get the mechanism that can
actually be pinned.

It also means there is nothing to hallucinate. The pass never produces a
string the document does not contain; it can only fail to find one.

TITLE BLOCKS AND DOORS PREAMBLES ARE THE SAME SHAPE
---------------------------------------------------
A drawing title block prints ``Document No.: 12345-002``. A DOORS export
preamble prints ``Document Number: SRS-MRAD-001``. Both are a labelled line.
So there is ONE extractor and two callers, rather than a title-block parser and
a DOORS parser that will drift apart. ``document_identity`` takes page texts;
``identity_from_doors_text`` is a thin wrapper that points it at an export's
preamble region. Nothing here imports the DOORS parser, so neither owns the
other.

TWO INVARIANTS, ENFORCED IN CODE
--------------------------------
1. every ``source`` is a verbatim substring of the page text it is attributed to
2. every ``value`` is a verbatim substring of its own ``source``

Both are checked by ``_verify_chain`` on the way out, and a violation raises
rather than returning a field. They matter in that order and only together: a
citation that resolves proves nothing about the value printed beside it unless
the value is IN the citation. Invariant 2 is what anchors the claim to the
document; invariant 1 is what makes it locatable.

Note on naming: the per-field key is ``method``/``label``/``region``, NOT
``obtained_via``. ``obtained_via`` already means something else in this repo —
ADR-0041 drop provenance, how a document ENTERED the system ("user-drop") — and
the two are unrelated. Reusing the name would silently merge them.

REFUSED IF NOT PRINTED
----------------------
A field with no labelled line is ``None`` and is named in ``refused``. It is
never inferred from a filename, a path, a neighbouring value, or a shape match
on unlabelled text. A bare five-character token is not a CAGE code just because
CAGE codes are five characters; ``EU-TTI-MASTK`` printed after ``Agreement:``
is not a contract number; ``Sub Document Number: SUB-9`` is a sub-assembly's
number, not this document's, and is refused rather than taken (see
``_value_after_label``). A guessed identity field is a false provenance claim
about a real document, which is worse than an absent one: absence is visible in
``refused`` and a guess is not visible anywhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Iterable, Mapping, Sequence


class IdentityError(RuntimeError):
    """An invariant broke. Not raised for a missing field — that is a refusal."""


#: Field name -> label aliases, longest-first within each field so ``Revision``
#: is tried before ``Rev`` and the shorter alias cannot shadow the longer one.
#: This table is the whole configuration surface of the pass. A new site whose
#: title block says something else gains an alias HERE; it does not gain a
#: looser matcher, because loosening the matcher is how a label-anchored
#: extractor turns into a shape-guessing one.
LABEL_ALIASES: Mapping[str, tuple[str, ...]] = {
    "document_number": (
        # Engineering title blocks.
        "Document Number", "Document No", "Document", "Doc Number", "Doc No",
        "Drawing Number", "Drawing No", "Specification Number",
        "Specification No", "Spec No", "Report Number", "Report No",
        # Change-notice front matter. A notice's document number IS its notice
        # number; vendors print it under the notice's own name.
        "Product Change Notification", "Product Discontinuance Notification",
        "Notification Number", "PCN Number", "PDN Number", "PCN No", "PDN No",
    ),
    "revision": ("Revision", "Rev Level", "Rev"),
    "cage_code": ("CAGE Code", "CAGE"),
    "contract_number": (
        "Contract Number", "Contract No", "Contract",
        "Program Number", "Program No",
    ),
}

#: Fields this pass reports, in report order.
IDENTITY_FIELDS: tuple[str, ...] = tuple(LABEL_ALIASES)

#: A label is a capitalised run ending in a colon. Used ONLY to find where a
#: value STOPS when a second field shares the line -- never to discover a
#: label, which is alias-driven. See ``_value_after_label``.
_NEXT_LABEL = re.compile(r"\s{1,}([A-Z][A-Za-z0-9 /.()\-]{0,40}):(?:\s|$)")

#: Trailing punctuation a title block puts after a value but which is not part
#: of it. A leading/trailing quote is stripped for the same reason.
_TRIM = " \t\r\n,;:|\"'"


@dataclass(frozen=True)
class IdentityField:
    """One field, verbatim, with the line it was read out of.

    ``value`` is a substring of ``source``; ``source`` is a substring of the
    page text at ``page_number``. ``label`` is the alias that actually matched,
    so a reviewer can see WHICH spelling fired rather than inferring it.
    """

    field: str
    value: str
    source: str
    label: str
    page_number: int | None
    region: str
    method: str = "labelled_line"


@dataclass(frozen=True)
class DocumentIdentity:
    """The pass's result. Absent fields are refusals, not failures."""

    fields: Mapping[str, IdentityField] = dc_field(default_factory=dict)
    refused: tuple[str, ...] = ()
    region: str = ""

    def get(self, name: str) -> IdentityField | None:
        return self.fields.get(name)

    def value(self, name: str) -> str | None:
        f = self.fields.get(name)
        return f.value if f else None

    def as_dict(self) -> dict[str, object]:
        """Flat ``{field, field_source, field_page, field_label}`` + refusals.

        The ``<field>``/``<field>_source`` shape mirrors ``NoticeHeader`` in
        ``baml_src/sustainment.baml`` so a consumer that already reads a value
        beside its source needs no second convention.
        """
        out: dict[str, object] = {}
        for name in IDENTITY_FIELDS:
            f = self.fields.get(name)
            out[name] = f.value if f else None
            out[f"{name}_source"] = f.source if f else None
            out[f"{name}_page"] = f.page_number if f else None
            out[f"{name}_label"] = f.label if f else None
        out["refused"] = list(self.refused)
        out["region"] = self.region
        return out


def _lines_with_pages(pages: Sequence[str]) -> list[tuple[str, int]]:
    """``(line, 1-based page number)`` for every line, in document order.

    Pages are searched in order and the FIRST labelled line wins, because a
    title block is front matter: when a document number is printed on the cover
    and repeated in a page footer, the cover is the one that was declared.
    """
    out: list[tuple[str, int]] = []
    for page_no, text in enumerate(pages, start=1):
        for line in (text or "").splitlines():
            out.append((line, page_no))
    return out


def _value_after_label(line: str, label: str) -> str | None:
    """The value printed after ``label:`` on ``line``, or None.

    TRUNCATED AT THE NEXT LABEL ON THE SAME LINE. A flattened PDF text layer
    routinely puts two fields on one line::

        Product Change Notification: PCN-24-210412 PCN Date: 07-JUN-24

    Reading to end-of-line yields ``PCN-24-210412 PCN Date: 07-JUN-24`` as the
    document number -- a value that still "resolves" against the page and is
    still wrong. The remainder is therefore cut at the next ``Label:`` run.

    The label must be followed by a colon and a NON-EMPTY value. That is what
    makes the bare banner line ``Product Change Notification`` (no colon, no
    value) yield nothing instead of becoming a field, and what makes an empty
    title-block cell (``Revision:`` with nothing after it) a refusal.

    A QUALIFIED LABEL IS A DIFFERENT FIELD. ``Sub Document Number: SUB-9`` and
    ``Customer Document Number: C-4`` both contain ``Document Number:``, and
    neither is THIS document's number -- reading one is the false-provenance
    failure the module exists to avoid, and it would not be caught downstream
    because the chain still resolves. So a match is rejected when the token
    immediately before it is a bare alphabetic word.

    That guard stands down once a colon has already appeared on the line,
    because from there on a preceding word is ambiguous between a qualifier and
    the tail of the previous field's VALUE: in ``Agreement: EU-TTI-MASTK
    Contract No: X`` the word before ``Contract No`` is a value, and refusing it
    would cost a real field. The residual hole is stated rather than papered
    over -- ``Customer: ACME Sub Document Number: X`` is accepted, because at
    that point the two cases are not distinguishable from the line alone.
    """
    # Word-boundary, case-insensitive, optional period before the colon
    # ("Document No." as well as "Document No").
    pat = re.compile(
        r"(?:^|(?<=\s))" + re.escape(label) + r"\.?\s*:\s*",
        re.IGNORECASE,
    )
    for m in pat.finditer(line):
        prefix = line[: m.start()]
        if ":" not in prefix:
            tail = prefix.rstrip()
            if tail and tail.split()[-1].isalpha():
                continue  # a qualified label, not this field
        rest = line[m.end():]
        cut = _NEXT_LABEL.search(rest)
        if cut:
            rest = rest[: cut.start()]
        value = rest.strip(_TRIM)
        if value:
            return value
    return None


def _verify_chain(value: str, source: str, page_text: str, name: str) -> None:
    """Invariants 2 then 1. Raises ``IdentityError``; never returns a verdict.

    Checked against the RAW page text, never a normalised copy. Whitespace
    folding is not offset- or substring-preserving in this repo (it collapses
    runs and strips), so a chain verified against a folded copy is a chain
    verified against a different document.
    """
    if value not in source:
        raise IdentityError(
            f"{name}: value {value!r} is not a substring of its own source "
            f"{source!r}. The citation would resolve while the value beside it "
            f"was assembled rather than copied."
        )
    if source not in page_text:
        raise IdentityError(
            f"{name}: source {source!r} is not a verbatim substring of the "
            f"page it is attributed to, so the field is not locatable."
        )


def document_identity(
    pages: Sequence[str] | str,
    *,
    region: str = "title_block",
    aliases: Mapping[str, Iterable[str]] | None = None,
) -> DocumentIdentity:
    """Read document number, revision, CAGE code and contract id, verbatim.

    ``pages`` is the document's text: a sequence of page texts (page numbers
    come out 1-based), or a single string (page 1). ``region`` is recorded on
    every field so a consumer can tell a title-block read from a DOORS preamble
    read without re-deriving it.

    Every field is either present with a source or named in ``refused``. The
    function does not raise for a missing field; it raises only if an invariant
    breaks, which would be a defect in this module.
    """
    page_list = [pages] if isinstance(pages, str) else list(pages)
    table = {k: tuple(v) for k, v in (aliases or LABEL_ALIASES).items()}
    lines = _lines_with_pages(page_list)

    found: dict[str, IdentityField] = {}
    for name in table:
        hit = None
        # Document order, then alias order (longest-first). The first labelled
        # line wins; a later repeat of the same field is not a second opinion.
        for line, page_no in lines:
            for label in table[name]:
                value = _value_after_label(line, label)
                if value:
                    hit = (value, line, label, page_no)
                    break
            if hit:
                break
        if not hit:
            continue
        value, source, label, page_no = hit
        _verify_chain(value, source, page_list[page_no - 1], name)
        found[name] = IdentityField(
            field=name, value=value, source=source, label=label,
            page_number=page_no, region=region,
        )

    refused = tuple(n for n in table if n not in found)
    return DocumentIdentity(fields=found, refused=refused, region=region)


def identity_from_doors_text(
    text: str,
    *,
    header_markers: Iterable[str] = (
        "Object Identifier", "Object Heading", "Object Text", "Absolute Number",
    ),
) -> DocumentIdentity:
    """The DOORS-module-attribute half, same extractor, preamble region only.

    Scoped to the preamble — everything above the export's column-header row —
    so an OBJECT whose text happens to read ``Contract No: ...`` cannot be
    mistaken for a module attribute. A requirement that quotes a contract
    number is a requirement, not the module's identity.

    The preamble boundary is found by marker, matching the DOORS parser's own
    rule, and is deliberately duplicated as a default argument rather than
    imported: this pass must run on a title block with no DOORS parser in the
    picture, and a format-level pass that imports a format-specific parser
    inverts the dependency.

    If no header row is found the whole text is treated as preamble, because a
    header-row refusal belongs to the DOORS parser, not here — refusing twice
    in two modules with two messages is how a caller learns to catch both.
    """
    markers = tuple(header_markers)
    lines = text.splitlines()
    cut = len(lines)
    for i, line in enumerate(lines):
        if any(m in line for m in markers):
            cut = i
            break
    return document_identity(
        "\n".join(lines[:cut]), region="doors_preamble",
    )
