"""The shipping content kinds, registered — ruling 2026-10-02.

*"7f registers the shipping kinds (PDF, EngineeringDocument, PCN, PDN,
S1000D-data-module) with their domains, as the kind-registration rows the
picker derives from."*

and, on what "with their domains" means for the format-level ones:

*"KIND_MAPPING rows: pcn, pdn → SUSTAINMENT; s1000d-data-module → MAINTENANCE;
engineering-document, doors-export, pdf → none (origin resolved by evidence,
not kind)."*

THREE SEAMS ARE PINNED HERE, and they fail in three different ways if left
unpinned:

 1. **The table vs the rows.** ``registered_kinds()`` makes the picker's legal
    set the registered rows. If the rows drifted from ``KIND_MAPPING``, the
    picker would offer a kind the mapping table cannot resolve, and ADR-0021's
    halt would fire on a kind that IS registered.
 2. **The two spellings of a kind.** The table is keyed by
    ``kind_source_value``; the picker offers ``kind``. They differ for exactly
    one row.
 3. **The phantoms.** Two output classes and one pass are declared before they
    exist. That is the ordered sequence the architect set, not an oversight —
    so the set of not-yet-real references is asserted to be EXACTLY the
    declared one, which turns "someone added a third phantom quietly" into a
    failure.
"""
import json
from pathlib import Path

import pytest

