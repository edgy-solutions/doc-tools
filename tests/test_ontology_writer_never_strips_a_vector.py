"""The ontology writer must not ERASE a vector while trying to degrade a row.

THE DEFECT. `sync_ontology_to_weaviate` embeds each class and, on embed-gateway
failure, wrote the row anyway with no vector -- deliberately, as a best-effort
fallback ("BM25 still answers; a backfill can populate it later"). That reasoning
holds for a row that never had a vector. It is exactly inverted for a row that
did: `batch.add_object(uuid=...)` onto an existing id is a whole-object PUT in
weaviate-client 4.21.3, the same semantics as `data.replace`, so the row is
SUBSTITUTED and its stored vector is dropped. The deterministic uuid
(`generate_uuid5(uri)`) is what makes every re-ingest land on the existing row,
so the fallback was not writing a thinner row -- it was deleting a healthy one,
on every re-drive that hit a gateway blip.

WHY IT WAS UNDETECTABLE AFTERWARDS, which is what makes it a loss rather than a
degradation. A row whose vector was erased reads as present, correct, and merely
unvectorised -- indistinguishable from a row that arrived that way. A backfill can
populate a vector that was never written; nothing can identify which vectors a
blip removed. The fix is therefore asymmetric on purpose: refuse the write when
there is a vector to lose, allow it when there is not.

REFUSE-AND-RECORD, NEVER REFUSE-AND-RAISE. The sibling fix in `_index_chunk`
(tests/test_index_chunk_identity.py) established the rule and the vocabulary:
a hard failure raised from inside a writer is swallowed by callers that wrap each
item in their own `except`, and the asset then materializes GREEN over zero rows.
So the refusal leaves by two doors that cannot be swallowed -- a warning log, and
a tally the function returns for the run's Dagster metadata.

HOW THIS DIFFERS FROM `_index_chunk`, deliberately. `_index_chunk` refuses on
`exists()` alone. This writer asks the further question "does the existing row
actually hold a vector", and refreshes it if not. That is not gold-plating: rows
written before the named-space fix (2026-09-19) legitimately carry no vector, they
are numerous, and an ontology class's label/definition is prompt text Engine O
reads at resolve time. Blanket-refusing on existence would freeze that text
forever on exactly the rows most in need of a re-ingest.

Loaded by AST, like the sibling ontology seals, so the file never imports the
`doc_tools` package.
"""
from __future__ import annotations

import ast
import pathlib
from unittest.mock import MagicMock

import pytest

_SRC = (pathlib.Path(__file__).resolve().parents[1]
        / "doc_tools" / "assets" / "ontology_assets.py")

EX = "http://example.com/ontology#"
GOOD = EX + "AaaGood"      # sorts first, so it is also the deterministic probe
BAD = EX + "ZzzBad"


def _load(*names: str) -> dict:
    """Exec named top-level nodes of the module in an isolated namespace."""
    import rdflib
    from weaviate.util import generate_uuid5

    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    ns: dict = {
        "rdflib": rdflib,
        "generate_uuid5": generate_uuid5,
        # Only needed so the `def` line evaluates; never called.
        "AssetExecutionContext": object,
    }
    wanted = set(names)
    for node in tree.body:
        got = None
        if isinstance(node, ast.FunctionDef):
            got = node.name
        elif isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            got = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            got = node.target.id
        if got in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(_SRC), "exec"), ns)
    missing = wanted - set(ns)
    assert not missing, f"could not load {missing} from {_SRC.name}"
    return ns


_verdict = _load("_vectorless_write_verdict")["_vectorless_write_verdict"]


def _ctx():
    ctx = MagicMock()
    ctx.log = MagicMock()
    return ctx


def _stored(vector):
    """A fetched object carrying `vector` (v4 returns a dict of named spaces)."""
    obj = MagicMock()
    obj.vector = vector
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# 1. THE DECISION. _vectorless_write_verdict, every branch.
# ─────────────────────────────────────────────────────────────────────────────

def test_no_row_yet_is_written_without_a_vector():
    """Nothing to lose: the best-effort fallback is exactly right here."""
    col = MagicMock()
    col.data.exists.return_value = False
    assert _verdict(col, "uuid-1", GOOD, _ctx()) == "written_without_vector"
    # Refused the round-trip it did not need.
    col.query.fetch_object_by_id.assert_not_called()


