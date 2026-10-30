"""Seal for registry/export_field_catalogue.json.

Written for the 2026-10-28 packet item 2.

The catalogue sits in the middle of a three-hop span:

    producer (BAML classes + sustainment_merge review items)
        -> registry/export_field_catalogue.json
        -> pinned extract of the platform contract
           (tests/fixtures/cortex_bff_extraction_pin.json)

This file seals the first two hops (producer -> catalogue, catalogue ->
pinned extract) plus the catalogue's own internal consistency. It does NOT
seal the third: that the platform still serves the pinned shape. The pin is a
frozen copy, so a platform-side change does not red anything here until the
pin is re-taken. That freshness leg is #181 and it is not built. Two green
legs are not a covered span.
"""
import json
import re
from pathlib import Path

from doc_tools.utils import sustainment_merge as merge

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_PATH = ROOT / "registry" / "export_field_catalogue.json"
PIN_PATH = ROOT / "tests" / "fixtures" / "cortex_bff_extraction_pin.json"
TYPE_BUILDER_PATH = ROOT / "doc_tools" / "baml_client" / "type_builder.py"

CATALOGUE_FILE = "registry/export_field_catalogue.json"
PIN_FILE = "tests/fixtures/cortex_bff_extraction_pin.json"

ENTRY_KEYS = {
    "name", "scope", "type", "nullable", "producer", "review_json", "wire",
    "served_by", "vocabulary", "evidence", "notes",
}
EXTRACTION_ROUTE = "GET /ingest/{ingest_id}/extraction"
EXTRACTION_CONTAINERS = {"Extraction", "ExtractionRow", "Notice", "EvidenceRef"}
EDIT_CONTAINERS = {"HeaderEdit", "RowEdits", "RowEditCounts"}

# Schema properties that are deliberately NOT claimed by a catalogue entry.
# Exactly these two, each for a stated reason; the test below asserts the set
# is exactly this and that both still exist, so it cannot quietly cover
# something new.
#  - Extraction.rows: the row array itself; its members are catalogued under
#    the `row` scope (container ExtractionRow).
#  - Extraction.notice: the Notice sub-object; its members are catalogued
#    under their own container (Notice).
UNCLAIMED_BY_DESIGN = {("Extraction", "rows"), ("Extraction", "notice")}

REVIEW_ITEM_KEYS = {
    "field_path", "value", "source_snippet", "region", "page_number", "bboxes",
    "match_method", "match_confidence", "needs_review", "review_reason",
    "approval_state",
}
WIRE_EVIDENCE_KEYS = {"page", "bbox", "note"}
EXPECTED_FIELD_PATHS = {
    "header.pub_date", "header.mfr", "header.mfr_parent",
    "header.doc_level_ltb_date", "header.summary", "header.categories",
    "parts[0].affected_mpn", "parts[0].replacement_mpn", "parts[0].ltb_date",
}


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


CATALOGUE = _load(CATALOGUE_PATH)
PIN = _load(PIN_PATH)
FIELDS = CATALOGUE["fields"]
SCHEMAS = PIN["schemas"]


def _wired():
    return [f for f in FIELDS if f["wire"] is not None]


def _claims():
    out = {}
    for f in _wired():
        out.setdefault((f["wire"]["container"], f["wire"]["name"]), []).append(f)
    return out


def _enum_of(prop):
    """The enum of a property, directly or inside an anyOf branch; else None."""
    if "enum" in prop:
        return set(prop["enum"])
    for branch in prop.get("anyOf", []):
        if "enum" in branch:
            return set(branch["enum"])
    return None


# ---------------------------------------------------------------- Leg 1

def test_catalogue_names_are_unique():
    names = [f["name"] for f in FIELDS]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, (
        f"Duplicate field names {dupes}. Update {CATALOGUE_FILE}: every entry "
        "needs a unique name."
    )