from doc_tools.utils.content_kind import (
    KIND_MAPPING,
    PHANTOM_OUTPUTS,
    UNBUILT_PASSES,
    UnclassifiableContentKindError,
    resolve_content_kind,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROWS_DIR = REPO_ROOT / "registry" / "content_kinds"
DOMAINS_FILE = REPO_ROOT / "registry" / "content_kind_domains.json"

#: The ruling, transcribed as data. Lowercase because ``domain_type`` is the
#: pipeline value and ``domain_label`` is its uppercase (the Neo4j label and
#: the ``<http://internal/{DOMAIN}_INSTANCES>`` graph name) — the ruling's
#: SUSTAINMENT/MAINTENANCE is what reaches the graph either way.
RULED_DOMAINS = {
    "pcn": "sustainment",
    "pdn": "sustainment",
    "s1000d-data-module": "maintenance",
    "engineering-document": None,
    "doors-export": None,
    "pdf": None,
}


# --------------------------------------------------------------------------- #
# 1. The ruling, row by row
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind,domain", sorted(RULED_DOMAINS.items(), key=str))
def test_the_ruled_domain_is_what_the_row_declares(kind, domain):
    entry = KIND_MAPPING[kind]
    assert entry.domain_type == domain, (
        f"{kind!r} must declare domain {domain!r}; row says "
        f"{entry.domain_type!r}"
    )


def test_a_format_level_kind_declares_none_and_that_is_not_an_empty_string():
    """``None``, not ``""``. The difference is load-bearing: ``""`` is falsy
    the same way a missing value is, so it would read as "nobody filled this
    in" at every call site — while ``None`` here is a POSITIVE assertion that
    a PDF has no domain of its own. The write path branches on
    ``is None``, so an empty string would sail past it into
    ``"".upper()`` and a blank Neo4j label.
    """
    for kind in ("pdf", "engineering-document", "doors-export"):
        assert KIND_MAPPING[kind].domain_type is None


def test_the_registered_kind_spelling_also_resolves():
    """Seam 2. ``work-instructions`` (the kind-source value, the table key) and
    ``work-instruction`` (the registered kind, what a picker offers) must reach
    the same row, or "the legal set IS the registered rows" is false for one of
    seven rows — and false in the direction that halts a legitimate drop.
    """
    by_source = resolve_content_kind({"content_kind": "work-instructions"}, "")
    by_kind = resolve_content_kind({"content_kind": "work-instruction"}, "")
    assert by_source is by_kind

    for entry in KIND_MAPPING.values():
        assert resolve_content_kind({"content_kind": entry.kind}, "") is entry


def test_an_unregistered_kind_still_halts():
    """Adding six rows must not have turned the halt into a near-miss match."""
    with pytest.raises(UnclassifiableContentKindError):
        resolve_content_kind({"content_kind": "pcn-notice"}, "")


def test_no_live_sensor_prefix_path_derives_onto_a_new_row():
    """Why adding these rows changes nothing for the live corpus.

    ``_derive_from_path`` returns the segment AFTER the domain segment. The
    configured sensors watch ``manufacturing/inbound/`` and
    ``sustainment/inbound/``, so a curated key path-derives to ``"inbound"``,
    which has no row — the PCN corpus keeps taking the scoped-migration
    fallback it takes today. The new rows are reachable only through an
    EXPLICIT ``metadata.content_kind``, which only the ``/ingest`` door sets.
    That is the measurement behind claiming this PR is inert for the gate, so
    it is pinned rather than asserted in prose.
    """
    from doc_tools.utils.content_kind import _derive_from_path

    assert _derive_from_path("sustainment/inbound/x.pdf", "sustainment") == "inbound"
    assert "inbound" not in KIND_MAPPING
    with pytest.raises(UnclassifiableContentKindError):
        resolve_content_kind(
            {"domain_type": "sustainment"}, "sustainment/inbound/x.pdf"
        )


# --------------------------------------------------------------------------- #
# 2. The projection the picker reads
# --------------------------------------------------------------------------- #
def test_the_generated_rows_are_in_sync_with_the_table():
    """Seam 1, as the generator's own ``--check``."""
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_kind_registrations.py"),
         "--check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_rows_load_and_validate_through_the_sdk():
    """The rows are only the picker's legal set if the SDK accepts them.

    ``load_content_kind_registrations`` applies the whole composer discipline
    — one row per file, keyed by ``kind``, duplicate keys and empty files
    refused — and then builds each row through a model that is
    ``extra="forbid"`` and demands non-empty ``passes``/``outputs``. So this
    one call covers the file conventions and the field contract together.

    MEASURED, not deferred to CI: run against a pristine ``v0.9.5`` tree (the
    ``pyproject`` pin), all seven rows load and ``registered_kinds()`` returns
    them sorted. The installed venv copy predates the ``ingest`` module, which
    is why this skips locally.

    **IF THIS TEST STARTS FAILING WITH "domain Field required", THAT IS THE
    ALARM, NOT A BUG HERE.** The SDK has an in-flight, untagged 0.9.7 that adds
    a REQUIRED non-empty ``domain: str`` to ``ContentKindRegistration``
    ("a kind with no domain has no audience"). It refuses all seven of these
    row files, and it cannot represent the ruling's ``none`` for ``pdf`` /
    ``engineering-document`` / ``doors-export`` at all — a required non-empty
    string has no spelling for "this kind has no domain of its own". That
    collision is the architect's to resolve (either the ruled ``none`` or the
    required field moves); a pin bump to 0.9.7 lands it here first.
    """
    ingest = pytest.importorskip(
        "iagent_mesh.ingest",
        reason="the installed iagent_mesh predates v0.9.5's ingest module; CI "
               "installs the pinned SDK and runs this",
    )
    rows = ingest.load_content_kind_registrations(ROWS_DIR)
    assert ingest.registered_kinds(rows) == tuple(
        sorted(e.kind for e in KIND_MAPPING.values())
    )
    for row in rows:
        entry = KIND_MAPPING[row.kind] if row.kind in KIND_MAPPING else next(
            e for e in KIND_MAPPING.values() if e.kind == row.kind
        )
        assert row.passes == entry.passes
        assert row.outputs == entry.outputs


def test_a_domain_key_in_a_row_would_be_refused_at_the_pin():
    """Why the domain rides BESIDE the rows instead of in them — AT THE PIN.

    At ``v0.9.5``, ``ContentKindRegistration`` is ``extra="forbid"`` with
    exactly ``kind``/``passes``/``outputs`` and no domain field: the SDK ships
    no rows and takes no position on domain. So ``domain:`` in a YAML row would
    not be ignored, it would raise, and the whole registry directory would stop
    loading — measured, ``ValidationError``. That is the constraint the sidecar
    ``content_kind_domains.json`` exists to satisfy.

    THIS ASSERTION IS PINNED TO THE PIN, AND IT IS EXPECTED TO INVERT. The
    untagged 0.9.7 makes ``domain`` a required field, so the same call that
    raises here would then be the only call that SUCCEEDS. Written as a
    version-conditional rather than a bare ``raises`` so a pin bump produces a
    readable failure naming the collision instead of a bare assertion error —
    see ``test_the_rows_load_and_validate_through_the_sdk`` for what else
    breaks at that bump.
    """
    ingest = pytest.importorskip("iagent_mesh.ingest")
    fields = set(ingest.ContentKindRegistration.model_fields)
    if "domain" in fields:
        pytest.fail(
            "the installed SDK's ContentKindRegistration declares a `domain` "
            "field (0.9.7+), so the sidecar split in registry/ is no longer "
            "the only way to carry a domain -- AND a required non-empty "
            "`domain` cannot express the ruled `none` for pdf / "
            "engineering-document / doors-export. Resolve the collision with "
            "the architect before adapting the rows; do not invent a domain "
            "for a format-level kind to satisfy the model."
        )
    assert fields == {"kind", "passes", "outputs"}, sorted(fields)
    with pytest.raises(Exception):
        ingest.ContentKindRegistration(
            kind="pcn", passes=("x",), outputs=("y",), domain="sustainment"
        )


def test_the_domain_sidecar_covers_every_registered_kind():
    payload = json.loads(DOMAINS_FILE.read_text(encoding="utf-8"))["domains"]
    assert payload == {
        e.kind: e.domain_type for e in KIND_MAPPING.values()
    }
    # And the ruling's six, under their registered spelling.
    for kind, domain in RULED_DOMAINS.items():
        assert payload[KIND_MAPPING[kind].kind] == domain


# --------------------------------------------------------------------------- #
# 3. The phantoms stay visible
# --------------------------------------------------------------------------- #
def test_the_phantom_outputs_are_exactly_the_two_owed_by_lane_1():
    """ADR-0019 §6: an output URI is a phantom until it resolves to a declared
    class. Two are, by the architect's own sequencing — ``mesh_system.ttl`` is
    Lane 1's TTL and the leaf lands there ("7f registers the row now and it
    resolves when the TTL lands"). Asserting the set EXACTLY means a third
    phantom cannot arrive unannounced.
    """
    declared_curies = {
        "mfg:WorkInstruction",
        "pcn:ProcessChangeNotification",
        "pcn:ProductDiscontinuationNotice",
        "pcn:Component",
        "mil:DataModule",
        "mesh:PDFArtifact",
    }
    all_outputs = {o for e in KIND_MAPPING.values() for o in e.outputs}
    assert all_outputs - declared_curies == set(PHANTOM_OUTPUTS)
    assert "mesh:CADArtifact" not in all_outputs, (
        "the architect ruled against aliasing an engineering document to CAD: "
        "'an engineering document is not a CAD artifact'"
    )


def test_every_unbuilt_pass_belongs_to_a_kind_that_writes_nothing():
    """The safety property that makes declaring an unbuilt pass harmless.

    ``identity.document_identity`` does not exist yet — it is the next ordered
    item of work. Nothing can run it, because every kind that declares it also
    declares no domain, and a domainless kind short-circuits at
    "origin unresolved" before any pass could be dispatched. If someone gave a
    DOMAIN-declaring kind an unbuilt pass, this test fails and says so.
    """
    for entry in KIND_MAPPING.values():
        unbuilt = set(entry.passes) & set(UNBUILT_PASSES)
        if unbuilt:
            assert entry.domain_type is None, (
                f"{entry.kind!r} declares unbuilt pass(es) {sorted(unbuilt)} "
                f"AND a domain ({entry.domain_type!r}), so the pipeline would "
                f"try to run a pass that does not exist"
            )


def test_every_row_has_a_nonempty_pass_and_output():
    """The SDK model refuses ``()`` for either ("a kind with no pass is not a
    kind, it is a row someone forgot to finish"). Checked here too, so the
    failure names the table row rather than a YAML file."""
    for source, entry in KIND_MAPPING.items():
        assert entry.passes, f"{source!r} has no passes"
        assert entry.outputs, f"{source!r} has no outputs"
        assert len(set(entry.passes)) == len(entry.passes), source
        assert len(set(entry.outputs)) == len(entry.outputs), source
