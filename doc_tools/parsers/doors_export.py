"""DOORS export ingest — module identity, objects, and TIER-1 table artifacts.

A DOORS spreadsheet export is a flat CSV of *objects*, not a document: each row
is one DOORS object carrying its outline level, an optional heading, optional
text, a type, and the module's user-defined attributes as further columns. The
module's own attributes (project, baseline, prefix, CAGE, contract) ride ABOVE
the header row as a ``Key: Value`` preamble written by the exporting DXL script.

What this module is for, in one line: turn that file into (a) an identity we can
key the drop on, and (b) the tables it contains, as artifacts, deterministically
and with NO LLM.

THE STRUCTURE THIS PARSES, and the honest caveat about it
--------------------------------------------------------
DOORS encodes a table as a *subtree of objects*, not as a cell block: one object
of type ``Table``, whose children are ``Table Row`` objects, whose children are
``Table Cell`` objects holding the text. A grid is therefore reconstructed by
walking outline levels, never by splitting a string.

The shape is modelled on the classic "Export -> Spreadsheet" output plus a
DXL-written module preamble. **Real exports vary** — column names are
site-configurable and some sites emit no preamble at all. So every assumption
here is checked and failure is LOUD (see the refusals below): a misparsed export
that silently yields a plausible-looking artifact is far worse than one that
stops. ``tests/fixtures/doors/`` holds a synthetic export with this structure;
when a real one arrives, the refusals are what will tell us where it differs,
and they name the values they actually saw so the diff is readable.

TIER-1 vs TIER-2 — the word is used here as the corpus work uses it
------------------------------------------------------------------
A table is **tier-1** when it reconstructs into a clean rectangle: every
``Table Row`` under it yields the same number of ``Table Cell`` children. Only
tier-1 tables become artifacts, because only they can be written as a CSV grid
without inventing or dropping a cell.

A ragged table is **tier-2** and is reported, not padded and not silently
emitted. Padding a ragged grid would put a value under the wrong column header,
which is exactly the class of defect the PCN crop work spent weeks disproving —
a cell in the wrong column reads as a *correct-looking* wrong answer. Tier-2
forwarding is separate work; this module's job is to refuse to guess.

REFUSALS (all raise ``DoorsParseError``; none of them degrade quietly)
---------------------------------------------------------------------
  1. No recognizable header row. Treating line 1 as headers would turn a
     preamble line into column names and every object into garbage.
  2. No module identity. ``project`` and ``baseline`` are what the drop is keyed
     on; without them the artifacts cannot be attributed to a baseline, and an
     artifact nobody can attribute is worse than no artifact.
  3. A ``Table Row`` or ``Table Cell`` that is not inside a ``Table``, or a
     ``Table`` with no rows. Each means the outline levels are not what this
     parser believes, so the grids it would emit are untrustworthy.

NO DOMAIN, DELIBERATELY. ``doors-export`` is a *format* kind: per the architect's
2026-10-02 ruling, origin is resolved from evidence in the document, not from the
kind, so this kind declares no semantic domain. That is a positive assertion,
not an omission. Note the standing seam collision while it is open: the
platform's review step refuses ``domain is None`` with ``422 no_declared_domain``
(``invincible-agent`` ``914c7fa``), so a real drop of this kind stops at review
until that is ruled on. Do NOT "fix" it by inventing a domain here.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence


class DoorsParseError(ValueError):
    """The export is not the shape this parser understands. Always loud."""


#: Any ONE of these appearing as a column name identifies the header row. Kept
#: deliberately small: these are the DOORS built-ins a spreadsheet export always
#: carries, so a site's custom attribute columns cannot be mistaken for it.
HEADER_MARKERS = (
    "Object Identifier",
    "Object Heading",
    "Object Text",
    "Absolute Number",
)

#: Object types that make up a table subtree.
TABLE_ROOT = "Table"
TABLE_ROW = "Table Row"
TABLE_CELL = "Table Cell"

#: Module-attribute preamble keys -> the identity field they feed. A site that
#: spells one differently shows up as a refusal naming the keys it DID see.
IDENTITY_KEYS = {
    "project": ("Project",),
    "baseline": ("Baseline",),
    "module_path": ("Module", "Module Path"),
    "module_name": ("Module Name",),
    "prefix": ("Prefix",),
    "document_number": ("Document Number", "Document No", "Doc Number"),
    "revision": ("Revision", "Rev"),
    "cage_code": ("CAGE Code", "CAGE"),
    "contract_number": ("Contract Number", "Contract", "Contract No"),
}


@dataclass(frozen=True)
class DoorsIdentity:
    """What the drop is keyed on, read verbatim from the module preamble.

    ``project`` and ``baseline`` are required -- see refusal 2. Everything else
    is reported when present and ``None`` when absent, never guessed, because
    these fields feed the origin resolver and a guessed CAGE is a false
    provenance claim.
    """

    project: str
    baseline: str
    module_path: str | None = None
    module_name: str | None = None
    prefix: str | None = None
    document_number: str | None = None
    revision: str | None = None
    cage_code: str | None = None
    contract_number: str | None = None

    @property
    def key(self) -> str:
        """Stable identity string.

        The module path wins when the export gives one: a DOORS module path is
        absolute and already globally unique within the database, so it needs no
        project prefix -- prefixing it produces ``project//project/...``, which
        is the same module under two spellings. Only the fallback handles
        (document number, module name), which are unique to a project at best,
        are qualified by project.
        """
        if self.module_path:
            return f"doors:{self.module_path.rstrip('/')}@{self.baseline}"
        handle = self.document_number or self.module_name
        return f"doors:{self.project}/{handle}@{self.baseline}"


@dataclass(frozen=True)
class DoorsObject:
    """One row of the export, verbatim."""

    identifier: str
    level: int
    object_type: str
    heading: str | None
    text: str | None
    attributes: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_heading(self) -> bool:
        return bool(self.heading) and not self.text


@dataclass(frozen=True)
class DoorsTable:
    """A reconstructed table subtree.

    ``tier`` is 1 for a clean rectangle and 2 for a ragged one. A tier-2 table
    keeps its rows exactly as found -- ragged -- so a later forwarding pass has
    the real shape to work with rather than a padded fiction.
    """

    anchor_id: str
    rows: tuple[tuple[str, ...], ...]
    tier: int
    ragged_reason: str | None = None

    @property
    def header(self) -> tuple[str, ...]:
        return self.rows[0] if self.rows else ()

    @property
    def body(self) -> tuple[tuple[str, ...], ...]:
        return self.rows[1:] if len(self.rows) > 1 else ()

    def to_csv(self) -> str:
        """CSV text. ``csv`` does the quoting, so a cell containing a comma,
        a quote or a newline round-trips instead of corrupting the grid."""
        buf = io.StringIO(newline="")
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerows(self.rows)
        return buf.getvalue()

    def to_json(self) -> str:
        """JSON with the header split out, so a consumer does not have to
        decide for itself whether row 0 is data."""
        return json.dumps(
            {
                "anchor_id": self.anchor_id,
                "tier": self.tier,
                "header": list(self.header),
                "rows": [list(r) for r in self.body],
            },
            indent=2,
        )


@dataclass(frozen=True)
class DoorsExport:
    identity: DoorsIdentity
    module_attributes: Mapping[str, str]
    objects: tuple[DoorsObject, ...]
    tables: tuple[DoorsTable, ...]

    @property
    def tier1_tables(self) -> tuple[DoorsTable, ...]:
        return tuple(t for t in self.tables if t.tier == 1)

    @property
    def tier2_tables(self) -> tuple[DoorsTable, ...]:
        return tuple(t for t in self.tables if t.tier != 1)

    def artifacts(self) -> dict[str, str]:
        """TIER-1 TABLES ONLY, as ``{path: text}`` held in memory.

        Returned as a dict rather than written to disk, per the repo's
        convention for passing parse output between assets (an isolated K8s pod
        has no shared filesystem). Tier-2 tables are deliberately absent: see
        the module docstring.
        """
        out: dict[str, str] = {}
        for t in self.tier1_tables:
            out[f"tables/{t.anchor_id}.csv"] = t.to_csv()
            out[f"tables/{t.anchor_id}.json"] = t.to_json()
        return out


def _split_preamble(text: str) -> tuple[list[str], str]:
    """``(preamble lines, csv text)``, splitting at the header row.

    Refusal 1 lives here. The header row is found by marker, never by position,
    because a preamble is optional and its length varies by exporting script.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        # Parse the single line rather than string-matching, so a marker
        # appearing inside a quoted preamble value cannot be mistaken for it.
        try:
            cells = next(csv.reader([line]))
        except csv.Error:  # pragma: no cover - defensive
            continue
        if any(c.strip() in HEADER_MARKERS for c in cells):
            return [l.rstrip("\r\n") for l in lines[:i]], "".join(lines[i:])
    raise DoorsParseError(
        "no DOORS header row found: no line declares any of "
        f"{list(HEADER_MARKERS)} as a column. Refusing to treat line 1 as the "
        "header -- in an export with a module preamble that would turn a "
        "preamble line into column names and every object into garbage. If this "
        "site names its columns differently, add the real names to "
        "HEADER_MARKERS rather than loosening the check."
    )