def test_every_entry_has_exactly_the_eleven_keys():
    for f in FIELDS:
        keys = set(f)
        assert keys == ENTRY_KEYS, (
            f"Entry {f.get('name')!r} has keys off the schema: missing "
            f"{sorted(ENTRY_KEYS - keys)}, extra {sorted(keys - ENTRY_KEYS)}. "
            f"Update {CATALOGUE_FILE}."
        )


def test_every_scope_is_declared():
    scopes = set(CATALOGUE["scopes"])
    for f in FIELDS:
        assert f["scope"] in scopes, (
            f"Entry {f['name']!r} uses scope {f['scope']!r}, which is not a key "
            f"of the top-level scopes {sorted(scopes)}. Update {CATALOGUE_FILE}."
        )


def test_wire_and_served_by_agree():
    for f in FIELDS:
        wire, served = f["wire"], f["served_by"]
        if wire is None:
            assert served is None, (
                f"Entry {f['name']!r} has no wire but served_by={served!r}. "
                f"Update {CATALOGUE_FILE}."
            )
        elif wire["container"] in EXTRACTION_CONTAINERS:
            assert served == EXTRACTION_ROUTE, (
                f"Entry {f['name']!r} is on container {wire['container']} but "
                f"served_by={served!r}, expected {EXTRACTION_ROUTE!r}. "
                f"Update {CATALOGUE_FILE}."
            )
        else:
            # HeaderEdit / RowEdits / RowEditCounts: a different route, so
            # wire is set and served_by is null. Allow exactly that.
            assert wire["container"] in EDIT_CONTAINERS and served is None, (
                f"Entry {f['name']!r} is on container {wire['container']} with "
                f"served_by={served!r}; edit containers {sorted(EDIT_CONTAINERS)} "
                f"must have served_by null. Update {CATALOGUE_FILE}."
            )


# ---------------------------------------------------------------- Leg 2

def test_catalogue_wire_entries_exist_in_pinned_schema():
    for f in _wired():
        container, name = f["wire"]["container"], f["wire"]["name"]
        assert container in SCHEMAS, (
            f"Entry {f['name']!r} names container {container!r}, which is not "
            f"in the pinned schemas {sorted(SCHEMAS)}. Update {CATALOGUE_FILE} "
            f"or re-take {PIN_FILE}."
        )
        assert name in SCHEMAS[container]["properties"], (
            f"Entry {f['name']!r} claims {container}.{name}, which the pinned "
            f"schema does not have. Update {CATALOGUE_FILE} or re-take {PIN_FILE}."
        )


# ---------------------------------------------------------------- Leg 3

def test_every_pinned_property_is_claimed_by_the_catalogue():
    """Reds when the platform adds a field (once the pin is re-taken)."""
    claims = _claims()
    for container, schema in SCHEMAS.items():
        for prop in schema["properties"]:
            if (container, prop) in UNCLAIMED_BY_DESIGN:
                continue
            assert (container, prop) in claims, (
                f"Pinned {container}.{prop} is claimed by no catalogue entry. "
                f"Add an entry to {CATALOGUE_FILE} with wire "
                f"{{container: {container!r}, name: {prop!r}}}."
            )


def test_the_unclaimed_exemption_is_exactly_the_two_structural_properties():
    assert UNCLAIMED_BY_DESIGN == {("Extraction", "rows"), ("Extraction", "notice")}, (
        "The exemption set changed. It may cover only the row array and the "
        "Notice sub-object; catalogue anything else in "
        f"{CATALOGUE_FILE} instead."
    )
    for container, prop in UNCLAIMED_BY_DESIGN:
        assert prop in SCHEMAS[container]["properties"], (
            f"Exempted {container}.{prop} is no longer a pinned property. "
            f"Remove it from UNCLAIMED_BY_DESIGN (or re-check {PIN_FILE})."
        )


# ---------------------------------------------------------------- Leg 4

