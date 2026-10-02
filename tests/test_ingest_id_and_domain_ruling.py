"""The 2026-10-02 architect ruling on #43, pinned in three parts.

The ruling, verbatim:

    domain_type comes from the registered content kind's declared domain,
    never a run tag; ingest_id is the SDK shape (sha256:<hex>) everywhere,
    uuid form is a defect; extracted_count/extracted_total are two fields
    with units stated.

PART A — `ingest_id` shape (`doc_tools/utils/ingest_id.py`).
PART B — `domain_type` provenance (`doc_tools/assets/semantic_assets.py`).
PART C — the two counts and their units (`IngestStatusResource`).

ONE PREMISE OF THE RULING IS CORRECTED HERE, deliberately and in a test
rather than only in a comment. The ruling calls ``sha256:<hex>`` "the SDK
shape". It is not an SDK contract: `iagent_mesh/provenance.py` declares
``ingest_id: Optional[str] = None`` with no validator, and the literal
``sha256:`` appears nowhere in the SDK. The rule lives in
`invincible-agent/src/iagent/promotion.py`'s ``INGEST_ID_RE``, which
doc-tools cannot import (it is not in the published package). So the regex
in `ingest_id.py` is a MIRROR, and `test_a1_*` below pins its pattern
STRING — not because the pattern is interesting, but because that is the
only way a narrowing on Lane 1's side shows up as a failing diff here
instead of as an ingest silently refused promotion in sandbox.
"""
import inspect
import logging
import re
from unittest.mock import MagicMock

import pytest
from dagster import build_asset_context

from doc_tools.config import IngestionConfig

BUCKET = "test-bucket"

_CANON = "sha256:" + "ab" * 32
_BARE = "ab" * 32
_UUID = "550e8400-e29b-41d4-a716-446655440000"


# --------------------------------------------------------------------------- #
# Source-level assertions need the CODE, not the prose around it.
#
# Three of the tests below pin something by its ABSENCE — a deleted run-tag
# read, a deleted bare-hexdigest mint. Deleting a read leaves nothing to
# assert behaviourally (a tag that is ignored and a tag that is never read
# look identical from outside), so the assertion has to be against the
# source. But the comments recording WHY each thing was deleted necessarily
# quote it, so a naive substring check over `inspect.getsource` matches the
# explanation and fails. Strip comments and string literals first, via
# `tokenize`, so these tests read the code and not the commentary.
#
# The resolution lives in `_build_knowledge_graph_impl`, NOT in the
# `build_knowledge_graph` name the other tests invoke: that name is bound to
# an `AssetsDefinition` produced by `make_build_knowledge_graph()`, which
# `inspect.getsource` refuses outright. The impl is where the code is.
# --------------------------------------------------------------------------- #
def _code_only(module):
    """Module source with every comment and string literal blanked IN PLACE.

    Blanked rather than removed: the character ranges tokenize reports are
    overwritten with spaces, so line numbers, indentation and the relative
    order of everything else survive exactly. Re-joining token strings
    instead would run adjacent tokens together (`def` + a name becomes one
    word) and destroy the layout the ordering check in `test_b6_*` reads.
    """
    import io as _io
    import tokenize

    # COMMENT and STRING are not enough on 3.12+: PEP 701 made f-strings
    # their own token stream (FSTRING_START / FSTRING_MIDDLE / FSTRING_END),
    # so an f-string's literal text is NOT a STRING token and survives a
    # naive blanking pass. This module's error messages are f-strings that
    # quote the very things these tests pin by absence — the removed
    # "Training" default among them — so missing these types makes the test
    # read its own explanation and fail. `getattr` because the names do not
    # exist before 3.12.
    _blank = {tokenize.COMMENT, tokenize.STRING}
    for _name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        _tt = getattr(tokenize, _name, None)
        if _tt is not None:
            _blank.add(_tt)

    lines = inspect.getsource(module).splitlines(keepends=True)
    for tok in tokenize.generate_tokens(_io.StringIO("".join(lines)).readline):
        if tok.type not in _blank:
            continue
        (r1, c1), (r2, c2) = tok.start, tok.end
        for row in range(r1, r2 + 1):
            line = lines[row - 1]
            lo = c1 if row == r1 else 0
            hi = c2 if row == r2 else len(line.rstrip("\n"))
            keep_nl = "\n" if line.endswith("\n") and hi >= len(line.rstrip("\n")) else ""
            lines[row - 1] = (
                line[:lo] + " " * (hi - lo) + line[hi:].rstrip("\n") + keep_nl
            )
    return "".join(lines)