def test_an_existing_row_that_never_had_a_vector_is_REFRESHED_not_refused():
    """THE ANTI-OVERREACH CONTROL. The refusal is about LOSS, not about
    vectorlessness. Rows written before the named-space fix carry no vector and
    are numerous; refusing them would freeze their label/definition -- the text
    Engine O reads -- on precisely the rows a re-ingest exists to repair."""
    col = MagicMock()
    col.data.exists.return_value = True
    col.query.fetch_object_by_id.return_value = _stored({})
    assert _verdict(col, "uuid-1", GOOD, _ctx()) == "written_without_vector"


def test_an_existing_row_WITH_a_named_vector_is_refused():
    """The load-bearing case. This write would erase `default`."""
    col = MagicMock()
    col.data.exists.return_value = True
    col.query.fetch_object_by_id.return_value = _stored({"default": [0.1, 0.2]})
    assert _verdict(col, "uuid-1", GOOD, _ctx()) == "skipped_would_strip_vector"


def test_a_LEGACY_unnamed_vector_also_counts_as_a_vector_to_lose():
    """The live pool's rows carry their vector in the legacy unnamed slot until
    74's backfill runs (see tests/test_ontology_rows_are_retrievable.py). A guard
    that only recognised the named space would have happily erased every one of
    them -- the exact population the fix is for."""
    col = MagicMock()
    col.data.exists.return_value = True
    col.query.fetch_object_by_id.return_value = _stored([0.1, 0.2, 0.3])
    assert _verdict(col, "uuid-1", GOOD, _ctx()) == "skipped_would_strip_vector"


def test_a_row_that_vanished_between_the_two_reads_is_written():
    col = MagicMock()
    col.data.exists.return_value = True
    col.query.fetch_object_by_id.return_value = None
    assert _verdict(col, "uuid-1", GOOD, _ctx()) == "written_without_vector"


@pytest.mark.parametrize("failing", ["exists", "fetch"])
def test_a_store_we_cannot_interrogate_is_REFUSED_and_says_so(failing):
    """Both verdicts are wrong sometimes; they are not equally wrong. Refusing a
    row that needed writing leaves it stale but searchable, and the tally reports
    it. Writing a row that needed refusing destroys a vector silently. So an
    unreadable store resolves to the recoverable error, out loud."""
    col = MagicMock()
    if failing == "exists":
        col.data.exists.side_effect = RuntimeError("connection reset")
    else:
        col.data.exists.return_value = True
        col.query.fetch_object_by_id.side_effect = RuntimeError("connection reset")

    ctx = _ctx()
    assert _verdict(col, "uuid-1", GOOD, ctx) == "skipped_would_strip_vector"
    assert ctx.log.warning.called, "a refusal that logs nothing is a silent skip"
    assert "REFUSING" in " ".join(str(c) for c in ctx.log.warning.call_args_list)


# ─────────────────────────────────────────────────────────────────────────────
# 2. THE WIRING. sync_ontology_to_weaviate itself, exec-loaded with fakes.
#    A correct decision that the writer ignores is not a fix.
# ─────────────────────────────────────────────────────────────────────────────