def _parse_module_attributes(lines: Iterable[str]) -> dict[str, str]:
    """``Key: Value`` preamble lines -> dict. Lines without a colon are kept
    out rather than coerced; a free-text banner line is not an attribute."""
    attrs: dict[str, str] = {}
    for line in lines:
        line = line.strip().rstrip(",")
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().strip('"'), value.strip().strip('"')
        if key and value:
            attrs[key] = value
    return attrs


def _identity(attrs: Mapping[str, str]) -> DoorsIdentity:
    """Refusal 2. Reads only the keys it knows; never infers from a filename."""
    picked: dict[str, str | None] = {}
    for field_name, candidates in IDENTITY_KEYS.items():
        picked[field_name] = next(
            (attrs[c] for c in candidates if attrs.get(c)), None)

    missing = [f for f in ("project", "baseline") if not picked.get(f)]
    if missing:
        raise DoorsParseError(
            f"the export declares no {' and no '.join(missing)}, so the drop "
            f"cannot be keyed to a baseline. Module attributes actually "
            f"present: {sorted(attrs)}. Identity comes from the module "
            f"preamble only -- deriving it from the filename would attribute "
            f"artifacts to a baseline the file never claimed."
        )
    return DoorsIdentity(**picked)  # type: ignore[arg-type]


