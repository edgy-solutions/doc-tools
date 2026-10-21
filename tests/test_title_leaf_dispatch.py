"""Step 5's dispatch: `IngestStatusResource.title_leaf` against Lane 1's route.

Every test here stubs `httpx.post`. Nothing reaches a network, and the
`_FakeResponse` carries a `.json()` because unlike `/stage` this route's
ANSWER is the point — a stage write is observability, a `title_leaf` answer
gates whether parts extraction runs at all.

The contract under test is `sessions/2026-10-21-packet-to-7f-the-final-shape-
your-lifted-read-against-title-leaf-and-the-relaunch-runs-as-the-leaf.md` §2
and its mapping table, plus the dispatch packet's answer table.

THE DISTINCTION MOST OF THESE TESTS EXIST FOR is `asked` vs `proceed`. "Lane 1
held this document" and "I could not ask Lane 1" are the same silence and
opposite consequences: the first must stop extraction, the second must behave
exactly as the pre-204 code did and let Lane 1's 300 s manifest-leaf backstop
cover the run. A 422 read as a hold strands a document on my own bad body; a
hold read as a failure extracts parts as a kind nobody granted.
"""

import httpx
import pytest

from doc_tools.utils import dagster_resources
from doc_tools.utils import mesh_identity
from doc_tools.utils.dagster_resources import IngestStatusResource

CANON_INGEST_ID = "sha256:" + "cd" * 32
FAKE_TOKEN_HEADERS = {"Authorization": "Bearer test-mesh-token"}

#: A candidate in the ruled shape: `{leaf, score, evidence_ref}` with the
#: evidence_ref the 202 struct `{page, bbox, note?}`.
CAND_PCN = {"leaf": "pcn", "score": 0.9,
            "evidence_ref": {"page": 1, "bbox": [0.1, 0.1, 0.5, 0.2]}}
CAND_PDN = {"leaf": "pdn", "score": 0.3,
            "evidence_ref": {"page": 1, "bbox": [0.1, 0.3, 0.5, 0.4]}}
#: The ruled-but-unreadable one: a page, no box. The architect made this legal
#: on 2026-10-21; Lane 1's 204 still 422s it, and fails the WHOLE call for it.
CAND_BOXLESS = {"leaf": "pdn", "score": 0.3,
                "evidence_ref": {"page": 2, "bbox": None,
                                 "note": "no page dimensions"}}


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "",
                 raise_on_json=False):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("not json")
        return self._payload