def _run_writer(classes, embed, *, exists, stored_vector):
    """Call the real sync_ontology_to_weaviate against a fake Weaviate.

    `embed` maps uri -> vector, or raises. Returns (tally, add_object kwargs
    list, uris handed to the retrievability seal, ctx).
    """
    import sys
    import types

    from weaviate.util import generate_uuid5

    ns = _load(
        "sync_ontology_to_weaviate", "_vectorless_write_verdict",
        "partition_ontology_classes", "_is_meta_ontology_iri",
        "_META_ONTOLOGY_IRI_PREFIXES", "EXCLUSION_META_ONTOLOGY",
        "EXCLUSION_RESPONSE_SHAPE",
    )

    added: list[dict] = []
    batch = MagicMock()
    batch.add_object.side_effect = lambda **kw: added.append(kw)

    collection = MagicMock()
    collection.batch.dynamic.return_value.__enter__.return_value = batch
    collection.batch.failed_objects = []
    collection.data.exists.return_value = exists
    collection.query.fetch_object_by_id.return_value = (
        _stored(stored_vector) if stored_vector is not None else None
    )

    client = MagicMock()
    client.collections.exists.return_value = True      # skip the create path
    client.collections.get.return_value = collection

    probed: list[list[dict]] = []
    ns["get_weaviate_client"] = lambda: client
    ns["wvc"] = MagicMock()
    ns["write_collection_marker"] = MagicMock()
    ns["seal_declared_classes_are_rows"] = lambda c, rows, d, ctx: len(rows)
    ns["seal_a_written_row_is_RETRIEVABLE"] = (
        lambda c, to_write, d, ctx: (probed.append(list(to_write)),
                                     to_write[0]["uri"] if to_write else "")[1]
    )

    # The writer imports embed_document INSIDE the function body, so the stub has
    # to be a module in sys.modules rather than a namespace entry.
    fake = types.ModuleType("doc_tools.utils.embed")
    fake.embed_document = lambda text: embed(text)
    saved = {k: sys.modules.get(k) for k in
             ("doc_tools", "doc_tools.utils", "doc_tools.utils.embed")}
    try:
        sys.modules.setdefault("doc_tools", types.ModuleType("doc_tools"))
        sys.modules.setdefault("doc_tools.utils", types.ModuleType("doc_tools.utils"))
        sys.modules["doc_tools.utils.embed"] = fake
        ctx = _ctx()
        tally = ns["sync_ontology_to_weaviate"](classes, "mesh", ctx)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    by_uri = {kw["properties"]["uri"]: kw for kw in added}
    assert len(by_uri) == len(added), "a uri was written twice"
    _ = generate_uuid5  # imported for parity with the writer's identity scheme
    return tally, by_uri, [c["uri"] for c in (probed[0] if probed else [])], ctx


_CLASSES = [
    {"uri": GOOD, "label": "Aaa Good", "definition": "Embeds fine."},
    {"uri": BAD, "label": "Zzz Bad", "definition": "Embed will fail."},
]


def _embed_fails_for_bad(text):
    if "Zzz Bad" in text:
        raise RuntimeError("embedding gateway down")
    return [0.1] * 768


def test_the_writer_SKIPS_the_row_whose_vector_it_would_strip():
    """THE MUTATION CHECK for this commit. Restore the old unconditional
    `batch.add_object(**add_kwargs)` and this reds two ways: BAD appears in the
    written set, and it appears carrying no vector."""
    tally, by_uri, _probed, ctx = _run_writer(
        _CLASSES, _embed_fails_for_bad, exists=True, stored_vector={"default": [0.5] * 768},
    )

    assert BAD not in by_uri, (
        "the row whose embed failed was written anyway onto an existing "
        "vector-bearing uuid -- that is a whole-object PUT and the stored "
        "vector is now gone"
    )
    assert GOOD in by_uri and "vector" in by_uri[GOOD]
    assert tally == {
        "written": 1,
        "written_without_vector": 0,
        "skipped_would_strip_vector": 1,
        "declared": 2,
    }
    # RECORDED, not merely skipped.
    assert any("REFUSED" in str(c) for c in ctx.log.warning.call_args_list)


def test_the_writer_STILL_writes_a_vectorless_row_when_nothing_is_lost():
    """The best-effort fallback survives where it was always correct. If this
    reds, the fix has widened into the embed path, which Ruling 1 forbids."""
    tally, by_uri, _probed, _ctx = _run_writer(
        _CLASSES, _embed_fails_for_bad, exists=False, stored_vector=None,
    )

    assert BAD in by_uri, "a brand-new row was refused -- nothing was at risk"
    assert "vector" not in by_uri[BAD]
    assert "vector" in by_uri[GOOD]
    assert tally == {
        "written": 1,
        "written_without_vector": 1,
        "skipped_would_strip_vector": 0,
        "declared": 2,
    }


