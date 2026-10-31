"""Validate a batch export profile against the contract schema and the catalogue.

Reports ALL findings and fails closed: a profile with any ``error`` finding is not
usable; ``warning`` findings do not block. Nothing here exports anything.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml
from jsonschema import Draft202012Validator

_ROOT = Path(__file__).resolve().parents[2]
CATALOGUE_PATH = _ROOT / "registry" / "export_field_catalogue.json"
SCHEMA_PATH = _ROOT / "docs" / "contracts" / "batch-column-map.schema.json"
_ROW_PREFIX = "parts[i]."
# A dotted lower-case identifier, which is what every catalogue `name` is.
_NAME = re.compile(r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_*]*)*\Z")


def _leading_name(entry: str) -> str:
    """The field name a prose catalogue entry starts with, or ``""`` if it does
    not start with one. See ``Catalogue.load`` for why this is not ``split()[0]``."""
    head = entry.split()[0].rstrip(".,") if entry.split() else ""
    return head if _NAME.match(head) else ""


@dataclass(frozen=True)
class Finding:
    severity: str  # "error" | "warning"
    code: str
    where: str
    detail: str


@dataclass(frozen=True)
class Catalogue:
    """registry/export_field_catalogue.json, read not transcribed."""

    by_name: Mapping[str, Mapping]
    shared_wire_names: frozenset
    unverified: frozenset
    not_extracted: tuple
    row_field_values: frozenset = frozenset()

    @classmethod
    def load(cls, path=None) -> "Catalogue":
        data = json.loads(Path(path or CATALOGUE_PATH).read_text(encoding="utf-8"))
        fields = data["fields"]
        by_name = {f["name"]: f for f in fields}
        counts: dict = {}
        for f in fields:
            wire = f.get("wire")
            if isinstance(wire, dict) and wire.get("name"):
                counts[wire["name"]] = counts.get(wire["name"], 0) + 1
        shared = frozenset(n for n, c in counts.items() if c > 1)
        # Both lists hold prose, and only SOME entries begin with a field name:
        # `not_extracted` carries one entry that is a sentence ("A batch column-map
        # vocabulary. SUPERSEDED..."), whose leading token is the word "A". Taking
        # the leading token unconditionally would put "A" in the refused set --
        # harmless today, because no field is called that, and wrong the moment one
        # entry starts with a real word. So a leading token counts as a name only if
        # it LOOKS like one and, for the refusal list, only if the catalogue agrees
        # it is not a field: a name in `by_name` is served or not by `served_by`,
        # and `field-not-served` is that finding, not this one.
        unverified = frozenset(filter(None, (_leading_name(e)
                                             for e in data.get("unverified_mappings", []))))
        not_extracted = tuple(n for n in (_leading_name(e) for e in data.get("not_extracted", []))
                              if n and n not in by_name)
        vocab = (by_name.get("row.field") or {}).get("vocabulary") or {}
        return cls(
            by_name=by_name,
            shared_wire_names=shared,
            unverified=unverified,
            not_extracted=not_extracted,
            row_field_values=frozenset(vocab.get("values") or ()),
        )


def load_profile(path):
    """Read a YAML profile with yaml.safe_load: no exec, no custom tags."""
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _where(path) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "profile"


def _norm_row_field(value: str) -> str:
    return value if value.startswith(_ROW_PREFIX) else _ROW_PREFIX + value


def validate_profile(profile, catalogue=None, schema_path=None) -> tuple:
    cat = catalogue or Catalogue.load()
    schema = json.loads(Path(schema_path or SCHEMA_PATH).read_text(encoding="utf-8"))
    findings: list = []

    for err in sorted(Draft202012Validator(schema).iter_errors(profile),
                      key=lambda e: [str(p) for p in e.absolute_path]):
        findings.append(Finding("error", "schema", _where(err.absolute_path), err.message))

    if not isinstance(profile, dict):
        return tuple(findings)
    columns = profile.get("columns")
    if not isinstance(columns, list):
        return tuple(findings)
    notice_level = profile.get("granularity") == "notice"
    outputs = [c.get("output") for c in columns if isinstance(c, dict) and isinstance(c.get("output"), str)]
    seen: dict = {}

    for i, col in enumerate(columns):
        if not isinstance(col, dict):
            continue
        at = f"columns[{i}]"
        out = col.get("output")
        if isinstance(out, str):
            if out in seen:
                findings.append(Finding("error", "duplicate-output", f"{at}.output",
                                        f"Output {out!r} is already used by columns[{seen[out]}]."))
            else:
                seen[out] = i
        landing = col.get("landing")
        if isinstance(landing, str) and landing not in outputs:
            findings.append(Finding("error", "landing-not-declared", f"{at}.landing",
                                    f"Landing {landing!r} is not one of the profile's own output columns; declare it."))
        src = col.get("source")
        if not isinstance(src, dict) or not isinstance(src.get("field"), str):
            continue
        name = src["field"]
        sw = f"{at}.source.field"
        fld = cat.by_name.get(name)
        if name in cat.not_extracted:
            findings.append(Finding("error", "field-not-extracted", sw,
                                    f"{name!r} is declared but the extractor does not produce it."))
        if fld is None:
            if name not in cat.not_extracted:
                findings.append(Finding("error", "field-unknown", sw,
                                        f"{name!r} is not a catalogue field name."))
            continue
        if fld.get("served_by") is None:
            findings.append(Finding("error", "field-not-served", sw,
                                    f"{name!r} is declared, not produced: no route serves it."))
        if name in cat.unverified:
            findings.append(Finding("warning", "mapping-unverified", sw,
                                    f"The catalogue marks the mapping of {name!r} unverified."))
        if notice_level and fld.get("field_scope") == "row":
            findings.append(Finding("error", "granularity-row-field", sw,
                                    f"{name!r} is a per-row value; a granularity: notice profile cannot name it."))
        wire = fld.get("wire")
        wire_name = wire.get("name") if isinstance(wire, dict) else None
        shared = wire_name in cat.shared_wire_names
        rf = src.get("row_field")
        if shared and rf is None:
            findings.append(Finding("error", "row-field-required", f"{at}.source",
                                    f"Wire name {wire_name!r} of {name!r} is shared by several fields; add row_field."))
        elif not shared and rf is not None:
            findings.append(Finding("error", "row-field-refused", f"{at}.source.row_field",
                                    f"Wire name {wire_name!r} of {name!r} is not shared; a row_field would match nothing."))
        elif isinstance(rf, str) and cat.row_field_values and _norm_row_field(rf) not in cat.row_field_values:
            findings.append(Finding("warning", "row-field-unrecognised", f"{at}.source.row_field",
                                    f"{rf!r} is not among the row.field values the producer emits today."))
    return tuple(findings)
