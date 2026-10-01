"""PRODUCTION WIRING for the second witness -- the witness is actually built at runtime.

`tests/test_text_layer_second_witness.py` proves the DETECTOR and the CONSULTATION logic:
handed a hand-built `witness_index`, does `refuse_unsourced_header_values` do the right
thing with it? That file never calls `_transcribe_pages_witness` and never exercises
`_extract_fulltext`'s decision about whether to build one at all -- it assumes the witness
already exists. This file is the other half: does the PLUGIN actually build that witness,
on demand, only when it is needed, calling the real BAML function with the real per-page
fetch -- or does it just have the machinery lying around unwired?

No network, no real LLM: `sync_client.b` is monkeypatched with a fake that records what it
was called with, and the S3 client is a fake that hands back a fixed PNG payload. What is
under test is the WIRING -- call count, call ordering, which records reach the witness,
and the gate that decides whether any of this runs at all -- not BAML's own request/response
handling.

THE SAME FIXTURE AS THE OTHER FILE, copied rather than imported, for the same reason that
file gives for copying it from nowhere: `_strip_ti` deletes exactly what TYC's broken font
deletes, so the healthy and degraded elements here are the same prose in two states from
one source, and a wiring test that passes cannot be passing because a hand-tuned fixture
happened to cooperate.

ONE MORE TEST HERE THAT NEITHER FILE HAD: 520 green tests said nothing about the text the
model actually receives, and that is exactly how the TranscribePage prompt shipped with a
dangling `### OUTPUT FORMAT ###` heading over an empty string (`ctx.output_format` renders
to nothing for a bare `-> string` return type -- there are no fields to describe). A
monkeypatched `b.TranscribePage` cannot catch that; it never looks at the rendered prompt at
all. So `test_the_transcribe_page_request_has_no_dangling_output_format_heading` builds the
REAL BAML request (via `b.request.TranscribePage`, never sent) and asserts on the rendered
message text directly.
"""
import base64
import json
from types import SimpleNamespace

import pytest

from doc_tools.plugins.sustainment import SustainmentPlugin


# --------------------------------------------------------------------------- #
# the control document, in both states -- copied from
# tests/test_text_layer_second_witness.py; see that file's module docstring for why a
# shared source rather than two hand-written fixtures is the point.
# --------------------------------------------------------------------------- #
_CONTROL_PARAGRAPHS = [
    "Product Change Notification",
    "TE Connectivity",
    "This notification informs customers that the identified parts are transitioning to "
    "a new manufacturing site. The qualification testing is complete and the "
    "certification report is available on request.",
    "Customers with further questions about this notification should contact their TE "
    "Connectivity field sales engineer, who will gather the information and coordinate "
    "the transition with the operations team.",
    "There is no change to the form, fit or function of the affected parts. The "
    "estimated date of the first shipment from the new location is stated in the "
    "attached schedule, together with the last time buy instructions.",
]


def _strip_ti(text):
    """Exactly what TYC's broken font mapping does: delete every `ti`."""
    return text.replace("ti", "")


def _el(text, page=1, etype="NarrativeText"):
    return {"type": etype, "text": text,
            "metadata": {"page_number": page,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792}}}


def _healthy_elements():
    return [_el(p, etype="Title" if i < 2 else "NarrativeText")
            for i, p in enumerate(_CONTROL_PARAGRAPHS)]


def _degraded_elements():
    return [_el(_strip_ti(p), etype="Title" if i < 2 else "NarrativeText")
            for i, p in enumerate(_CONTROL_PARAGRAPHS)]


def _full_text(healthy=True):
    paras = _CONTROL_PARAGRAPHS if healthy else [_strip_ti(p) for p in _CONTROL_PARAGRAPHS]
    return " ".join(paras)


