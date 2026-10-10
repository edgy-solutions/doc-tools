"""CAD format identity passes: ``cad.step_ap242_identity`` and ``cad.dxf_identity``.

Same two invariants as ``identity.py``, enforced by the same ``_verify_chain``:

1. every ``source`` is a verbatim substring of the text it was read from
2. every ``value`` is a verbatim substring of its own ``source``

and the same refusal rule: a field that is not printed is named in ``refused``,
never guessed and never defaulted. A STEP file's NAME is not its document
number, and a DXF drawing with no title block has no identity to report; a
filename substituted for either would be a false provenance claim.

IDENTITY ONLY. Nothing here reads geometry, assemblies or layers. Both passes
are pure text functions: no model, no network, no clock, no filesystem.

``schema`` is reported, never asserted. ``FILE_SCHEMA`` is how an AP242 file is
told from AP203/AP214, so the pass records what the file says and leaves the
decision to the caller.

The result types are ``identity.DocumentIdentity`` / ``IdentityField`` unchanged.
Their ``as_dict`` only emits the title-block field names, so a consumer of this
pass reads ``.fields`` / ``.value(name)`` / ``.refused`` rather than ``as_dict``.
"""
from __future__ import annotations

import re
from typing import Mapping

from doc_tools.passes.identity import (
    DocumentIdentity,
    IdentityError,
    IdentityField,
    _verify_chain,
)

#: Fields each pass reports, in report order.
STEP_FIELDS: tuple[str, ...] = (
    "schema", "document_number", "revision",
    "file_name", "timestamp", "author", "organization",
)
DXF_FIELDS: tuple[str, ...] = (
    "project_name", "document_number", "revision", "cage_code", "contract_number",
)

#: DXF attribute TAG aliases, compared case-insensitively.
DXF_TAG_ALIASES: Mapping[str, frozenset[str]] = {
    "document_number": frozenset({
        "DWG_NO", "DWGNO", "DRAWING_NUMBER", "DRAWING_NO", "DOC_NO",
        "DOCUMENT_NUMBER",
    }),
    "revision": frozenset({"REV", "REVISION", "REV_LEVEL"}),
    "cage_code": frozenset({"CAGE", "CAGEC", "CAGE_CODE"}),
    "contract_number": frozenset({"CONTRACT", "CONTRACT_NO", "CONTRACT_NUMBER"}),
}

# ---------------------------------------------------------------------------
# STEP (ISO 10303-21)
# ---------------------------------------------------------------------------

_STEP_STRING = re.compile(r"'((?:[^']|'')*)'")


def _entity_re(name: str) -> re.Pattern[str]:
    """An entity keyword immediately followed by an open paren, not part of a
    longer name (``PRODUCT_DEFINITION_FORMATION(`` must not satisfy ``PRODUCT(``).
    """
    return re.compile(r"(?<![A-Za-z0-9_])" + name + r"\s*\(", re.IGNORECASE)


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _first_string_arg(text: str, name: str) -> tuple[str, str] | None:
    """``(value, source)`` of the first string argument of entity ``name``.

    ``source`` runs from the keyword through the closing quote of that string.
    The string must be the first thing inside the parentheses; an entity whose
    first argument is not a string, or is empty, is skipped.
    """
    for m in _entity_re(name).finditer(text):
        s = _STEP_STRING.match(text, _skip_ws(text, m.end()))
        if s and s.group(1).strip():
            return s.group(1), text[m.start(): s.end()]
    return None


def _split_args(text: str, start: int) -> list[tuple[int, int]]:
    """``(begin, end)`` spans of the top-level arguments after an open paren.

    ``start`` is the index just past the paren. Quotes (with doubled-quote
    escapes) and nested parentheses are respected. Returns [] if the call never
    closes.
    """
    spans: list[tuple[int, int]] = []
    depth, i, begin, n = 0, start, start, len(text)
    while i < n:
        c = text[i]
        if c == "'":
            i += 1
            while i < n:
                if text[i] == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        i += 2
                        continue
                    break
                i += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            if depth == 0:
                spans.append((begin, i))
                return spans
            depth -= 1
        elif c == "," and depth == 0:
            spans.append((begin, i))
            begin = i + 1
        i += 1
    return []


def _arg_value(arg: str) -> str | None:
    """The printed value of one header argument, or None if it prints nothing.

    A lone string (bare or as a one-element list) yields its contents; any
    other non-empty argument (a multi-element list) yields the argument text
    exactly as printed, quotes included.
    """
    a = arg.strip()
    if not a or a == "$":
        return None
    inner = a[1:-1].strip() if a.startswith("(") and a.endswith(")") else a
    s = _STEP_STRING.fullmatch(inner)
    if s:
        return s.group(1) if s.group(1).strip() else None
    return a if inner else None


