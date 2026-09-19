"""A partial ingest must not report as a success. Rulings 1, 2 and 3 of dispatch 7f.

THE SHAPE ALL THREE REFUSE. Jena is authoritative for what EXISTS and the vector store for
what can be GROUNDED. A run that populates one and not the other leaves the mesh in a state
no consumer can detect from the outside -- the class genuinely exists, ``/resolve`` reports
success, every component is healthy, and routing dies with nothing red anywhere. The
MAINTENANCE work-order class was chased as a missing manifest row for a day; it was this.

    Ruling 1  a THROWN Weaviate write fails the asset, instead of logging and falling
              through to the same MaterializeResult the success path returns.
    Ruling 2  every class the run DECLARED is a row, or is excluded for a NAMED reason.
              Derived from the run's own record of what it was handed, never from a copy
              of a manifest that lives in the other repo.
    Ruling 3  the readiness sentinel is per domain AND per manifest entry, so it can tell
              "Weaviate answers" from "MAINTENANCE ingested".

WHAT IS DELIBERATELY LEFT BEST-EFFORT, asserted here so a later cleanup cannot quietly
widen Ruling 1 into it. The distinction the ruling turns on is ROW MISSING versus ROW
PRESENT BUT THINNER:

  * ``embed_document`` failure writes the row with no vector and says so. BM25 still
    answers and a backfill can populate the vector later. A degraded row.
  * ``write_collection_marker`` is metadata ABOUT the collection, not a row in it.

Both stay best-effort. Widening the raise into them would turn a recoverable degradation
into a failed ingest, which is a different bug with the same shape.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = (pathlib.Path(__file__).resolve().parents[1]
        / "doc_tools" / "assets" / "ontology_assets.py")

MESH = "http://invincible-agent/mesh#"
PROV = "http://www.w3.org/ns/prov#"
EX = "http://example.com/ontology#"


def _load(*names: str) -> dict:
    """Exec only the named top-level defs/assigns -- no dagster, no weaviate client."""
    import rdflib
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    ns: dict = {"rdflib": rdflib}
    wanted = set(names)
    for node in tree.body:
        got = None
        if isinstance(node, ast.FunctionDef):
            got = node.name
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            got = node.target.id
        elif isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            got = node.targets[0].id
        if got in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(_SRC), "exec"), ns)
    missing = wanted - set(ns)
    assert not missing, f"could not load {missing} from {_SRC.name}"
    return ns


_NS = _load(
    "_META_ONTOLOGY_IRI_PREFIXES",
    "_is_meta_ontology_iri",
    "EXCLUSION_META_ONTOLOGY",
    "EXCLUSION_RESPONSE_SHAPE",
    "partition_ontology_classes",
)
partition_ontology_classes = _NS["partition_ontology_classes"]
EXCL_META = _NS["EXCLUSION_META_ONTOLOGY"]
EXCL_SHAPE = _NS["EXCLUSION_RESPONSE_SHAPE"]


def _fn(name: str) -> ast.FunctionDef:
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)
    assert node is not None, f"{name} not found in {_SRC.name} -- renamed?"
    return node


# ── RULING 1: the dual-write failure fails the asset ─────────────────────────

def test_the_dual_write_except_RAISES_instead_of_falling_through():
    """THE RULING, checked on the AST rather than by grepping.

    A substring search cannot tell code from the long comment above it explaining why the
    code must exist, so it would pass on the prose it is meant to be policing. This walks
    the actual handler.
    """
    fn = _fn("ingest_ontology_to_jena")
    handlers = [
        h for h in ast.walk(fn)
        if isinstance(h, ast.ExceptHandler)
        and any("Weaviate" in getattr(c, "value", "")
                for c in ast.walk(h) if isinstance(c, ast.Constant)
                and isinstance(getattr(c, "value", None), str))
    ]
    assert handlers, "the Weaviate dual-write except handler is gone -- renamed?"
    for h in handlers:
        raises = [n for n in ast.walk(h) if isinstance(n, ast.Raise)]
        assert raises, (
            "the Weaviate dual-write handler catches and does NOT raise. It therefore "
            "falls through to the same MaterializeResult the success path returns: "
            "Dagster sees a materialised asset, Jena has the triples, Weaviate has "
            "nothing, and the run is green. That is the exact state the class system "
            "exists to refuse."
        )


def test_the_raise_says_the_substrate_is_now_PARTIAL():
    """An operator reading the failure has to know the Jena half LANDED, or the obvious
    recovery (re-drive everything) is indistinguishable from the right one."""
    src = _SRC.read_text(encoding="utf-8")
    assert "PARTIAL" in src and "Weaviate dual-write FAILED" in src


def test_the_batch_error_channel_is_READ():
    """THE HALF THE RULING AS WRITTEN WOULD HAVE MISSED.

    weaviate-client 4.21.3's batch does not raise on per-object failure -- it collects
    into ``collection.batch.failed_objects`` and logs (collections/batch/base.py:722).
    So a re-raising ``except`` closes the case where the whole leg throws and leaves the
    likelier one untouched: every row rejected, context manager exits clean, nothing ever
    reaches the handler, run green. A write failure only fails the asset if the write's
    own error channel is read.
    """
    fn = _fn("sync_ontology_to_weaviate")
    names = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    consts = {c.value for c in ast.walk(fn)
              if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    assert "failed_objects" in names or "failed_objects" in consts, (
        "sync_ontology_to_weaviate never reads collection.batch.failed_objects, so a "
        "batch that rejects every row still reports a green materialisation"
    )
    assert any(isinstance(n, ast.Raise) for n in ast.walk(fn)), (
        "sync_ontology_to_weaviate raises nowhere -- reading failed_objects without "
        "failing on them is a log line with extra steps"
    )


def test_the_embed_fallback_STAYS_best_effort():
    """THE ANTI-WIDENING CONTROL. A degraded row is not a missing one: BM25 still answers
    a vector-less row and a backfill can populate it later. If this ever starts raising,
    a gateway blip turns every ingest red for a recoverable condition."""
    src = _SRC.read_text(encoding="utf-8")
    i = src.index("embed_document failed for")
    window = src[i - 400:i + 400]
    assert "cls_vector = None" in window, (
        "the embed_document fallback no longer writes the row without a vector -- "
        "Ruling 1 has been widened into the embed path, which it explicitly must not be"
    )


def test_write_collection_marker_STAYS_best_effort():
    """Metadata ABOUT the collection, not a row in it. Same category as the embed
    fallback and explicitly left alone by the ruling."""
    marker = (pathlib.Path(__file__).resolve().parents[1]
              / "doc_tools" / "utils" / "collection_marker.py").read_text(encoding="utf-8")
    assert "never raises" in marker.lower() or "best-effort" in marker.lower()


# ── RULING 2: the partition, and the reason attached to every exclusion ──────

_CLASSES = [
    {"uri": EX + "Pump", "label": "Pump", "definition": "A pump."},
    {"uri": EX + "Valve", "label": "Valve", "definition": ""},
    {"uri": PROV + "Bundle", "label": "Bundle", "definition": "PROV-O."},
    {"uri": MESH + "BurnRateSeries", "label": "Burn Rate Series", "definition": ""},
]
_SHAPES = {MESH + "BurnRateSeries"}


def test_every_declared_class_lands_in_exactly_one_bucket():
    to_write, exclusions = partition_ontology_classes(_CLASSES, _SHAPES)
    assert len(to_write) + len(exclusions) == len(_CLASSES)
    seen = {c["uri"] for c in to_write} | {e["uri"] for e in exclusions}
    assert seen == {c["uri"] for c in _CLASSES}


def test_every_exclusion_carries_its_REASON():
    """"Skip the ones we filter" loses the ability to tell a deliberate exclusion from a
    dropped row, which is the bug the seal exists to catch."""
    _, exclusions = partition_ontology_classes(_CLASSES, _SHAPES)
    by_uri = {e["uri"]: e["reason"] for e in exclusions}
    assert by_uri[PROV + "Bundle"] == EXCL_META
    assert by_uri[MESH + "BurnRateSeries"] == EXCL_SHAPE
    assert all(e["reason"] for e in exclusions)


def test_domain_nouns_are_WRITTEN():
    """THE NEGATIVE CONTROL: a partition that excluded everything would satisfy every
    assertion above."""
    to_write, _ = partition_ontology_classes(_CLASSES, _SHAPES)
    assert {c["uri"] for c in to_write} == {EX + "Pump", EX + "Valve"}


def test_the_reconciliation_is_ASSERTED_not_assumed():
    """An ``else`` branch that silently grows a third outcome is how a partition stops
    being one. The function must refuse rather than return a short list."""
    fn = _fn("partition_ontology_classes")
    assert any(isinstance(n, ast.Raise) for n in ast.walk(fn)), (
        "partition_ontology_classes cannot refuse a non-reconciling split"
    )


def test_the_seal_reads_back_by_the_SAME_uuid_the_write_used():
    """A count-shaped check passes on the run that wrote the right NUMBER of the wrong
    rows. The seal has to ask the store the same question the write answered."""
    fn = _fn("seal_declared_classes_are_rows")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "generate_uuid5" in called, (
        "the row seal does not look rows up by the deterministic UUID the write used"
    )
    assert any(isinstance(n, ast.Raise) for n in ast.walk(fn))


def test_doc_tools_holds_NO_copy_of_the_manifest():
    """THE TWO-MASTERS GUARD, and the one the dispatch was most emphatic about.

    A seal here derived from a list there is complete on its own side and blind to the
    entry that exists in only one master -- and a copy makes that drift invisible to BOTH
    repos. The basis is the run's own record instead; this asserts nobody later "fixed"
    that by pasting the list in.
    """
    hits = []
    for path in (pathlib.Path(__file__).resolve().parents[1] / "doc_tools").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "CANONICAL_TTL_MANIFEST" in text and "prime_databases" not in text:
            hits.append(path.name)
    assert not hits, (
        f"a copy of CANONICAL_TTL_MANIFEST has appeared in doc-tools: {hits}. "
        f"That mints a second master and the drift becomes invisible to both repos. "
        f"The seal is derived from the ingest run's own record on purpose."
    )


# ── RULING 3: per domain, per manifest entry ─────────────────────────────────

from doc_tools.utils.ontology_readiness import (  # noqa: E402
    ontology_ingest_posture,
    format_posture,
    STATE_ABSENT,
    STATE_EXCLUDED,
    STATE_INGESTED,
    STATE_UNATTRIBUTED,
)

_DECLARED = {
    "maintenance/IOF_Core.rdf": "MAINTENANCE",
    "maintenance/mro_extension.ttl": "MAINTENANCE",
    "sustainment/safety_extension.ttl": "SUSTAINMENT",
}


def test_a_domain_with_one_good_entry_and_one_absent_is_NOT_ready():
    """THE WHOLE RULING. MAINTENANCE has six manifest entries; a per-DOMAIN check is
    green as soon as one lands, which is the same store-liveness defect one level in."""
    postures = ontology_ingest_posture(
        declared=_DECLARED,
        rows_by_source={"maintenance/IOF_Core.rdf": 400,
                        "sustainment/safety_extension.ttl": 12},
    )
    maintenance = next(p for p in postures if p.domain == "MAINTENANCE")
    assert maintenance.rows == 400, "the domain HAS rows -- that is the trap"
    assert not maintenance.ready
    assert [e.s3_key for e in maintenance.not_ready] == ["maintenance/mro_extension.ttl"]
    assert maintenance.entries[1].state == STATE_ABSENT


def test_a_fully_ingested_domain_IS_ready():
    """POSITIVE CONTROL. A sentinel that is never green is not a sentinel."""
    postures = ontology_ingest_posture(
        declared=_DECLARED,
        rows_by_source={k: 5 for k in _DECLARED},
    )
    assert all(p.ready for p in postures)
    assert all(e.state == STATE_INGESTED for p in postures for e in p.entries)


def test_a_domain_that_ingested_NOTHING_is_still_enumerated():
    """THE CIRCULARITY GUARD, and the reason the expectation comes off the bucket rather
    than out of the store. Derived from Weaviate's own distinct domains, a domain with
    zero rows contributes no rows, so it is not in the list, so it is never checked, and
    the sentinel is green exactly when it should not be."""
    postures = ontology_ingest_posture(declared=_DECLARED, rows_by_source={})
    assert {p.domain for p in postures} == {"MAINTENANCE", "SUSTAINMENT"}
    assert not any(p.ready for p in postures)


def test_an_excluded_entry_is_not_reported_as_a_failure():
    """A class-less policy/rules TTL, or one whose every class is meta-ontology, CORRECTLY
    contributes zero rows. Calling that ABSENT trains readers to ignore the red."""
    postures = ontology_ingest_posture(
        declared=_DECLARED,
        rows_by_source={"maintenance/IOF_Core.rdf": 400,
                        "sustainment/safety_extension.ttl": 12},
        excluded_sources=frozenset({"maintenance/mro_extension.ttl"}),
    )
    maintenance = next(p for p in postures if p.domain == "MAINTENANCE")
    assert maintenance.ready
    assert maintenance.entries[1].state == STATE_EXCLUDED


def test_unattributed_rows_are_NOT_green():
    """Rows written before source_ontology existed cannot be told apart. That is a
    measurement that could not be made, and reporting it as INGESTED would be the
    sentinel lying in exactly the direction it was built to stop lying in."""
    postures = ontology_ingest_posture(
        declared=_DECLARED,
        rows_by_source={},
        unattributed_rows_by_domain={"MAINTENANCE": 900},
    )
    maintenance = next(p for p in postures if p.domain == "MAINTENANCE")
    assert all(e.state == STATE_UNATTRIBUTED for e in maintenance.entries)
    assert not maintenance.ready
    sustainment = next(p for p in postures if p.domain == "SUSTAINMENT")
    assert all(e.state == STATE_ABSENT for e in sustainment.entries), (
        "an unattributed count in ONE domain leaked into another -- the states are "
        "per domain, not global"
    )


def test_the_report_names_every_entry_not_just_the_verdict():
    """A sentinel that prints only its verdict cannot be checked."""
    postures = ontology_ingest_posture(
        declared=_DECLARED,
        rows_by_source={"maintenance/IOF_Core.rdf": 400},
    )
    report = format_posture(postures)
    for key in _DECLARED:
        assert key in report
    assert STATE_ABSENT in report and STATE_INGESTED in report


def test_the_sentinel_asset_is_NOT_partitioned():
    """A per-partition readiness check cannot see the entry whose partition NEVER RAN,
    which is the blind spot the ruling exists to close."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    node = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "weaviate_ontology_readiness"), None)
    assert node is not None, "weaviate_ontology_readiness is gone -- renamed?"
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            kwargs = {k.arg for k in dec.keywords}
            assert "partitions_def" not in kwargs, (
                "the readiness sentinel has been partitioned. It then inherits the exact "
                "blind spot it exists to remove: an entry that never ran has no partition "
                "run to be absent in."
            )


def test_the_sentinel_RAISES_rather_than_warning():
    """A sentinel whose failure mode is a log line is the thing being replaced."""
    node = _fn("weaviate_ontology_readiness")
    assert any(isinstance(n, ast.Raise) for n in ast.walk(node))


def test_an_empty_bucket_is_a_FAILURE_not_a_vacuous_pass():
    """Nothing declared means every domain is vacuously ready, which is the most
    dangerous green there is."""
    assert ontology_ingest_posture(declared={}, rows_by_source={}) == ()
    src = _SRC.read_text(encoding="utf-8")
    assert "vacuously ready" in src, (
        "the asset no longer refuses an empty ontology bucket"
    )