def _asset_body(module, name):
    """The code of one `@asset`-decorated function, comments stripped.

    Sliced out of the comment-stripped module source rather than fetched
    from the `AssetsDefinition` (`@asset` returns one, and
    `inspect.getsource` refuses it outright) — so the slice runs from
    `def <name>` to the next TOP-LEVEL `def`/`@`/`class`. Not "the next
    line at column 0": a multi-line signature closes with `)` in column 0,
    which would cut the slice off before the body ever starts.
    """
    import re as _re

    code = _code_only(module)
    start = code.index(f"def {name}(")
    rest = code[start:]
    m = _re.search(r"^(def |@|class )", rest[1:], _re.MULTILINE)
    return rest[: m.start() + 1] if m else rest


# =========================================================================== #
# PART A — ingest_id is sha256:<64 hex> everywhere; uuid form is a defect
# =========================================================================== #
def test_a1_pattern_string_is_pinned_to_lane_1s_regex():
    """A MIRROR tripwire, not a tautology.

    `invincible-agent/src/iagent/promotion.py:65` is the authority and is
    not importable from here. If Lane 1 narrows it (lowercase-only is
    already narrower than hex), this assertion is what makes the divergence
    visible in a diff. Do not "fix" a failure here by editing the literal:
    read Lane 1's regex first and decide which side moved.
    """
    from doc_tools.utils.ingest_id import INGEST_ID_RE

    assert INGEST_ID_RE.pattern == r"^sha256:[0-9a-f]{64}$"


def test_a2_mint_matches_lane_1s_derivation_exactly():
    """`mint_ingest_id(b)` must equal Lane 1's ``ingest_id_for(b)``.

    Recomputed here from stdlib rather than compared to a stored constant,
    because the thing under test is the DERIVATION (prefix + lowercase hex
    of sha256 over the raw bytes), which is the sole reason an id minted in
    doc-tools can be joined to a row Lane 1 minted for the same file.
    """
    import hashlib

    from doc_tools.utils.ingest_id import INGEST_ID_RE, mint_ingest_id

    data = b"%PDF-1.7\nnot really a pdf\n"
    minted = mint_ingest_id(data)

    assert minted == "sha256:" + hashlib.sha256(data).hexdigest()
    assert INGEST_ID_RE.match(minted)


def test_a3_canonical_passes_through_untouched():
    from doc_tools.utils.ingest_id import canonical_ingest_id

    assert canonical_ingest_id(_CANON, where="t") == _CANON


def test_a4_bare_hexdigest_is_coerced_but_warns(caplog):
    """The old doc-tools mint. Recoverable — and still a producer defect.

    Coerced rather than refused because it IS the same digest, so the join
    survives; warned rather than coerced silently because the producer is
    emitting a spelling Lane 1's promotion guard refuses outright, which is
    how an ingest gets refused promotion for a spelling mismatch.
    """
    from doc_tools.utils.ingest_id import canonical_ingest_id

    with caplog.at_level(logging.WARNING, logger="doc_tools.utils.ingest_id"):
        out = canonical_ingest_id(_BARE, where="the-producer")

    assert out == _CANON
    assert "the-producer" in caplog.text, "the warning must name the producer"
    assert "BARE" in caplog.text


def test_a5_uuid_form_raises_and_is_never_substituted():
    """The ruling's named defect.

    A uuid is not a digest of the document's bytes, so there is no
    conversion to the canonical form — only a substitution, which would
    mint an id naming no row in Lane 1's projection. Refused.
    """
    from doc_tools.utils.ingest_id import IngestIdShapeError, canonical_ingest_id

    with pytest.raises(IngestIdShapeError, match="uuid"):
        canonical_ingest_id(_UUID, where="t")


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "   ",
        "sha256:deadbeef",          # the OLD fixture value: 8 hex, not 64
        "sha256:" + "AB" * 32,      # uppercase — Lane 1's regex is lowercase
        "sha512:" + "ab" * 32,
        _BARE[:-1],                 # 63 hex: not coercible
    ],
)
def test_a6_everything_else_raises(bad):
    from doc_tools.utils.ingest_id import IngestIdShapeError, canonical_ingest_id

    with pytest.raises(IngestIdShapeError):
        canonical_ingest_id(bad, where="t")