def _manifest(n_pages):
    """One `pages` entry per page, shaped like `document_parser.py` actually produces it
    (`page`, `s3_url`, `basename`, `width`, `height`, `dpi`). No `source_key`, so tier 1's
    text-layer pass (`_extract_parts_text_layer`) short-circuits to `([], stats)` before it
    ever tries to import pdfplumber -- these fixtures have no Table elements and no real
    PDF behind them, and tier 1 is not what this file is testing."""
    return {"pages": [
        {"page": n, "s3_url": f"s3://notices/doc-1/page{n}.png",
         "basename": f"page{n}.png", "width": 612, "height": 792, "dpi": 150}
        for n in range(1, n_pages + 1)
    ]}


def _header(mfr="TE Connectivity", mfr_source="TE Connectivity"):
    """Duck-typed BAML NoticeHeader -- `header_to_dict` reads it via `getattr`, so a plain
    SimpleNamespace with the same field names is indistinguishable from the real model."""
    return SimpleNamespace(
        doc_id="PCN-TEST-001", doc_type="PCN", revision=None,
        pub_date=None, pub_date_source=None,
        mfr=mfr, mfr_source=mfr_source, categories=[], summary=None,
        doc_level_ltb_date=None, doc_level_ltb_date_source=None,
    )


def _page_png(width=1224, height=1584):
    """A blank render the size of a real page raster, at 2x the fixtures' layout space.

    It used to be a hardcoded 1x1 PNG, which was enough while the only consumer was
    `_fetch_image_b64` -- the whole-page witness fetches the bytes and hands them
    straight to the model, and a monkeypatched `TranscribePage` never looks at them.
    The REGION witness does look: `witness_regions.region_pixel_box` scales the text
    layer's box by `img_h / layout_height` and REFUSES when the two rasters disagree
    about the page's shape, so a 1x1 stand-in is not a neutral placeholder here -- it
    is a page whose aspect ratio contradicts the layout, and it correctly produces no
    crop at all. Any multiple of the layout's 612x792 works; 2x is small enough to
    build per test and large enough that the crop clears the degenerate-box floor."""
    from io import BytesIO
    from PIL import Image as PILImage
    buf = BytesIO()
    PILImage.new("RGB", (width, height), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


class _FakeS3:
    """Hands back a blank page-sized PNG for any `s3://...` key the witnesses ask for,
    and records every key it was asked for -- enough to prove a fetch actually happened
    per page, without a real MinIO.

    `size=(1, 1)` is available deliberately, to drive the shape-disagreement refusal
    that `region_pixel_box` exists for."""

    def __init__(self, size=(1224, 1584)):
        self.get_object_calls = []
        self._png = _page_png(*size)

    def get_object(self, Bucket, Key):
        self.get_object_calls.append(Key)
        return {"Body": SimpleNamespace(read=lambda: self._png)}


class _BamlTimeoutError(Exception):
    """Stands in for BAML's own timeout error, by NAME. See `_FakeB.RAISE_TIMEOUT`."""


class _FakeB:
    """Stands in for `doc_tools.baml_client.sync_client.b`. `ExtractHeader` returns a fixed
    header; `TranscribePage` pops one behavior per call, in call order.

    Call order is what makes this safe to use without threading a page number through the
    fake: `_transcribe_pages_witness` walks `manifest['pages']` in list order and (with
    `_FakeS3` always succeeding) calls `TranscribePage` exactly once per page in that same
    order -- so `transcribe_behaviors[i]` is page `i + 1`'s response.
    """
    RAISE = "__raise__"
    # A failure whose CLASS NAME says timeout. The retry in `_read_one_region`
    # discriminates on the name rather than on an imported type, so the fake has to
    # as well -- importing BAML's real error class here would couple these tests to a
    # vendored exception hierarchy to assert one branch.
    RAISE_TIMEOUT = "__raise_timeout__"

    def __init__(self, header=None, transcribe_behaviors=None, region_behaviors=None):
        self.header = header
        self.transcribe_calls = 0
        self.region_calls = 0
        self.region_instructions = []
        self._behaviors = list(transcribe_behaviors or [])
        self._region_behaviors = list(region_behaviors or [])

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        return self.header

    def TranscribePage(self, page_image, system_instructions, baml_options=None):
        self.transcribe_calls += 1
        behavior = self._behaviors.pop(0) if self._behaviors else ""
        if behavior == self.RAISE:
            raise RuntimeError("simulated vision failure")
        return behavior

    def ReadRegion(self, region_image, system_instructions, baml_options=None):
        """The region witness's call, counted SEPARATELY from TranscribePage.

        Both witnesses are built for a degraded document now, so one counter cannot
        stand for both: a regression that silently stopped cropping would still leave
        `transcribe_calls` at one per page and look healthy. The instructions are
        recorded too, because which region was asked is the whole content of the call
        -- the fake has no image to inspect."""
        self.region_calls += 1
        self.region_instructions.append(system_instructions)
        behavior = (self._region_behaviors.pop(0) if self._region_behaviors else "")
        if behavior == self.RAISE:
            raise RuntimeError("simulated vision failure")
        if behavior == self.RAISE_TIMEOUT:
            raise _BamlTimeoutError("simulated server-side timeout")
        return behavior


def _patch_b(monkeypatch, fake_b):
    # The plugin does `from doc_tools.baml_client.sync_client import b` as a LOCAL import
    # inside each method (`_extract_header`, `_transcribe_pages_witness`) -- that import
    # rebinds the local name to whatever `sync_client.b` currently is at call time, so
    # patching the module attribute here is picked up on the next call without needing to
    # patch every call site individually.
    from doc_tools.baml_client import sync_client as sync_client_module
    monkeypatch.setattr(sync_client_module, "b", fake_b)


@pytest.fixture(autouse=True)
def _prompt_source_file(monkeypatch):
    # Pin the canonical, git-committed prompt path (the production default) rather than
    # whatever a developer's shell happens to have set for PROMPT_SOURCE.
    monkeypatch.setenv("PROMPT_SOURCE", "file")


@pytest.fixture
def plugin():
    return SustainmentPlugin(domain_type="sustainment")


# --------------------------------------------------------------------------- #
# _transcribe_pages_witness in isolation -- the per-page mechanics.
# --------------------------------------------------------------------------- #

def test_short_circuits_return_empty_list_without_touching_transcribe_page(monkeypatch, plugin):
    """A witness call is a real vision round-trip (measured elsewhere at ~100s a page).
    The cheap gates that exist specifically to avoid paying for one -- no manifest, no
    pages, no VISION_LLM_BASE_URL -- have to be true dead ends: reaching `b.TranscribePage`
    at all and merely discarding the result would still cost the round-trip this method
    exists to avoid when it isn't warranted."""
    fake_b = _FakeB(transcribe_behaviors=["should never be used"])
    _patch_b(monkeypatch, fake_b)
    fake_s3 = _FakeS3()

    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    assert plugin._transcribe_pages_witness(None, fake_s3) == []
    assert plugin._transcribe_pages_witness({}, fake_s3) == []
    assert plugin._transcribe_pages_witness({"pages": []}, fake_s3) == []

    monkeypatch.delenv("VISION_LLM_BASE_URL", raising=False)
    assert plugin._transcribe_pages_witness(_manifest(2), fake_s3) == []

    assert fake_b.transcribe_calls == 0
    assert fake_s3.get_object_calls == []


def test_one_record_per_page_shaped_as_a_page_image_witness(monkeypatch, plugin):
    """The shape matters as much as the content. `region: "page_image"` is the third
    reading `provenance.build_positioned_index` never produces (it only ever emits
    "table" or "narrative", derived from an `unstructured` element type) -- it is how
    `refuse_unsourced_header_values` and `text_layer_health.uncorroborated_parts` tell a
    page-pixel witness apart from either half of the ordinary text layer. Get the tag
    wrong and the witness either gets treated as ordinary text-layer evidence (defeating
    the point: a broken text layer corroborating itself) or never gets consulted at all."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(transcribe_behaviors=["page one text", "page two text"])
    _patch_b(monkeypatch, fake_b)
    fake_s3 = _FakeS3()

    witness = plugin._transcribe_pages_witness(_manifest(2), fake_s3)

    assert fake_b.transcribe_calls == 2
    assert [w["page_number"] for w in witness] == [1, 2]
    assert [w["region"] for w in witness] == ["page_image", "page_image"]
    assert [w["element_id"] for w in witness] == ["page_ocr_1", "page_ocr_2"]
    assert [w["type"] for w in witness] == ["PageTranscription", "PageTranscription"]
    assert [w["text"] for w in witness] == ["page one text", "page two text"]
    assert all(w["bbox"] is None for w in witness)
    assert [w["page_width"] for w in witness] == [612, 612]
    assert [w["page_height"] for w in witness] == [792, 792]


def test_one_page_raising_does_not_lose_the_others_transcriptions(monkeypatch, plugin, capsys):
    """THE WHOLE POINT of a witness with more than one page: a witness exists to be there
    for the pages a run's own text layer failed on, so it has to survive losing a page of
    ITSELF too -- a vision timeout on page 2 of 3 must cost page 2's corroboration and
    nothing else, not the other two pages that transcribed fine. Written so it fails
    against a version that lets one page's exception propagate out of the loop, which
    would silently drop every later page's corroboration for a completely unrelated
    reason."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(transcribe_behaviors=["page one text", _FakeB.RAISE, "page three text"])
    _patch_b(monkeypatch, fake_b)
    fake_s3 = _FakeS3()

    witness = plugin._transcribe_pages_witness(_manifest(3), fake_s3)

    assert fake_b.transcribe_calls == 3
    assert [w["page_number"] for w in witness] == [1, 3]
    assert [w["text"] for w in witness] == ["page one text", "page three text"]
    captured = capsys.readouterr()
    assert "[SustainmentPlugin]" in captured.out
    assert "page 2" in captured.out


# --------------------------------------------------------------------------- #
# the gate in _extract_fulltext -- does the plugin actually build the witness only when
# the document earns one, and only then?
# --------------------------------------------------------------------------- #

def test_a_healthy_document_never_calls_transcribe_page(monkeypatch, plugin):
    """The gating decision lives in `_extract_fulltext`, not in `_transcribe_pages_witness`
    itself (see that method's own docstring) -- this is the other half of that contract.
    A healthy document's text layer already corroborates its own header values, so a
    witness is pure cost with nothing to buy: this asserts the real end-to-end pipeline
    pays NOTHING for one, not just that the isolated method can return an empty list when
    asked to."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(header=_header(), transcribe_behaviors=["should never be used"])
    _patch_b(monkeypatch, fake_b)
    fake_s3 = _FakeS3()

    nodes = plugin._extract_fulltext(
        _full_text(healthy=True), "doc-1", elements=_healthy_elements(),
        manifest=_manifest(2), s3_client=fake_s3, bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert fake_b.transcribe_calls == 0
    assert fake_s3.get_object_calls == []
    assert aug.stats["text_layer_degraded"] is False
    assert aug.stats["witness_pages"] == 0
    assert aug.notice.mfr == "TE Connectivity"
    assert not any("refused" in r for r in aug.review_reasons)


def test_a_degraded_document_builds_a_witness_and_lets_the_correct_manufacturer_through(
        monkeypatch, plugin):
    """The seal, driven through the REAL wiring rather than a hand-built `witness_index`.
    `test_the_page_image_witness_lets_the_correct_manufacturer_through` in
    test_text_layer_second_witness.py proves the CONSULTATION logic works once handed a
    witness; this proves `_extract_fulltext` actually BUILDS one, on demand, when the text
    layer it measured is degraded -- the missing half that a passing consultation test
    alone cannot show.

    WHAT CHANGED WITH THE REGION SPLIT. `mfr` is a HEADER field, and header fields are
    now corroborated from a CROP of the header block, not from the whole-page
    transcription (measured on TYC 2026-10-01: whole page answers `10-Jan-2024` for a date
    the page prints as `10-Jun-2024`; the crop answers it correctly). So the witness that
    lets this value through is `ReadRegion`'s, and the page transcription -- still built,
    still one call per page -- now serves only `uncorroborated_parts`. Both counters are
    asserted, because the test would otherwise keep passing if the crop stopped happening:
    the page witness alone would still contain this manufacturer."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(header=_header(), transcribe_behaviors=list(_CONTROL_PARAGRAPHS),
                    region_behaviors=["Manufacturer: TE Connectivity\n"
                                      "Document Number: PCN-TEST-001\n"
                                      "Notice Date: not printed\n"
                                      "Current Date: not printed"])
    _patch_b(monkeypatch, fake_b)
    fake_s3 = _FakeS3()

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=_manifest(len(_CONTROL_PARAGRAPHS)), s3_client=fake_s3, bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert fake_b.transcribe_calls == len(_CONTROL_PARAGRAPHS)
    assert fake_b.region_calls == 1, fake_b.region_instructions
    assert aug.stats["text_layer_degraded"] is True
    assert aug.stats["witness_pages"] == len(_CONTROL_PARAGRAPHS)
    assert aug.stats["witness_regions"] == 1
    assert aug.notice.mfr == "TE Connectivity"
    assert any("corroborated by the page image" in r for r in aug.review_reasons)
    assert not any("refused" in r for r in aug.review_reasons)