class _FakePost:
    def __init__(self, response=None, exc=None):
        self.response = response if response is not None else _FakeResponse(200, {})
        self.exc = exc
        self.calls = []

    def __call__(self, url, *, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers,
                           "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return self.response


def _authed(monkeypatch, headers=FAKE_TOKEN_HEADERS):
    monkeypatch.setattr(mesh_identity, "stage_auth_headers", lambda: headers)


def _post(monkeypatch, response=None, exc=None):
    fake = _FakePost(response=response, exc=exc)
    monkeypatch.setattr(httpx, "post", fake)
    return fake


def _call(**kw):
    kw.setdefault("doc_type", "pcn")
    kw.setdefault("doc_type_source", "title")
    return IngestStatusResource().title_leaf(CANON_INGEST_ID, **kw)


# --------------------------------------------------------------------------- #
# The body. An extra key is a 422, so the body is pinned EXACTLY.
# --------------------------------------------------------------------------- #
def test_the_body_carries_exactly_the_four_contract_keys(monkeypatch):
    _authed(monkeypatch)
    post = _post(monkeypatch, _FakeResponse(200, {"proceed": False}))

    _call(candidates=[CAND_PCN], run_id="run-abc")

    call = post.calls[0]
    assert call["url"] == (
        f"http://iagent-cortex-bff:8090/ingest/{CANON_INGEST_ID}/title_leaf")
    assert call["headers"] == FAKE_TOKEN_HEADERS
    assert call["timeout"] == dagster_resources._TITLE_LEAF_TIMEOUT_S
    assert set(call["json"]) == {"doc_type", "doc_type_source", "candidates",
                                 "run_id"}


def test_the_manifest_blocks_other_keys_never_reach_the_wire(monkeypatch):
    """`leaf_source`, `outcome` and a top-level `evidence_ref` are 422s.

    *"leaf_source is the BFF's to write. You send none."* And the route has no
    slot for a confident read's evidence. The method takes no such argument,
    so this test pins the SIGNATURE as much as the body — the way these keys
    would arrive is somebody passing the manifest block through whole.
    """
    _authed(monkeypatch)
    post = _post(monkeypatch, _FakeResponse(200, {"proceed": False}))

    _call(candidates=[CAND_PCN])

    body = post.calls[0]["json"]
    for forbidden in ("leaf_source", "outcome", "evidence_ref", "leaf",
                      "stage", "content_kind"):
        assert forbidden not in body


def test_doc_type_and_source_go_out_UNCHANGED(monkeypatch):
    """*"Do not decide confidence yourself."*

    A `title-ambiguous` read is sent as `title-ambiguous`. Nothing here
    promotes it, and nothing re-cases the doc_type — their rule lowercases it
    themselves, so `pcn` and `PCN` both work and neither is rewritten.
    """
    _authed(monkeypatch)
    post = _post(monkeypatch, _FakeResponse(200, {"proceed": False}))

    _call(doc_type=None, doc_type_source="title-ambiguous",
          candidates=[CAND_PCN, CAND_PDN])

    body = post.calls[0]["json"]
    assert body["doc_type"] is None
    assert body["doc_type_source"] == "title-ambiguous"


def test_run_id_is_omitted_rather_than_nulled_when_absent(monkeypatch):
    _authed(monkeypatch)
    post = _post(monkeypatch, _FakeResponse(200, {"proceed": False}))

    _call(candidates=None, run_id=None)

    body = post.calls[0]["json"]
    assert "run_id" not in body
    assert "candidates" not in body


# --------------------------------------------------------------------------- #
# The boxless candidate. Theirs: "leave it out; if none remain, send []".
# --------------------------------------------------------------------------- #
def test_a_candidate_with_no_box_is_LEFT_OUT_not_sent(monkeypatch):
    """One boxless candidate fails the WHOLE call at 204, so it costs the
    document's answer rather than one row of a picker."""
    _authed(monkeypatch)
    post = _post(monkeypatch, _FakeResponse(200, {"proceed": False}))

    _call(candidates=[CAND_PCN, CAND_BOXLESS])

    assert post.calls[0]["json"]["candidates"] == [CAND_PCN]


def test_all_candidates_boxless_sends_an_EMPTY_LIST_and_still_calls(monkeypatch):
    """*"If none remain, send `candidates: []`."* The call still has to be
    made: the row holds at `awaiting_kind` and cortex offers a plain PCN/PDN
    picker, which only happens if Lane 1 hears about the document at all."""
    _authed(monkeypatch)
    post = _post(monkeypatch, _FakeResponse(200, {"proceed": False,
                                                  "stage": "awaiting_kind"}))

    answer = _call(candidates=[CAND_BOXLESS])

    assert len(post.calls) == 1
    assert post.calls[0]["json"]["candidates"] == []
    assert answer.held is True


def test_the_filter_is_the_only_narrowing_and_keeps_order_and_scores(monkeypatch):
    """The BFF sorts by score itself, but the producer already emits best
    first and nothing here reorders or rescores — a second ordering rule is
    how two sides come to disagree about which candidate was best."""
    _authed(monkeypatch)
    post = _post(monkeypatch, _FakeResponse(200, {"proceed": False}))

    _call(candidates=[CAND_PCN, CAND_PDN])

    assert post.calls[0]["json"]["candidates"] == [CAND_PCN, CAND_PDN]


def test_a_non_dict_candidate_is_dropped_rather_than_sent(monkeypatch):
    """The earlier dispatch packet spelled candidates as bare strings
    (`["pcn", "pdn"]`); the final shape made them objects. A string reaching
    this function is that older shape, and it is a 422 ("a string is a
    422"), so it is dropped rather than forwarded."""
    _authed(monkeypatch)
    post = _post(monkeypatch, _FakeResponse(200, {"proceed": False}))

    _call(candidates=["pcn", CAND_PCN])

    assert post.calls[0]["json"]["candidates"] == [CAND_PCN]


# --------------------------------------------------------------------------- #
# The answer table.
# --------------------------------------------------------------------------- #
def test_proceed_true_with_a_content_kind_is_a_grant(monkeypatch):
    _authed(monkeypatch)
    _post(monkeypatch, _FakeResponse(200, {
        "ingest_id": CANON_INGEST_ID, "proceed": True, "stage": "extracting",
        "content_kind": "pdn", "leaf": "pdn", "leaf_source": "declared",
        "leaf_candidates": []}))

    answer = _call()

    assert (answer.asked, answer.proceed) == (True, True)
    assert answer.content_kind == "pdn"
    assert answer.leaf_source == "declared"
    assert answer.held is False
    assert answer.stop is False


def test_proceed_false_is_a_HOLD_and_names_the_stage(monkeypatch):
    _authed(monkeypatch)
    _post(monkeypatch, _FakeResponse(200, {
        "ingest_id": CANON_INGEST_ID, "proceed": False,
        "stage": "awaiting_kind", "content_kind": None, "leaf": None,
        "leaf_candidates": ["pcn", "pdn"]}))

    answer = _call(doc_type=None, doc_type_source="no-title-evidence")

    assert answer.asked is True
    assert answer.held is True
    assert answer.stage == "awaiting_kind"
    assert answer.stop is False


@pytest.mark.parametrize("truthy_but_not_true", ["true", 1, "yes", {}, None])
def test_only_a_LITERAL_true_opens_the_gate(monkeypatch, truthy_but_not_true):
    """`is True`, deliberately.

    A missing `proceed`, a null one, or a truthy string must not run parts
    extraction. The only thing that opens this gate is Lane 1 saying so, and
    a JSON `"true"` from some future serializer change would otherwise grant
    every document silently.
    """
    _authed(monkeypatch)
    _post(monkeypatch, _FakeResponse(200, {"proceed": truthy_but_not_true,
                                            "content_kind": "pcn"}))

    answer = _call()

    assert answer.proceed is False
    assert answer.held is True


def test_a_200_with_no_proceed_key_at_all_holds(monkeypatch):
    _authed(monkeypatch)
    _post(monkeypatch, _FakeResponse(200, {"ingest_id": CANON_INGEST_ID}))

    answer = _call()

    assert (answer.asked, answer.proceed, answer.held) == (True, False, True)


# --------------------------------------------------------------------------- #
# ASKED vs PROCEED — the distinction the whole module exists for.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code", [404, 409])
def test_lane1s_stop_codes_are_an_ANSWER_and_stop_the_run(monkeypatch, code):
    """409 `not_extracting` and 404 `ingest_not_found` say something about the
    ROW: it moved on, or it never existed. Their rule is stop, and post no
    further stages — so these are `asked=True` (the caller must not extract)
    AND `stop=True` (it must not post either)."""
    _authed(monkeypatch)
    _post(monkeypatch, _FakeResponse(code, text='{"detail":"not_extracting"}'))

    answer = _call()

    assert answer.asked is True
    assert answer.held is True
    assert answer.stop is True


@pytest.mark.parametrize("code", [400, 403, 422, 500, 502])
def test_every_other_non_2xx_is_NOT_a_hold(monkeypatch, code):
    """A 422 is about my BODY. A 403 is about my token. A 500 is about their
    gateway. None of them says the document is held, and reading them as a
    hold would park a document for a person to fix on the strength of my own
    bad request. They fall through to the pre-204 behaviour instead."""
    _authed(monkeypatch)
    _post(monkeypatch, _FakeResponse(code, text="nope"))

    answer = _call()

    assert answer.asked is False
    assert answer.proceed is False
    assert answer.stop is False


def test_a_transport_exception_is_not_a_hold_and_never_raises(monkeypatch):
    _authed(monkeypatch)
    _post(monkeypatch, exc=httpx.ConnectError("no route to host"))

    answer = _call()

    assert answer.asked is False
    assert answer.content_kind is None


def test_a_2xx_body_that_is_not_readable_is_not_an_answer(monkeypatch):
    _authed(monkeypatch)
    _post(monkeypatch, _FakeResponse(200, raise_on_json=True))

    assert _call().asked is False


def test_a_2xx_body_that_is_not_an_object_is_not_an_answer(monkeypatch):
    _authed(monkeypatch)
    _post(monkeypatch, _FakeResponse(200, payload=["pcn"]))

    assert _call().asked is False


def test_no_token_means_no_post_at_all(monkeypatch):
    """The route 403s `not_doc_tools` without the `svc:doc-tools` token, so
    sending it buys a log line and the same fallthrough."""
    _authed(monkeypatch, headers=None)
    post = _post(monkeypatch)

    answer = _call()

    assert post.calls == []
    assert answer.asked is False


@pytest.mark.parametrize("bad_id", [None, "", "inbound/adi_run3", "not-a-sha"])
def test_an_unusable_ingest_id_does_not_raise_and_does_not_post(monkeypatch, bad_id):
    """`update()` lets `canonical_ingest_id` raise, and should. Here it must
    not: a manifest `doc_id` can be a path fragment, and failing the run over
    an unusable id would turn "I could not ask about the leaf" into a failed
    extraction — strictly worse than the pre-204 behaviour this falls back to.
    """
    _authed(monkeypatch)
    post = _post(monkeypatch)

    answer = IngestStatusResource().title_leaf(
        bad_id, doc_type="pcn", doc_type_source="title")

    assert post.calls == []
    assert answer.asked is False


# --------------------------------------------------------------------------- #
# The gate's projection: `_ask_lane1_for_the_leaf(context, manifest)`.
# --------------------------------------------------------------------------- #
class _FakeLog:
    def __init__(self):
        self.lines = []

    def _rec(self, msg, *a):
        self.lines.append(str(msg) % a if a else str(msg))

    info = warning = error = _rec


class _FakeContext:
    def __init__(self, run_id="run-xyz"):
        self.log = _FakeLog()
        self.run_id = run_id


LEAF_BLOCK_CONFIDENT = {
    "leaf": "pcn", "leaf_source": "title", "outcome": "title",
    "evidence_ref": {"page": 1, "bbox": [0.1, 0.1, 0.5, 0.2],
                     "element_id": "el_3", "text": "PRODUCT CHANGE NOTICE"},
    "candidates": [],
}
LEAF_BLOCK_AMBIGUOUS = {
    "leaf": None, "leaf_source": None, "outcome": "title-ambiguous",
    "evidence_ref": None, "candidates": [CAND_PCN, CAND_PDN],
}


def _ask(manifest, monkeypatch, response=None):
    from doc_tools.assets import semantic_assets

    _authed(monkeypatch)
    post = _post(monkeypatch, response or _FakeResponse(200, {"proceed": False}))
    ctx = _FakeContext()
    answer = semantic_assets._ask_lane1_for_the_leaf(ctx, manifest)
    return answer, post, ctx


def test_the_gate_projects_the_leaf_block_onto_the_four_wire_keys(monkeypatch):
    """`leaf` -> `doc_type`, `outcome` -> `doc_type_source`, and NOTHING else
    from the block crosses. The manifest block carries `leaf_source` and a
    rich `evidence_ref` with `element_id` and `text`; each is an extra key and
    therefore a 422, and the way they would arrive is somebody passing the
    block through whole."""
    _, post, _ = _ask(
        {"doc_id": "PCN24_029", "ingest_id": CANON_INGEST_ID,
         "leaf": LEAF_BLOCK_CONFIDENT}, monkeypatch)

    body = post.calls[0]["json"]
    assert body["doc_type"] == "pcn"
    assert body["doc_type_source"] == "title"
    assert body["run_id"] == "run-xyz"
    assert set(body) == {"doc_type", "doc_type_source", "candidates", "run_id"}


def test_an_ambiguous_read_sends_its_candidates_and_a_null_doc_type(monkeypatch):
    _, post, _ = _ask(
        {"doc_id": "x", "ingest_id": CANON_INGEST_ID,
         "leaf": LEAF_BLOCK_AMBIGUOUS}, monkeypatch)

    body = post.calls[0]["json"]
    assert body["doc_type"] is None
    assert body["doc_type_source"] == "title-ambiguous"
    assert body["candidates"] == [CAND_PCN, CAND_PDN]


def test_no_ingest_id_asks_NOTHING(monkeypatch):
    """The vetted `sustainment/inbound/` path has no ingest_id and no Lane 1
    row to address — the same rule the `review` post already follows."""
    answer, post, ctx = _ask(
        {"doc_id": "x", "leaf": LEAF_BLOCK_CONFIDENT}, monkeypatch)

    assert answer is None
    assert post.calls == []


def test_no_leaf_block_asks_NOTHING(monkeypatch):
    """Every image built before the leaf work writes no `leaf` block at all
    (measured: 0 occurrences on `origin/main`). Such a run must reach the
    origin-unresolved return exactly as it does today."""
    answer, post, _ = _ask(
        {"doc_id": "x", "ingest_id": CANON_INGEST_ID}, monkeypatch)

    assert answer is None
    assert post.calls == []


def test_a_half_written_leaf_block_asks_nothing(monkeypatch):
    """`resolve_leaf` failing leaves no block, by design — but a non-dict in
    that slot is not a block either, and `.get()` on it would raise inside the
    gate."""
    answer, post, _ = _ask(
        {"doc_id": "x", "ingest_id": CANON_INGEST_ID, "leaf": "pcn"},
        monkeypatch)

    assert answer is None
    assert post.calls == []


# --------------------------------------------------------------------------- #
# The gate's STRUCTURE. Source-read, in the style of
# `tests/test_ingest_id_and_domain_ruling.py`, because the three branches live
# inside `_build_knowledge_graph_impl` and executing it needs Neo4j, Weaviate
# and a plugin — none of which has anything to do with what is pinned here.
# --------------------------------------------------------------------------- #
def _impl_source():
    import inspect

    from doc_tools.assets import semantic_assets

    return inspect.getsource(semantic_assets._build_knowledge_graph_impl)


def _code_only(src: str) -> str:
    """The source with comment LINES dropped.

    The same trap `tests/test_ingest_id_and_domain_ruling.py` documents at
    length, and it caught this suite on its first run: the comments in the
    step-5 block necessarily quote what these tests pin ("nothing raises,
    nothing posts"), so a naive substring check reads the explanation instead
    of the code and fails on prose. Line-wise is enough here -- the block
    holds no docstring, and dropping whole comment lines keeps the ordering
    the other assertions read.
    """
    return chr(10).join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )


