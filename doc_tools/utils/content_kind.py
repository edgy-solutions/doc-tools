"""ADR-0021 deterministic content-kind selection at ingest.

Single source of truth for "what kinds exist and what each maps to."
Adding a kind = one line in ``KIND_MAPPING`` + the target ``OntologyClass``
declared in the matching TTL.

Precedence (per ADR-0021 §Decision):

    1. ``manifest.metadata.content_kind`` (explicit declaration)
    2. Path-derived segment AFTER the ``domain_type`` segment of the S3 key
    3. **HALT** with :class:`UnclassifiableContentKindError` — never silent default

The legacy ``domain_type`` chain in ``semantic_assets.py`` falls through to a
hardcoded ``"Training"`` default. **That behavior is deliberately NOT
inherited here.** The asymmetry is intentional and documented at the call
site; whether ``domain_type`` should also halt is a future ADR's question.
"""

from dataclasses import dataclass
from typing import Optional


class UnclassifiableContentKindError(Exception):
    """Raised when neither metadata.content_kind nor the path-derived segment
    yields a kind_source_value present in ``KIND_MAPPING``.

    Per ADR-0021 §Precedence rule §3 the kind-selection chain MUST halt here.
    There is no silent default — that is the rule the legacy ``domain_type``
    chain breaks and that this resolver deliberately does not inherit.
    """


@dataclass(frozen=True)
class ContentKindEntry:
    """A single row of the ADR-0021 mapping table.

    The row IS the contract: adding a content kind = adding an entry to
    ``KIND_MAPPING`` whose ``target_ontology_class`` is declared in the
    matching domain TTL (e.g. ``mfg_extension.ttl`` for manufacturing).
    """
    kind_source_value: str
    kind: str
    extractor_config: str
    baml_function: str
    target_ontology_class: str
    domain_type: str


# The mapping table. THE single source of truth for content kinds.
#
# "No row" and "HALT" are wired to the same condition by the resolver
# (``KIND_MAPPING.get(value)`` returning ``None`` triggers ``raise``).
# They cannot diverge.
#
# Today: one row. As of ADR-0021 ratification (2026-06-20) the architect
# chose single-kind manufacturing — sub-kinds wait for routing-demand
# evidence (§Alternatives considered). When a second row is justified,
# it lands here and the manufacturing TTL grows by one class.
KIND_MAPPING: dict[str, ContentKindEntry] = {
    "work-instructions": ContentKindEntry(
        kind_source_value="work-instructions",
        kind="work-instruction",
        extractor_config="manufacturing_default",
        baml_function="ExtractWorkInstructions",
        target_ontology_class="http://edgy-solutions.com/ontology/mfg#WorkInstruction",
        domain_type="manufacturing",
    ),
}


def _derive_from_path(s3_key: str, domain_type: Optional[str]) -> Optional[str]:
    """Per ADR-0021 §Path-derived: segment AFTER the ``domain_type`` segment.

    Returns ``None`` on shape mismatch (key has < 2 segments, or first
    segment does not match ``domain_type``). The caller's halt fires at
    the table lookup — ``None`` is not in the table — so a malformed path
    routes THROUGH the halt rather than around it.
    """
    if not s3_key or domain_type is None:
        return None
    parts = s3_key.split("/")
    if len(parts) < 2 or parts[0] != domain_type:
        return None
    return parts[1]


def resolve_content_kind(
    manifest_metadata: dict, s3_key: str
) -> ContentKindEntry:
    """ADR-0021 precedence: metadata > path > HALT.

    The function NEVER returns a default. The only way to NOT raise is for
    the resolved ``kind_source_value`` to have a row in ``KIND_MAPPING``.
    Table-miss == unclassifiable == HALT. Contract tested by
    ``test_unclassifiable_kind_HALTS_does_not_default``.

    Empty-string handling (sharpening 2026-06-20 architect ruling): an
    explicit ``content_kind = ""`` value in ``manifest_metadata`` is
    treated as ABSENT — i.e. falls through to path-derive. The decision is
    that an empty-string from JSON/metadata tooling reflects a "field exists
    but unset" shape, not an explicit "no kind" assertion. A
    genuinely-wrong explicit value (``content_kind = "nonsense"``) does NOT
    fall through — it goes straight to the table lookup, finds no row, and
    halts. That asymmetry is deliberate: explicit-wrong should halt loudly;
    explicit-empty is treated as "no signal given." The behavior is named
    here and tested by
    ``test_empty_string_content_kind_falls_through_to_path``.
    """
    raw_metadata_value = manifest_metadata.get("content_kind")
    # Strip whitespace; treat empty/whitespace-only as ABSENT (deliberate
    # named decision, NOT an `or`-truthiness accident).
    metadata_value = raw_metadata_value.strip() if isinstance(raw_metadata_value, str) else raw_metadata_value
    if metadata_value:
        kind_source_value = metadata_value
    else:
        kind_source_value = _derive_from_path(s3_key, manifest_metadata.get("domain_type"))

    entry = KIND_MAPPING.get(kind_source_value)
    if entry is None:
        raise UnclassifiableContentKindError(
            f"No KIND_MAPPING row for kind_source_value={kind_source_value!r} "
            f"(from manifest.metadata.content_kind={raw_metadata_value!r} "
            f"or path-derive over s3_key={s3_key!r}). "
            f"Per ADR-0021 §Precedence the kind-selection chain HALTS here — "
            f"there is no silent default. Either add a row to KIND_MAPPING "
            f"(in doc_tools/utils/content_kind.py) with a registered "
            f"target_ontology_class and BAML extractor, or correct the "
            f"upstream manifest/path."
        )
    return entry