def test_closed_vocabularies_match_schema_enums():
    claims = _claims()
    seen = set()
    for container, schema in SCHEMAS.items():
        for prop, spec in schema["properties"].items():
            enum = _enum_of(spec)
            if enum is None:
                continue
            seen.add((container, prop))
            entries = claims.get((container, prop), [])
            assert entries, (
                f"Pinned {container}.{prop} has an enum but no catalogue entry "
                f"claims it. Update {CATALOGUE_FILE}."
            )
            for f in entries:
                vocab = f["vocabulary"]
                assert vocab is not None and vocab.get("closed") is True, (
                    f"Entry {f['name']!r} claims enum-bearing {container}.{prop} "
                    f"but its vocabulary is not closed ({vocab!r}). "
                    f"Update {CATALOGUE_FILE}."
                )
                assert set(vocab.get("values") or []) == enum, (
                    f"Entry {f['name']!r} vocabulary {sorted(vocab.get('values') or [])} "
                    f"differs from pinned enum {sorted(enum)} on {container}.{prop}. "
                    f"Update {CATALOGUE_FILE}."
                )
    must_bite = {
        ("Extraction", "leaf"), ("Extraction", "leaf_source"),
        ("Notice", "mfr_source"), ("HeaderEdit", "field"),
    }
    assert must_bite <= seen, (
        f"The enum walk no longer reaches {sorted(must_bite - seen)}; the pin "
        f"{PIN_FILE} or this walker changed shape."
    )


# ---------------------------------------------------------------- Leg 5

def test_evidence_ref_is_the_ruled_wire_shape():
    """Pins EvidenceRef to the ruled shape {page, bbox, note?}.

    This leg is what caught the 2026-10-27 PCN-2683 P0 from the other side:
    the producer side was checked against what it wrote, and this checks the
    contract that refuses anything else.
    """
    ev = SCHEMAS["EvidenceRef"]
    assert ev.get("additionalProperties") is False, (
        f"EvidenceRef must refuse extra keys (additionalProperties false); "
        f"pinned value is {ev.get('additionalProperties')!r}. Re-check {PIN_FILE}."
    )
    assert ev.get("required") == ["page"], (
        f"EvidenceRef.required must be ['page'], pinned {ev.get('required')!r}. "
        f"Re-check {PIN_FILE}."
    )
    assert set(ev["properties"]) == WIRE_EVIDENCE_KEYS, (
        f"EvidenceRef properties are {sorted(ev['properties'])}, expected "
        f"{sorted(WIRE_EVIDENCE_KEYS)}. Update {CATALOGUE_FILE} and the producer."
    )
    assert ev["properties"]["page"].get("minimum") == 1, (
        f"EvidenceRef.page minimum must be 1, pinned "
        f"{ev['properties']['page'].get('minimum')!r}."
    )
    note = ev["properties"]["note"]
    assert note.get("type") == "string", (
        f"EvidenceRef.note must be type string, pinned {note!r}."
    )
    assert "anyOf" not in note and "null" not in json.dumps(note), (
        "EvidenceRef.note must NOT be nullable: the producer writes the key "
        f"only when truthy, so a nullable note is a real divergence ({note!r})."
    )


# ---------------------------------------------------------------- Leg 6

def _build_items():
    header = {
        "pub_date": "2026-01-02", "pub_date_source": "Published 2 January 2026",
        "mfr": "Acme Semiconductor", "mfr_source": "Acme Semiconductor",
        "mfr_parent": "Acme Holdings", "mfr_parent_source": "Acme Holdings",
        "doc_level_ltb_date": "2026-06-30",
        "doc_level_ltb_date_source": "last time buy 30 June 2026",
        "summary": "One part is discontinued.",
        "categories": ["discontinuance"],
    }
    parts = [{
        "affected_mpn": "ABC123", "affected_mpn_source": "ABC123",
        "replacement_mpn": "ABC124", "replacement_mpn_source": "ABC124",
        "ltb_date": "2026-06-30", "ltb_date_source": "30 June 2026",
        "text_layer_bbox": [100, 200, 300, 240],
        "text_layer_page": 1,
        "text_layer_page_dims": {"width": 1000, "height": 1000},
    }]
    items, _reasons = merge.build_review_items(header, parts, [], "")
    return items