def test_the_dispatch_is_a_SEPARATE_if_before_the_origin_unresolved_one():
    """The whole safety argument for step 5 rests on this shape.

    The dispatch tests `kind_entry.domain_type is None`, may REASSIGN
    `kind_entry` to a domain-declaring kind, and is followed by the original
    branch testing the same condition again. So:

      * a grant makes the second test False and the run continues into the
        ordinary domain path;
      * a hold returns from the first block;
      * and a call that could not be made leaves `kind_entry` untouched, so
        the second block runs THE SAME CODE a pre-204 image ran.

    That last one is why this is two `if`s and not an edit inside one. If
    someone merges them, the fallthrough stops being the original code and
    starts being a re-implementation of it, which is exactly the kind of
    change that passes every test and alters what a gateway outage does to a
    live drop.
    """
    src = _code_only(_impl_source())
    gate = "if kind_entry is not None and kind_entry.domain_type is None:"
    assert src.count(gate) == 2, (
        "step 5's dispatch and the origin-unresolved return must be two "
        "separate `if`s on the same condition — see this test's docstring"
    )
    first, second = src.index(gate), src.rindex(gate)
    assert src.index("_ask_lane1_for_the_leaf") > first
    assert src.index("_ask_lane1_for_the_leaf") < second
    assert src.index('"status": "origin_unresolved"') > second


