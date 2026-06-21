"""Contract tests for ADR-0021 deterministic content-kind selection.

These tests are the design's enforcement layer. The architect's ratification
gave four sharpenings that must each be testable:

  1. HALT-not-silent-default: ``test_unclassifiable_kind_HALTS_does_not_default``
     fails if the resolver is ever softened to fall through to a default.
  2. Empty-string is treated as ABSENT (deliberate named decision, not an
     ``or``-truthiness accident): ``test_empty_string_content_kind_falls_through_to_path``.
  3. Positive control for the dispatch swap: the resolver's output for the
     existing manufacturing path MUST match the URI the legacy hardcode used:
     ``test_resolver_output_matches_legacy_hardcode_for_manufacturing``.
  4. Mapping table well-formedness check — docstring matches assertion
     (asserts URI well-formedness, NOT substrate routability):
     ``test_every_KIND_MAPPING_row_has_a_well_formed_target_uri``.
"""
from __future__ import annotations

import pytest

from doc_tools.utils.content_kind import (
    ContentKindEntry,
    KIND_MAPPING,
    UnclassifiableContentKindError,
    resolve_content_kind,
)


# ---------------------------------------------------------------------------
# Sharpening 1 — HALT is structural, not "log-and-continue"
# ---------------------------------------------------------------------------

def test_unclassifiable_kind_HALTS_does_not_default():
    """ADR-0021 §Precedence §3: HALT, never silent default.

    The legacy ``domain_type`` chain in ``semantic_assets.py`` ends in
    ``metadata.get("project", "Training")`` — silent default. This test
    proves the content_kind chain does NOT inherit that tail.

    Failure mode this guards against: a future change softens the ``raise``
    to ``return DEFAULT_ENTRY``. The test goes red because the call returns
    instead of raising. The masks-rule applied to the resolver's own
    correctness.
    """
    with pytest.raises(UnclassifiableContentKindError) as exc_info:
        resolve_content_kind(
            manifest_metadata={"domain_type": "manufacturing"},
            s3_key="manufacturing/zzz-not-a-registered-kind/M67/file.pdf",
        )
    msg = str(exc_info.value)
    # The failure message names the resolved value AND points at the table.
    assert "zzz-not-a-registered-kind" in msg, msg
    assert "KIND_MAPPING" in msg, msg
    assert "ADR-0021" in msg, msg


def test_unclassifiable_kind_HALTS_when_metadata_present_but_wrong():
    """Explicit-but-wrong content_kind HALTS at the table lookup.

    The metadata > path > HALT precedence means that if metadata is
    present and non-empty but doesn't match a table row, the chain MUST
    NOT fall through to path-derive — it MUST halt. Explicit-wrong is a
    loud failure mode; quiet fallback is exactly what the discipline
    rejects.
    """
    with pytest.raises(UnclassifiableContentKindError) as exc_info:
        resolve_content_kind(
            manifest_metadata={
                "domain_type": "manufacturing",
                "content_kind": "nonsense-value-that-does-not-exist",
            },
            # Path WOULD path-derive to "work-instructions" (a valid row)
            # — but metadata is non-empty so path-derive is bypassed and we
            # halt on the explicit-wrong value.
            s3_key="manufacturing/work-instructions/M67/file.pdf",
        )
    assert "nonsense-value-that-does-not-exist" in str(exc_info.value)


def test_unclassifiable_kind_HALTS_on_path_with_unregistered_segment():
    """Path-derive produces a value not in the table → HALT, not default."""
    with pytest.raises(UnclassifiableContentKindError):
        resolve_content_kind(
            manifest_metadata={"domain_type": "manufacturing"},
            s3_key="manufacturing/some-other-content-type/file.pdf",
        )


def test_unclassifiable_kind_HALTS_on_malformed_path():
    """Malformed path → ``_derive_from_path`` returns ``None`` → halt.

    ``None`` is not in the table, so the halt fires by the same condition
    as a path that derives to a non-mapped value. The malformed path
    routes THROUGH the halt rather than around it.
    """
    with pytest.raises(UnclassifiableContentKindError):
        resolve_content_kind(
            manifest_metadata={"domain_type": "manufacturing"},
            s3_key="just-a-filename.pdf",  # no slashes; _derive_from_path returns None
        )
    with pytest.raises(UnclassifiableContentKindError):
        resolve_content_kind(
            manifest_metadata={"domain_type": "manufacturing"},
            s3_key="",  # empty key
        )


# ---------------------------------------------------------------------------
# Sharpening 2 — empty-string treated as ABSENT (named decision)
# ---------------------------------------------------------------------------

def test_empty_string_content_kind_falls_through_to_path():
    """The empty-string precedence decision, named and tested.

    Architect's ratification (2026-06-20): ``content_kind=""`` reflects a
    "field exists but unset" shape from JSON/metadata tooling, NOT an
    explicit "no kind" assertion. The resolver treats empty-string as
    ABSENT (whitespace too), so path-derive runs as if the field were
    missing. The decision is deliberate and lives in the resolver
    docstring; this test makes it a contract.

    If a future maintainer softens this to "empty string is explicit-no-
    kind → halt immediately even with a valid path," this test goes red
    because the call would raise instead of returning the path-derived row.
    """
    entry = resolve_content_kind(
        manifest_metadata={"domain_type": "manufacturing", "content_kind": ""},
        s3_key="manufacturing/work-instructions/M67/grenade-assembly.pdf",
    )
    assert entry.kind == "work-instruction"
    assert entry.target_ontology_class == "http://edgy-solutions.com/ontology/mfg#WorkInstruction"