def test_the_header_witness_is_the_crop_not_the_page_transcription(monkeypatch, plugin):
    """The split, asserted as a SEPARATION rather than as two call counts.

    This is the one test that would have caught the defect the split exists for. The page
    transcription here is handed the document's own undamaged prose -- a witness that
    contains "TE Connectivity" -- and the CROP is handed a refusal. If header
    corroboration were still reading the page witness, the manufacturer would sail
    through; because it reads only the region witness, the value is emptied. A regression
    that re-pointed `refuse_unsourced_header_values` back at `witness_index` passes every
    other test in this file and fails this one."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(header=_header(), transcribe_behaviors=list(_CONTROL_PARAGRAPHS),
                    region_behaviors=["Manufacturer: not printed"])
    _patch_b(monkeypatch, fake_b)

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=_manifest(len(_CONTROL_PARAGRAPHS)), s3_client=_FakeS3(), bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert fake_b.region_calls == 1
    assert aug.notice.mfr == ""
    assert any("refused" in r for r in aug.review_reasons), aug.review_reasons


def test_a_render_whose_shape_contradicts_the_text_layer_yields_no_region_call(
        monkeypatch, plugin):
    """`region_pixel_box` refuses rather than guesses when the page raster and the text
    layer disagree about the page's shape, and that refusal has to reach the CALL: a crop
    box computed from a mismatched ratio would be placed confidently somewhere wrong, and
    the model would answer about it with no indication anything was off. Spending nothing
    and corroborating nothing is the correct outcome -- the header then refuses, exactly
    as it does when no vision endpoint is configured at all."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(header=_header(), transcribe_behaviors=list(_CONTROL_PARAGRAPHS),
                    region_behaviors=["should never be used"])
    _patch_b(monkeypatch, fake_b)

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=_manifest(len(_CONTROL_PARAGRAPHS)),
        s3_client=_FakeS3(size=(1, 1)), bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert fake_b.region_calls == 0
    assert aug.stats["witness_regions"] == 0
    assert aug.notice.mfr == ""