def test_a_grant_is_honoured_only_through_the_REGISTRY():
    """*"The allowed leaves are the content-kind registry's domain-declaring
    kinds, read from the registry, never a literal list."*

    So the grant is looked up in `KIND_MAPPING` and checked for a declared
    domain before it is adopted. A literal `("pcn", "pdn")` here would be the
    hand-widening the ruling forbids, and it would also silently accept a
    grant this registry cannot select a plugin for.
    """
    src = _code_only(_impl_source())
    head = src[src.index("_ask_lane1_for_the_leaf"):src.rindex(
        "if kind_entry is not None and kind_entry.domain_type is None:")]
    assert "KIND_MAPPING.get(leaf_answer.content_kind)" in head
    assert "granted.domain_type" in head
    assert '"pcn"' not in head and "'pcn'" not in head


def test_the_hold_posts_no_stage_and_returns_rather_than_raising():
    """Lane 1's rule, verbatim: *"Stop before parts extraction. End the run
    SUCCESS. Post no `review` and no `failed`."* A raise here would mark the
    run failed and, through the wrapper, stamp `failed` on a row that is
    correctly parked for the dropper's picker."""
    src = _code_only(_impl_source())
    head = src[src.index("_ask_lane1_for_the_leaf"):src.rindex(
        "if kind_entry is not None and kind_entry.domain_type is None:")]
    assert '"post_no_further_stages": True' in head
    assert "raise" not in head
    assert ".update(" not in head


def test_the_run_id_prefers_the_accessor_dagster_has_not_deprecated(monkeypatch):
    """`context.run_id` warns today and is slated for removal. When it goes, a
    bare `getattr` would send `run_id: None` silently — and `run_id` is what
    Lane 1 correlates a held row against in their log, so losing it would show
    up as an unexplained gap on their side, not an error on mine."""
    from doc_tools.assets import semantic_assets

    class _Run:
        run_id = "run-from-context-dot-run"

    ctx = _FakeContext(run_id="run-from-the-deprecated-attribute")
    ctx.run = _Run()
    assert semantic_assets._dagster_run_id(ctx) == "run-from-context-dot-run"

    # And the fallback still works for a context that has only the old one.
    assert semantic_assets._dagster_run_id(_FakeContext(run_id="old")) == "old"