def test_a7_is_a_valueerror_so_existing_handlers_still_catch_it():
    """Subclassing `ValueError` is load-bearing, not incidental.

    `IngestStatusResource.update` already raised `ValueError` for a bad
    stage and a blank detail, and callers catch that. A new sibling error
    that was not a `ValueError` would escape those handlers.
    """
    from doc_tools.utils.ingest_id import IngestIdShapeError

    assert issubclass(IngestIdShapeError, ValueError)


def test_a8_the_status_seam_refuses_a_uuid():
    """The ruling says "everywhere" — so at the seam, not only in the util."""
    pytest.importorskip("iagent_mesh.ingest")
    from doc_tools.utils.dagster_resources import IngestStatusResource
    from doc_tools.utils.ingest_id import IngestIdShapeError

    with pytest.raises(IngestIdShapeError):
        IngestStatusResource().update(_UUID, "received")


def test_a9_the_provenance_block_builder_refuses_a_uuid():
    """...and at the block builder, which is where the join key is WRITTEN.

    The SDK would have accepted it (`ingest_id` has no validator there), so
    without this check a uuid rides SDK validation onto the manifest and
    fails only later, in another repo.
    """
    pytest.importorskip("iagent_mesh.provenance")
    from doc_tools.utils.ingest_id import IngestIdShapeError
    from doc_tools.utils.ingest_provenance import build_ingest_provenance

    with pytest.raises(IngestIdShapeError):
        build_ingest_provenance(
            obtained_via="user-drop",
            authoritative_source="user-upload",
            ingest_run="run-1",
            standing="unverified",
            ingest_id=_UUID,
        )


def test_a10_a_none_ingest_id_stays_none_in_the_block():
    """`None` is NOT a shape defect at the builder.

    The SDK declares the field optional and the non-user-drop sources have
    no ingest at all. Refusing a None belongs at the call site that knows
    one was required — `document_parser`'s sidecar guard, covered by
    `test_b5_*`-style sidecar tests in test_ingress_user_stamp.py — not at
    a builder shared by paths that legitimately have nothing to spell.
    """
    pytest.importorskip("iagent_mesh.provenance")
    from doc_tools.utils.ingest_provenance import build_ingest_provenance

    block = build_ingest_provenance(
        # A non-user-drop rung: OBTAINED_VIA is
        # ("direct", "etl", "warehouse", "manual-export", "user-drop") — the
        # SDK validates it, so an invented rung fails here and not where the
        # test means to look.
        obtained_via="direct",
        authoritative_source="vendor-portal",
        ingest_run="run-1",
        standing="verified",
    )
    assert block.get("ingest_id") is None


def test_a11_no_bare_hexdigest_mint_survives_in_the_parser():
    """The removed fallback, pinned by its absence.

    `document_parser` used to mint ``hashlib.sha256(f.read()).hexdigest()``
    — the bare form. A reader cannot tell from the current source that the
    bare mint is GONE rather than moved, so assert it: the module must not
    call `hexdigest()` to build an ingest_id, and must not import hashlib
    for one.
    """
    from doc_tools.components import document_parser

    src = _code_only(document_parser)
    assert "mint_ingest_id" in src
    assert "hexdigest" not in src, (
        "document_parser must mint via ingest_id.mint_ingest_id (which adds "
        "the 'sha256:' prefix), never a raw hexdigest"
    )


# =========================================================================== #
# PART B — domain_type comes from the registered content kind, never a run tag
#
# Driven by DIRECT INVOCATION of build_knowledge_graph with mocked
# resources, the same pattern test_ingress_user_stamp.py uses: the
# orchestration past the top of the function is heavy I/O left to
# integration tests. The RESOLVED domain is observable without reaching any
# of it, because the ADR-0041 provenance check sits immediately after the
# resolution and puts `domain_label` in its own message. So a manifest that
# carries a provenance block turns "which domain did it resolve to?" into
# "which exception, naming which label?" — a real discriminator rather than
# a mock assertion.
# =========================================================================== #
def _bkg_config():
    return IngestionConfig(
        graph_node_label="WorkInstruction",
        graph_child_label="Page",
        vector_collection_name="DocumentChunk",
        bucket=BUCKET,
    )