def step_ap242_identity(text: str) -> DocumentIdentity:
    """Read schema, product id, revision and FILE_NAME fields, verbatim."""
    found: dict[str, IdentityField] = {}

    def add(name: str, value: str, source: str, label: str, region: str) -> None:
        _verify_chain(value, source, text, name)
        found[name] = IdentityField(
            field=name, value=value, source=source, label=label,
            page_number=None, region=region, method="step_entity",
        )

    m = _entity_re("FILE_SCHEMA").search(text)
    if m:
        spans = _split_args(text, m.end())
        if spans:
            b, e = spans[0]
            s = _STEP_STRING.search(text[b:e])
            if s and s.group(1).strip():
                add("schema", s.group(1), text[m.start(): e + 1],
                    "FILE_SCHEMA", "step_header")

    m = _entity_re("FILE_NAME").search(text)
    if m:
        spans = _split_args(text, m.end())
        for pos, name in ((0, "file_name"), (1, "timestamp"),
                          (2, "author"), (3, "organization")):
            if pos < len(spans):
                b, e = spans[pos]
                value = _arg_value(text[b:e])
                if value is not None:
                    arg = text[b:e].strip()
                    end = text.index(arg, b) + len(arg)
                    add(name, value, text[m.start(): end],
                        "FILE_NAME", "step_header")

    hit = _first_string_arg(text, "PRODUCT")
    if hit:
        add("document_number", hit[0], hit[1], "PRODUCT", "step_data")
    hit = _first_string_arg(text, "PRODUCT_DEFINITION_FORMATION")
    if hit:
        add("revision", hit[0], hit[1], "PRODUCT_DEFINITION_FORMATION",
            "step_data")

    fields = {n: found[n] for n in STEP_FIELDS if n in found}
    refused = tuple(n for n in STEP_FIELDS if n not in fields)
    return DocumentIdentity(fields=fields, refused=refused, region="step")


# ---------------------------------------------------------------------------
# DXF (ASCII group-code pairs)
# ---------------------------------------------------------------------------

_BINARY_SENTINEL = "AutoCAD Binary DXF"


def _binary_error() -> IdentityError:
    return IdentityError(
        "not ASCII DXF: binary DXF is unsupported by cad.dxf_identity "
        "(refusing rather than returning an empty identity, which would read "
        "as a drawing with no title block)"
    )


def _pairs(text: str) -> list[tuple[int, str, int, int]]:
    """``(group code, value, start offset, end offset)`` per pair, in order.

    The value is the line exactly as printed, minus its line terminator. The
    offsets span both lines of the pair in ``text``. Raises ``IdentityError``
    if the text is not ASCII group-code pairs.
    """
    if "\x00" in text or text.lstrip().startswith(_BINARY_SENTINEL):
        raise _binary_error()
    lines = text.splitlines(keepends=True)
    offsets, pos = [], 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)
    out: list[tuple[int, str, int, int]] = []
    i = 0
    while i + 1 < len(lines):
        code_s = lines[i].strip()
        if not re.fullmatch(r"-?\d+", code_s):
            if not code_s and not out:  # leading blank lines
                i += 1
                continue
            raise _binary_error()
        value = lines[i + 1].rstrip("\r\n")
        out.append((int(code_s), value, offsets[i], offsets[i + 1] + len(value)))
        i += 2
    # Comment pairs (999) may precede the first SECTION.
    body = [p for p in out if p[0] != 999]
    if not body or body[0][0] != 0 or body[0][1].strip() != "SECTION":
        raise _binary_error()
    return out


def dxf_identity(text: str) -> DocumentIdentity:
    """Read ``$PROJECTNAME`` and ATTRIB/ATTDEF title-block values, verbatim."""
    pairs = _pairs(text)
    found: dict[str, IdentityField] = {}

    def add(name: str, value: str, source: str, label: str, region: str) -> None:
        _verify_chain(value, source, text, name)
        found[name] = IdentityField(
            field=name, value=value, source=source, label=label,
            page_number=None, region=region, method="dxf_group_code",
        )

    # HEADER variable: group 9 names it, the next pair is its value.
    for i, (code, val, b, _e) in enumerate(pairs[:-1]):
        if code == 9 and val.strip().upper() == "$PROJECTNAME":
            _vc, vval, _vb, ve = pairs[i + 1]
            if vval.strip():
                add("project_name", vval, text[b:ve], val.strip(), "dxf_header")
                break

    # Entities: split on group code 0, keep ATTRIB / ATTDEF.
    entities: list[list[tuple[int, str, int, int]]] = []
    for p in pairs:
        if p[0] == 0:
            entities.append([p])
        elif entities:
            entities[-1].append(p)
    for ent in entities:
        if ent[0][1].strip().upper() not in ("ATTRIB", "ATTDEF"):
            continue
        tag = next((p for p in ent if p[0] == 2), None)
        val = next((p for p in ent if p[0] == 1), None)
        if not tag or not val or not val[1].strip():
            continue
        for name, aliases in DXF_TAG_ALIASES.items():
            if name not in found and tag[1].strip().upper() in aliases:
                b, e = min(tag[2], val[2]), max(tag[3], val[3])
                add(name, val[1], text[b:e], tag[1].strip(), "dxf_attrib")

    fields = {n: found[n] for n in DXF_FIELDS if n in found}
    refused = tuple(n for n in DXF_FIELDS if n not in fields)
    return DocumentIdentity(fields=fields, refused=refused, region="dxf")