def test_no_vision_endpoint_degrades_to_exactly_the_no_witness_behavior(monkeypatch, plugin):
    """A missing vision endpoint is an ordinary deployment shape (VISION_LLM_BASE_URL
    unset), not an error -- `_transcribe_pages_witness` must fall through to `[]` even on
    a document its OWN measurement calls degraded, and the refusal that follows must land
    exactly where `test_without_a_witness_the_degraded_layer_refuses_a_correct_manufacturer`
    (test_text_layer_second_witness.py) pins it for a witness that was never offered: the
    field is correct, the model read it off the page, and it is emptied anyway because
    nothing in this run can prove it."""
    monkeypatch.delenv("VISION_LLM_BASE_URL", raising=False)
    fake_b = _FakeB(header=_header(), transcribe_behaviors=["should never be called"])
    _patch_b(monkeypatch, fake_b)
    fake_s3 = _FakeS3()

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=_manifest(2), s3_client=fake_s3, bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert fake_b.transcribe_calls == 0
    assert aug.stats["text_layer_degraded"] is True
    assert aug.stats["witness_pages"] == 0
    assert aug.notice.mfr == ""
    assert any("refused" in r for r in aug.review_reasons)


def test_a_manifest_with_no_pages_on_a_degraded_document_also_yields_no_witness(
        monkeypatch, plugin):
    """The other TASK-4 shape: vision IS configured, but there is nothing to point it at
    (no page manifest at all -- e.g. the renderer step did not run). Distinct from the
    VISION_LLM_BASE_URL case above; both must land on the same no-witness behavior, and
    for the same reason `_transcribe_pages_witness` treats them as siblings -- neither is
    a per-document failure worth flagging, both are "there is nothing here to consult"."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(header=_header(), transcribe_behaviors=["should never be called"])
    _patch_b(monkeypatch, fake_b)
    fake_s3 = _FakeS3()

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=None, s3_client=fake_s3, bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert fake_b.transcribe_calls == 0
    assert aug.stats["witness_pages"] == 0
    assert aug.notice.mfr == ""
    assert any("refused" in r for r in aug.review_reasons)


# --------------------------------------------------------------------------- #
# the rendered request -- a stubbed vision call cannot catch a prompt defect, because it
# never looks at the prompt. This test does.
# --------------------------------------------------------------------------- #

def test_the_transcribe_page_request_has_no_dangling_output_format_heading(monkeypatch):
    """Every test above stubs `b.TranscribePage` and asserts on call counts and return
    values -- exactly the shape of test that stayed green while the real prompt shipped a
    `### OUTPUT FORMAT ###` heading over nothing. `ctx.output_format` renders the return
    type's schema; `TranscribePage` returns a bare `string`, which has no fields to
    describe, so the heading rendered with an empty body immediately before the image --
    at best noise, at worst an invitation for the model to try to satisfy an empty format
    spec, directly against this prompt's own "plain text only" instruction. Guarding
    against a regression here means building the ACTUAL request BAML would send (never
    sending it) and reading the rendered message text, the one thing none of the
    call-count tests above ever look at."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    monkeypatch.setenv("VISION_LLM_MODEL", "fake-model")
    monkeypatch.setenv("PROMPT_SOURCE", "file")

    from baml_py import Image
    from doc_tools.baml_client.sync_client import b

    png_1x1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    img = Image.from_base64("image/png", base64.b64encode(png_1x1).decode())

    req = b.request.TranscribePage(page_image=img, system_instructions="transcribe verbatim")
    body = req.body.json()

    rendered = json.dumps(body)
    assert "OUTPUT FORMAT" not in rendered

    user_msg = next(m for m in body["messages"] if m["role"] == "user")
    # The user turn's content is a list of parts (text/image); the LAST one must be the
    # image, with nothing after it -- the vLLM/gemma multimodal template only inserts the
    # image placeholder for an image in a USER turn and fails to place it at all when text
    # follows it in that turn (see the NOTE above `function TranscribePage` in
    # baml_src/sustainment.baml).
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][-1]["type"] == "image_url"