def _manifest(metadata, *, s3_key="", with_provenance=True):
    m = {
        "doc_id": "doc-1",
        "text_location": "x/text.json",
        "metadata": metadata,
    }
    if s3_key:
        m["source_object_key"] = s3_key
    if with_provenance:
        m["provenance"] = {
            "obtained_via": "user-drop",
            "authoritative_source": "user-upload",
            "as_of": "unknown",
            "ingested_at": "2026-10-02T00:00:00+00:00",
            "ingest_run": "run-1",
            "standing": "unverified",
            "ingest_id": _CANON,
        }
    return m


def _invoke(manifest, s3=None):
    from doc_tools.assets.semantic_assets import build_knowledge_graph

    return build_knowledge_graph(
        build_asset_context(),
        _bkg_config(),
        manifest,
        s3=s3 or MagicMock(), neo4j=MagicMock(), weaviate=MagicMock(),
        llm=MagicMock(), jena=MagicMock(),
    )


def test_b1_the_registered_kind_overrides_the_manifests_declared_domain():
    """THE RULING, at its only live discriminator.

    `content_kind="work-instructions"` is the one row in KIND_MAPPING and it
    declares domain manufacturing. The manifest declares sustainment. If the
    kind wins, domain_label is MANUFACTURING, which is NOT in
    DOMAINS_THAT_PERSIST_PROVENANCE, so the provenance check halts and names
    it. If the MANIFEST had won, domain_label would be SUSTAINMENT, which IS
    in that set, and execution would have fallen through to the s3 sentinel.
    The two outcomes are mutually exclusive, so this test cannot pass for
    the wrong reason.
    """
    from doc_tools.assets.semantic_assets import (
        DOMAINS_THAT_PERSIST_PROVENANCE, ProvenanceNotPersistableError,
    )
    assert "SUSTAINMENT" in DOMAINS_THAT_PERSIST_PROVENANCE
    assert "MANUFACTURING" not in DOMAINS_THAT_PERSIST_PROVENANCE

    s3 = MagicMock()
    s3.get_client.side_effect = RuntimeError("SENTINEL_MANIFEST_WON")

    with pytest.raises(ProvenanceNotPersistableError, match="MANUFACTURING"):
        _invoke(
            _manifest({
                "domain_type": "sustainment",
                "content_kind": "work-instructions",
            }),
            s3=s3,
        )


def test_b2_an_unmigrated_domain_still_falls_back_to_the_manifest():
    """The SCOPED MIGRATION, pinned.

    KIND_MAPPING has one row, so SUSTAINMENT — and the entire PCN corpus
    gate — has no kind to resolve. The resolver's halt must NOT propagate
    for it, or every non-manufacturing drop bricks. Proven by reaching the
    sentinel: resolution completed, domain_label became SUSTAINMENT, and
    the provenance check passed it through.
    """
    s3 = MagicMock()
    s3.get_client.side_effect = RuntimeError("SENTINEL_PAST_RESOLUTION")

    with pytest.raises(RuntimeError, match="SENTINEL_PAST_RESOLUTION"):
        _invoke(_manifest({"domain_type": "sustainment"}), s3=s3)


def test_b3_manufacturing_still_halts_on_an_unresolvable_kind():
    """Manufacturing IS migrated, so for it the resolver's halt stands.

    A declared-manufacturing document whose kind does not resolve is a
    document whose registered kind is missing, and ADR-0021 §Precedence has
    no default for that.
    """
    from doc_tools.utils.content_kind import UnclassifiableContentKindError

    with pytest.raises(UnclassifiableContentKindError):
        _invoke(_manifest({
            "domain_type": "manufacturing",
            "content_kind": "no-such-kind",
        }))