def test_review_items_emit_the_catalogued_field_paths_and_keys():
    items = _build_items()
    paths = {i["field_path"] for i in items}
    assert paths == EXPECTED_FIELD_PATHS, (
        f"build_review_items emitted {sorted(paths)}; expected "
        f"{sorted(EXPECTED_FIELD_PATHS)}. The producer moved: update "
        f"{CATALOGUE_FILE}."
    )
    allowed = REVIEW_ITEM_KEYS | {"wire_evidence_ref"}
    for item in items:
        keys = set(item)
        assert REVIEW_ITEM_KEYS <= keys <= allowed, (
            f"Review item {item['field_path']} has keys {sorted(keys)}; allowed "
            f"exactly {sorted(REVIEW_ITEM_KEYS)} plus optional wire_evidence_ref. "
            f"The producer moved: update {CATALOGUE_FILE}."
        )


def test_wire_evidence_ref_can_never_break_the_pinned_evidence_ref():
    items = _build_items()
    refs = [i["wire_evidence_ref"] for i in items if "wire_evidence_ref" in i]
    assert refs, "No synthetic item produced a wire_evidence_ref; the test input no longer reaches it."
    for ref in refs:
        extra = set(ref) - WIRE_EVIDENCE_KEYS
        assert not extra, (
            f"wire_evidence_ref carries {sorted(extra)}, which the pinned "
            f"EvidenceRef refuses (additionalProperties false). Fix the producer "
            f"or re-check {PIN_FILE}."
        )
        assert "page_dims" not in ref, (
            "wire_evidence_ref contains page_dims; it must be OMITTED, never nulled."
        )
        if "note" in ref:
            assert ref["note"], f"wire_evidence_ref note is {ref['note']!r}; omit the key instead."

        # ARCHITECT RULING 2026-10-28, relayed in cortex-ui's packet of the same
        # day: *"A ref without `bbox` is not legal; the shape is {page, bbox,
        # note?}."* It stays NULLABLE -- null means "on this page, no box"
        # (ruling 205) -- but the KEY is always present. This reverses the
        # earlier 205 note that omitting it was the same as null.
        #
        # The pinned schema still says `required: ["page"]`, because lane 01 had
        # not regenerated the doc when the pin was taken. So this leg is
        # DELIBERATELY STRICTER THAN THE PIN: it holds us to the ruling now,
        # rather than discovering a gap when they re-pin onto
        # `required: [page, bbox]` and cortex turns an absent key malformed.
        assert {"page", "bbox"} <= set(ref), (
            f"wire_evidence_ref is {sorted(ref)}; the ruled shape requires the "
            f"page AND bbox keys to be present (bbox may be null). Ruling 2026-10-28."
        )


def test_catalogued_review_item_fields_are_emitted():
    emitted = set()
    for item in _build_items():
        emitted |= set(item)
    for f in FIELDS:
        prod = f["producer"]
        if prod["origin"] == "review_item" and prod["field"] in REVIEW_ITEM_KEYS | {"wire_evidence_ref"}:
            assert prod["field"] in emitted, (
                f"Entry {f['name']!r} says review items carry {prod['field']!r}, "
                f"but none emitted it. The producer moved: update {CATALOGUE_FILE}."
            )


# ---------------------------------------------------------------- Leg 7

def _baml_sets():
    text = TYPE_BUILDER_PATH.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if "_properties: typing.Set[str] = set([" in ln]

    def pick(marker):
        hits = [ln for ln in lines if f'"{marker}"' in ln]
        assert len(hits) == 1, (
            f"Expected exactly one _properties line containing {marker!r} in "
            f"doc_tools/baml_client/type_builder.py, found {len(hits)}. A BAML "
            f"regen moved the producer; update {CATALOGUE_FILE}."
        )
        return set(re.findall(r'"([^"]+)"', hits[0]))

    return pick("doc_level_ltb_date_source"), pick("affected_mpn_source")