# --------------------------------------------------------------------------- #
# The parts half of the witness -- the expensive one.
# --------------------------------------------------------------------------- #

_TIER1_ROWS = [{
    "affected_mpn": "V23026-A1001-B201",
    "affected_mpn_source": "V23026-A1001-B201",
    "replacement_mpn": None,
    "replacement_mpn_source": None,
    "ltb_date": None,
    "ltb_date_source": None,
    "text_layer_bbox": None,
    "text_layer_replacement_bbox": None,
    # The tier-1 row shape carries its page HERE and has no `page_number` key at all.
    "text_layer_page": 1,
    "text_layer_page_dims": None,
}]


def _patch_tier1(monkeypatch, plugin, rows):
    monkeypatch.setattr(
        plugin, "_extract_parts_text_layer",
        lambda manifest, s3_client, bucket: (
            [dict(r) for r in rows],
            {"text_layer_pages": 1, "text_layer_parts": len(rows), "text_layer_used": True},
        ))


def test_a_part_the_page_image_does_not_corroborate_is_raised_but_not_rewritten(
        monkeypatch, plugin):
    """The silent failure this whole half exists for. Tier 1 reads MPNs out of the text
    layer, so a dropped ligature does not lose a part -- it yields a DIFFERENT, perfectly
    well-formed MPN with correct per-cell provenance, and every downstream check stays
    green while the corpus count quietly drops by one.

    The assertion that matters most here is the LAST one: the row is raised for a human
    and is NOT edited. Flagging cannot lower a corpus score; replacing can.

    `uncorroborated_parts` requires POSITIVE evidence (see
    `doc_tools/utils/text_layer_health.py`): mere absence from the witness text is not
    enough, because a vision transcription substitutes characters as often as a damaged
    text layer drops them, and non-containment alone cannot tell those apart (measured on
    the real TYC-PCN-24-210412 fire, where that weaker rule raised 9 false positives on a
    correct notice). So the witness page here prints `V23026-A10001-B201` -- one digit
    longer than the tier-1 read, with the tier-1 MPN a strict subsequence of it -- which is
    exactly the shape a dropped ligature leaves behind and is what the check now requires
    before it will flag anything.
    """
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    _patch_tier1(monkeypatch, plugin, _TIER1_ROWS)
    fake_b = _FakeB(
        header=_header(),
        transcribe_behaviors=["Affected part: V23026-A10001-B201"] + list(_CONTROL_PARAGRAPHS[1:]),
    )
    _patch_b(monkeypatch, fake_b)

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=_manifest(len(_CONTROL_PARAGRAPHS)), s3_client=_FakeS3(), bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert aug.stats["parts_uncorroborated"] == 1
    finding = aug.stats["parts_uncorroborated_detail"][0]
    assert finding["field"] == "affected_mpn"
    # Read off `text_layer_page`, not the absent `page_number` -- reporting None here
    # would strip a reviewer of the only thing they navigate the PDF by.
    assert finding["page_number"] == 1
    assert aug.needs_review is True
    assert any("not corroborated by the page image" in r for r in aug.review_reasons)
    # `doc_review_reasons` is the banner a reviewer actually reads, as distinct from the
    # full `review_reasons` narrative -- a misread part number belongs in BOTH.
    assert any("PART NUMBERS MAY BE MISREAD" in f
               for f in aug.review["doc_review_reasons"])
    # FLAG, NOT REPLACE.
    assert aug.notice.impacted_parts[0].affected_mpn == "V23026-A1001-B201"