def test_b4_no_kind_and_no_declared_domain_raises_rather_than_defaulting():
    """Where `metadata.get("project", "Training")` used to sit.

    BEYOND THE LITERAL RULING, and flagged as such: the ruling names the
    run tag as the thing to remove. The old "Training" default was
    unreachable dead code (it lived inside an `except AttributeError` that
    never fired on dagster 1.12.21, because `.get` returns None without
    raising), so deleting it changed no behaviour — but choosing to RAISE
    where it sat is a decision. It is the right one: writing an
    unidentified document into the TRAINING domain's graph on no evidence
    makes a semantic claim nothing supports, and TRAINING is a real domain
    with real downstream consumers filtering on that label.
    """
    from doc_tools.assets.semantic_assets import DomainTypeNotResolvableError

    with pytest.raises(DomainTypeNotResolvableError):
        _invoke(_manifest({}, s3_key="whatever/thing.pdf"))


def test_b5_the_run_tag_read_is_gone_from_the_source():
    """The explicit half of the ruling, pinned by absence.

    Deleting a read leaves nothing to assert behaviourally — a run tag that
    is ignored and a run tag that is never read look identical from
    outside. Asserted against the source instead. (It was ALSO already
    inert: AGENTS.md claims sensors inject a `domain_type` run tag, and the
    installed S3SensorComponent injects no run tags at all.)
    """
    from doc_tools.assets import semantic_assets

    src = _asset_body(semantic_assets, "_build_knowledge_graph_impl")
    assert "run.tags" not in src, (
        "domain_type must come from the registered content kind's declared "
        "domain, never a run tag (architect ruling 2026-10-02)"
    )
    assert '"Training"' not in src and "'Training'" not in src


def test_b6_the_kind_is_resolved_before_the_domain_not_after():
    """The ordering inversion the ruling forced, pinned where it can regress.

    The old code resolved domain_type first and then gated the content-kind
    resolution on `if domain_type == "manufacturing"` — using domain_type to
    decide whether to resolve the kind that now SUPPLIES domain_type. If
    someone restores that gate, `resolve_content_kind` runs after the
    assignment again and the ruling is silently reverted while every other
    test here still passes (they all exercise paths where the order happens
    not to matter for the outcome). So: the resolver call must appear BEFORE
    the first `domain_type =` assignment.
    """
    from doc_tools.assets import semantic_assets

    src = _asset_body(semantic_assets, "_build_knowledge_graph_impl")
    resolve_at = src.index("kind_entry = resolve_content_kind")
    assign_at = re.search(r"^\s+domain_type = ", src, re.MULTILINE).start()
    assert resolve_at < assign_at, (
        "resolve_content_kind must run BEFORE domain_type is assigned — it "
        "is the source of the value"
    )


# =========================================================================== #
# PART C — extracted_count / extracted_total are two fields, with units
# =========================================================================== #
def test_c1_the_units_are_named_as_constants_and_differ():
    """Two fields, two units — not a numerator and a denominator.

    They count different things (unstructured ELEMENTS vs rasterized
    PAGES), so `extracted_count / extracted_total` is meaningless and
    count > total is the NORMAL case. A consumer rendering "412 of 9" has
    mistaken the contract.
    """
    from doc_tools.utils.dagster_resources import IngestStatusResource

    assert "element" in IngestStatusResource.EXTRACTED_COUNT_UNIT
    assert "page" in IngestStatusResource.EXTRACTED_TOTAL_UNIT
    assert (IngestStatusResource.EXTRACTED_COUNT_UNIT
            != IngestStatusResource.EXTRACTED_TOTAL_UNIT)


def test_c2_the_emitted_log_carries_the_units_with_the_values(caplog):
    """Units in the DOCSTRING are units a reader of the logs does not have.

    This seam is a validating no-op: there is no write path to Lane 1's
    ingest_status_projection yet, so the log line is its ENTIRE observable
    surface. If the units are not in that line, nobody downstream has them.
    Also pinned here: count > total emits cleanly, with no clamping, no
    warning and no reordering — because it is correct.
    """
    pytest.importorskip("iagent_mesh.ingest")
    from doc_tools.utils.dagster_resources import IngestStatusResource

    with caplog.at_level(logging.INFO, logger="doc_tools.utils.dagster_resources"):
        IngestStatusResource().update(
            _CANON, "awaiting_disposition",
            extracted_count=412, extracted_total=9,
        )

    text = caplog.text
    assert "extracted_count=412" in text
    assert "extracted_total=9" in text
    assert IngestStatusResource.EXTRACTED_COUNT_UNIT in text
    assert IngestStatusResource.EXTRACTED_TOTAL_UNIT in text