def test_the_healthy_path_pays_NOTHING_for_the_guard():
    """Two extra round-trips per class across 26,239 rows would be a real cost.
    The guard is consulted only when the embed already failed."""
    _tally, by_uri, _probed, _ctx = _run_writer(
        _CLASSES, lambda text: [0.1] * 768, exists=True, stored_vector={"default": [0.5]},
    )
    assert set(by_uri) == {GOOD, BAD}
    collection_calls = _tally  # keep the tally referenced for clarity
    assert collection_calls["written"] == 2
    assert collection_calls["skipped_would_strip_vector"] == 0


def test_the_healthy_path_makes_no_store_reads():
    """Separated from the tally assertion above so a regression names itself."""
    import sys, types
    from unittest.mock import MagicMock as MM

    ns = _load("sync_ontology_to_weaviate", "_vectorless_write_verdict",
               "partition_ontology_classes", "_is_meta_ontology_iri",
        "_META_ONTOLOGY_IRI_PREFIXES", "EXCLUSION_META_ONTOLOGY",
               "EXCLUSION_RESPONSE_SHAPE")
    collection = MM()
    collection.batch.dynamic.return_value.__enter__.return_value = MM()
    collection.batch.failed_objects = []
    client = MM()
    client.collections.exists.return_value = True
    client.collections.get.return_value = collection
    ns["get_weaviate_client"] = lambda: client
    ns["wvc"] = MM()
    ns["write_collection_marker"] = MM()
    ns["seal_declared_classes_are_rows"] = lambda c, rows, d, ctx: len(rows)
    ns["seal_a_written_row_is_RETRIEVABLE"] = lambda c, rows, d, ctx: ""

    fake = types.ModuleType("doc_tools.utils.embed")
    fake.embed_document = lambda text: [0.1] * 768
    saved = {k: sys.modules.get(k) for k in
             ("doc_tools", "doc_tools.utils", "doc_tools.utils.embed")}
    try:
        sys.modules.setdefault("doc_tools", types.ModuleType("doc_tools"))
        sys.modules.setdefault("doc_tools.utils", types.ModuleType("doc_tools.utils"))
        sys.modules["doc_tools.utils.embed"] = fake
        ns["sync_ontology_to_weaviate"](_CLASSES, "mesh", _ctx())
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    collection.data.exists.assert_not_called()
    collection.query.fetch_object_by_id.assert_not_called()


def test_the_retrievability_seal_is_given_only_rows_this_run_VECTORISED():
    """The seal skips itself when its probe row has no vector. Handing it the
    declared list would let it pick a refused or vectorless row and report green
    from a run whose every vectorised write it never checked."""
    _tally, _by_uri, probed, _ctx = _run_writer(
        _CLASSES, _embed_fails_for_bad, exists=True, stored_vector={"default": [0.5] * 768},
    )
    assert probed == [GOOD], (
        f"the retrievability seal was handed {probed}; a row that was refused or "
        f"written without a vector can only make it skip itself"
    )


def test_the_refusal_NEVER_raises():
    """Refuse-and-record, not refuse-and-raise. A raise here is swallowed by
    per-item `except` handlers upstream and the asset materializes green over an
    empty pool -- measured in `_index_chunk`'s callers. Total embed outage is the
    worst case: every row refused, and the run still returns its tally."""
    tally, by_uri, probed, ctx = _run_writer(
        _CLASSES, lambda text: (_ for _ in ()).throw(RuntimeError("total outage")),
        exists=True, stored_vector={"default": [0.5] * 768},
    )
    assert by_uri == {}
    assert tally["skipped_would_strip_vector"] == 2
    assert tally["written"] == 0
    assert probed == [], "nothing was vectorised, so there is nothing to probe"
    assert any("REFUSED" in str(c) for c in ctx.log.warning.call_args_list)


def test_the_tally_is_RETURNED_so_the_run_can_report_it():
    """A degradation only the logs know about is not reported. The asset puts
    these keys in its MaterializeResult metadata."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "sync_ontology_to_weaviate")
    assert any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(fn)), (
        "sync_ontology_to_weaviate returns nothing, so its caller cannot report "
        "the degraded counts in the run's metadata"
    )
    src = _SRC.read_text(encoding="utf-8")
    for key in ("rows_written_without_vector", "rows_refused_would_strip_vector"):
        assert key in src, f"{key} never reaches MaterializeResult.metadata"