def test_a_part_printed_on_the_page_is_not_raised(monkeypatch, plugin):
    """The other side of the same gate -- corroboration has to be able to PASS, or the
    check is just a second review flag on every degraded document."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    _patch_tier1(monkeypatch, plugin, _TIER1_ROWS)
    fake_b = _FakeB(
        header=_header(),
        transcribe_behaviors=["Affected part: V23026-A1001-B201"] + list(_CONTROL_PARAGRAPHS[1:]),
    )
    _patch_b(monkeypatch, fake_b)

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=_manifest(len(_CONTROL_PARAGRAPHS)), s3_client=_FakeS3(), bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert aug.stats["parts_uncorroborated"] == 0
    assert not any("not corroborated by the page image" in r for r in aug.review_reasons)


def test_a_healthy_document_never_raises_a_part_even_though_no_witness_exists(
        monkeypatch, plugin):
    """The failure mode that would be worst in production: no witness is built for a
    healthy document, and "the pixels did not confirm it" must therefore mean nothing
    rather than everything. An absent witness is not evidence against a part -- read the
    other way, this check would flag EVERY part in the corpus."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    _patch_tier1(monkeypatch, plugin, _TIER1_ROWS)
    fake_b = _FakeB(header=_header(), transcribe_behaviors=["should never be called"])
    _patch_b(monkeypatch, fake_b)

    nodes = plugin._extract_fulltext(
        _full_text(healthy=True), "doc-1", elements=_healthy_elements(),
        manifest=_manifest(len(_CONTROL_PARAGRAPHS)), s3_client=_FakeS3(), bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert aug.stats["text_layer_degraded"] is False
    assert fake_b.transcribe_calls == 0
    assert aug.stats["parts_uncorroborated"] == 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))