def test_baml_producer_fields_match_the_catalogue():
    header_set, part_set = _baml_sets()
    hint = f"A BAML regen moved the producer; update {CATALOGUE_FILE}."
    header_claimed, part_claimed = set(), set()
    for f in FIELDS:
        prod = f["producer"]
        if prod["origin"] == "baml:SustainmentHeader":
            assert prod["field"] in header_set, (
                f"Entry {f['name']!r} names SustainmentHeader field "
                f"{prod['field']!r}, not in the BAML class {sorted(header_set)}. {hint}"
            )
            header_claimed.add(prod["field"])
        elif prod["origin"] == "baml:ImpactedPart":
            assert prod["field"] in part_set, (
                f"Entry {f['name']!r} names ImpactedPart field "
                f"{prod['field']!r}, not in the BAML class {sorted(part_set)}. {hint}"
            )
            part_claimed.add(prod["field"])
    assert header_set <= header_claimed, (
        f"BAML SustainmentHeader fields {sorted(header_set - header_claimed)} "
        f"are claimed by no catalogue entry. {hint}"
    )
    # customer_mpn joined these on 2026-10-29 (the customer-alias ruling). It is a
    # VALUE field like the other three and must be claimed by a catalogue entry; it
    # deliberately has no *_source, so the count asserted below stays at three.
    values = {"affected_mpn", "replacement_mpn", "customer_mpn", "ltb_date"}
    assert values <= part_claimed, (
        f"ImpactedPart value fields {sorted(values - part_claimed)} are claimed "
        f"by no catalogue entry. {hint}"
    )
    # The three *_source names are accounted for by the single row.source_snippet
    # entry: one wire field carries all three, by row.
    sources = {n for n in part_set if n.endswith("_source")}
    assert len(sources) == 3, f"Expected three *_source names on ImpactedPart, got {sorted(sources)}. {hint}"
    assert any(f["name"] == "row.source_snippet" for f in FIELDS), (
        f"The row.source_snippet entry that carries the three *_source names is "
        f"missing. {hint}"
    )
    # TOTAL, as the header leg above already is. Asserting only that the three
    # VALUE fields are claimed left the part side one-way: a seventh
    # ImpactedPart property arriving from a BAML regen would be claimed by no
    # entry, and nothing here would say so -- the catalogue would quietly stop
    # naming every promoted field while every assertion stayed green. The three
    # `*_source` names are exempt because `row.source_snippet` claims them
    # collectively, by row, and that entry is required just above.
    assert part_set <= part_claimed | sources, (
        f"ImpactedPart fields {sorted(part_set - part_claimed - sources)} are "
        f"claimed by no catalogue entry. Every promoted field must be named: "
        f"add an entry, or extend the `row.source_snippet` exemption if it is "
        f"another verbatim-source sibling. {hint}"
    )


# ---------------------------------------------------------------- Leg 8

def test_the_pin_is_declared_and_the_unsealed_hop_is_named():
    pin = PIN["_pin"]
    assert re.fullmatch(r"[0-9a-f]{40}", pin["ref"]), (
        f"_pin.ref {pin['ref']!r} is not a 40-hex sha. Fix {PIN_FILE}."
    )
    assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256_of_whole_file"]), (
        f"_pin.sha256_of_whole_file is not 64-hex. Fix {PIN_FILE}."
    )
    seal = CATALOGUE["seal"]
    assert PIN_FILE in seal["contract_leg"], (
        f"seal.contract_leg must mention {PIN_FILE}. Update {CATALOGUE_FILE}."
    )
    assert isinstance(seal["NOT_sealed"], str) and seal["NOT_sealed"].strip(), (
        f"seal.NOT_sealed must name the open hop (pin freshness, #181). "
        f"Update {CATALOGUE_FILE}."
    )