def _parse_objects(csv_text: str) -> tuple[list[DoorsObject], list[str]]:
    """Rows -> objects, verbatim. Returns the fieldnames too, so attribute
    columns can be reported without re-reading the file."""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = list(reader.fieldnames or [])
    known = {"Object Identifier", "Object Level", "Object Heading",
             "Object Text", "Object Type"}

    objects: list[DoorsObject] = []
    for n, row in enumerate(reader, start=1):
        raw_level = (row.get("Object Level") or "").strip()
        try:
            level = int(raw_level)
        except ValueError:
            raise DoorsParseError(
                f"row {n} has Object Level {raw_level!r}, which is not an "
                f"integer. Outline level is how a table's rows and cells are "
                f"found, so a bad level means the grids would be wrong rather "
                f"than missing."
            ) from None
        objects.append(DoorsObject(
            identifier=(row.get("Object Identifier") or "").strip(),
            level=level,
            object_type=(row.get("Object Type") or "").strip(),
            heading=(row.get("Object Heading") or "").strip() or None,
            text=row.get("Object Text") or None,
            attributes={k: v for k, v in row.items()
                        if k and k not in known and (v or "").strip()},
        ))
    return objects, fieldnames


def _reconstruct_tables(objects: Sequence[DoorsObject]) -> list[DoorsTable]:
    """Walk the outline to rebuild each ``Table`` subtree. Refusal 3.

    A row's cells are the ``Table Cell`` objects that follow it at a deeper
    level, in export order -- which is DOORS' own left-to-right, top-to-bottom
    order, so no sorting is applied or needed.
    """
    tables: list[DoorsTable] = []
    i = 0
    while i < len(objects):
        obj = objects[i]
        if obj.object_type in (TABLE_ROW, TABLE_CELL):
            raise DoorsParseError(
                f"{obj.identifier} is a {obj.object_type!r} that is not inside "
                f"a {TABLE_ROOT!r} object. The outline is not the nesting this "
                f"parser assumes, so any grid built from it would be wrong."
            )
        if obj.object_type != TABLE_ROOT:
            i += 1
            continue

        root, rows, i = obj, [], i + 1
        while i < len(objects) and objects[i].level > root.level:
            node = objects[i]
            if node.object_type == TABLE_ROW:
                cells: list[str] = []
                i += 1
                while (i < len(objects) and objects[i].level > node.level
                       and objects[i].object_type == TABLE_CELL):
                    cells.append((objects[i].text or "").strip())
                    i += 1
                rows.append(tuple(cells))
            else:
                # A nested table or a stray object inside the subtree. Stop
                # rather than flatten it into the parent's grid.
                break

        if not rows:
            raise DoorsParseError(
                f"table {root.identifier} has no {TABLE_ROW!r} children. An "
                f"empty table means the level nesting differs from what this "
                f"parser expects, not that the author wrote an empty table."
            )

        widths = {len(r) for r in rows}
        if len(widths) == 1:
            tables.append(DoorsTable(root.identifier, tuple(rows), tier=1))
        else:
            tables.append(DoorsTable(
                root.identifier, tuple(rows), tier=2,
                ragged_reason=(
                    f"rows have differing cell counts {sorted(widths)}; a "
                    f"padded grid would put values under the wrong header, so "
                    f"this table is tier-2 and is NOT emitted as an artifact"),
            ))
    return tables


def parse_doors_export(text: str) -> DoorsExport:
    """Parse a DOORS spreadsheet export. Deterministic; no LLM, no network.

    Raises ``DoorsParseError`` for every shape it does not understand -- see the
    module docstring's refusal list.
    """
    preamble, csv_text = _split_preamble(text)
    module_attributes = _parse_module_attributes(preamble)
    identity = _identity(module_attributes)
    objects, _fieldnames = _parse_objects(csv_text)
    tables = _reconstruct_tables(objects)
    return DoorsExport(
        identity=identity,
        module_attributes=module_attributes,
        objects=tuple(objects),
        tables=tuple(tables),
    )