# --------------------------------------------------------------------------- #
# A LOST REGION
# --------------------------------------------------------------------------- #
# Three tests for one measured event. On 2026-10-01 one fire of three against the live
# host lost the header-block crop to `400 Bad Request: Failed to load image or audio
# file` and published `TE Connecvity` with the portal's print stamp as the notice date,
# while the other two fires read both correctly. The crop was not at fault: built once
# and sent eight times, byte-identical, it succeeded 8/8. So the region read needs a
# retry, and a region that still fails has to be VISIBLE -- it is no longer a lost
# cross-check but a header field falling back to a text layer already known to be
# damaged.


def test_a_region_read_that_fails_once_is_retried_with_the_same_bytes(monkeypatch, plugin):
    """The first failure must not cost the field. Two calls, one region, value supplied."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(header=_header(), transcribe_behaviors=list(_CONTROL_PARAGRAPHS),
                    region_behaviors=[_FakeB.RAISE,
                                      "Manufacturer: TE Connectivity\n"
                                      "Document Number: PCN-TEST-001\n"
                                      "Notice Date: not printed\n"
                                      "Current Date: not printed"])
    _patch_b(monkeypatch, fake_b)

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=_manifest(len(_CONTROL_PARAGRAPHS)), s3_client=_FakeS3(), bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert fake_b.region_calls == 2, "the failed region read was not retried"
    assert aug.stats["witness_regions"] == 1
    assert aug.stats["witness_regions_lost"] == 0
    assert aug.notice.mfr == "TE Connectivity"
    assert not any("LOST" in r for r in aug.review_reasons), aug.review_reasons


def test_a_region_that_fails_twice_is_recorded_as_a_lost_field(monkeypatch, plugin):
    """The retry is bounded, and exhausting it is REPORTED.

    `witness_regions == 0` alone is not enough: that is also what a document with no
    locatable masthead looks like, and neither reaches a reviewer. This asserts the
    reason, the counter and the doc_flags banner, because the banner is what makes a
    degraded document stop looking clean -- a degraded text layer by itself deliberately
    raises none."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(header=_header(), transcribe_behaviors=list(_CONTROL_PARAGRAPHS),
                    region_behaviors=[_FakeB.RAISE, _FakeB.RAISE])
    _patch_b(monkeypatch, fake_b)

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=_manifest(len(_CONTROL_PARAGRAPHS)), s3_client=_FakeS3(), bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert fake_b.region_calls == 2, "the retry is not bounded at one"
    assert aug.stats["witness_regions"] == 0
    assert aug.stats["witness_regions_lost"] == 1
    assert aug.needs_review is True
    lost = [r for r in aug.review_reasons if "LOST the header_block region" in r]
    assert lost, aug.review_reasons
    assert "mfr" in lost[0], lost[0]
    banner = aug.review.get("doc_review_reasons") or []
    assert any("degraded" in f and "header region" in f for f in banner), banner


def test_a_region_read_that_times_out_is_not_retried(monkeypatch, plugin):
    """A ~300s server-side ceiling is not ours and not configurable from this repo, so
    retrying into it buys the same answer for twice the wall clock. One call, recorded
    as lost."""
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision:1234/v1")
    fake_b = _FakeB(header=_header(), transcribe_behaviors=list(_CONTROL_PARAGRAPHS),
                    region_behaviors=[_FakeB.RAISE_TIMEOUT, "should never be used"])
    _patch_b(monkeypatch, fake_b)

    nodes = plugin._extract_fulltext(
        _full_text(healthy=False), "doc-1", elements=_degraded_elements(),
        manifest=_manifest(len(_CONTROL_PARAGRAPHS)), s3_client=_FakeS3(), bucket="notices",
    )

    aug = nodes[0].domain_augmentation
    assert fake_b.region_calls == 1, "a timeout was retried"
    assert aug.stats["witness_regions_lost"] == 1
    assert any("LOST the header_block region" in r for r in aug.review_reasons)