def test_whitespace_only_content_kind_also_falls_through_to_path():
    """Whitespace-only string follows the same rule as empty-string.

    The resolver strips whitespace; whitespace-only is ABSENT semantics.
    Same rationale as the empty-string case: tooling shapes that produce
    whitespace-only values reflect "no signal given," not an explicit halt.
    """
    entry = resolve_content_kind(
        manifest_metadata={"domain_type": "manufacturing", "content_kind": "   "},
        s3_key="manufacturing/work-instructions/M67/grenade-assembly.pdf",
    )
    assert entry.kind == "work-instruction"


# ---------------------------------------------------------------------------
# Sharpening 3 — positive control: resolver output matches legacy hardcode
# ---------------------------------------------------------------------------

def test_resolver_output_matches_legacy_hardcode_for_manufacturing():
    """Positive control for the dispatch swap.

    Before the manufacturing plugin called the resolver, its INSTANCE_OF
    target was the hardcoded literal
    ``"http://edgy-solutions.com/ontology/mfg#WorkInstruction"`` (formerly
    at ``manufacturing.py:333``). After the swap, that URI comes from
    ``KIND_MAPPING["work-instructions"].target_ontology_class``.

    The architect's discipline: the new machinery MUST reproduce the old
    behavior for the one path that exists today, BEFORE trusting it for
    paths that don't exist yet. This test asserts byte-identity between
    the legacy hardcode and the table-resolved value, so a future
    contributor cannot edit the table to a different URI without this
    safety control going red.
    """
    LEGACY_HARDCODED_URI = "http://edgy-solutions.com/ontology/mfg#WorkInstruction"
    LEGACY_HARDCODED_BAML = "ExtractWorkInstructions"

    entry = resolve_content_kind(
        manifest_metadata={"domain_type": "manufacturing"},
        s3_key="manufacturing/work-instructions/M67/grenade-assembly.pdf",
    )
    assert entry.target_ontology_class == LEGACY_HARDCODED_URI, (
        "Resolver output diverged from the legacy hardcoded URI. The "
        "dispatch swap's positive control is violated — the existing "
        "manufacturing path will produce different INSTANCE_OF edges "
        "than it did before ADR-0021."
    )
    assert entry.baml_function == LEGACY_HARDCODED_BAML
    assert entry.extractor_config == "manufacturing_default"


# ---------------------------------------------------------------------------
# Sharpening 4 — match docstring to assertion (no false promises)
# ---------------------------------------------------------------------------

def test_every_KIND_MAPPING_row_has_a_well_formed_target_uri():
    """Asserts the target_ontology_class is a syntactically well-formed URI.

    Scope NOTE (architect's sharpening 2026-06-20): this test does NOT
    check that the target class is actually reachable through the
    canonical pipeline — that would require a substrate integration check
    (Neo4j or TTL parsing). It catches "someone put garbage in the field"
    only. A typo'd-but-well-formed URI passes this test; routing would
    then break at runtime.

    A substrate-existence check (the target class actually exists at
    ``domain=<entry.domain_type>`` in Neo4j with canonical provenance) is
    a richer integration test for a future change — likely an addition
    to ``tests/routing/test_no_legacy_residue.py`` or a sibling. Don't
    let this unit test claim a guarantee it doesn't provide.
    """
    for source_value, entry in KIND_MAPPING.items():
        assert entry.kind_source_value == source_value, (
            f"row key {source_value!r} must match entry.kind_source_value "
            f"{entry.kind_source_value!r}"
        )
        assert entry.target_ontology_class.startswith("http://") or \
               entry.target_ontology_class.startswith("https://"), (
            f"target_ontology_class must be a well-formed HTTP(S) URI; "
            f"row {source_value!r} has {entry.target_ontology_class!r}"
        )
        assert entry.kind, f"row {source_value!r} has empty kind"
        assert entry.baml_function, f"row {source_value!r} has empty baml_function"
        assert entry.extractor_config, f"row {source_value!r} has empty extractor_config"


# ---------------------------------------------------------------------------
# Positive coverage of the precedence rules
# ---------------------------------------------------------------------------

def test_metadata_content_kind_overrides_path_derived():
    """Per ADR-0021 §Precedence: metadata > path. Metadata wins."""
    # path-derive WOULD yield "something-else" (not in the table)
    # but metadata declares "work-instructions" (valid row)
    entry = resolve_content_kind(
        manifest_metadata={
            "domain_type": "manufacturing",
            "content_kind": "work-instructions",
        },
        s3_key="manufacturing/something-else/M67/file.pdf",
    )
    assert entry.kind == "work-instruction"


def test_path_derives_when_metadata_absent():
    """When metadata.content_kind is missing entirely, path-derive runs."""
    entry = resolve_content_kind(
        manifest_metadata={"domain_type": "manufacturing"},
        s3_key="manufacturing/work-instructions/M67/grenade-assembly.pdf",
    )
    assert entry.kind == "work-instruction"
    assert entry.target_ontology_class == "http://edgy-solutions.com/ontology/mfg#WorkInstruction"
